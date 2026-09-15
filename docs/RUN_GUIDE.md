# NbS Opportunity Mapping — Run Guide

**For:** Severn Trent analysts running the tool in-house
**Companion docs:** methodology (`docs/methodology/`), dataset registry (`src/datasets.py`), developer runbook (`RUNBOOK.md`)

This guide is everything you need to run the tool and get outputs. You do **not** need to edit any Python. The only input you must supply is a boundary polygon for the area you want to map.

> **This is the current, authoritative run guide.** Where it differs from the Word run guide
> issued to Severn Trent (`STW_NbS_Run_Guide.docx`, not included in this repository), this
> document supersedes it.

---

## 1. What the tool does

For any area boundary you give it, the tool maps **Nature-based Solutions (NbS) opportunity areas** across seven layers:

pond/pool/scrape · leaky barriers · bunds (catchment storage) · floodplain reconnection · riparian buffer strips · woodland planting · peat restoration (experimental — upland grip/gully restoration).

Each layer follows the same logic: identify opportunity areas from open EA/Defra/OS/UKCEH data, remove constrained land (roads, rail, surface water, urban, drinking-water source-protection zones), then score each area (`tot_prio`, 0–1) from land use, agricultural grade, habitat networks, soil, and groundwater recharge. Everything is EPSG:27700 (British National Grid) and open-data-only.

---

## 2. What you need before you start

