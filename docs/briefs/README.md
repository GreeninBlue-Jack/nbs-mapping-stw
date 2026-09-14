# Development briefs

These are the briefs the development work was executed against, kept as a **provenance record**
of how the method evolved and why each change was made. Each carries its original text plus a
`**Status (2026-09-14):**` line recording when it was executed and whether anything later
superseded it.

**These are not instructions for running the tool.** For that, read
[`../RUN_GUIDE.md`](../RUN_GUIDE.md).

They matter more than usual here because the repository was published with a **squashed
history** — a single commit — so the per-change commit trail that would normally carry this
reasoning is not reachable from the published repo. These documents and the dated records in
[`../methodology/`](../methodology/) are the provenance trail.

## Why the numbering starts at 06 and skips 16

Neither gap is a removal. Verified against the full repository history on 2026-09-14: **no
`Brief_16_*` or `Brief_01…05_*` file has ever existed in this repository.**

- **Briefs 01–05 pre-date the practice.** The `docs/briefs/` folder was created on 2026-06-22, in
  a single commit that added Briefs 06–15 retrospectively. The earlier briefs — the data audit,
  the dataset registry, the vector-only architecture decision, the first full pipeline build and
  the RoFSW/WFD source corrections — were worked before briefs were kept as repo documents. Their
  substance is recorded in the numbered methodology docs (`01`–`07`) and the audit outputs under
  `outputs/data_audit/`.
- **Brief 16 was issued and executed, but its document was never committed.** It landed on
  2026-06-23/24 — the day after the briefs folder was created — and built the per-water-body
  tiled runner that produced the full Severn-Trent-scale outputs. The document simply was not
  added alongside the code; an administrative omission rather than anything withdrawn. Its work
  is fully described in [`../methodology/08_scaling_and_fetch_strategy.md`](../methodology/08_scaling_and_fetch_strategy.md) §3
  and lives in `scripts/build_wb_tiles.py`, `scripts/run_full_tiled.py` and `scripts/merge_tiles.py`.

## The briefs

| Brief | Subject | Executed |
|---|---|---|
| 06 | Paged WFS fetch with a no-silent-partial guard | 2026-06-11 |
| 07 | Full AOI redefined as the WFD water-body union | 2026-06-11 |
| 08 | Harden the paged WFS fetch (streaming retry) | 2026-06-11 |
| 09 | Gentler, resumable fetch (survive the flaky EA server) | 2026-06-12 |
| 10 | Fix resumable-fetch bugs (cache out of OneDrive) | 2026-06-15 |
| 11 | Automated bulk/OGC fetch for dense layers | 2026-06-15 |
| 12 | Optimise the constraint overlay (fix the hang) | 2026-06-18 |
| 13 | Supplementary + prioritisation fixes; bunds sliver filter | 2026-06-19/20 |
| 14 | Fast connected-components dissolve | 2026-06-22 |
| 15 | Point-ify the last polygon-polygon supplementary join | 2026-06-22 |
| *16* | *Per-water-body tiled runner — executed, document never committed (see above)* | *2026-06-23/24* |
| 17 | Consolidation + usability (`run_area.py`) | 2026-07-02 |
| 18 | Review fixes, ALC coverage QA, peat preprocess | 2026-07-06/08 |
| 19 | Peat finalised (grip/gully erosion screen) + EWCS truncation fix | 2026-07-10→23 |
| 20 | Close verifications, push (its PR step no longer applies) | 2026-07-23 |
| 21 | SPZ constraint fix + floodplain-woodland revert | 2026-07-23/24 |
| 22 | Consolidated finishing run — ALC Provisional, peat constraints | 2026-07-29 |
| 23 | Leaky barriers exclude Flood Zone 3 → **delivered `20260730` set** | 2026-07-30 |

Briefs 20 and 23 refer to a review pull request. That no longer applies — the history was
squashed for publication and the `feat/bulk-download` branch retired, so there is no PR to open
or merge. Both documents carry a note saying so.

## Where to look instead

- **Why a decision was made:** [`../methodology/`](../methodology/) — nine dated decision records.
- **What the model actually is now:** [`../methodology/10_current_configuration.md`](../methodology/10_current_configuration.md)
  — the delivered configuration in one place.
- **How to run it:** [`../RUN_GUIDE.md`](../RUN_GUIDE.md).
