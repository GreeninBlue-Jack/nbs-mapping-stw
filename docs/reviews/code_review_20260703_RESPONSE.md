# Response to Adversarial Review 2026-07-03 — Implementation Record

**Implementer:** Jack Beard, 2026-07-04
**Review:** `docs/reviews/code_review_20260703.md`
**Status (2026-09-14):** Complete — this is the record of how every finding from the 2026-07-03
review was dispositioned. The output set it produced (`20260706`) has since been superseded by
the delivered `20260730` set; see
[`../methodology/10_current_configuration.md`](../methodology/10_current_configuration.md).
**Scope:** every finding dispositioned; all code fixes implemented, smoke-tested, and the
two damaged tiles recomputed + full prioritised/opportunity/supplemented sets re-merged.

## Headline outcomes

1. **The review's central C1 fear was confirmed and quantified.** Scanning the delivered
   run's 747 `DONE` markers: the `skip:` entries were 383 × `ValueError` (legitimate
   zero-features — now recorded as `empty`) and **6 × `KeyError` — real swallowed bugs**
   on 2 tiles (`GB104028042550` bunds; `GB109054032750` pond/leaky/bunds/floodplain/
   riparian). Root cause: those tiles have zero HML recharge coverage; the per-tile HML
   fetch produced an empty layer and supplementary's Brief 13 A2 "raise loudly" check
   killed the whole layer output, which the old handler recorded as `skip:` and marked
   DONE. Both tiles were recomputed with the fixed code (all 6 lost layer outputs
   recovered: bunds 60+122, pond 9, leaky 2, floodplain 25, riparian 61 features).
