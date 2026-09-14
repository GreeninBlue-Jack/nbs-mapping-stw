"""
NbS opportunity mapping pipeline runner.

Usage
-----
    python scripts/run_pipeline.py --nbs pond_pool_scrape --aoi dev
    python scripts/run_pipeline.py --all --aoi dev
    python scripts/run_pipeline.py --nbs woodland_planting --aoi dev --stage opportunity

Options
-------
--nbs <name>     One of the 7 NbS type names. Required unless --all is set.
--all            Run all NbS types in sequence.
--aoi dev|full   AOI to use (default: dev). 'full' requires explicit flag.
--stage          One of: opportunity, supplemented, prioritised (default: all three).

Safety: --aoi full is refused unless explicitly passed and all three stages have
        passed dev-AOI review (enforced by the absence of outputs/validation/).

Outputs
-------
Per-layer:
  outputs/<nbs_type>/<nbs_type>_<aoi>_<stage>_<date>.gpkg
  outputs/validation/<nbs_type>_review.md
  outputs/validation/<nbs_type>_preview.png

Index:
  outputs/validation/pipeline_run_<date>.md
"""

import argparse
import sys
from datetime import date
from pathlib import Path

# Allow running from repo root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline import (
    bunds,
    constraints as constraints_mod,
    floodplain_reconnection,
    leaky_barriers,
    peat_restoration,
    pond_pool_scrape,
    prioritisation as prio_mod,
    riparian_buffer_strips,
    supplementary as supp_mod,
    utils,
    woodland_planting,
)

_TODAY = date.today().strftime("%Y%m%d")

_LAYER_MODULES = {
    "pond_pool_scrape":        pond_pool_scrape,
    "leaky_barriers":          leaky_barriers,
    "bunds":                   bunds,
    "floodplain_reconnection": floodplain_reconnection,
    "riparian_buffer_strips":  riparian_buffer_strips,
    "woodland_planting":       woodland_planting,
    "peat_restoration":        peat_restoration,
}

_STAGES = ("opportunity", "supplemented", "prioritised")


def run_layer(
    nbs_type: str,
    aoi_name: str,
    stages: tuple[str, ...],
    aoi,
    constraints,
    index_rows: list,
) -> None:
    """Run the full three-stage pipeline for one NbS type."""
    print(f"\n{'='*60}")
    print(f"  {nbs_type.upper()}  (AOI: {aoi_name})")
    print(f"{'='*60}")

    module = _LAYER_MODULES[nbs_type]
    parity_results = []

    # ---- Stage 1: Opportunity ------------------------------------------
    opp_gdf = None
    if "opportunity" in stages:
        print("\n--- Stage 1: Opportunity ---")
        try:
            opp_gdf = module.run(aoi, constraints, aoi_name=aoi_name)
            utils.validate(opp_gdf, f"{nbs_type}: stage1")
            p = utils.parity_check(opp_gdf, nbs_type, "opportunity")
            parity_results.append(p)
            status1 = p["status"]
            print(f"  Parity: {status1}")
            index_rows.append({"nbs_type": nbs_type, "stage": "opportunity", "status": status1})
        except Exception as exc:
            print(f"  ERROR in stage 1: {exc}", file=sys.stderr)
            index_rows.append({"nbs_type": nbs_type, "stage": "opportunity", "status": f"ERROR: {exc}"})
            return

    # ---- Stage 2: Supplemented -----------------------------------------
    supped_gdf = None
    if "supplemented" in stages:
        print("\n--- Stage 2: Supplemented ---")
        if opp_gdf is None:
            print("  SKIP: opportunity layer not produced in this run.", file=sys.stderr)
        else:
            try:
                supped_gdf = supp_mod.add_supplementary(opp_gdf, aoi, aoi_name=aoi_name, nbs_type=nbs_type)
                utils.validate(supped_gdf, f"{nbs_type}: stage2")
                p = utils.parity_check(supped_gdf, nbs_type, "supplemented")
                parity_results.append(p)
                status2 = p["status"]
                print(f"  Parity: {status2}")
                index_rows.append({"nbs_type": nbs_type, "stage": "supplemented", "status": status2})
            except Exception as exc:
                print(f"  ERROR in stage 2: {exc}", file=sys.stderr)
                index_rows.append({"nbs_type": nbs_type, "stage": "supplemented", "status": f"ERROR: {exc}"})

    # ---- Stage 3: Prioritised ------------------------------------------
    if "prioritised" in stages:
        print("\n--- Stage 3: Prioritised ---")
        if supped_gdf is None:
            print("  SKIP: supplemented layer not produced in this run.", file=sys.stderr)
        else:
            try:
                prio_gdf = prio_mod.add_priority_scores(supped_gdf, nbs_type=nbs_type, aoi_name=aoi_name)
                utils.validate(prio_gdf, f"{nbs_type}: stage3")
                p = utils.parity_check(prio_gdf, nbs_type, "prioritised")
                parity_results.append(p)
                status3 = p["status"]
                print(f"  Parity: {status3}")
                index_rows.append({"nbs_type": nbs_type, "stage": "prioritised", "status": status3})
            except Exception as exc:
                print(f"  ERROR in stage 3: {exc}", file=sys.stderr)
                index_rows.append({"nbs_type": nbs_type, "stage": "prioritised", "status": f"ERROR: {exc}"})

    # ---- Review pack ---------------------------------------------------
    if opp_gdf is not None:
        md_path = utils.review_pack(opp_gdf, nbs_type, aoi_name, parity_results)
        print(f"\n  Review: {md_path.relative_to(Path(__file__).parent.parent)}")


