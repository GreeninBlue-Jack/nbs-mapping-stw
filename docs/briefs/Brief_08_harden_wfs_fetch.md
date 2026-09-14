# Brief 08 — Harden the paged WFS fetch (streaming retry + per-layer page size)

**Repo:** `python/nbs-mapping`
**Date issued:** 2026-06-11
**Status (2026-09-14):** executed 2026-06-11 — streaming retry moved inside the retry loop, per-layer page size.
**Follows:** Brief 06 (paged WFS fetch).
**Background:** `docs/methodology/08_scaling_and_fetch_strategy.md §2`.

**Symptom:** a `--force` dev re-fetch errored on one dense layer with
`IncompleteRead(... bytes read, ... more expected)` and then **hung for 30+ minutes** on the RoFSW
NaFRA2 extent. The EA GeoServer is slow and drops connections mid-response.

---

## 0. Root cause (confirmed in `src/data_access.py::query_wfs_features()`)

1. **The per-page retry only wraps the initial `requests.get`.** The response body is streamed
   separately in `for chunk in r.iter_content(...)`, which sits **outside** the `try/except`. So a
   connection broken *mid-stream* raises `ChunkedEncodingError`/`IncompleteRead` that is **not
   retried** — it kills the fetch (this is the WWNP Runoff error).
2. **A slow trickle never times out.** `timeout=_WFS_TIMEOUT*4` (120 s) is a per-socket-read
   timeout; while the server dribbles bytes it keeps resetting, so a large dense response (RoFSW)
   streams for tens of minutes with no error and no real progress (this is the hang).
3. **Page size is a single 10,000 default for every layer.** RoFSW is dense, detailed geometry, so
   each 10k page is a big, slow, stall-prone download.

Clipping is fine (BBOX is correctly embedded in CQL) — this is purely robustness + volume.

---

## The task

### A. Retry the whole page download, not just the initial request
In `query_wfs_features()`, move the **streaming-to-temp-file** step *inside* the retry loop so a
mid-stream failure re-fetches that page from `STARTINDEX`. Specifically:

- For each attempt: issue the request, `raise_for_status()`, stream the body to a **fresh** temp
  file, and only then parse it. If anything fails, delete the partial temp file and retry.
- Broaden the caught exceptions to include mid-stream breaks:
  `requests.exceptions.RequestException` (covers Timeout, ConnectionError, ChunkedEncodingError),
  plus `urllib3.exceptions.ProtocolError` and `http.client.IncompleteRead`.
- On final failure, raise a clear `RuntimeError` naming the layer, `STARTINDEX`, and attempt count.
- Never accept a partially-streamed page (no silent partials — CONTRIBUTING.md rule, and the
  `numberMatched` completeness guard must stay intact).

### B. Per-layer page size
- Add an optional `wfs_page_size` field to the dataset registry (`src/datasets.py`). Thread it
  through `scripts/fetch_and_cache_remote_datasets.py` into `query_wfs_features(page_size=...)`;
  fall back to the existing 10,000 default when unset.
- Set `wfs_page_size: 2000` on the **RoFSW** entry (the one with
  `wfs_cql_filter = "risk_band IN ('High','Medium')"`). Leave others at the default for now.
- Also add a `--page-size N` CLI flag to the fetch script for ad-hoc global override.

### C. Progress visibility
- Log per page: page index, features this page, running total vs `numberMatched`
  (e.g. `page 3: 2000 features (6000/13742)`), so a slow fetch is visibly progressing rather than
  apparently hung.

**Optional (only if A+B don't settle it):** add a per-page wall-clock deadline that aborts and
retries a page exceeding, say, 5 minutes.

---

## Acceptance

- A `--force` dev re-fetch of the RoFSW layer **completes** and returns a feature count equal to the
  server's `numberMatched` for the dev bbox (no hang, no silent partial).
- A simulated/transient mid-stream break on a page is **retried**, not fatal.
- Other layers still fetch unchanged (default page size preserved when `wfs_page_size` unset).

## Then

Re-run, and confirm completeness, then proceed to the parity run:
```
python scripts/fetch_and_cache_remote_datasets.py --aoi data/reference/R_Model/Wavon_WCS_simple.shp --force
python scripts/run_pipeline.py --all --aoi dev
```

## Docs + commit

- Update `docs/methodology/08_scaling_and_fetch_strategy.md §2` with the streaming-retry hardening
  and the per-layer `wfs_page_size` knob. Update CONTRIBUTING.md Project Status.
- `git diff` after editing `src/datasets.py` (OneDrive truncation history) before committing.

Commit message:
```
Harden paged WFS fetch: retry streaming body + per-layer page size

query_wfs_features() retried only the initial GetFeature request; the
response body was streamed outside the retry, so a connection broken
mid-stream (ChunkedEncodingError/IncompleteRead) was fatal rather than
retried, and a slow trickle never tripped the per-read timeout — causing
the RoFSW dev fetch to error on one layer and then hang for 30+ minutes.

Move the stream-to-temp-file step inside the retry (catching mid-stream
breaks), discard partial temp files between attempts, and keep the
numberMatched completeness guard. Add an optional per-layer wfs_page_size
(registry) plus a --page-size CLI flag; set RoFSW to 2000 (dense geometry).
Add per-page progress logging.
```
