"""
Priority scoring — add_priority_scores().

Ports the prio_score block of OppMapp_extractSupplementary_v2.R,
with a deliberate five-key extension (R used four keys).

Algorithm:
  1. Map four lookup tables from config/prioritisation_scores.yaml — the editable
     score tables relocated from the read-only reference xlsx (Brief 13 A5)
     (CEH_LU → lu_prio, alc_grade → alc_prio, prio_hb → hb_prio, sl_grp → sl_prio).
  2. Map HML rch_pt (HIGH/MEDIUM/LOW) via config lookup → rch_prio.
  3. Fill hb_prio NaN with the config na_value (0.5; per R habs_NA_value).
  4. tot_prio = row-wise mean of (lu_prio, alc_prio, hb_prio, sl_prio, rch_prio).
  5. Drop individual sub-score columns, relabel CEH_LU to its authoritative text
     label for the final output (Brief 13 A3), reattach geometry.

CEH_LU is kept NUMERIC through scoring (lu_prio joins on the class code) and is
relabelled to text only on the written prioritised output.

Scores live in config/prioritisation_scores.yaml (edit there to re-weight — no code
change). The reference Priority_Scores.xlsx is retained as provenance only and is no
longer read at runtime.

Excluded keys: wb_prio (Avon-specific), wood_prio (not applied uniformly
across all NbS types). See config/prioritisation.yaml for rationale.

Note: stage-3 tot_prio is a five-key extension of the R's four-key mean.
Parity of tot_prio VALUES against R reference is expected to diverge by design.
Parity of stage-3 GEOMETRY against R reference is the meaningful check.

Missing sub-scores (2026-07-03 review, H1/C2 — DELIBERATE deviation from R):
  R computed rowMeans(na.rm=FALSE) — any NA sub-score made tot_prio NA. Here the
  row mean SKIPS NaN sub-scores, so a feature missing e.g. alc_prio is scored on
  the keys it does have rather than dropping out of the ranking entirely. This is
  intentional (ALC/recharge coverage is partial across the STW area; R's Avon run
  never hit it), but it means weakly-supported scores exist, so:
    * every prioritised output carries n_prio_scores = how many of the five
      sub-scores actually backed that feature's tot_prio (provenance);
    * any attribute VALUE present in the data but absent from
      config/prioritisation_scores.yaml is reported loudly with counts —
      never silently NaN'd (previously Grade 3a/3b ALC values vanished this way).
"""

import sys
from pathlib import Path

import pandas as pd
import geopandas as gpd

from src.pipeline.utils import load_prio_config, load_prio_scores, validate, write_output

_REPO = Path(__file__).parent.parent.parent
# Provenance only — scores are now read from config/prioritisation_scores.yaml (A5):
_XLSX_PROVENANCE = _REPO / "data" / "reference" / "R_Model" / "Prioritisation_Lookup" / "Priority_Scores.xlsx"


