# Brief 20 — Close verification, push, open the review PR

**Author:** Jack Beard
**For:** development
**Status:** ready to execute — do the tasks in order
**Status (2026-09-14):** executed 2026-07-23 — the two verifications were closed and the re-run traps documented. Its "final" framing was superseded by Brief 21. **The review PR referred to below was never opened, and no longer applies:** under Brief 24 the repository history was squashed for publication and `feat/bulk-download` was retired, so there is no branch to raise a PR from. Ignore the PR instructions in Task 3.
**Continues:** Brief 19 complete. Jack has signed off the peat outputs after a QGIS visual check.

## Context

All of Briefs 17–19 are committed on branch **`feat/bulk-download`**; nothing is pushed. Jack has now visually checked the peat grip/gully corridors in QGIS and is happy. Deliverable state:
- Five core layers — `outputs/<nbs>/<nbs>_full_<stage>_20260706.gpkg` (untouched, final).
- `woodland_planting` — `…_20260710.gpkg` (+47% features / +21% area after the EWCS truncation fix).
- `peat_restoration` — `…_20260720.gpkg` (new, erosion-only experimental screening layer).

This brief closes two outstanding verifications, pushes the branch for backup, and opens a **review** PR (Jack merges — do NOT auto-merge). Work stays on `feat/bulk-download`.

---

## Task 1 — Close two verifications before the PR

### 1a. Confirm the grips/gullies fetch never hit the 2000 cap (H4 insurance)
Grips and gullies are ArcGIS FeatureServers with `max_record_count = 2000`, and the upland tiles carry 3,472 and 10,653 grip/gully features — well over the cap that silently one-paged EWCS and cost the woodland re-run. The `--refetch` in Brief 19 presumably used the H4-fixed pagination, but this was never explicitly confirmed.
- Check the peat run's per-tile fetch logs (or re-probe a couple of the densest upland tiles) for any grips or gullies fetch that returned **exactly 2000** — the cap-hit signature.
- **If none:** record "grips/gullies fetch complete, no 2000-cap hits" and proceed.
- **If any:** re-fetch + recompute peat on the affected tiles with the fixed pagination and re-merge peat (fresh date). Report the before/after.

### 1b. Merge + marker robustness (recurrence — do not leave as a manual patch)
In Brief 19 the peat merge double-counted stale old-method tile files (fixed by manually deleting 15 files) and a stale June `FETCHED` marker blocked the refetch (fixed with `--refetch`). Both are recurrences of the H3/M5 and resumability classes we already "fixed" — meaning the fix doesn't cover superseded-*method* files or stale markers, and the next person to run this (STW) will hit the same traps.
- Confirm whether `scripts/merge_tiles.py` actually dedupes to the newest file per (tile, nbs, stage). If it does not robustly exclude superseded files, **either** make it robust **or** document the trap explicitly in `RUNBOOK.md` with the manual cleanup step.
- Same for stale `FETCHED`/`DONE` markers: document (in `RUNBOOK.md`) when a re-run needs `--refetch`/`--force` and how to spot a stale-marker false-empty (implausible `empty:` count), since that's how Brief 19 caught it.
- This is about not handing STW a pipeline with known silent traps — a doc note is acceptable if a code fix is disproportionate, but it must not stay undocumented.

**Gate 1:** report the fetch-cap result and the merge/marker disposition (fixed vs documented). Report to Jack.

---

## Task 2 — Push the branch (backup, no merge)

Push `feat/bulk-download` to `origin`. This is backup + review enablement only — it merges nothing. Confirm the push succeeded and report the remote branch URL.

Before pushing, sanity-check that all the working docs are committed and current, since this is also the "put it on GitHub" milestone (project instruction): `docs/methodology/03_*` (erosion-only peat), `docs/methodology/06_*`, `docs/reviews/code_review_20260703_RESPONSE.md`, and Briefs 17–20. If any are uncommitted, commit them (docs commit) before the push.

---

## Task 3 — Open the review PR (do NOT merge)

Open a PR from `feat/bulk-download` into the default branch (confirm the base — likely `main`). Mark it a review PR; Jack merges after review. Use this description as the template:

```
## Summary
Adversarial code+methodology review of the NbS pipeline, the fixes it surfaced, a
corrected full-STW re-run, and a new experimental peat layer. Built over Briefs 17–20.

## What changed
- **Review fixes (20 findings: 2 critical, 4 high, 7 medium, 7 low)** — see
  docs/reviews/code_review_20260703_RESPONSE.md for the disposition table.
  Headline: silent per-tile errors (C1), ALC scoring gap (C2), skipna semantics (H1),
  peat AOI-hash bug (H2), ArcGIS pagination truncation (H4), merge double-count (H3/M5).
- **Core EWCS truncation fix** — the H4 pagination bug had silently truncated EWCS on
  376/747 tiles in the June run. Re-fetched + recomputed woodland only: +47% features /
  +21% area. → woodland_planting_full_*_20260710.gpkg.
- **Peat restoration (experimental)** — rewritten to an erosion-only screening method:
  buffered (10 m) upland grips + gullies → dissolve → constraints → clip. Deliberately an
  upland erosion/drainage screening map (Moor Resilience 2030), no depth refinement,
  requires site validation. → peat_restoration_full_*_20260720.gpkg (6,578 ha).

## Deliverable state / blast radius
- Five core layers (pond, leaky, bunds, floodplain, riparian) — UNCHANGED, 20260706.
- woodland_planting — 20260710 (EWCS fix only).
- peat_restoration — 20260720 (new).
- ALC stays Post-1988; tot_prio keeps skipna + n_prio_scores (both documented decisions).

## Known gotchas (see RUNBOOK.md)
- <fetch-cap result from Task 1a>
- <merge dedupe / stale-marker disposition from Task 1b>

## Not in scope
- Lowland/agricultural fen peat (erosion-only method is upland by design).
- Six core layers not recomputed — only woodland re-merged.
```

Fill the two `<…>` lines from Task 1's findings. Do NOT merge — leave for Jack.

---

## Acceptance criteria
- Task 1a fetch-cap result reported; if capped, peat re-merged.
- Task 1b merge/marker either fixed or documented in RUNBOOK.md — not left as an undocumented manual patch.
- All methodology docs + Briefs 17–20 committed; `feat/bulk-download` pushed to origin.
- Review PR opened into the default branch with the description above; **not merged**.

## Explicitly out of scope / do not do
- Do NOT merge the PR — Jack reviews and merges.
- Do NOT recompute the five core `20260706` layers.
- Do NOT reintroduce the retired peat machinery (veg/bare peat/haggs/depth gate).
- Do NOT switch ALC to Provisional or `tot_prio` to strict NA propagation.
