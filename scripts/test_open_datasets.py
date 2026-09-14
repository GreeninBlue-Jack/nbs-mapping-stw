"""
Test programmatic accessibility of all NbS mapping datasets.

Run from the repo root with the venv active:

    python scripts/test_open_datasets.py

Dispatches on the explicit access_method field in src/datasets.py:

  wfs_direct / wfs_via_dataset_page
      → test_wfs_url() on the wfs_url
  arcgis_featureserver
      → probe_arcgis_featureserver() on service_url + layer_index
        (layer_index=None for BGZ-tiled services probes the service root)
  arcgis_static_download
      → HEAD request to download_url
  manual_download / requires_login
      → HEAD request to source_url (link-rot check)
  pending_url
      → skipped; recorded as 'pending'

Results are written to:
  outputs/data_audit/dataset_access_<YYYYMMDD>.csv
  outputs/data_audit/dataset_access_<YYYYMMDD>.md

Experimental entries (peat_restoration NbS) appear in a labelled subsection
of the markdown report and are gated by INCLUDE_EXPERIMENTAL in src/datasets.py.

Usage notes
-----------
- 1 second sleep between network requests (polite crawl rate).
- 30 s timeout on all requests.
- User-Agent: green-in-blue/nbs-mapping (jack@greeninblue.co.uk)
"""

import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from src.datasets import DATASETS, INCLUDE_EXPERIMENTAL
from src.data_access import (
    test_wfs_url,
    probe_arcgis_featureserver,
    check_url_reachable,
)

OUTPUT_DIR = Path(__file__).parent.parent / "outputs" / "data_audit"
TODAY = date.today().strftime("%Y%m%d")

COLUMNS = [
    "name",
    "category",
    "nbs_types",
    "experimental",
    "coverage",
    "access_method",
    "probe_result",
    "layer_name",
    "notes",
    "error",
]

_SLEEP = 1.0


def _nbs_types_str(nbs_types) -> str:
    if isinstance(nbs_types, list):
        return ", ".join(nbs_types)
    return str(nbs_types)


def _notes_str(ds: dict) -> str:
    parts = []
    if ds.get("also_used_as_supplementary"):
        parts.append("[also_used_as_supplementary]")
    if ds.get("bgz_tiled"):
        parts.append(f"[bgz_tiled layers: {ds.get('bgz_layer_ids', [])}]")
    derived = ds.get("derived_uses", [])
    if derived:
        uses = ", ".join(d["use"] for d in derived)
        parts.append(f"[derived_uses: {uses}]")
    raw = ds.get("notes") or ""
    if raw:
        parts.append(raw)
    return " ".join(parts)


