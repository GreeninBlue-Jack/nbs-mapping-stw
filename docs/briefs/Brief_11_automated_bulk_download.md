# Brief 11 — Automated bulk/OGC fetch for dense layers (no manual staging)

**Repo:** `python/nbs-mapping`
**Date issued:** 2026-06-11
**Status (2026-09-14):** executed 2026-06-15 — `src/bulk_access.py` added with the `ogc_api` and `bulk_download` access methods. The per-layer routing chosen here was later revised by Briefs 17, 21 and 22.
**Follows:** Brief 09/10 (WFS hardening). **Runs in parallel with Brief 10 — read the guardrails.**
**Background:** `docs/methodology/08_scaling_and_fetch_strategy.md §3–§4`.

**Goal.** Make the dense layers fetch **fully automatically and boundary-swappably** — a fresh
checkout with a different AOI gets a new result with no manual download. Move the dense layers off
page-by-page WFS-GML (which truncates and overloads the EA server) onto a robust automated route,
and keep WFS only for the sparse layers where it already works. No manual one-off staging.

---

## 0. Parallel-execution guardrails (READ FIRST)

Brief 10 is being worked at the same time. To avoid clobbering:

- **Work on a separate branch/worktree:** `git worktree add ../nbs-bulk feat/bulk-download`.
- **Do NOT edit `query_wfs_features` in `src/data_access.py`** — that is Brief 10's file. Put ALL
  new download logic in a **new module `src/bulk_access.py`**.
- **Shared files** (also edited by Brief 10): `scripts/fetch_and_cache_remote_datasets.py`,
  `docs/methodology/08_*.md`, `CONTRIBUTING.md`. Keep edits here in **distinct regions** (add a new
  routing branch / new doc section; don't rewrite existing lines). **Merge order: Brief 10 first,
  then this branch**, and resolve the fetch-script + docs conflicts (they will be in different
  regions).
- Reuse Brief 10's local, un-synced cache-dir convention (`--cache-dir` / `%LOCALAPPDATA%`); do NOT
  write caches into the OneDrive-synced repo tree.

---

## A. New access method: `bulk_download`

- **Registry fields** (`src/datasets.py`): `access_method: "bulk_download"`, `bulk_url` (direct
  static file: national gpkg/zip/geojson), optional `bulk_layer`, `bulk_format`.
- **`src/bulk_access.py::download_bulk(url, dest, force=False)`:** streamed, **resumable** download
  (HTTP Range if the server supports it, else clean restart) to the local cache dir; validate via
  `Content-Length`/ETag; idempotent (skip if cached + valid unless `--force`). Unzip if needed.
- **`load_layer` (`src/pipeline/utils.py`):** add a `bulk_download` branch that reads the cached
  bulk file with a **bbox filter** (`pyogrio` `bbox=`) to clip to the AOI on read, reproject to
  EPSG:27700. Mirror the existing `local_file` branch; this is the only edit to utils.py.
- **Fetch script:** add a new routing branch for `bulk_download` → `download_bulk`, isolated from
  the existing WFS branch.

This gives download-once-clip-many: the national file is boundary-independent, cached once, and
re-clipped to whatever AOI a new user supplies.

---

## B. Pick + TEST each dense layer's route (do not guess — verify before wiring)

Layers to migrate off plain WFS (confirm the full set against the registry): **RoFSW**
(`ROFSW_0_0_Hazard`), **WWNP Runoff Attenuation**, **WWNP Floodplain Woodland**, **WWNP Floodplain
Reconnection**; also check **ALC** and **Habitat Networks**. For each, choose in priority order and
**test the URL (download a few MB / one bbox page and confirm it parses) before committing it:**

1. **Static bulk file** (.zip gpkg/shp/geojson) on the DSP dataset page → `bulk_download`.
2. **OGC API Features** (verified live — see §C): GeoJSON + bbox + EPSG:27700, more robust than the
   GML WFS. Use for layers with no clean bulk file. Items endpoint:
   ```
   https://environment.data.gov.uk/geoservices/datasets/<GUID>/ogc/features/v1/collections/<COLLECTION>/items?f=application/geo+json&bbox=<minx>,<miny>,<maxx>,<maxy>&crs=http://www.opengis.net/def/crs/EPSG/0/27700&limit=<n>
   ```
   Page via the response's `next` link (OGC cursor paging), not STARTINDEX. Parse GeoJSON (validate
   it's a FeatureCollection, not an exception/HTML) and retry on bad/short bodies — reuse the
   resilience pattern. If you add an OGC fetch helper, put it in `src/bulk_access.py` too.
3. **Area-of-interest extract / per-waterbody tiling** (doc 08 §3) — last resort.

**RoFSW note:** its OGC API `collections` probe returned empty on 2026-06-11, and doc 08 §4 records
no clean bulk. So RoFSW specifically must have its route **confirmed by testing**: try the DSP
download (bulk/AOI) and the OGC API items endpoint with its GUID; pick whatever actually returns
data reliably. If nothing robust exists, fall back to per-WB tiled fetch (doc 08 §3).

---

## C. Verified findings (2026-06-11 probe — use these, they're confirmed)

- **OGC API Features is LIVE** on the DSP and returns clean GeoJSON with `bbox` + EPSG:27700.
- **WFD** (GUID `7846354f-d465-11e4-89d9-f0def148f590`): collection
  `WFD_River_Water_Body_Catchments_Cycle_2`, `storageCrs = EPSG:27700`, `geo+json` items endpoint
  works. Canonical base: `https://environment.data.gov.uk/geoservices/datasets/<GUID>/ogc/features/v1/`.
- **RoFSW** GUID for testing: `4e51df30-8437-4a56-92c2-ab14ff6e565b` (collection likely
  `ROFSW_0_0_Hazard`). OGC `collections` returned empty in the probe — confirm by direct test.

---

## Acceptance

- Dense layers fetch with **no manual step**; a clean checkout pointed at a different boundary
  downloads + clips automatically.
- Bulk/extract files cached in the local un-synced cache dir; re-runs skip re-download unless
  `--force`.
- A dev `--force` fetch completes the migrated layers **without** the WFS GML-truncation failures.
- WFS retained only for sparse layers; `query_wfs_features` untouched by this brief.

## Then / Docs / Commit

- Update `docs/methodology/08_scaling_and_fetch_strategy.md §4` (bulk_download + OGC API routes; a
  per-layer routing table) and CONTRIBUTING.md registry conventions + Project Status. `git diff` after
  editing `src/datasets.py`.

Commit message:
```
Add automated bulk/OGC fetch for dense layers (boundary-swappable, no manual staging)

Dense layers (RoFSW, WWNP runoff/floodplain) overload the WFS GML endpoint
and truncate. Add a bulk_download access method (src/bulk_access.py):
download a static national file once to the local cache, clip to the AOI on
read via pyogrio bbox — download-once, clip-many, fully automated. For layers
with no clean bulk, use the DSP OGC API Features endpoint (GeoJSON + bbox +
EPSG:27700), which is more robust than the GML WFS. Per-layer routes chosen
and tested; WFS retained for sparse layers. query_wfs_features untouched.
```

---

## Note

If most dense layers end up on the OGC API rather than static bulk, consider (later, not now)
migrating the remaining WFS layers to OGC API too for one consistent, more-robust path — but that's
out of scope here to keep this parallel-safe with Brief 10.
