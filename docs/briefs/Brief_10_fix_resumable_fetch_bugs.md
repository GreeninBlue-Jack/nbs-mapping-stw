# Brief 10 — Fix the two resumable-fetch bugs (unblock dev parity)

**Repo:** `python/nbs-mapping`
**Date issued:** 2026-06-11
**Status (2026-09-14):** executed 2026-06-15 — page cache moved out of the OneDrive tree; truncated-parse pages retried.
**Follows:** Brief 09 (gentler, resumable fetch).
**Background:** `docs/methodology/08_scaling_and_fetch_strategy.md §2`.

A `--force` dev fetch surfaced two **distinct** bugs in the Brief 09 resumable fetch. Note: two of
the failing layers (WWNP Runoff Attenuation 83,955/83,955; WWNP Floodplain Reconnection
14,924/14,924) **fully fetched all features** and only failed on cache cleanup — so the fetch logic
is close; these are robustness bugs.

---

## Bug A — `WinError 5 Access is denied` on partial-cache cleanup

**Root cause.** The resume cache (`partial_cache_dir`) lives under
`data/processed/raw_clipped/_partial/<slug>/` — inside the **OneDrive-synced** tree. After a fully
successful fetch, `query_wfs_features()` calls `shutil.rmtree(partial_cache_dir)` (~line 364) with
no error handling. OneDrive holds the just-written page files locked mid-sync, so the delete throws
`WinError 5` and the layer errors **despite every feature having been downloaded**. Writing
thousands of transient page `.gpkg` files into a synced folder is itself wrong (sync storm).

**Fix.**
1. Move the resume cache **out of the OneDrive-synced repo tree** to a local, persistent,
   un-synced location — default e.g. `%LOCALAPPDATA%\nbs-mapping\fetch_cache\<slug>\` on Windows
   (use `platformdirs.user_cache_dir` if available, else
   `Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "nbs-mapping" / "fetch_cache"`).
   Make it overridable via env var / CLI (`--cache-dir`). It must persist across runs (resume still
   works) but never sync.
2. Ensure each cached page file handle is released before any delete (read into memory / close).
3. Make cleanup tolerant: wrap the final `rmtree` in `ignore_errors=True` plus a short retry loop
   (a few attempts with a small sleep) as a backstop.
4. Thread the new cache location through `scripts/fetch_and_cache_remote_datasets.py` (per-slug
   subdir), replacing the current `raw_clipped/_partial` path.

---

## Bug B — truncated/corrupt page GML fails fatally instead of retrying

**Root cause.** The page parse `gpd.read_file(tmp_path)` (~line 310) sits inside the request block,
but the retry `except` only catches network errors (`RequestException`, `ProtocolError`,
`IncompleteRead`) — **not parse errors**. A truncated download (server closes the connection
cleanly but the body is short — RoFSW emits ~2-million-line GML pages; "unclosed token at line
2095525" / "no element found" are mid-file cut-offs) produces corrupt GML; the parse raises and
kills the layer. An OWS `ExceptionReport` body would also be mis-parsed as data.

**Fix.**
1. Bring the parse **inside** the retry: catch parse/datasource errors (e.g.
   `pyogrio.errors.DataSourceError`, `fiona` `DriverError`, `lxml.etree.XMLSyntaxError`, and a
   generic fallback) → delete the bad temp file **and** any cached page file → retry the page.
2. Before parsing, sanity-check the response body: reject OWS `ExceptionReport` / HTML error pages
   (e.g. body starts with `<ows:ExceptionReport`, `<ServiceExceptionReport`, or `<html`) and treat
   as a retryable failure.
3. If the server provides `Content-Length`, verify the streamed byte count matches; a short read is
   a retryable failure.
4. **Never cache a page that failed to parse** (only write the page cache after a successful parse).

---

## Acceptance

- A `--force` dev re-fetch completes **all 13 datasets**: a layer that fully fetched is no longer
  killed by cache cleanup (Bug A), and a transient truncated/corrupt page is retried rather than
  fatal (Bug B).
- Re-running after an interruption still resumes from the cache (now in the local cache dir).
- No `_partial` directories are written inside the OneDrive-synced repo.

## Then

```
python scripts/fetch_and_cache_remote_datasets.py --aoi data/reference/R_Model/Wavon_WCS_simple.shp --force
python scripts/run_pipeline.py --all --aoi dev
```

## Docs + commit

- Update `docs/methodology/08_scaling_and_fetch_strategy.md §2` (cache moved out of OneDrive;
  parse-validate-and-retry). Update CONTRIBUTING.md Project Status.
- `git diff` after editing `src/datasets.py` / `src/data_access.py` (OneDrive truncation history).

Commit message:
```
Fix resumable-fetch bugs: cache outside OneDrive + retry bad-parse pages

Two bugs from the Brief 09 resumable fetch. (A) The per-page cache lived
under data/processed/raw_clipped/_partial (OneDrive-synced); the post-fetch
shutil.rmtree hit WinError 5 (Access denied) on OneDrive-locked files, so
layers that had fully fetched still errored. (B) The page parse sat inside
the request block but parse errors weren't caught by the retry, so a
truncated GML page (RoFSW emits ~2M-line pages) was fatal instead of retried.

Move the resume cache to a local, un-synced cache dir (configurable) with
tolerant cleanup; bring the parse inside the retry, reject OWS exception /
short-read bodies, and only cache successfully parsed pages.
```

---

## Important — this unblocks DEV only, not full-STW scale

Bug B is a symptom, not the disease: RoFSW returning 2-million-line GML pages that truncate is why
the dense layers must not be streamed page-by-page at full-STW scale. The agreed fix remains —
move the dense layers (RoFSW, dense WWNP layers, etc.) to an **automated `bulk_download`** access
method (download the static bulk/extract file once, cache locally, clip to the AOI on read), keeping
WFS only for sparse layers. That is the **next** brief and is what makes a boundary-swap run reliable
and fully automated.