def write_index(index_rows: list, aoi_name: str) -> Path:
    val_dir = Path(__file__).parent.parent / "outputs" / "validation"
    val_dir.mkdir(parents=True, exist_ok=True)
    idx_path = val_dir / f"pipeline_run_{_TODAY}.md"

    lines = [
        f"# Pipeline Run — {_TODAY}",
        "",
        f"**AOI:** {aoi_name}  ",
        f"**Layers:** {len(set(r['nbs_type'] for r in index_rows))}  ",
        "",
        "| NbS type | Stage | Status |",
        "|---|---|---|",
    ]
    for row in index_rows:
        st = row["status"]
        flag = " ⚠" if "FLAGGED" in st or "ERROR" in st else " ✓"
        lines.append(f"| {row['nbs_type']} | {row['stage']} | {st}{flag} |")

    lines.append("")
    idx_path.write_text("\n".join(lines), encoding="utf-8")
    return idx_path


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--nbs", choices=list(_LAYER_MODULES), help="NbS type to run")
    parser.add_argument("--all", action="store_true", dest="run_all", help="Run all NbS types")
    parser.add_argument("--aoi", choices=["dev", "full"], default="dev", help="AOI (default: dev)")
    parser.add_argument(
        "--stage",
        choices=["opportunity", "supplemented", "prioritised", "all"],
        default="all",
        help="Pipeline stage to run (default: all)",
    )
    args = parser.parse_args()

    if not args.nbs and not args.run_all:
        parser.error("Specify --nbs <type> or --all.")

    if args.aoi == "full":
        print(
            "WARNING: --aoi full runs the pipeline over the entire STW Plc operational "
            "footprint (~24,321 km²). This is a long-running operation. "
            "Ensure all dev-AOI parity checks have passed before proceeding.",
            file=sys.stderr,
        )

    stages = tuple(_STAGES) if args.stage == "all" else (args.stage,)
    targets = list(_LAYER_MODULES) if args.run_all else [args.nbs]

    print(f"Loading AOI: {args.aoi}")
    aoi = utils.load_aoi(args.aoi)
    print(f"AOI loaded — {len(aoi)} feature(s), {aoi.crs}")

    print("Building generic constraints layer...")
    constraints = constraints_mod.build_constraints_layer(aoi)
    # Peat uses PHYSICAL constraints only (no CEH land-cover mask, which excludes the bog it
    # maps) — Brief 22. Built once, only if peat is a target.
    peat_constraints = (
        constraints_mod.build_constraints_layer(aoi, include_ceh=False)
        if "peat_restoration" in targets else None
    )

    index_rows = []
    for nbs_type in targets:
        c = peat_constraints if nbs_type == "peat_restoration" else constraints
        run_layer(nbs_type, args.aoi, stages, aoi, c, index_rows)

    idx_path = write_index(index_rows, args.aoi)
    print(f"\nIndex: {idx_path.relative_to(Path(__file__).parent.parent)}")

    errors = sum(1 for r in index_rows if "ERROR" in r["status"])
    flags  = sum(1 for r in index_rows if "FLAGGED" in r["status"])
    print(f"\nSummary: {len(index_rows)} stage runs — {errors} errors, {flags} flagged parity")
    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
