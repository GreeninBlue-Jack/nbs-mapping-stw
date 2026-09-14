# Brief 22 — Consolidated finishing run (ALC + peat constraint + floodplain woodland)

**Author:** Jack Beard
**For:** development
**Status:** do this in ONE sitting on a stable connection — supersedes the piecemeal Brief 21 re-run
**Status (2026-09-14):** executed 2026-07-29 — ALC switched to the national Provisional product, peat moved to physical-constraints-only, producing the consolidated `20260729` set. **Its leaky-barriers layer was superseded by Brief 23**, which produced the delivered `20260730` set.

## Why this brief exists

The Brief 21 SPZ re-run produced `20260724` (6 layers), but it is **not final** — it predates two approved changes and floodplain is broken:

1. **ALC → Provisional not applied.** The `20260724` set still uses the Post-1988 Survey ALC (sparse patchwork → `alc_grade` null over most of STW). Jack approved switching to the national Provisional ALC. ALC feeds supplementary/prioritisation of **all seven layers**, so this restages every layer.
2. **Peat constraint fix not applied.** Peat is still cropped by the CEH bog mask (class 11) in the generic constraints. Approved fix: peat uses physical constraints only (no CEH land-cover mask).
3. **Floodplain woodland broken → reverted to OGC (committed in Brief 21).** The Brief 17 `bulk_download` for WWNP Floodplain Woodland used a spatially **incomplete** DSP export (202k national but ~0 over large STW areas; OGC 199 vs bulk 0 on a sample tile), collapsing floodplain 712→211 tiles. Reverted to `ogc_api`; needs an OGC re-fetch to recompute.

Rather than three more partial runs, do **one consolidated recompute** with all three folded in → one internally consistent dated set that supersedes `20260706/10/20` and `20260724`.

## Prerequisite — the real bottleneck is the environment, not the code

The floodplain OGC re-fetch has repeatedly failed on **intermittent internet (DNS `getaddrinfo` / SSL handshake drops) + the machine sleeping for days**. Do NOT attempt this on flaky wifi. Before starting:
- Stable, sustained internet connection.
- **Disable sleep** for the duration (the resumable run still works across sleeps, but it dribbles across days otherwise).
- Use **gentle fetch concurrency** (`--fetch-workers 2`, not the default 4) — the DSP OGC server refuses connections under load (the Brief 08–10 lesson); the first stuck run was 4 workers hammering it.

On a stable connection the per-tile OGC path works — it's how leaky/bunds got their RoFSW OGC data in the `20260724` run.

## Task 1 — ALC → Provisional (registry + score table)

- Swap the `Agricultural Land Classification (ALC)` registry entry to the **Provisional ALC (England)** national product (Natural England; digitised 1:250,000; national coverage, unlike the Post-1988 survey patchwork). Prefer a verified national file / OGC route; keep the old Post-1988 `bulk_url` dormant with a note.
- Revert the `alc_grade` score table in `config/prioritisation_scores.yaml` to single **`Grade 3`** keys (Provisional does not subdivide 3a/3b) — matches R.
- Keep the unmapped-value reporter on; it should now report ~0 unmapped (national coverage).
- Doc note (methodology 06 / data audit): ALC switched Post-1988 → Provisional because the Post-1988 survey is a sparse patchwork (~1.9% area, 0% on upland peat), leaving `alc_grade` null across most of STW; Provisional is national and matches the R model.

## Task 2 — Peat constraint fix (don't crop the peat)

- Give peat a **physical-constraints-only** layer: keep roads (10 m), rail (20 m), surface water, and SPZ (1/1c/2), but **drop the CEH land-cover mask** (which excludes bog class 11 — the peat itself). Cleanest: parameterise `build_constraints_layer` to omit the CEH component and build a peat-specific constraint in `compute_tile`, passed to `peat_restoration.run`.
- Doc note in methodology 03: peat is constrained by infrastructure only; the CEH land-cover mask is excluded because it removes the peat/bog the layer is mapping.

## Task 3 — Floodplain woodland fetch (OGC, gentle)

- Woodland is already reverted to `ogc_api` (in Brief 21). With a stable connection + `--fetch-workers 2`, the per-tile OGC re-fetch completes.
- **Follow-up for STW robustness (NON-blocking — note it, don't let it hold the deliverable):** per-tile OGC × 747 of a dense layer is fragile for anyone re-running against the flaky DSP. The durable fix is a **fetch-once-over-AOI OGC route** — a single *resumable* paged pull over the whole AOI, staged locally, clip-many (download-once/clip-many, like `bulk_download` but OGC-sourced). This needs `query_ogc_features` made resumable (page cache keyed by query identity, like the WFS `partial_cache_dir`), since it currently loses progress on a mid-pull drop. Applies equally to RoFSW and Floodplain Reconnection (also per-tile OGC). Spec as a later brief unless trivial to fold in now.

## Task 4 — Consolidated recompute (efficient: re-fetch only what changed)

- Force a **recompute of all tiles** so the ALC, peat-constraint, and SPZ changes all propagate: constraints and supplementary/prioritisation re-derive for every layer.
- **Minimise network load:** reuse the existing tile fetch caches; only re-fetch the two datasets that actually changed — **ALC (now Provisional)** and **Floodplain Woodland (OGC)**. (`--refetch` those; keep the rest cached; `--force` the compute, or clear DONE markers so tiles recompute without re-fetching unchanged layers.)
- Clear stale per-tile output files first (RUNBOOK §7b) so the merge can't pick up `20260724`/old-method files.
- Keep the C1 discipline: `empty:`/`error:`/`FAILED` surfaced; investigate any before merge. Merge cross-check must pass (no layer collapse like the floodplain regression).

## Task 5 — Merge, QA, push

- Merge all 7 layers + peat to ONE fresh date, superseding `20260706/10/20` and `20260724` (don't delete the old sets until Jack confirms the new one).
- **QA table:** per-layer features/area/valid/CRS/`tot_prio ∈ [0,1]`; confirm `alc_grade` now populated ~nationally (the point of Task 1); confirm peat no longer cropped by bog (area up vs `20260720`); confirm floodplain back to ~full coverage (~712 tiles, not 211); North Notts opportunity gain from the SPZ fix quantified.
- Commit; push `feat/bulk-download`; update the draft PR body to the single consolidated set; add the deliverable README notes (gpkg authoritative / shapefile lossy; ALC now Provisional national).
- Do NOT merge — Jack reviews.

## Acceptance criteria
- One consistent dated set, all seven layers + peat, superseding every prior set.
- ALC Provisional applied (`alc_grade` populated nationally, single Grade 3 key); peat uncropped by CEH mask; floodplain back to full coverage on OGC.
- 0 unexplained `error:`/`FAILED`; merge cross-check clean; North Notts gain + full QA table reported.
- Branch pushed; PR updated; not merged.

## Explicitly out of scope / do not do
- Do NOT attempt the OGC re-fetch on flaky/train internet — stable connection + no-sleep only.
- Do NOT use the incomplete Floodplain Woodland bulk file, or go back to Post-1988 ALC.
- Do NOT keep the patchwork dating — one consolidated set replaces `20260706/10/20/24`.
- Do NOT merge the PR — Jack reviews and merges.
