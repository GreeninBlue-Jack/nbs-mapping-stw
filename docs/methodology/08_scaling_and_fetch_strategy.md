# 08 — Scaling and Fetch Strategy (paged WFS + per-waterbody tiling)

**Date:** 2026-06-05
**Status:** Pagination fix (§2) chosen and scoped in Brief 06. Per-waterbody tiling (§3) is a
**deferred contingency** for full-STW scale only. **§4 superseded by Brief 11 (2026-06-15):** the
dense layers are now moved off plain WFS onto automated `ogc_api` / `bulk_download` routes — see the
rewritten §4.
**Status (2026-09-14):** Current, as amended. Both contingencies were built and are the delivered
path — §3 per-waterbody tiling was implemented in Brief 16 (`scripts/build_wb_tiles.py`,
`run_full_tiled.py`, `merge_tiles.py`; the delivered full-STW run is 747 tiles) and §4 bulk/OGC
routing in Briefs 11/17/21/22. The "deferred contingency" / "not being pursued" framing in the
line above and in §5 is therefore historical; read §3, §4 and §6 for the as-delivered state, and
doc 10 for the delivered configuration. The only genuinely open item is the §4 fetch-once-over-AOI
resumable OGC route (still spec'd-not-built).
**Affects:** `src/data_access.py` (sparse WFS fetch), `src/bulk_access.py` (dense bulk/OGC fetch),
`scripts/fetch_and_cache_remote_datasets.py`, `src/pipeline/utils.py` (`load_layer`); later, at
full-STW scale only, `scripts/run_pipeline.py`.

---

## 1. Problem

Raw WFS outputs were coming back **partial**. Root cause: `query_wfs_features()` issues a single
WFS `GetFeature` with `COUNT=50000` and (a) never paginates and (b) never checks the returned
count against the server's `numberMatched`. GeoServer caps features per response, so any AOI whose
result exceeds the cap is **silently truncated**. The dense RoFSW surface-water extent (~274k
features nationally; even a 10 km test tile times out) makes this acute.

Two separate issues, two fixes:
1. **Silent truncation** — a fetch-layer bug; fix with pagination + a completeness guard (§2).
2. **Scale / volume** — a national-extent processing problem; fix with per-waterbody tiling (§3)
   and staged local files for the densest layers (§4).

---

## 2. Paged fetch with a no-silent-partial guard (always on)

- Paginate WFS 2.0 with `STARTINDEX` + `COUNT` (page size, e.g. 10,000), accumulating pages until
  a page returns fewer than the page size.
- Read `numberMatched` (from the GetFeature response, or a preliminary `resultType=hits` request)
  and **assert** the accumulated feature count equals it. If short, **raise** an informative error
  naming the dataset, AOI/tile, expected vs received. This upholds the CONTRIBUTING.md "no silent
  failures" rule — the previous behaviour violated it.
- Keep the existing CQL-BBOX embedding (avoids the GeoServer 500 when BBOX + CQL coexist).
- Page size is configurable; keep it conservative to avoid per-request timeouts on dense layers.

**Streaming retry (Brief 08, 2026-06-11).** The initial Brief 06 retry only caught errors on the
initial `requests.get()` — the response body was streamed *outside* the retry loop, so a connection
broken mid-stream (`ChunkedEncodingError`, `IncompleteRead`) was fatal. Fix: move the full
stream-to-temp-file step *inside* the retry; discard any partial temp file between attempts; catch
`requests.exceptions.RequestException` (covers Timeout, ConnectionError, ChunkedEncodingError),
`urllib3.exceptions.ProtocolError`, and `http.client.IncompleteRead`. Per-page progress is now
logged (page index, features, running total vs `numberMatched`).

**Per-layer page size (Brief 08, 2026-06-11).** An optional `wfs_page_size` field in the dataset
registry (`src/datasets.py`) overrides the default 10,000 for individual layers. The fetch script
also accepts `--page-size N` for a global CLI override. RoFSW is set to 2,000; WWNP Runoff
Attenuation to 5,000 (dense; leave others at 10,000 default).

**Resumable page cache + gentler pacing (Brief 09, 2026-06-11).** The EA GeoServer refuses
connections under sustained load — hardening alone could not recover, because each refusal was
genuine and a failed run restarted from scratch and re-hammered the server.

`query_wfs_features()` now caches each fully-downloaded, parsed page as a GeoPackage under
`<cache_base>/<slug>/start_<STARTINDEX:08d>.gpkg`. A `query.json` manifest records query identity
(typename, bbox, CQL, `page_size`, `numberMatched`). On re-run: if the manifest matches,
already-fetched pages load from cache (logged `(cached)`) and the loop resumes from the first
missing STARTINDEX; if the manifest differs, the partial dir is cleared. The partial dir is
deleted on successful, verified completion. `numberMatched` completeness guard retained; the
partial cache is *not* deleted on a guard failure, preserving it for the next run.

Also: inter-page `_PAGE_DELAY` (0.75 s) added; `_PAGE_RETRIES` raised 3 → 5 with longer jittered
backoff (`min(60, 3×2^attempt) + uniform(0,1)` s); `--delay S` CLI flag (default 2 s) for
inter-dataset sleep in the fetch script; `partial_cache_dir` parameter on `query_wfs_features()`.

The cache is bbox-keyed so the same machinery can back per-waterbody tiling (§3) later — each WB
bbox becomes its own partial dir, resumable independently.

**Cache outside OneDrive + parse-validate-and-retry (Brief 10, 2026-06-15).** The Brief 09 cache
lived at `data/processed/raw_clipped/_partial/<slug>/` — inside the OneDrive-synced tree. On
Windows, OneDrive holds just-written files locked mid-sync, so the post-fetch `rmtree` raised
WinError 5 and errored layers that had already fully fetched. Separately, a truncated page
download produced corrupt GML (RoFSW emits ~2M-line pages; server can close the connection with
the body short) and the parse raised outside the retry's except clause, killing the layer.

- **Cache location:** The `<cache_base>` is now `%LOCALAPPDATA%/nbs-mapping/fetch_cache` on
  Windows (never synced). Override with env var `NBS_FETCH_CACHE_DIR` or `--cache-dir` CLI flag.
  `data_access.default_page_cache_dir()` computes it; the fetch script calls it to derive
  per-slug paths.
- **Tolerant cleanup:** `_rmtree_tolerant()` retries the rmtree up to 4 times (1.5 s gaps) before
  falling back to `ignore_errors=True`. Both the post-fetch cleanup and the identity-change reset
  use it.
- **Parse inside retry:** The except clause is now `except Exception` — network errors, short
  reads, ExceptionReport bodies, and parse failures all retry the same way.
- **Body pre-check:** After streaming to temp GML, the first 512 bytes are checked for
  `ExceptionReport`, `ServiceExceptionReport`, or `<html` — a retryable failure rather than a
  mis-parsed empty GeoDataFrame.
- **Content-Length guard:** If the server provides `Content-Length`, the streamed byte count is
  compared; a short read is raised before `gpd.read_file()` is attempted.

This fix matters even at dev scale: a dev catchment dense in RoFSW could otherwise truncate, and
the "first parity report" would be built on incomplete input. **Apply this before trusting any
parity numbers.**

---

## 3. Per-waterbody tiling (scaling unit for full-STW)

> **Implemented (Brief 16, 2026-06-23).** `scripts/build_wb_tiles.py` writes the tile index
> (`data/processed/aoi_wb_tiles.gpkg`, **747 WB tiles** over the 25,508 km² full AOI);
> `scripts/run_full_tiled.py` is the orchestrator (pipelined **process** fetch pool → **process**
> compute pool, +250 m halo, clip-to-exact-WB, resumable per `tiles/<id>/DONE`);
> `scripts/merge_tiles.py` concats the per-tile outputs. The pipeline runs unchanged per tile via
> `utils.set_tile_context()` (tile-scoped `load_layer`/`write_output`) and the reusable
> `fetch_and_cache_remote_datasets.fetch_one()`. Both pools are processes — a thread fetch pool
> corrupts the per-tile stdout redirect (process-global). Validated on a 3-tile Avon subset.

Process one **WFD river waterbody catchment** at a time, then merge. Rationale:
- The waterbody is already the analytical and output unit (Stage-2 `WB_ID` join key), so processing
  matches delivery and gives natural per-WB review.
- Resumable and parallelisable: cache each WB's output, skip completed — a cap/timeout on one tile
  doesn't sink the run.
- Bounds memory and compute for vector overlays.

**Tile index:** the WFD River Waterbody Catchments Cycle 2 layer (already in the registry).

**Two correctness rules:**
- **Halo.** Fetch/process each WB buffered outward by the largest distance the methodology uses
  (constraint road/rail buffers, waterline buffers up to 150 m, riparian buffers) — default
  **+250 m** (config). Process on the haloed tile, then clip the *final* output back to the exact
  WB boundary. Prevents seam artefacts where a buffer or a just-outside constraint is truncated at
  the boundary.
- **Clip-to-WB before merge.** Each tile's final output is clipped to its exact WB polygon, so
  tiles do not overlap and the final merge is a plain concat/union — no de-duplication needed.
  Point outputs (leaky barriers) are assigned to the containing WB.

**Default:** tiling ON for `--aoi full`; the dev AOI (a single WFD catchment) runs as a single tile.

---

## 4. Automated bulk + OGC API routes for dense layers (Brief 11, 2026-06-15)

> Supersedes the earlier "staged `local_file`, not being pursued" stance. The dense layers now fetch
> **fully automatically and boundary-swappably** — a fresh checkout pointed at a different AOI
> downloads + clips with no manual one-off staging. All new download logic lives in
> `src/bulk_access.py`; `query_wfs_features` in `src/data_access.py` is untouched.

WFS GML is the right tool for the *sparse* layers but the wrong tool for the *dense* national layers:
large GetFeature responses truncate mid-stream and the EA GeoServer refuses connections under load
(§2 documents hardening that could not fully recover this). Brief 11 adds two robust automated routes.

**Two new `access_method` values:**

1. **`bulk_download`** — download a static national file (gpkg / shp / geojson, or a `.zip`) **once**
   to the local, un-synced cache (`<cache_base>/_bulk/<slug>/`, reusing Brief 10's `--cache-dir` /
   `%LOCALAPPDATA%` convention — never the OneDrive tree), then clip to the AOI bbox **on read**
   (`pyogrio bbox=`, CRS-aware). Download-once, clip-many: a new boundary needs no re-download.
   `download_bulk()` is streamed, resumable (HTTP Range when the server supports it, else clean
   restart), Content-Length-validated, idempotent (skips a valid cached file unless `--force`), and
   unzips archives. `read_bulk_clipped()` performs the per-AOI clip; `load_layer` calls it so the
   pipeline reads the cached national file directly. Registry fields: `bulk_url`, optional
   `bulk_layer` / `bulk_format` / `bulk_filename`.

2. **`ogc_api`** — the DSP **OGC API Features** endpoint (GeoJSON + bbox), verified materially more
   robust than the GML WFS. `query_ogc_features()`:
   - sends a native EPSG:27700 bbox **with `bbox-crs`** — *omitting `bbox-crs` makes the server read
     the bbox as CRS84 degrees and silently return zero matches* (the trap in the original brief's
     example URL; confirmed live);
   - pages via the response `rel="next"` **cursor** link (not STARTINDEX/offset);
   - validates each GeoJSON `FeatureCollection`, rejects/retries transient 502/504/HTML bodies with
     jittered backoff, and **raises on a `numberMatched` mismatch** (no silent partials);
   - applies attribute filters via OGC API **Part 3 CQL2 text** (`filter=…&filter-lang=cql2-text`) —
     the simple `<prop>=<value>` query param is **not** supported by the DSP (repeated 500s).
   Registry fields: `ogc_url`, `ogc_collection`, optional `ogc_cql_filter` / `ogc_page_size`
   (default 2000). `ogc_api` layers are fetched + clipped by the fetch script into
   `data/processed/raw_clipped/<slug>.gpkg`, exactly like WFS, and `load_layer` reads them from there.

**Per-layer routing — UPDATED Brief 17 (2026-07-02), corrected Brief 21 (2026-07-24):** three dense
layers are on `bulk_download` (verified national GeoPackages on `environment.data.gov.uk`, downloaded
once → clipped per tile). Three stay on `ogc_api`. Counts are the clipped-count over the dev AOI.

**Brief 21 correction:** WWNP Floodplain Woodland was reverted `bulk_download` → `ogc_api`. Its DSP
bulk `.gpkg.zip` export is **spatially incomplete** — 202,651 features nationally but MISSING large
STW areas the OGC feed covers (tile GB104027052280: OGC 199 features vs bulk **0**). The Brief 17
switch was never run in a full tiled compute until the Brief 21 SPZ re-run, which surfaced floodplain
collapsing 712 → 211 tiles. Same DSP-bulk-export unreliability that kept the sibling Reconnection
layer on OGC — **do not trust the DSP `.gpkg.zip` for the WWNP floodplain layers; verify a bulk
national file against its OGC `numberMatched` before switching any layer to `bulk_download`.**

| Layer | Route | Note |
|---|---|---|
| RoFSW surface-water hazard | `ogc_api` | **no national file** (WMS + area-download only) — stays on OGC |
| WWNP Runoff Attenuation 1% AEP | `bulk_download` | national gpkg (1.05M feat; 83,954 over dev) |
| WWNP Floodplain Woodland Potential | `ogc_api` | **reverted Brief 21** — DSP bulk gpkg spatially incomplete (OGC 199 vs bulk 0 on a sample tile) |
| WWNP Floodplain Reconnection Potential | `ogc_api` | DSP bulk export is an **empty** gpkg (0 feat) — stays on OGC |
| Agricultural Land Classification | `bulk_download` | national gpkg (46,981 feat; 3,427 over dev) |
| Habitat Networks Combined | `bulk_download` | national gpkg (813,420 feat; 31,332 over dev) |
| England Woodland Creation Sensitivity | `arcgis_featureserver` | no static file (FC ArcGIS Hub only); fast via make_valid(structure) + load-once |

**Validate-once at the cache boundary.** `bulk_access.ensure_national_validated()` runs
`make_valid(method="structure")` over a national file's **invalid** geometries a single time on
download (most are already clean → no rewrite), recording a marker; every per-tile clip read is then
clean. The tiled runner **prefetches** all bulk files single-threaded *before* the worker pools
(concurrent first-download across processes is unsafe), and skips bulk layers in per-tile fetch
(`load_layer` reads them straight from the national cache). This is the EWCS-hang lesson (Brief 16)
applied once-globally instead of per tile — see `docs/methodology/06`.

**Not migrated:** RoFSW (no file), WWNP Floodplain Reconnection + Floodplain Woodland (DSP bulk
exports empty/incomplete — Woodland reverted to `ogc_api` in Brief 21) remain on `ogc_api`; EWCS
remains `arcgis_featureserver` (FC Hub has no stable static URL). ALC switched to the Provisional
product on `ogc_api` (Brief 22 — coarse/tiny, so light per tile). Wire any of them to
`bulk_download` if/when a clean national file appears — **and verify its count against the OGC
`numberMatched` first** (the Woodland bulk was spatially incomplete; Brief 21).

**Durable follow-up (TODO — spec'd, not yet built; Brief 22 Task 3).** Per-tile `ogc_api` × 747 of a
*dense* layer is fragile for anyone re-running against the flaky DSP OGC endpoints (DNS/SSL drops mid-
run). The robust fix is a **fetch-once-over-AOI OGC route**: a single *resumable* paged pull over the
whole AOI, staged locally, then clip-many (download-once/clip-many like `bulk_download`, but
OGC-sourced so the data is complete). This needs `query_ogc_features` made resumable — a page cache
keyed by query identity, mirroring the WFS `partial_cache_dir` (Brief 09) — since it currently loses
progress on a mid-pull drop. Applies to the dense OGC layers (RoFSW, Floodplain Woodland/Reconnection).
On a **stable** connection the current per-tile path works (it's how RoFSW/reconnection fetched in the
full runs); this only bites on flaky links.

**Sparse layers retained on WFS** (work fine, no truncation): Source Protection Zones, WWNP Woodland
Constraints, WWNP Riparian Woodland Potential, WWNP Wider Catchment Woodland Potential, WFD River
Waterbody Catchments. Migrating these to the OGC API for one consistent path is a possible follow-up
(out of scope for Brief 11).

**Performance note.** The OGC GeoJSON endpoint is slow for very dense layers (≈1–3 min per
~1–2k-feature page; the bottleneck is server-side serialization, roughly linear in feature count, not
page size). A dense dev fetch (e.g. WWNP Runoff ~84k) takes tens of minutes but **completes without
truncation**, which the WFS route did not. For full-STW scale the per-waterbody tiling (§3) — which
is parallelisable — remains the scaling unit, with `bulk_download` the fast path if a national file
is sourced.

---

## 5. Sequencing

> **Superseded (2026-09-14).** This was the Brief 06 sequencing plan. In the event both §3 tiling
> and §4 bulk/OGC staging *were* pursued and are the delivered path — the full-STW run proved
> infeasible monolithically. The steps below are retained as the original plan of record.

1. Implement §2 (paged fetch + guard); re-fetch the dev AOI so inputs are complete.
2. Run the dev AOI parity report (single tile) — now trustworthy.
3. **Only if** the full-STW run then proves too slow / memory-heavy / timeout-prone, implement §3
   (tiling). §4 bulk staging is not being pursued.

---

## 6. Implementation log

**2026-06-08 — Plan drafted, awaiting approval (nothing implemented yet).** *[Snapshot of that
date only — superseded three days later by the "2026-06-11 — Implemented (Brief 06)" entry below.
Nothing here is outstanding.]* the developer was given
Brief 06, explored the affected files (`src/data_access.py`, `scripts/fetch_and_cache_remote_datasets.py`,
this doc, and the WFS entries in `src/datasets.py`), and produced an implementation plan. It is parked
in plan mode pending sign-off; no code has been changed or committed.

Plan specifics beyond §2 above:
- Concatenate pages into one GeoDataFrame, keeping the existing **per-page temp-file streaming** to
  bound memory.
- Add **light per-page retry on timeout**; keep page size conservative for dense layers.
- Preserve CRS handling and the CQL-BBOX embedding (GeoServer 500 workaround).
- **Acceptance test:** for a known-dense layer (RoFSW `ROFSW_0_0_Hazard`, `risk_band IN ('High','Medium')`)
  over the dev AOI, the function returns a feature count equal to the server's `numberMatched` for that
  bbox, and **raises rather than truncates** if a page is missed.

**2026-06-11 — Implemented (Brief 06).** Changes applied to `src/data_access.py` and
`scripts/fetch_and_cache_remote_datasets.py`:
- `query_wfs_features()`: renamed `max_features` → `page_size` (default 10,000); added
  `_hits_count()` helper (issues `resultType=hits` to get `numberMatched`); pagination loop with
  `STARTINDEX`; per-page retry (3 attempts, exponential backoff on timeout/connection error);
  `RuntimeError` guard if accumulated count != `numberMatched`; per-page temp-file streaming
  preserved; CQL-BBOX embedding and CRS handling unchanged.
- Fetch script: removed duplicate local `_fetch_wfs()` function; now calls canonical
  `query_wfs_features()` with a post-fetch `intersects(aoi_geom)` clip preserved.

Next: re-fetch dev AOI (`fetch_and_cache_remote_datasets.py --force`) → confirm counts vs
`numberMatched` per WFS layer → run parity report (`run_pipeline.py --all --aoi dev`).

**2026-06-11 — Streaming retry + per-layer page size (Brief 08).** Root cause of dev re-fetch
failure identified: the retry loop only wrapped `requests.get()`; `iter_content()` was outside, so
a mid-stream `ChunkedEncodingError`/`IncompleteRead` was fatal and the RoFSW fetch hung for 30+
minutes on a slow EA GeoServer trickle. Changes applied:
- `query_wfs_features()`: full stream-to-temp-file step moved inside retry; broadened to catch
  `requests.exceptions.RequestException`, `urllib3.exceptions.ProtocolError`,
  `http.client.IncompleteRead`; partial temp files cleaned up between attempts; progress logging
  added (page N: K features (running/total)).
- `src/datasets.py`: `wfs_page_size: 2000` added to RoFSW entry.
- Fetch script: `--page-size N` CLI flag; `wfs_page_size` from registry; CLI overrides registry.
- `numberMatched` completeness guard preserved.

**2026-06-11 — Resumable cache + pacing (Brief 09).** The EA GeoServer refused connections under
sustained sequential load — RoFSW refused at page 1; WWNP Runoff died at 60k/84k. Applied:
- Resumable per-page cache in `query_wfs_features()` (see §2 above for full description).
- `_PAGE_RETRIES` 3 → 5; `_PAGE_DELAY` 0.75 s; jittered backoff (`min(60,3×2^n)+uniform` s).
- `wfs_page_size: 5000` on WWNP Runoff Attenuation Features entry.
- `--delay S` (default 2 s) inter-dataset sleep added to fetch script.
- `partial_cache_dir` parameter on `query_wfs_features()`; fetch script passed
  `out_dir/_partial/<slug>` (inside OneDrive — fixed in Brief 10).

**2026-06-15 — Cache outside OneDrive + parse-validate-and-retry (Brief 10).** Two bugs from
Brief 09: (A) cache inside OneDrive tree caused WinError 5 on rmtree for fully-fetched layers;
(B) parse errors from truncated GML were not caught by the retry except clause. Applied:
- Cache moved to `%LOCALAPPDATA%/nbs-mapping/fetch_cache/<slug>/` via `default_page_cache_dir()`.
  Env var `NBS_FETCH_CACHE_DIR` and `--cache-dir` CLI flag override the default.
- `_rmtree_tolerant()` added — 4-attempt retry with 1.5 s gaps, falls back to
  `ignore_errors=True`. Used for both post-fetch cleanup and identity-change reset.
- Retry except broadened to `except Exception` — catches parse errors, short reads,
  ExceptionReport bodies alongside network errors.
- Body pre-check: first 512 bytes scanned for `ExceptionReport`/HTML before `gpd.read_file()`.
- Content-Length guard: streamed byte count vs `Content-Length` header; short read = retryable.

**2026-06-15 — Automated bulk/OGC fetch for dense layers (Brief 11).** New module
`src/bulk_access.py` (`query_wfs_features` deliberately untouched). Two new access methods added to
the registry and the fetch script: `ogc_api` (DSP OGC API Features — GeoJSON + bbox + `bbox-crs`,
CQL2 filter, `rel="next"` cursor paging, `numberMatched` guard, transient-5xx retry) and
`bulk_download` (streamed/resumable/idempotent national-file download → clip-on-read). Six dense
layers migrated WFS → `ogc_api`: RoFSW, WWNP Runoff Attenuation, WWNP Floodplain Woodland, WWNP
Floodplain Reconnection, ALC, Habitat Networks (see §4 table). `load_layer` gained a `bulk_download`
branch (reads the cached national file with a CRS-aware bbox via `read_bulk_clipped`) and routes
`ogc_api` to the `raw_clipped/` cache like WFS. Fetch script gained `ogc_api` / `bulk_download`
routing branches and a `--only SUBSTR` targeted-fetch flag.
- **Probe-driven, not guessed.** Live probes (2026-06-15) found: OGC API live for all candidates;
  the brief's example URL omits `bbox-crs` and so returns **zero** (server reads bbox as CRS84) —
  fixed by sending native 27700 bbox + `bbox-crs`; RoFSW's `risk_band IN ('High','Medium')` honoured
  via CQL2 (`numberMatched=17884`) while the simple `risk_band=High` param 500s; cursor `next` paging
  confirmed; endpoint emits intermittent 502/504 that succeed on retry (→ robust per-page retries).
- **Verified.** ALC fetched end-to-end through the real fetch script over the dev AOI (2 pages,
  guard 3427/3427, exact-clip 2,172 features, written to `raw_clipped/`). `load_layer(ogc_api)` read
  back OK. `bulk_download` exercised by a local HTTP smoke test (download + idempotent skip + zip
  extract + CRS-aware clip). No `bulk_download` layer wired — no clean static national file verified;
  all dense layers route to OGC per the priority order, as the brief anticipated.
- **Note:** running the fetch script with `--only` rewrites `data/processed/raw_clipped/manifest.csv`
  to just the matched rows (the file is gitignored; a full fetch regenerates it).

**2026-09-14 — Log closed at the delivered state (handover).** The entries above stop at Brief 11;
the scaling/fetch work that followed is recorded inline in §3 (tiling) and §4 (per-layer routing)
and is summarised here so the log does not dangle:
- **Brief 16 (2026-06-23) — per-waterbody tiling built (§3).** `scripts/build_wb_tiles.py` (747-tile
  index), `scripts/run_full_tiled.py` (pipelined fetch→compute process pools, +250 m halo,
  clip-to-WB, resumable per `tiles/<id>/DONE`), `scripts/merge_tiles.py` (concat). This is the
  delivered full-STW path; the monolithic `run_pipeline.py` remains the dev/parity path.
- **Brief 17 (2026-07-02) — bulk/OGC per-layer routing + `run_area.py`** for any boundary; scratch
  moved out of the OneDrive tree (`%LOCALAPPDATA%`).
- **Briefs 21/22 (2026-07-24/28) — routing corrections:** WWNP Floodplain Woodland reverted
  `bulk_download`→`ogc_api` (bulk export spatially incomplete); ALC → Provisional on `ogc_api`.
- **Still open:** the §4 fetch-once-over-AOI resumable OGC route (spec'd, not built) — only bites on
  flaky links; the delivered runs used the per-tile OGC path on a stable connection.

See doc 06 for the delivered pipeline description and doc 10 for the delivered configuration.