def audit_dataset(ds: dict) -> dict:
    method = ds["access_method"]
    result = {
        "name": ds["name"],
        "category": ds["category"],
        "nbs_types": _nbs_types_str(ds.get("nbs_types", [])),
        "experimental": bool(ds.get("experimental", False)),
        "coverage": ds.get("coverage", "unknown"),
        "access_method": method,
        "probe_result": "untested",
        "layer_name": "",
        "notes": _notes_str(ds),
        "error": "",
    }

    # ------------------------------------------------------------------ #
    # WFS direct                                                           #
    # ------------------------------------------------------------------ #
    if method in ("wfs_direct", "wfs_via_dataset_page"):
        wfs_url = ds.get("wfs_url", "")
        probe = test_wfs_url(wfs_url)
        time.sleep(_SLEEP)
        if probe["accessible"]:
            result["probe_result"] = "ok"
            result["layer_name"] = (probe["layers"] or [""])[0]
        else:
            result["probe_result"] = "fail"
            result["error"] = probe.get("error") or "WFS not accessible"
        return result

    # ------------------------------------------------------------------ #
    # ArcGIS FeatureServer                                                 #
    # ------------------------------------------------------------------ #
    if method == "arcgis_featureserver":
        service_url = ds.get("service_url", "")
        layer_index = ds.get("layer_index")  # may be None for BGZ-tiled
        probe = probe_arcgis_featureserver(service_url, layer_index)
        time.sleep(_SLEEP)
        if probe["accessible"]:
            result["probe_result"] = "ok"
            if layer_index is None:
                layers = probe.get("all_layers", [])
                result["layer_name"] = (
                    f"{len(layers)} BGZ layers: " + ", ".join(str(l["id"]) for l in layers[:5])
                    if layers else "service root accessible"
                )
            else:
                result["layer_name"] = probe.get("layer_name") or ds.get("layer_name", "")
        else:
            result["probe_result"] = "fail"
            result["error"] = probe.get("error") or "ArcGIS FeatureServer not accessible"
        return result

    # ------------------------------------------------------------------ #
    # ArcGIS static download (HEAD check)                                 #
    # ------------------------------------------------------------------ #
    if method == "arcgis_static_download":
        download_url = ds.get("download_url", "")
        reachable, err = check_url_reachable(download_url)
        time.sleep(_SLEEP)
        if reachable:
            result["probe_result"] = "ok"
            fmt = ds.get("file_format", "")
            size = ds.get("size_mb")
            result["layer_name"] = f"{fmt} ~{size} MB" if size else fmt
        else:
            result["probe_result"] = "fail"
            result["error"] = err or "download URL unreachable"
        return result

    # ------------------------------------------------------------------ #
    # Manual download / requires login — HEAD check on source_url         #
    # ------------------------------------------------------------------ #
    if method in ("manual_download", "requires_login"):
        source_url = ds.get("source_url")
        if source_url:
            reachable, err = check_url_reachable(source_url)
            time.sleep(_SLEEP)
            result["probe_result"] = "page_ok" if reachable else "page_fail"
            if not reachable:
                result["error"] = err or "source URL unreachable"
        else:
            result["probe_result"] = "no_url"
        return result

    # ------------------------------------------------------------------ #
    # Pending URL — not yet known                                         #
    # ------------------------------------------------------------------ #
    if method == "pending_url":
        result["probe_result"] = "pending"
        return result

    # ------------------------------------------------------------------ #
    # Local file — staged under data/raw/                                 #
    # ------------------------------------------------------------------ #
    if method == "local_file":
        from pathlib import Path as _Path

        file_path = ds.get("file_path", "")
        file_layer = ds.get("file_layer")
        repo_root = _Path(__file__).parent.parent
        full_path = repo_root / file_path

        if not full_path.exists():
            result["probe_result"] = "fail"
            result["error"] = f"file not found: {file_path}"
            return result

        try:
            try:
                import pyogrio
                from pyproj import CRS as _CRS

                if file_layer:
                    available = [row[0] for row in pyogrio.list_layers(str(full_path))]
                    if file_layer not in available:
                        result["probe_result"] = "fail"
                        result["error"] = (
                            f"layer '{file_layer}' not in {full_path.name}; "
                            f"available: {', '.join(available[:6])}"
                        )
                        return result

                open_kw = {"layer": file_layer} if file_layer else {}
                info = pyogrio.read_info(str(full_path), **open_kw)
                n = info.get("features", "?")
                geom_type = info.get("geometry_type", "unknown")
                try:
                    epsg = _CRS.from_wkt(info["crs"]).to_epsg() if info.get("crs") else "unknown"
                except Exception:
                    epsg = "unknown"

            except ImportError:
                import fiona
                from pyproj import CRS as _CRS

                if file_layer:
                    available = fiona.listlayers(str(full_path))
                    if file_layer not in available:
                        result["probe_result"] = "fail"
                        result["error"] = (
                            f"layer '{file_layer}' not in {full_path.name}; "
                            f"available: {', '.join(available[:6])}"
                        )
                        return result

                open_kw = {"layer": file_layer} if file_layer else {}
                with fiona.open(str(full_path), **open_kw) as src:
                    n = len(src)
                    geom_type = src.schema["geometry"]
                    try:
                        epsg = _CRS.from_dict(dict(src.crs)).to_epsg() if src.crs else "unknown"
                    except Exception:
                        epsg = "unknown"

            result["probe_result"] = "ok"
            n_str = f"{n:,}" if isinstance(n, int) else str(n)
            result["layer_name"] = f"{geom_type} | {n_str} features | EPSG:{epsg}"

        except Exception as exc:
            result["probe_result"] = "fail"
            result["error"] = str(exc)[:120]

        return result

    # Unrecognised method — shouldn't happen if registry is consistent
    result["probe_result"] = "unknown_method"
    result["error"] = f"Unrecognised access_method: {method!r}"
    return result


def write_csv(rows: list[dict]) -> Path:
    df = pd.DataFrame(rows, columns=COLUMNS)
    path = OUTPUT_DIR / f"dataset_access_{TODAY}.csv"
    df.to_csv(path, index=False)
    return path