2. **The delivered merge had real double-counting.** Re-merging with the H3/M5 fixes:
   up to 5 stale earlier-dated tile files per layer/stage were being concatenated twice,
   and **767 duplicate boundary points** existed in the prioritised leaky_barriers (815 at
   the opportunity stage — waterline sample points frequently sit exactly on WB
   boundaries, far commoner than the review's "rare" estimate).
   **The corrected deliverable set is `outputs/<nbs>/<nbs>_full_<stage>_20260706.gpkg`**
   (all three stages re-merged 2026-07-04/06); the 20260624 set is superseded.
   Corrected prioritised counts: pond 485,767 · leaky 47,537 pts · bunds 719,577 ·
   floodplain 112,734 · riparian 109,005 · woodland 115,652 (all layers valid,
   EPSG:27700).
3. **The M6 tiling assumption was verified retroactively:** the real 747-tile index has
   2,069 adjacent pairs and 0.000 m² total overlap — merge-by-concat was sound.

## Disposition of findings

| # | Finding | Action |
|---|---|---|
| C1 | `compute_tile` swallows exceptions, writes DONE | **Fixed.** `utils.EmptyLayerError` (raised by `validate()` on zero features) → `empty`; `FileNotFoundError` → `missing:`; anything else → `error:` + full traceback to compute.log + `FAILED` marker + **no DONE** (tile retried/visible). End-of-run per-layer ok/empty/missing/error breakdown added. Delivered-run markers audited (see above). |
| C2 | ALC wrong product + silent NaN scoring | **Scoring fixed; source flagged.** `Grade 3a`/`Grade 3b` → 0.75 (= R's `Grade 3`) in `prioritisation_scores.yaml`; `Other`/`Not Surveyed` deliberately unmapped. Any unmapped scoring value in any key is now reported loudly with counts at runtime. **Source-product switch (Post-1988 → Provisional) is an OPEN QUESTION for Jack** — flagged in the registry notes, the YAML, and doc 06; needs a decision + re-fetch (coverage differs). Not changed unilaterally per CONTRIBUTING.md. |
| H1 | skipna mean undocumented | **Documented as deliberate + provenance added.** skipna retained (partial-coverage supplementaries at STW scale); `n_prio_scores` column (2–5) on every prioritised output; per-run distribution printed; doc 06 updated (Known deviations table + Prioritisation method). |
| H2 | peat AOI hash is a constant | **Fixed both sides.** Hash = sha1 of AOI geometry WKB in `peat_restoration._aoi_hash` AND `preprocess_peat_depth._aoi_hash` (producer previously hashed file bytes — never matchable by the consumer). Fallback now picks the NEWEST enriched file with a loud warning. |
| H3 | merge date-wildcard double-count | **Fixed.** `_latest_per_tile` keeps the newest dated file per (tile, nbs, stage); fired on the real merge (9 stale files skipped). |
| H4 | ArcGIS paging: no order, no guard | **Fixed.** OID field probed from layer metadata; `orderByFields` set (graceful fallback if rejected); `returnCountOnly` pre-flight; post-concat OID dedupe; RuntimeError on count mismatch — same discipline as WFS/OGC. |
| M1 | clip GeometryCollections dropped | **Fixed.** `clip_to_aoi` extracts the parts matching the input geometry family from any GC and drops emptied rows. Smoke-tested with a real GC-producing clip. |
| M2 | Stale RoFSW docstrings | **Fixed** (leaky_barriers, bunds): NaFRA2 High+Medium = 1-in-100, matching R. |
| M3 | Woodland "down-weighting" never happens | **Docs corrected** (module, layer YAML, prioritisation.yaml, doc 06): `wood_s` is label-only, matching R. Wiring a woodland-specific `wood_prio` would be a methodology change — not implemented without a request. |
| M4 | `preprocess_aoi` buffer(0) | **Fixed.** `fix_invalid()` helper — `make_valid(method="structure")` on the invalid subset only; all 4 call sites switched. |
| M5 | Boundary points double-counted | **Fixed.** merge dedupes identical point coordinates (WKB) keeping first; dropped 767 on the real merge. |
| M6 | Tile overlap unverified | **Fixed + verified.** `check_no_overlap()` in `build_wb_tiles` (also runs for `run_area.py` via `build_tiles`); raises above 1 m² total overlap. Real 747-tile index passes with 0.000 m². |
| M7 | bbox-only bulk clip implicit | **Documented** on `read_bulk_clipped` and `load_layer` docstrings as an explicit contract. |
| L1 | `INCLUDE_EXPERIMENTAL = True` | Set **False** (delivery phase; gates audit only). |
| L2 | "threads" docstring | Fixed → processes. |
| L3 | `validate()` never raises on invalid | `strict=True` parameter added (raises); default still warns with count. |
| L4 | `root / OUT_DIR` on absolute path | Fixed — and it was worse than "confusing": `out_path.relative_to(root)` would have raised `ValueError` on every dataset since Brief 17 C1 made OUT_DIR absolute; manifest now records absolute paths. |
| L5 | `if "veg" not in dir()` | Fixed → `veg = None` init / `if veg is None`. |
| L6 | "Calcerous" | Fixed → "Calcareous" (label only; joined on numeric code, so no join impact). |
| L7 | peat whole-AOI unions | **Refactored** to `keep_within`/`subtract_mask`/`dissolve_connected` (dissolve_connected reproduces the union-first merge semantics). Peat remains experimental/unvalidated. |
| — | floodplain R name-swap note | One-line comment added to the module docstring. |
| — | rep-point join → count parity meaningless | Noted in doc 06 parity note. |

## Additional fix found during implementation (beyond the review)

**`supplementary.prepare_supplementary_context`:** the A2 empty-layer raise is now scoped to
the monolithic `dev`/`full` path (where empty = stale cache). On a per-WB tile, zero HML
coverage is legitimate → join columns null + loud warning. Without this, the C1 fix would
have made the two affected tiles retry forever. This is the actual bug behind the 6
`skip:KeyError` entries in the delivered run.

## Open questions for Jack (decisions needed)

1. **ALC source (C2):** switch registry back to the Provisional ALC (national coverage,
   `Grade 3`) to match R, then re-fetch + re-run? Current state (Post-1988 + 3a/3b keys)
   restores scoring but not coverage.
2. **skipna semantics (H1):** confirmed as a deliberate deviation and now documented +
   instrumented with `n_prio_scores`. If R-strict NA propagation is preferred instead, it
   is a one-line change — but many features would drop to NA tot_prio.
3. The 20260624 output set in `outputs/` is superseded by `*_20260706.gpkg` (corrected
   double-counting + recovered tiles; all three stages). Delete the old set when
   convenient.
