# RUNBOOK — NbS Opportunity Mapping pipeline

How to **run the pipeline for a new area** and **change what it does from config**, without
editing Python. For methodology see `docs/methodology/`; for the dataset registry see
`src/datasets.py`.

---

## 0. Prerequisites

- **Python 3.11+** with the project venv (`.venv`). Install deps: `pip install -r requirements.txt`
  (geopandas, shapely 2.x, pyogrio, requests, pyyaml, **scipy** — used by the connected-components
  dissolve).
- **A boundary polygon** for your area (any vector format / CRS): a GeoPackage or shapefile with one
  or more polygons. That's the only input you must supply.
- **Disk**: the dense national datasets are downloaded once to a local cache
  (`%LOCALAPPDATA%\nbs-mapping\fetch_cache\_bulk`, ~0.5 GB). Per-tile working data goes to
  `%LOCALAPPDATA%\nbs-mapping\tiles*`. **None of this is in OneDrive** (see §5).
- **Internet**: the WFD water-body catchments (tiling) and a few dense EA layers are fetched live;
  the big national files are cached after the first run.

---

## 1. Run a new area (the one-liner)

```bash
python scripts/run_area.py --boundary path/to/my_area.gpkg --name my_area
```

That's it. `run_area` will, with no further steps:
1. build the **WFD water-body-union AOI** for your boundary (whole water bodies overlapping it —
   the STW delivery unit; doc 09). Use `--mode as_is` to keep the raw boundary instead.
2. build the **per-WB tile index**,
3. **fetch + compute** every tile (constraints → 7 NbS layers → supplementary → prioritisation,
   `+250 m` halo, clipped to each exact water body), **resumable** — re-run to retry any failures,
4. **merge** to `outputs/<nbs>/<nbs>_my_area_<stage>_<date>.gpkg`.

Useful flags: `--fetch-workers N` (default 4; lower to 2–3 if the EA server refuses under load),
`--compute-workers N` (default 6; RAM-bound), `--limit N` (first N tiles, for a quick test),
`--include-experimental` (adds the peat layer), `--retries N` (extra passes over failed tiles),
`--skip-merge`. Progress prints a live `done/total | rate | ETA | running` line; a **watchdog**
warns if any tile runs longer than `--watchdog-min` minutes (default 10) so a hang is obvious.

### Dev vs full runs
- **Small dev AOI (Warwickshire Avon), monolithic** — fastest for development/parity:
  `python scripts/run_pipeline.py --all --aoi dev`.
- **Whole STW area, tiled** — `python scripts/run_full_tiled.py` then `python scripts/merge_tiles.py`
  (this is what `run_area` wraps, pre-pointed at the STW tile index).

---

## 2. Change the priority weighting (no code)

Scores live in **`config/prioritisation_scores.yaml`**. Each sub-score is in `[0, 1]`; the final
`tot_prio` is the row-wise **mean of the active sub-scores** (CEH land use, ALC grade, habitat, soil
group, HML recharge). Edit a value and re-run — `tot_prio` moves.

**Worked example** — make arable land less attractive for ponds: find `ceh_lu: lu_prio:` and lower the
score for the `Arable` class code (`3`), e.g. `3: 0.8` → `3: 0.2`. Re-run; features on arable land now
score lower. (The read-only `Priority_Scores.xlsx` is provenance only and is never read at runtime.)

---

## 3. Swap a layer's opportunity dataset (no code)

Each NbS layer names its source dataset(s) in **`config/nbs/<layer>.yaml`** (e.g.
`opportunity_dataset:` for pond_pool_scrape, `flood_dataset:` / `raf_dataset:` for leaky/bunds). The
value is a **registry dataset name** from `src/datasets.py`. To use a different source, point that key
at another registry entry (add the entry to `src/datasets.py` first if needed). No Python change.

---

## 4. Add or remove a supplementary / prioritisation layer (no code)

The attributes joined onto every opportunity feature are an ordered, editable list in
**`config/supplementary.yaml`**. `add_supplementary` iterates it.

**To ADD a supplementary layer:**
1. add a dataset entry to `src/datasets.py` (name, `access_method`, coverage, …);
2. add a row to `config/supplementary.yaml`:
   ```yaml
   - dataset: "My New Layer"          # registry name
     rename: {source_col: MY_COL}     # or column_match: {substr: MY_COL} for a fuzzy name
   ```
3. **(only if it should be scored)** add a `MY_COL` block to `config/prioritisation_scores.yaml` and
   wire it into `config/prioritisation.yaml`.