def write_markdown(core_rows: list[dict], exp_rows: list[dict]) -> Path:
    all_rows = core_rows + exp_rows
    lines = [
        f"# Dataset Access Audit — {TODAY}",
        "",
        "Generated by `scripts/test_open_datasets.py`. Re-run to refresh.",
        "",
        f"**Total datasets:** {len(all_rows)} "
        f"({len(core_rows)} core + {len(exp_rows)} experimental peat restoration)",
        "",
    ]

    # Summary table
    counts = Counter(r["probe_result"] for r in core_rows)
    exp_counts = Counter(r["probe_result"] for r in exp_rows)
    lines += [
        "## Summary — core datasets",
        "",
        "| Result | Count |",
        "|---|---|",
    ]
    for key in ["ok", "page_ok", "pending", "page_fail", "fail"]:
        label = {
            "ok": "ok (programmatically accessible)",
            "page_ok": "page_ok (landing page reachable, manual download)",
            "pending": "pending (URL not yet known)",
            "page_fail": "page_fail (landing page unreachable)",
            "fail": "fail (endpoint error)",
        }.get(key, key)
        lines.append(f"| {label} | {counts.get(key, 0)} |")
    lines.append("")

    if exp_rows:
        lines += [
            "## Summary — experimental (peat restoration)",
            "",
            "| Result | Count |",
            "|---|---|",
        ]
        for key in ["ok", "page_ok", "pending", "page_fail", "fail"]:
            lines.append(f"| {key} | {exp_counts.get(key, 0)} |")
        lines.append("")

    # Per-category tables for core datasets
    for category in ["opportunity", "constraint", "supplementary", "multi"]:
        cat_rows = [r for r in core_rows if r["category"] == category]
        if not cat_rows:
            continue
        lines += [f"## {category.capitalize()} datasets (core)", ""]
        lines += [
            "| Name | Coverage | Access method | Probe | Layer / info | Notes |",
            "|---|---|---|---|---|---|",
        ]
        for r in cat_rows:
            layer = r["layer_name"] or "—"
            notes = r["notes"] or "—"
            if r["error"]:
                notes = f"{notes} **Error:** {r['error']}"
            cov = r.get("coverage", "?")
            lines.append(
                f"| {r['name']} | `{cov}` | `{r['access_method']}` | `{r['probe_result']}` | {layer} | {notes} |"
            )
        lines.append("")

    # Experimental section
    if exp_rows:
        lines += [
            "## Experimental: peat restoration datasets",
            "",
            "> These entries are gated by `INCLUDE_EXPERIMENTAL` in `src/datasets.py`.",
            "> Awaiting stakeholder go/no-go from Matt Palmer (Severn Trent).",
            "> **All peat restoration datasets are England-only** — Wales gap documented separately.",
            "",
            "| Name | Coverage | Access method | Probe | Layer / info | Notes |",
            "|---|---|---|---|---|---|",
        ]
        for r in exp_rows:
            layer = r["layer_name"] or "—"
            notes = r["notes"] or "—"
            if r["error"]:
                notes = f"{notes} **Error:** {r['error']}"
            cov = r.get("coverage", "?")
            lines.append(
                f"| {r['name']} | `{cov}` | `{r['access_method']}` | `{r['probe_result']}` | {layer} | {notes} |"
            )
        lines.append("")

    # Coverage gap matrix
    lines += _coverage_gap_matrix(core_rows, exp_rows)

    # Action items
    action_rows = [
        r for r in core_rows
        if r["probe_result"] not in ("ok", "page_ok", "pending")
    ]
    if action_rows:
        lines += ["## Action items (errors)", ""]
        for r in action_rows:
            lines.append(f"- **{r['name']}** (`{r['access_method']}`): {r['error'] or '—'}")
        lines.append("")

    path = OUTPUT_DIR / f"dataset_access_{TODAY}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _coverage_gap_matrix(core_rows: list[dict], exp_rows: list[dict]) -> list[str]:
    """Build the coverage gap matrix section of the markdown report."""
    from src.datasets import NBS_TYPES, EXPERIMENTAL_NBS_TYPES

    lines = [
        "## Coverage gap matrix",
        "",
        "**Coverage field definitions:**",
        "- `england` — England only (EA, Natural England, FC, WWNP datasets)",
        "- `gb` — Great Britain (UKCEH, Ordnance Survey, BGS datasets)",
        "",
        (
            "> **STW AOI:** The canonical AOI is the merged STW Plc full operational "
            "footprint (ST + HD, clean water + wastewater, unioned into a single "
            "MultiPolygon at `data/processed/stw_full_aoi.gpkg`). Total area: 24,321 km²; "
            "Wales intersection: 2,990 km² (12.3%). England-only datasets will produce "
            "blank outputs for the Welsh portion served by Hafren Dyfrdwy."
        ),
        "",
        "### Core datasets — by NbS type",
        "",
    ]

    core_nbs = [t for t in NBS_TYPES if t not in EXPERIMENTAL_NBS_TYPES]
    lines += [
        "| NbS type | Category | england | gb | uk | wales | Total |",
        "|---|---|---|---|---|---|---|",
    ]

    for nbs_type in core_nbs:
        # nbs_types is stored as a comma-separated string after _nbs_types_str()
        type_rows = [
            r for r in core_rows
            if nbs_type in r["nbs_types"].split(", ") or "all" in r["nbs_types"].split(", ")
        ]
        if not type_rows:
            continue
        for cat in ["opportunity", "constraint", "supplementary", "multi"]:
            cat_rows = [r for r in type_rows if r["category"] == cat]
            if not cat_rows:
                continue
            eng = sum(1 for r in cat_rows if r.get("coverage") == "england")
            gb = sum(1 for r in cat_rows if r.get("coverage") == "gb")
            uk = sum(1 for r in cat_rows if r.get("coverage") == "uk")
            wales = sum(1 for r in cat_rows if r.get("coverage") == "wales")
            total = len(cat_rows)
            lines.append(f"| {nbs_type} | {cat} | {eng} | {gb} | {uk} | {wales} | {total} |")

    lines.append("")

    # Summary: england vs gb for core datasets
    eng_core = sum(1 for r in core_rows if r.get("coverage") == "england")
    gb_core = sum(1 for r in core_rows if r.get("coverage") == "gb")
    lines += [
        f"**Core dataset coverage summary:** {eng_core} England-only, {gb_core} GB (covers Wales), "
        f"0 Wales-specific.",
        "",
        (
            f"Of {len(core_rows)} core datasets, **{gb_core} cover Wales** (CEH LCM, OS Zoomstack Roads, "
            "OS Zoomstack Railways, BGS Soil Parent Material). The remaining "
            f"**{eng_core} are England-only** and will produce blank outputs for any Welsh "
            "portion of the STW operational area."
        ),
        "",
    ]

    # Experimental peat section
    if exp_rows:
        eng_exp = sum(1 for r in exp_rows if r.get("coverage") == "england")
        lines += [
            "### Experimental: peat restoration datasets",
            "",
            (
                f"All {len(exp_rows)} peat restoration datasets are **England-only** "
                f"({eng_exp}/{len(exp_rows)} tagged `england`). "
                "The England Peat Map (Natural England, May 2025) does not cover Wales. "
                "A Welsh equivalent — the Welsh National Peatland Action Programme (WNPAP) "
                "inventory — exists but has not been evaluated. See "
                "`docs/methodology/04_coverage_gaps_and_welsh_data.md` for Phase 1.5 backlog."
            ),
            "",
        ]

    return lines


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_entries = DATASETS if INCLUDE_EXPERIMENTAL else [
        d for d in DATASETS if not d.get("experimental", False)
    ]

    core = [d for d in all_entries if not d.get("experimental", False)]
    experimental = [d for d in all_entries if d.get("experimental", False)]

    print(f"NbS dataset access audit — {TODAY}")
    print(f"Testing {len(core)} core + {len(experimental)} experimental datasets...\n")

    core_rows = []
    exp_rows = []

    def _run(entries, rows, label):
        ok = fail = manual = pending = 0
        for ds in entries:
            result = audit_dataset(ds)
            rows.append(result)
            pr = result["probe_result"]
            if pr == "ok":
                tag, ok = "OK  ", ok + 1
            elif pr in ("page_ok",):
                tag, manual = "MANU", manual + 1
            elif pr in ("pending", "no_url"):
                tag, pending = "PEND", pending + 1
            else:
                tag, fail = "FAIL", fail + 1
            err = f"  [{result['error'][:80]}]" if result["error"] else ""
            print(f"  {tag}  {ds['name'][:55]:<55}  {pr}{err}")
        print(
            f"\n  {label}: {ok} ok / {manual} manual / {pending} pending / {fail} fail\n"
        )

    _run(core, core_rows, "Core")
    if experimental:
        print("--- Experimental: peat restoration ---")
        _run(experimental, exp_rows, "Experimental")

    all_rows = core_rows + exp_rows
    csv_path = write_csv(all_rows)
    md_path = write_markdown(core_rows, exp_rows)

    print(f"CSV: {csv_path}")
    print(f" MD: {md_path}")

    fail_count = sum(1 for r in core_rows if r["probe_result"] not in ("ok", "page_ok", "pending", "page_fail", "no_url"))
    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
