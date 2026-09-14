# Documentation

Everything documenting the NbS opportunity mapping pipeline: how to run it, how to get the data,
what the delivered model is, and why each methodological decision was made.

**New here?** Read [`methodology/10_current_configuration.md`](methodology/10_current_configuration.md)
for what the delivered model *is*, then [`RUN_GUIDE.md`](RUN_GUIDE.md) to run it.

## Start here

| Document | What it covers |
|---|---|
| [`RUN_GUIDE.md`](RUN_GUIDE.md) | **Running the tool.** Written for Severn Trent analysts — one command, no Python editing. The authoritative run instructions. |
| [`DATA_ACQUISITION.md`](DATA_ACQUISITION.md) | **The shopping list.** The three national datasets you must download by hand before a first run, with sources, destination paths and licence positions. |
| [`methodology/10_current_configuration.md`](methodology/10_current_configuration.md) | **The delivered model in one page** — AOI, seven layers, three stages, constraint stack, prioritisation, and the delivered output set with figures. |

## Client deliverables

| Document | What it covers |
|---|---|
| `STW_NbS_Methodology_v0.7.docx` / `.pdf` | The full client methodology report — the authoritative written methodology. |
| `STW_NbS_Run_Guide.docx` | The issued client run guide. **Superseded by [`RUN_GUIDE.md`](RUN_GUIDE.md)** where the two differ. |

## Methodology — the numbered decision records

Dated records written as the work progressed, each carrying a status stamp. Where any of them
disagrees with `06` or `10`, those two win.

| Doc | Covers |
|---|---|
| [`01_data_audit_findings.md`](methodology/01_data_audit_findings.md) | Dataset audit — what was available, what was accessible, what was blocked. *Historical snapshot.* |
| [`02_architecture_vector_only.md`](methodology/02_architecture_vector_only.md) | Why `src/` is vector-only, and the CEH land-cover constraint filter. |
| [`03_peat_restoration_experimental.md`](methodology/03_peat_restoration_experimental.md) | The experimental peat layer — why it exists and the grip/gully erosion method. |
| [`04_coverage_gaps_and_welsh_data.md`](methodology/04_coverage_gaps_and_welsh_data.md) | England-only coverage and the Welsh (Hafren Dyfrdwy) gap. *Historical.* |
| [`05_waterlines_source_clarification.md`](methodology/05_waterlines_source_clarification.md) | Why watercourses come from OS Open Zoomstack, not MasterMap. |
| [`06_pipeline_architecture.md`](methodology/06_pipeline_architecture.md) | **The reference description of the pipeline** — every stage, every layer, every deviation. |
| [`07_flood_and_waterbody_sources.md`](methodology/07_flood_and_waterbody_sources.md) | Surface-water flood extent and WFD water-body source resolution. |
| [`08_scaling_and_fetch_strategy.md`](methodology/08_scaling_and_fetch_strategy.md) | Paged fetching and per-water-body tiling — how a 25,508 km² run is made feasible. |
| [`09_aoi_waterbody_union.md`](methodology/09_aoi_waterbody_union.md) | Why the AOI is the WFD water-body union rather than the service boundary. |
| [`10_current_configuration.md`](methodology/10_current_configuration.md) | **The delivered configuration**, with figures re-derived from the outputs. |

## Supporting material

| Document | What it covers |
|---|---|
| [`HOWTO_add_nbs_layer.md`](HOWTO_add_nbs_layer.md) | Adding an eighth NbS layer, using the `_layer_template.py` pattern. |
| [`data_acquisition_checklist.md`](data_acquisition_checklist.md) | How two specific June data blockers were resolved. *Historical — use `DATA_ACQUISITION.md` for current instructions.* |
| [`briefs/`](briefs/) | The development briefs the work was executed against — the provenance record. See [`briefs/README.md`](briefs/README.md). |
| [`reviews/`](reviews/) | The 2026-07-03 adversarial code review and the record of how every finding was dispositioned. |

## Elsewhere in the repo

- [`../README.md`](../README.md) — project overview and getting started.
- [`../RUNBOOK.md`](../RUNBOOK.md) — developer detail: recovery, re-runs, cache internals.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — development conventions.
- `../src/datasets.py` — the dataset registry, and the single source of truth for every dataset
  and its access route.
