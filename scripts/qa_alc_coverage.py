"""
ALC coverage QA (Brief 18 Task B).

Jack's decision (2026-07-06): ALC stays on the Post-1988 Survey product, whose
coverage is PARTIAL (survey-led), unlike the national Provisional ALC the R model
used. The visible cost is that alc_prio is spatially uneven — features outside the
surveyed areas carry a null alc_grade and their tot_prio is a skipna mean over the
remaining sub-scores (tracked per-feature by n_prio_scores). This script makes that
transparency concrete:

  * per layer: % of prioritised opportunity AREA with a non-null alc_grade
    (feature % for point layers), plus the % carrying a SCORED grade;
  * unmapped-value check: any non-null alc_grade absent from
    config/prioritisation_scores.yaml (should be ~0 now 3a/3b are scored —
    a non-trivial count means the source schema shifted; surface it).

Reads the newest outputs/<nbs>/<nbs>_<name>_prioritised_*.gpkg per layer.
Writes outputs/qa/alc_coverage_<name>.json and prints a table.

Usage:  python scripts/qa_alc_coverage.py [--name full]
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import geopandas as gpd
import yaml

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

OUT_ROOT = REPO / "outputs"

NBS = [
    "pond_pool_scrape", "leaky_barriers", "bunds", "floodplain_reconnection",
    "riparian_buffer_strips", "woodland_planting", "peat_restoration",
]


def newest_prioritised(nbs: str, name: str):
    pat = re.compile(rf"^{re.escape(nbs)}_{re.escape(name)}_prioritised_(\d{{8}})\.gpkg$")
    cands = [(m.group(1), f) for f in (OUT_ROOT / nbs).glob("*.gpkg")
             if (m := pat.match(f.name))] if (OUT_ROOT / nbs).exists() else []
    return max(cands)[1] if cands else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--name", default="full", help="output set name (default: full)")
    args = ap.parse_args()

    scores = yaml.safe_load((REPO / "config" / "prioritisation_scores.yaml").read_text(encoding="utf-8"))
    scored_keys = set(scores["alc_grade"].keys())
    # Deliberately unscored Post-1988 categories (C2 decision): no grade signal, so they
    # are excluded from tot_prio via the skipna mean. Reported as info, NOT warned —
    # a warning here means a value outside BOTH sets, i.e. the source schema shifted.
    known_unscored = {"Other", "Not Surveyed", ""}

    rows, total_area, covered_area = {}, 0.0, 0.0
    print(f"{'layer':24s} {'features':>9s} {'alc non-null %':>14s} {'scored %':>9s} {'unexpctd':>8s}  source")
    print("-" * 100)
    for nbs in NBS:
        f = newest_prioritised(nbs, args.name)
        if f is None:
            continue
        g = gpd.read_file(f, columns=["alc_grade"])
        is_poly = g.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all()
        nonnull = g["alc_grade"].notna() if "alc_grade" in g.columns else None
        if nonnull is None:
            print(f"{nbs:24s} {'-':>9s}  no alc_grade column — investigate")
            continue
        unmapped_mask = nonnull & ~g["alc_grade"].isin(scored_keys)
        if is_poly:
            area = g.geometry.area
            layer_total, layer_cov = float(area.sum()), float(area[nonnull].sum())
            cov_pct = 100 * layer_cov / layer_total if layer_total else 0.0
            scored_pct = 100 * float(area[nonnull & ~unmapped_mask].sum()) / layer_total if layer_total else 0.0
            total_area += layer_total
            covered_area += layer_cov
            basis = "area"
        else:
            cov_pct = 100 * nonnull.mean()
            scored_pct = 100 * (nonnull & ~unmapped_mask).mean()
            basis = "features"
        unmapped_vals = g.loc[unmapped_mask, "alc_grade"].value_counts().to_dict()
        unexpected = {k: v for k, v in unmapped_vals.items() if k not in known_unscored}
        rows[nbs] = {
            "source": f.name, "features": int(len(g)), "basis": basis,
            "alc_nonnull_pct": round(cov_pct, 1), "alc_scored_pct": round(scored_pct, 1),
            "known_unscored_count": int(unmapped_mask.sum()) - sum(unexpected.values()),
            "known_unscored_values": {k: v for k, v in unmapped_vals.items() if k in known_unscored},
            "unexpected_count": sum(unexpected.values()), "unexpected_values": unexpected,
        }
        print(f"{nbs:24s} {len(g):>9,d} {cov_pct:>13.1f}% {scored_pct:>8.1f}% "
              f"{sum(unexpected.values()):>8d}  {f.name}")
        if unexpected:
            print(f"{'':24s} WARNING unexpected alc_grade values (not scored, not a known "
                  f"unscored category): {unexpected} — source schema shifted? Surface to Jack.")

    overall = round(100 * covered_area / total_area, 1) if total_area else None
    print("-" * 100)
    print(f"OVERALL (area-weighted, polygon layers): {overall}% of prioritised opportunity "
          f"area has a non-null alc_grade (Post-1988 Survey ALC is partial-coverage by design).")

    qa_dir = OUT_ROOT / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    out = qa_dir / f"alc_coverage_{args.name}.json"
    out.write_text(json.dumps({
        "generated": date.today().isoformat(),
        "name": args.name,
        "alc_source": "Agricultural Land Classification (ALC) — Post-1988 Survey (partial coverage; Jack's decision 2026-07-06)",
        "overall_area_weighted_nonnull_pct": overall,
        "layers": rows,
    }, indent=2), encoding="utf-8")
    print(f"Written: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
