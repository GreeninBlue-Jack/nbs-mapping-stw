# Brief 18 — Commit the review fixes, prove out peat, and gated re-run

**Author:** Jack Beard
**For:** development
**Status:** ready to execute — this is the single source of truth; do the tasks in order
**Status (2026-09-14):** executed 2026-07-06 to 2026-07-08 — adversarial-review fixes, ALC coverage QA and the peat preprocess. **Its peat vegetation/depth work was superseded by Brief 19**, which replaced the method with an erosion-only grip/gully screen.
**Depends on:** the review-response fixes already made and verified in the working tree; Brief 17 edits also present, uncommitted

## Where things stand (read before doing anything)

- The 20 review findings (2 critical, 4 high, 7 medium, 7 low) are **already implemented and verified** in the working tree (py_compile on all 16 edited files, a 25-check smoke suite, retroactive 747-tile overlap check = 0.000 m², a DONE-marker audit, recompute of the 2 damaged tiles, full re-merge of all three stages).
- The corrected full-STW deliverable is `outputs/<nbs>/<nbs>_full_<stage>_20260706.gpkg` (all three stages, uniformly dated). The re-merge produced **byte-identical** counts to the first corrected merge, confirming the merge is deterministic: pond 485,767 · leaky 47,537 · bunds 719,577 · floodplain 112,734 · riparian 109,005 · woodland 115,652. The interim `20260704` files are deleted; the superseded `20260624` set can be deleted when convenient.
- **This set is the six core layers only. Peat is unproven and not in it.**
- **Nothing is committed.** The working tree mixes the review fixes with pre-existing **Brief 17** edits, and — importantly — the four Brief 17 scripts are the *same four files the review touched*: `run_full_tiled.py` (C1), `merge_tiles.py` (H3/M5), `build_wb_tiles.py` (M6), `preprocess_aoi.py` (M4). So the entanglement is **hunk-level inside those four files**, not four separate files off to the side.

Two methodology decisions are **already made by Jack — do not reopen or change them**:

- **ALC stays on the Post-1988 Survey product** (partial coverage; `Grade 3a`/`3b` now scored 0.75, which is already implemented). Because coverage is partial, `alc_prio` is spatially uneven — make that transparent (Task B).
- **`tot_prio` keeps `skipna=True`** plus the `n_prio_scores` column (already implemented). Do **not** switch to strict NA propagation.

Work on a branch. Do not push until Jack signs off.

---

## Task A — Commit (Brief 17 peeled first, then thematic review commits)

The goal: Brief 17 leftovers land as their own commit, and the review fixes land in a small number of thematic commits — never one combined blob, and never Brief 17 mixed into a review commit.

### A0. Safety step before peeling
1. `git status` and `git diff` to see the full set of uncommitted changes.
2. Read `docs/briefs/Brief_17_consolidation_usability.md` to know exactly what Brief 17 was supposed to change in the four shared scripts, so hunks are attributed correctly.
3. A mis-attributed hunk is worse than a slightly coarser commit: **if any hunk in the four shared files is genuinely ambiguous between Brief 17 and a review fix, STOP and ask Jack** rather than guessing.

### A1. Peel Brief 17
For each of `run_full_tiled.py`, `merge_tiles.py`, `build_wb_tiles.py`, `preprocess_aoi.py`, use `git add -p` and stage **only** the Brief 17 hunks (use `s` to split, `e` to hand-edit a hunk that mixes both concerns). Do not `git add` these files wholesale. Commit the staged result:
```
Brief 17: <one-line summary of the consolidation/usability leftovers>
```

### A2. Commit the review fixes thematically
This is Jack's chosen granularity — Brief 17 separate, then logical groups. Use this grouping (collapse to fewer only if a group is trivially small):

1. **C1 — swallowed tile errors** — `run_full_tiled.py` (empty/`missing:`/`error:` separation, `FAILED` marker, no `DONE` on error, end-of-run breakdown) + `src/pipeline/utils.py` (`EmptyLayerError`, `validate(strict=)`). Message notes the two recovered tiles (GB104028042550, GB109054032750) and the tile-tolerant HML behaviour.
2. **M1 — `clip_to_aoi` GeometryCollection-safe** — `src/pipeline/utils.py`. Shares a file with #1; either `git add -p` its hunk or fold into #1 and list both findings.
3. **C2 + H1 — scoring** — `config/prioritisation_scores.yaml` + `src/pipeline/prioritisation.py` (Grade 3a/3b keys, unmapped-value reporter, skipna doc, `n_prio_scores`).
4. **H2 — peat hash + indexed-helper refactor** — `src/pipeline/peat_restoration.py`.
5. **H4 — ArcGIS paging** — `src/data_access.py` (OID `orderByFields`, `returnCountOnly` guard, OID dedupe).
6. **H3/M5 — merge** — `merge_tiles.py` (newest-per-tile dedupe + leaky point dedupe).
7. **M6 — tiling assertion** — `build_wb_tiles.py`.
8. **L1/L4/M4/M7 — hygiene** — `src/datasets.py` (`INCLUDE_EXPERIMENTAL=False`), `fetch_and_cache_remote_datasets.py` (manifest path crash), `preprocess_aoi.py` (buffer(0)→`make_valid`), `src/bulk_access.py` (bbox-only contract docstring).
9. **Docs** — `docs/reviews/code_review_20260703_RESPONSE.md`, `docs/methodology/06_pipeline_architecture.md`, `CONTRIBUTING.md`, docstring-only fixes (M2 RoFSW, M3 woodland, L6 "Calcareous"), and this brief.

