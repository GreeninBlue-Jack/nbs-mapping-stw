# Brief 06 — Paged WFS Fetch (pagination-first)

**Repo:** `python/nbs-mapping`
**Date issued:** 2026-06-05
**Status (2026-09-14):** executed 2026-06-11 — paged WFS fetch with a no-silent-partial guard. Superseded in part by Brief 11: the dense layers later moved off plain WFS onto `ogc_api` / `bulk_download` routes.
**Follows:** Brief 05 (source corrections).
**Background:** `docs/methodology/08_scaling_and_fetch_strategy.md`.

**Decision:** Fix the WFS pagination first and see if that resolves the partial-output problem. Per-waterbody tiling is **deferred** (a contingency for full-STW scale only — see bottom). Bulk downloads are **not** being used.

---

## 0. Why

Raw WFS outputs are coming back **partial**. `src/data_access.py::query_wfs_features()` issues a single `GetFeature` with `COUNT=50000`, never paginates, and never checks the returned count against the server's `numberMatched` — so any AOI exceeding GeoServer's page cap is silently truncated.

---

## The task — paged fetch + no-silent-partial guard

Modify `src/data_access.py::query_wfs_features()`:

1. **Paginate** WFS 2.0 with `STARTINDEX` + `COUNT` (page size, default 10,000, as a configurable arg). Loop, accumulating each page's features, until a page returns fewer than the page size.
2. **Determine `numberMatched`** — parse it from the `GetFeature` responses, or issue a preliminary `resultType=hits` request before paging.
3. **Guard:** after the loop, if the accumulated feature count != `numberMatched`, **raise** an informative error naming the dataset/typename, AOI bounds, and expected-vs-received. No silent partials (CONTRIBUTING.md "no silent failures").
4. Preserve the existing CQL-BBOX embedding (the GeoServer 500 workaround) and CRS handling.
5. Concatenate pages into one GeoDataFrame; keep the per-page temp-file streaming to bound memory.
6. Add light per-page retry on timeout; keep the page size conservative for dense layers.

**Acceptance:** for a known-dense layer (RoFSW `ROFSW_0_0_Hazard`, `risk_band IN ('High','Medium')`) over the dev AOI, the function returns a feature count equal to the server's `numberMatched` for that bbox, and **raises rather than truncates** if a page is missed.

---

## Then

1. **Re-fetch the dev AOI** and confirm counts are complete (no truncation):

   ```
   python scripts/fetch_and_cache_remote_datasets.py
   ```

2. Run the dev parity report (now trustworthy):

   ```
   python scripts/run_pipeline.py --all --aoi dev
   ```

3. Report: the dev-AOI completeness check (counts vs `numberMatched` per WFS layer), then the parity numbers per layer/stage, and anything still open.

---

## Docs + commit

- Commit the paged-fetch change with a clear message; `docs/methodology/08_*` is already written — review/commit it. Update CONTRIBUTING.md Project Status.
- Reminder: `git diff` after any `src/datasets.py` edits (OneDrive truncation history).

---

## Deferred — per-waterbody tiling (only if the full-STW run proves too heavy)

Not part of this brief. If, after pagination, the **full-STW** run is too slow / memory-heavy / timeout-prone, revisit `docs/methodology/08_scaling_and_fetch_strategy.md §3`: process one WFD river waterbody catchment at a time (tile index = WFD River Waterbody Catchments), with a **+250 m halo** (process haloed, clip final output back to the exact WB) and **clip-to-WB before merge** (so tiles don't overlap and no de-duplication is needed), resumable per-WB cache, default on for `--aoi full` only. Bulk/local staging (§4) is **not** being pursued.