- **A boundary polygon** — a GeoPackage or shapefile with one or more polygons, in any CRS. That's the only *per-run* input you supply.
- **Three national datasets staged once by hand** — OS Open Zoomstack, CEH Land Cover Map 2023, and BGS Soil Parent Material (which feeds the `sl_prio` sub-score). Everything else fetches automatically. See **[`docs/DATA_ACQUISITION.md`](DATA_ACQUISITION.md)** for exact download sources, destination paths and licence positions — it is the single shopping list, and this guide deliberately does not restate it. *(OS MasterMap Water is a fourth registry entry but is Phase 1.5 — not needed for a run.)*
- **A stable internet connection** for the run (see §4 — this matters more than you'd think).
- **Time**: a full Severn-Trent-scale run is a multi-hour job. A small test area is minutes.

### Technical requirements

| Item | Requirement |
|---|---|
| **Python** | **3.11+**, with the project virtual environment (`.venv`). One-time setup: `pip install -r requirements.txt`. Developed and run on 3.13. |
| **OS** | Windows, macOS or Linux. Developed on Windows 11. |
| **RAM** | **16 GB minimum, 32 GB recommended.** The dense surface-water layers are memory-bound. |
| **QGIS** | Optional — for viewing outputs only. No ArcGIS licence needed. |
| **Network** | Outbound HTTPS to `environment.data.gov.uk`, `services.arcgis.com`, `services2.arcgis.com`, `www.arcgis.com`. |
| **Cache location** | Defaults to `%LOCALAPPDATA%\nbs-mapping\`. Override with `NBS_FETCH_CACHE_DIR` or `--cache-dir` — **keep it out of OneDrive** (see §4.4). |

Dependencies are declared in [`requirements.txt`](../requirements.txt), with exact pinned
versions in `requirements-lock.txt` if you need to reproduce the delivered environment. Install
from the file rather than working from a list — that's the authoritative declaration.

### Disk space

A full Severn-Trent-scale run needs roughly **50 GB free**. It splits into three parts, which is
worth knowing because only one of them scales with the size of your area:

| | Size | Scales with area? |
|---|---|---|
| **One-off downloads** (staged national datasets) | **~13 GB** — OS Open Zoomstack alone is ~12 GB; CEH LCM ~500 MB; BGS SPM ~150 MB | **No** — same for any area |
| **Working space** (fetch cache, clipped inputs, per-tile scratch, under `%LOCALAPPDATA%`) | **~25 GB** at full STW scale | Yes |
| **Outputs** | **~5 GB** per full set (7 layers × 3 stages); ~1.8 GB if you keep only `prioritised` | Yes |

So a **small test area** still needs the ~13 GB of one-off downloads, but only a few GB of
working space and outputs. Nothing in the working space is precious — it can be deleted between
runs and will re-fetch.

---

## 3. Running it — the one command

```bash
python scripts/run_area.py --boundary path/to/your_area.gpkg --name your_area
```

That single command does the whole chain with no further steps: builds the water-body AOI for your boundary, tiles it by WFD water body, builds the watercourse inputs that leaky barriers and bunds need (from the staged OS Open Zoomstack), fetches + computes every tile, and merges the results to:

```
outputs/<layer>/<layer>_your_area_<stage>_<date>.gpkg
```

…for three stages per layer: `opportunity` (where it could go), `supplemented` (with attributes joined), and `prioritised` (the scored final layer — **this is the one to use**).

**Useful flags:**

| Flag | What it does |
|---|---|
| `--fetch-workers N` | Parallel download workers. **Use `2`, not the default 4** (see §4). |
| `--include-experimental` | Adds the peat restoration layer. |
| `--limit N` | Only the first N tiles — use this to smoke-test before a full run. |
| `--retries N` | Extra passes over any tiles that failed (the run is resumable). |
| `--mode as_is` | Records your raw boundary as the AOI instead of the water-body union. **It does not clip the outputs to your boundary** — they still cover every whole water body your boundary touches, exactly as in the default mode. |

A live progress line shows `done/total | rate | ETA | running`, and a watchdog warns if any tile runs unusually long.

**Quick test first.** Before a full-area run, do `--limit 5` to confirm your environment and connection are working — it takes a couple of minutes and saves you discovering a problem three hours in.

---

## 4. Operational must-knows (read this — it's the difference between a 30-minute run and a 3-day one)

These are lessons learned the hard way; they're not optional.

1. **Keep the machine awake for the whole run.** If the PC sleeps, the run pauses — it's resumable, so it won't break, but a 20-minute job can dribble across days. Set the power plan to never sleep while plugged in (`powercfg /change standby-timeout-ac 0`) before you start.
2. **Use a stable connection and gentle fetch workers (`--fetch-workers 2`).** A few of the EA data servers (the DSP OGC endpoints) refuse connections under load and are intermittently flaky. Two workers stays under their tolerance; four can hang. On an unstable connection (mobile/train), the fetch will stall — run from a wired or solid Wi-Fi connection.
3. **The run is resumable.** If it stops (sleep, dropped connection, closed laptop), just run the same command again — it skips completed tiles and picks up where it left off. To force a fresh recompute, see §6.
4. **Working data is stored locally, not in OneDrive.** Caches and per-tile scratch live under `%LOCALAPPDATA%\nbs-mapping\` on purpose — OneDrive locking files mid-write was a major source of stalls. Only the final `outputs/` land in the project folder. Nothing in the caches is precious; if you move machines it just re-fetches.

---

## 5. What you get, and how to use it

- **Use the `prioritised` GeoPackages.** Each has the opportunity geometry plus `tot_prio` (0–1 priority score) and the attributes behind it (`CEH_LU`, `alc_grade`, `prio_hb`, soil, recharge, `n_prio_scores`).
- **Work from the GeoPackages, not shapefiles.** If you export to shapefile, some columns lose data — shapefile field names truncate to 10 characters and some value types don't survive the conversion (e.g. `n_prio_scores` can read as null). The `.gpkg` is the authoritative, fully-populated source. Share and analyse from it.
- **`n_prio_scores`** tells you how many of the five sub-scores backed each feature's `tot_prio` (2–5). A low number means the score is weakly supported — useful for QC.
- **`alc_grade` is the national Provisional ALC** (Natural England, 1:250,000), so it's populated across effectively the whole area (~99%). A few features may still be null at coastal/urban edges — that's real coverage, not a fault. (This replaced the earlier Post-1988 Survey product, which only covered ~2% of the area.)
- **Peat is a screening layer.** The peat restoration layer maps buffered upland grip/gully corridors — a starting point for site investigation, not a work order, and deliberately upland-focused (Moor Resilience 2030), not lowland fen.

---

## 6. Changing what it does — all from config, no code

| To change… | Edit… |
|---|---|
| Priority weightings / scores | `config/prioritisation_scores.yaml` (each sub-score 0–1; `tot_prio` is their mean) |
| A layer's source dataset | `config/nbs/<layer>.yaml` (point the key at another registry entry) |
| Which attributes are joined/scored | `config/supplementary.yaml` |
| Add a whole new NbS layer | copy `src/pipeline/_layer_template.py`, follow `docs/HOWTO_add_nbs_layer.md` |

Edit the YAML, re-run, and the output changes. The developer runbook (`RUNBOOK.md` §2–5) has worked examples for each.

**Forcing a fresh run.** Because the tool is resumable, a plain re-run reuses cached data and completed tiles. If you've changed a dataset or config and need the change to take effect, force it:
- `--refetch "Name1,Name2"` re-pulls only the named datasets (leaves the rest cached).
- `--force` re-fetches and recomputes everything from scratch.

---

## 7. Two things to watch when re-running an area you've run before

The tool is resumable, which is a feature — but it means a plain re-run does **not** automatically pick up new data or a changed method. Two situations to recognise:

1. **An implausible number of "empty" tiles in the end-of-run summary.** If you've added or changed a dataset and see far more `empty:` tiles than expected, the run reused a stale cache and skipped the new data. Fix: re-run with `--refetch "<dataset name>"` (or `--force`). Always glance at the per-layer `ok / empty / error` breakdown at the end — an implausible empty count is the tell.
2. **A merge warning about tile-count mismatch.** If you change a method so some tiles now produce nothing, the merge can keep their *old* output files. The merge prints a WARNING when this happens. If you see it, clear that layer's old per-tile files (RUNBOOK §7b has the exact command) and re-merge.

Neither corrupts anything — they're both "the re-run reused something it shouldn't have," and both are visible in the run output if you read the summary line.

---

## 8. If something goes wrong

- **Fetch stalls / connection errors (DNS, SSL, "connection refused").** The EA server is flaky, not your setup. Stop, check your connection is stable, and re-run with `--fetch-workers 2` (or `1`). The run resumes — no progress lost.
- **A tile fails.** Failures are surfaced (not hidden) and retried automatically. Anything still failing after the run is listed; re-run with `--retries 2` to have another go.
- **`missing` in the per-layer summary.** A tile couldn't find a locally-built input. `run_area.py` builds the waterlines inputs for leaky barriers and bunds before any tile runs, so this should only happen if those files were deleted, or rebuilt for a different area, part-way through. Re-run with `--force` to rebuild them and recompute.
- **Run seems stuck.** Check the live progress line and the watchdog warnings. If a tile has been "running" far longer than the others, its log is under `%LOCALAPPDATA%\nbs-mapping\tiles\<tile>\`.
- **Zero features where you expected some.** Confirm your boundary actually overlaps England (the data is England-only) and is a valid polygon.

---

## 9. Going deeper

- **Methodology + rationale for every layer and decision:** `docs/methodology/` (numbered docs).
- **Every dataset, its source, and access route:** `src/datasets.py` (the single registry).
- **Developer detail, worked config examples, cache internals:** `RUNBOOK.md`.
- **Adding a new NbS layer:** `docs/HOWTO_add_nbs_layer.md`.