**To REMOVE one:** delete its row from `config/supplementary.yaml` (and its scores block). Re-run —
the column appears/disappears. No edits to `supplementary.py` / `prioritisation.py`.

See `config/supplementary.yaml`'s header for every field (`rename`, `column_match`, `make_valid`,
`on_fail`, `report`).

---

## 5. Add a whole new NbS layer

The seven layers share one shape (identify → subtract constraints → dissolve → supplementary →
prioritise). Copy the template and follow the guide:
- template: `src/pipeline/_layer_template.py`
- guide: **`docs/HOWTO_add_nbs_layer.md`** (one fully worked example).

---

## 6. Where working data lives (important — keep it out of OneDrive)

All **intermediate / scratch** data is written to a **local, un-synced** root so OneDrive can't lock
files mid-write and stall the run (this caused ~half the full-run incidents):

| What | Location | Override |
|---|---|---|
| Bulk national files | `%LOCALAPPDATA%\nbs-mapping\fetch_cache\_bulk` | `NBS_FETCH_CACHE_DIR` |
| WFS/OGC page cache | `%LOCALAPPDATA%\nbs-mapping\fetch_cache` | `NBS_FETCH_CACHE_DIR` |
| Monolithic per-AOI clipped cache | `%LOCALAPPDATA%\nbs-mapping\raw_clipped` | `NBS_RAW_CLIPPED_DIR` |
| Per-tile working tree | `%LOCALAPPDATA%\nbs-mapping\tiles*` | `NBS_TILE_DIR` |

Only the **final merged outputs** (`outputs/…`) live in the repo/OneDrive tree. If you move machines,
you re-fetch (the caches rebuild themselves); nothing in the caches is precious.

---

## 7. Re-run gotchas (read before re-running an area you've run before)

The per-tile working tree is **resumable by design** — a tile with a `DONE` marker is skipped, and a
tile with a `FETCHED` marker skips the fetch step. That saves hours on a resume, but it means a
re-run does **not** automatically pick up new data or a changed method. Two traps (both hit during
Brief 19 — documented here so you spot them, not rediscover them):

### 7a. Stale `FETCHED` / `DONE` markers → false `empty:` results

If you re-run to pick up a **newly-added dataset** (e.g. a layer that wasn't fetched last time), the
old `FETCHED` marker makes the runner skip fetching, the compute then finds no data, and the tile is
recorded `empty:` — a **false empty**, not a real one.

- **Fix when you know new data is needed:** force the fetch. Re-fetch specific datasets with
  `python scripts/run_full_tiled.py --refetch "Grips,Gullies" …` (name-substring match; deletes +
  re-pulls only those, leaving the rest cached), or everything with `--force`.
  `--only-layers <layer>` / `--refetch` also make the runner re-process tiles that already have a
  `DONE` marker (merging the result back into `DONE`, so the other layers' records survive).
- **How to spot it:** the end-of-run **per-layer breakdown** (`ok / empty / missing / error`). An
  **implausible `empty:` count** is the tell — Brief 19's first peat run reported 745/747 empty
  (should have been ~658), which is how the stale-marker skip was caught. Always eyeball that line.

### 7b. Merge can include **superseded** tile files when a re-run produces *fewer* tiles

`scripts/merge_tiles.py` dedupes to the **newest-dated file per (tile, nbs, stage)** — correct when you
re-run the **same** method (the new date supersedes the old for that tile). But if you **change the
method** (or the inputs) so a tile that used to produce output now comes back `empty:`, the new run
writes **no file** for that tile, so the merge keeps its **old (superseded) file** — silently mixing
old-method output into the new deliverable. (Brief 19: 3 old NERR149-method peat tiles leaked into
the erosion-only merge.)

- **Fix:** before a method-change re-run/merge, **delete the old per-tile outputs** for that layer:
  ```
  # PowerShell — clear one layer's stale tile outputs (keep only the current run's date)
  Get-ChildItem "$env:LOCALAPPDATA\nbs-mapping\tiles" -Recurse -Filter "*peat_restoration*" |
    Where-Object { $_.Name -notmatch "_<CURRENT_DATE>\.gpkg$" } | Remove-Item
  ```
- **How to spot it:** `merge_tiles.py` now prints a `WARNING` when the merged tile-count for a layer
  disagrees with the number of tiles whose `DONE` marker records that layer as `ok` (the exact
  Brief-19 signature: merged 90 vs 89 ok). If you see it, clear the stale files and re-merge.