**Acceptable fallback if Jack wants fewer commits:** Brief 17 (A1) + four thematic commits — (a) C1 tile-error handling + `EmptyLayerError`, (b) scoring (C2/H1), (c) merge/tiling geometry (H3/M5/M6/M1), (d) the rest + docs. **Not acceptable:** a single combined commit, or Brief 17 folded into any review commit.

**Gate A:** all edited files byte-compile; the 25-check smoke suite passes; `git log --oneline` shows Brief 17 isolated from the review fixes; the four shared scripts have their Brief 17 vs review-fix hunks in the right commits. Report the commit list to Jack. **Do not push.**

---

## Task B — ALC coverage transparency (Post-1988 decision is final)

The 3a/3b scoring and unmapped-value reporter are already implemented. What remains is to make the partial coverage visible:

1. Compute and record an **ALC coverage %** for the AOI (share of prioritised opportunity *area* with a non-null `alc_grade`). Emit it in the run log and write `outputs/qa/alc_coverage_<name>.json`.
2. Confirm the **unmapped-value reporter** now reports ~0 unmapped `alc_grade` values (3a/3b are scored). Any non-trivial count means the source schema shifted — surface it, don't swallow it.
3. Add one line to `docs/methodology/06_pipeline_architecture.md` stating the ALC coverage caveat for STW readers.

**Gate B:** ALC coverage % printed + saved; unmapped count ≈0. Report the number to Jack (a low value is the visible, expected cost of keeping Post-1988).

---

## Task C — Peat restoration: diagnose first, then fix

**Do not assume "no output" == "bug".** Peat produced nothing for two independent legitimate reasons plus real open TODOs. Work through them in order; report before changing methodology.

### C0. Confirm it was even asked to run
Peat is experimental and gated. Both the fetch and the tiled run must be passed `--include-experimental`, and `src/datasets.py` now ships `INCLUDE_EXPERIMENTAL=False`. The June/July runs did **not** pass the flag, so peat's absence from the `20260706` set is expected, not a bug.

### C1. Diagnose peat extent over the STW AOI (the gating question)
The STW area is largely lowland Midlands; England Peat Map peaty-soil extent may be genuinely sparse or near-zero there.
- Fetch **"England Peat Map — Peaty Soil Extent"** clipped to `stw_full_aoi.gpkg`; report polygon count + total area (ha).
- If near-zero: peat is **legitimately empty** for STW. Emit a clear logged statement ("N peaty-soil polygons, X ha in AOI → no peat opportunity") via the new `empty:` path, report to Jack, and stop the peat track — do not force an output.
- If non-trivial: continue C2–C4.

### C2. Enriched-extent prerequisite
`peat_restoration.run` needs `data/processed/peat_extent_enriched_<hash>.gpkg` from `scripts/preprocess_peat_depth.py` (the only rasterio user).
- Run `preprocess_peat_depth.py --aoi data/processed/stw_full_aoi.gpkg` **once** first.
- In the **tiled** path each tile passes its haloed WB geometry, whose WKB hash will **not** match the full-AOI producer hash, so `_find_enriched_peat` uses the **newest-file fallback** — this is expected after the H2 fix, not an error. Confirm the fallback fires and that `peat_depth_cm_mean` is present so the ≥40 cm filter actually engages (else the depth filter is silently skipped).

### C3. Resolve the veg_class stubs (long-standing open TODO)
`config/nbs/peat_restoration.yaml` `dry_peat_veg_classes` / `wet_bog_veg_classes` are **guessed strings**. On first real fetch of "England Peat Map — Vegetation and Land Cover on Peaty Soils":
- Print the **actual distinct `veg_class` values** (and confirm the attribute is even called `veg_class`).
- Map the real values into the dry/wet lists in the YAML. Until then, Step 2's vegetation signal contributes nothing and Step 3 excludes nothing (both silently no-op via `.isin([...])`).
- The upland erosion layers (bare peat, grips, gullies, haggs) are *upland* features and may be empty over STW — if so, Step 2 hits the "no degradation signal → return all restorable peat" path. Flag that to Jack as a methodology choice, don't ship it blind.

