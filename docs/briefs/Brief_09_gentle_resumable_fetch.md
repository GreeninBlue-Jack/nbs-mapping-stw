# Brief 09 — Gentler, resumable WFS fetch (survive the flaky EA server)

**Repo:** `python/nbs-mapping`
**Date issued:** 2026-06-11
**Status (2026-09-14):** executed 2026-06-12 — resumable per-page cache plus pacing/jittered backoff.
**Follows:** Brief 08 (streaming-retry hardening).
**Background:** `docs/methodology/08_scaling_and_fetch_strategy.md §2`–§3.

**Symptom (after Brief 08):** the fetch now fails *cleanly* instead of hanging, but the EA
GeoServer **refuses connections under sustained load**. Fetching dense layers back-to-back with no
pacing exhausted all retries — RoFSW was refused at page 1 ("Max retries exceeded / connection
refused"); WWNP Runoff Attenuation died at 60,000 of 83,955 features. Each failure was a genuine
server refusal, and a failed run **restarts from scratch and re-hammers the server**.

**Note on approach (decided 2026-06-11):** do NOT parallelise — the server is the bottleneck and is
already refusing sequential load; concurrency would worsen it. The fix is gentler, paced, resumable
fetching. Design the resume cache to be **bbox-keyed** so the same machinery extends to a per-
waterbody tiled fetch for full-STW later (doc 08 §3) — but tiling is **not** part of this brief.

---

## The task

### A. Resumable per-page cache (the key change)
In `src/data_access.py::query_wfs_features()`:

- Cache each page **only after it is fully downloaded AND successfully parsed**, to a per-query
  partial dir, e.g. `data/processed/raw_clipped/_partial/<slug>/start_<STARTINDEX:08d>.gpkg`.
- Write a `query.json` manifest in that dir recording query identity: typename, rounded bbox, CQL,
  `page_size`, and `numberMatched`. On entry, if an existing manifest **differs** from the current
  query (e.g. `numberMatched` changed due to a data update), clear the partial dir and start fresh.
- The page loop: for each `STARTINDEX`, if its cache file exists load it (log `(cached)`) and skip
  the network call; otherwise fetch (with the Brief 08 retry + pacing below), parse, then write to
  cache. Resume naturally begins at the first missing `STARTINDEX`.
- On completion, assemble all pages, **keep the existing `numberMatched` completeness guard**, write
  the final `<slug>.gpkg`, then delete the `_partial/<slug>/` dir.
- `data/processed/` is gitignored, so the partial cache never pollutes commits.

### B. Gentler pacing + sturdier retries
- Add a configurable inter-page delay (`_PAGE_DELAY`, default ~0.5–1.0 s) — sleep between page
  requests, not just on retry.
- Raise `_PAGE_RETRIES` (3 → 5) and use longer backoff with jitter
  (e.g. `sleep(min(60, base * 2**attempt) + random_jitter)`, base ~3 s). ConnectionError /
  "max retries exceeded" is already caught (RequestException) — ensure it is treated as retryable.
- Add a short inter-**layer** delay in `scripts/fetch_and_cache_remote_datasets.py` (configurable
  `--delay`, default ~2 s) so moving between datasets doesn't slam the server.

### C. Lower the other dense layer's page size
- Set `"wfs_page_size": 5000` on the **WWNP Runoff Attenuation Features** entry (83,955 features).
  RoFSW already at 2000 (Brief 08). Leave the rest at the 10,000 default.

---

## Acceptance

- Killing a run mid-layer and re-running **resumes**: already-fetched pages load from cache (visible
  as `(cached)`) and the fetch continues from the first gap — no re-download, no re-hammering.
- RoFSW and WWNP Runoff Attenuation complete (across one or more runs) with assembled
  count == `numberMatched`; partial dirs are cleaned up on success.
- Other layers fetch unchanged when `wfs_page_size` is unset.
- If a single `STARTINDEX` repeatedly fails every attempt, the run stops with a clear error naming
  layer + STARTINDEX (so it's obvious which page/layer to lower further or stage locally).

## Then

```
python scripts/fetch_and_cache_remote_datasets.py --aoi data/reference/R_Model/Wavon_WCS_simple.shp --force
# (re-run the same command if the server drops a layer — it will resume)
python scripts/run_pipeline.py --all --aoi dev
```

## Docs + commit

- Update `docs/methodology/08_scaling_and_fetch_strategy.md §2` with the resumable cache + pacing,
  and add a sentence to §3 noting the cache is bbox-keyed and ready to back per-WB tiling. Update
  CONTRIBUTING.md Project Status.
- `git diff` after editing `src/datasets.py` (OneDrive truncation history) before committing.

Commit message:
```
Make WFS fetch gentler and resumable (survive flaky EA server)

The EA GeoServer refuses connections under sustained load: fetching dense
layers back-to-back with no pacing exhausted all retries (RoFSW refused at
page 1; WWNP Runoff died at 60k/84k). Hardening alone could not recover
because each failure was a genuine refusal, and a failed run restarted from
scratch and re-hammered the server.

query_wfs_features() now caches each fully-downloaded, parsed page under
data/processed/raw_clipped/_partial/<slug>/ keyed by query identity
(typename, bbox, cql, page_size, numberMatched); a re-run skips cached pages
and resumes from the first gap, then assembles and cleans up on completion.
Adds inter-page pacing, more retries with longer jittered backoff, and an
inter-layer delay in the fetch script. Lowers the WWNP Runoff Attenuation
page size. numberMatched completeness guard retained. Cache is bbox-keyed so
it can back per-waterbody tiling (doc 08 §3) later.
```

---

## Deferred (not this brief) — per-waterbody tiled fetch for full-STW

If the gentler/resumable fetch still struggles at full-STW scale, extend the bbox-keyed cache to
iterate WFD river waterbody catchments (doc 08 §3): fetch each WB's small bbox in turn, resume per
WB. Smaller per-request AOIs are the real reliability win at scale — still sequential/paced, not
parallel.