def add_priority_scores(
    supped_gdf: gpd.GeoDataFrame,
    nbs_type: str = "unknown",
    aoi_name: str = "dev",
) -> gpd.GeoDataFrame:
    """
    Apply the Priority_Scores.xlsx lookups and compute tot_prio.

    Parameters
    ----------
    supped_gdf : Stage-2 supplemented GeoDataFrame in EPSG:27700.
    nbs_type   : NbS type name — used for output path naming.
    aoi_name   : 'dev' or 'full'.

    Returns
    -------
    GeoDataFrame with tot_prio column, stage-3 output.
    """
    cfg = load_prio_config()
    scores = load_prio_scores()
    join_keys   = cfg["xlsx_join_keys"]   # e.g. [CEH_LU, alc_grade, prio_hb, sl_grp]
    prio_names  = cfg["xlsx_prio_names"]  # e.g. [lu_prio, alc_prio, hb_prio, sl_prio]
    hml_lookup  = dict(cfg["hml_recharge_lookup"])  # copy (we pop 'default')
    hml_default = hml_lookup.pop("default", 0.0)

    validate(supped_gdf, "prioritisation: input")

    # Extract geometry for re-attachment later (mirrors R: keep geom separate)
    geom = supped_gdf[["geometry"]].copy()
    dat = supped_gdf.drop(columns="geometry").copy()

    # ------------------------------------------------------------------ #
    # Score lookup tables from config/prioritisation_scores.yaml (A5)     #
    # ------------------------------------------------------------------ #
    ceh_labels = {int(k): str(v).strip() for k, v in scores["ceh_lu"]["labels"].items()}
    lu_map     = {int(k): float(v) for k, v in scores["ceh_lu"]["lu_prio"].items()}
    alc_map    = {k: float(v) for k, v in scores["alc_grade"].items()}
    hb_map     = {k: float(v) for k, v in scores["prio_hb"]["scores"].items()}
    hb_prio_na = float(scores["prio_hb"]["na_value"])
    sl_map     = {k: float(v) for k, v in scores["sl_grp"].items()}
    score_map  = {"CEH_LU": lu_map, "alc_grade": alc_map, "prio_hb": hb_map, "sl_grp": sl_map}

    # CEH_LU is kept numeric for the lu_prio join; relabelled to text at the end (A3).
    ceh_codes = (
        pd.to_numeric(dat["CEH_LU"], errors="coerce").astype("Int64")
        if "CEH_LU" in dat.columns else None
    )

    # ------------------------------------------------------------------ #
    # 1. Map four lookup tables (value -> sub-score)                      #
    # ------------------------------------------------------------------ #
    for key, prio_col in zip(join_keys, prio_names):
        if key not in dat.columns:
            dat[prio_col] = None
            continue
        src = ceh_codes if key == "CEH_LU" else dat[key]
        dat[prio_col] = src.map(lu_map if key == "CEH_LU" else score_map[key]).astype("float")
        # A value present in the data but absent from prioritisation_scores.yaml maps
        # to NaN and is then excluded from tot_prio (skipna mean). Report it loudly —
        # this is how the Grade 3a/3b ALC hole went unnoticed (2026-07-03 review, C2).
        unmapped = src.notna() & dat[prio_col].isna()
        if unmapped.any():
            top = src[unmapped].value_counts().head(5).to_dict()
            print(
                f"  [prioritisation] WARNING: {int(unmapped.sum()):,}/{len(dat):,} features "
                f"have a {key} value with no score in config/prioritisation_scores.yaml — "
                f"excluded from their tot_prio mean. Unmapped values (top 5): {top}. "
                f"Add the missing keys to the YAML or confirm the exclusion.",
                file=sys.stderr,
            )

    # ------------------------------------------------------------------ #
    # 2. Fill hb_prio NaN with the config na_value (matches R)           #
    # ------------------------------------------------------------------ #
    if "hb_prio" in dat.columns:
        dat["hb_prio"] = dat["hb_prio"].fillna(hb_prio_na)

    # ------------------------------------------------------------------ #
    # 3. Map HML rch_pt → rch_prio via config lookup                    #
    # ------------------------------------------------------------------ #
    if "rch_pt" in dat.columns:
        dat["rch_prio"] = dat["rch_pt"].map(hml_lookup).fillna(hml_default)
    else:
        dat["rch_prio"] = hml_default

    # ------------------------------------------------------------------ #
    # 4. Compute tot_prio = row-wise mean of 5 sub-scores                #
    # ------------------------------------------------------------------ #
    # skipna=True is a DELIBERATE deviation from R's rowMeans(na.rm=FALSE): features
    # missing a sub-score are scored on the keys they have instead of dropping to NA.
    # n_prio_scores records how many sub-scores backed each tot_prio so weakly-
    # supported scores are visible downstream (2026-07-03 review, H1).
    all_prio_cols = prio_names + ["rch_prio"]
    active_cols = [c for c in all_prio_cols if c in dat.columns]
    dat["n_prio_scores"] = dat[active_cols].notna().sum(axis=1).astype("int32")
    dat["tot_prio"] = dat[active_cols].mean(axis=1, skipna=True)

    # ------------------------------------------------------------------ #
    # 5. Drop sub-scores, relabel CEH_LU to text (A3), reattach geometry  #
    # ------------------------------------------------------------------ #
    drop_cols = [c for c in all_prio_cols if c in dat.columns]
    dat = dat.drop(columns=drop_cols)
    if ceh_codes is not None:
        dat["CEH_LU"] = ceh_codes.map(ceh_labels)  # numeric code -> authoritative label

    result = gpd.GeoDataFrame(dat, geometry=geom["geometry"].values, crs="EPSG:27700")
    validate(result, "prioritisation: final")

    print(f"  [prioritisation] tot_prio: min={result['tot_prio'].min():.3f} "
          f"mean={result['tot_prio'].mean():.3f} max={result['tot_prio'].max():.3f}")
    n_dist = result["n_prio_scores"].value_counts().sort_index().to_dict()
    print(f"  [prioritisation] sub-scores backing tot_prio (n_prio_scores: count): {n_dist}")

    write_output(result, nbs_type, aoi_name, "prioritised")
    return result