### C4. Peat scale sanity
`peat_restoration.run` still does whole-geometry `union_all`/`intersection` in Steps 2–3. Confirm it completes in reasonable time on the largest peat-bearing tile; watch for the GEOS blow-up the six core layers had.

**Gate C:** report (a) peat extent count/area over STW AOI, (b) whether enriched depth filtering engaged, (c) the real veg_class values + updated YAML, (d) whether peat is legitimately empty or producing genuine opportunity. **Jack decides** whether peat ships based on this report.

---

## Task D — Gated re-run

The six core layers are final and deterministic (`20260706`); **do not** redo them unless Jack explicitly asks for a clean from-scratch reproduction. The purpose of this run is (1) to produce peat if Gate C found non-trivial coverage, and (2) a reproducibility spot-check. Peat runs with `--include-experimental`.

At every gate: if a check fails, **stop and report to Jack** — do not auto-proceed. Use the new `empty:` / `missing:` / `error:` / `FAILED` distinctions as first-class signals.

**Gate D0 — pre-flight.** Tasks A–B landed; smoke suite green; `INCLUDE_EXPERIMENTAL=False`; branch clean. Confirm with Jack whether this run is peat-only (default) or a full core reproduction.

**Gate D1 — AOI + tiles.** Tile index present; the **M6 overlap assertion passes (≈0 m²)**; tile count as expected (747 for STW); all EPSG:27700.

**Gate D2 — fetch / prefetch.** `--include-experimental` fetch: bulk national files download + validate once; per-dataset feature counts sane vs `manifest.csv`; **zero fetch errors surfaced (not swallowed)**; peat ArcGIS/BGZ layers return features; ALC coverage % (Task B) computed. Report the manifest summary + any non-ok rows.

**Gate D3 — compute smoke (subset first).** Run `run_full_tiled.py --include-experimental --only-tiles`/`--limit` on a small set (the 3 Avon parity tiles + at least one peat-bearing tile if Gate C found any). Inspect:
- end-of-run breakdown shows **0 `error:` and 0 `FAILED`** (empty/missing are fine);
- one sample tile: layers `is_valid.all()`, EPSG:27700, `tot_prio ∈ [0,1]`, `n_prio_scores ∈ [2,5]`, `WB_ID`/`WB_NAME` populated, `CEH_LU` text labels.
Report; proceed only on Jack's OK.

**Gate D4 — full compute.** Run all tiles (peat included). **Any `FAILED` marker or `error:` entry must be investigated before merge** — this is exactly the C1 class of bug we just fixed; do not let it recur silently. Report done/empty/error counts per layer.

**Gate D5 — merge.** `merge_tiles.py` with newest-per-tile dedupe:
- no tile contributes two dated files (H3);
- leaky_barriers has **no duplicate boundary points** (M5);
- the six core layers, if re-run, match the `20260706` baseline exactly (deterministic — any drift means a regression, investigate); if peat-only, the core set is untouched;
- peat merges cleanly; `is_valid.all()` true, EPSG:27700, `tot_prio ∈ [0,1]`.
Report the count table vs baseline.

**Gate D6 — peat outcome.** Peat outputs present with sane geometry/validity, **or** a clear logged "legitimately empty — N peat polygons in AOI" statement backed by Gate C. No silent absence either way.

**Gate D7 — QA / sign-off.** Dev-AOI parity for the six core layers unchanged/improved vs R (geometry, not tot_prio values); `tot_prio`/`n_prio_scores` distributions sane; note anything for a QGIS visual cross-check. Summarise for Jack and hold for sign-off before any push or deliverable-metadata commit.

---

## Acceptance criteria (whole brief)

- Commits: Brief 17 isolated (hunk-level peel from the four shared scripts done correctly); review fixes in thematic commits per Task A; smoke suite green; nothing pushed.
- ALC coverage % recorded + caveat documented; unmapped `alc_grade` count ≈0.
- Peat: an evidence-backed answer to "bug or legitimately empty", real `veg_class` values in the YAML, and depth filtering confirmed to engage.
- Re-run (if it proceeds past Gate C): completed through the gates with **0 unexplained `error:`/`FAILED` tiles**, a clean deduped merge, and — if core layers were re-run — counts identical to `20260706`.
- No silent failures anywhere: every empty labelled `empty:`, every error surfaced with a traceback + `FAILED` marker.

## Explicitly out of scope / do not do

- Do not switch ALC to Provisional (Jack chose Post-1988).
- Do not switch `tot_prio` to strict NA propagation.
- Do not re-run/regenerate the six core layers unless Jack asks — `20260706` is final.
- Do not push or commit deliverable metadata until Gate D7 sign-off.
- Do not combine Brief 17 with the review fixes in one commit, and do not stage the four shared scripts wholesale.
- Do not "improve" methodology silently — any new deviation (e.g. the peat "no degradation → return all peat" path) is flagged to Jack, per CONTRIBUTING.md.
