# Brief 15 — Point-ify the last polygon-polygon supplementary join (bunds stage-2 = 7.3h)

**Repo:** `python/nbs-mapping`
**Date issued:** 2026-06-20
**Status (2026-09-14):** executed 2026-06-22 — the last polygon-polygon supplementary join was point-ified.
**Follows:** Brief 13 (rep-point `_sjoin_largest`), Brief 14 (connected-components dissolve).
**Background:** `src/pipeline/supplementary.py`.

## 0. Root cause

Brief 14 fixed the bunds **dissolve** (45 min → ~16 min, bit-exact). That exposed the next, separate
bottleneck — bunds **stage-2 (supplementary) ran ~7.3 hours** and only went unnoticed in Brief 13
because it ran overnight in the background.

Cause: Brief 13 converted `_sjoin_largest` to a fast **representative-point** sjoin, but left
`_sjoin_nearest_polygon` (supplementary.py ~line 59) doing a full **polygon–polygon**
`gpd.sjoin(left, right, predicate="intersects")`. That helper serves the **HML `rch_pt`** and
**Habitat `prio_hb`** joins, so it runs polygon-intersects over all **199,512 complex bund polygons**
— hours. Two join paths, only one was optimised; the slow one survived.

## The change — one point-based join path, no polygon-polygon sjoin left

In `src/pipeline/supplementary.py`:

1. **Point-ify `_sjoin_nearest_polygon`** to mirror `_sjoin_largest`: build representative points of
   the left features (`left.geometry` if `_is_pointwise(left)` else `left.geometry.representative_point()`),
   then `gpd.sjoin(points, right[[col, "geometry"]], how="left", predicate="intersects")`, dedupe by
   index, assign index-aligned (not positional `.values`). i.e. the same body as `_sjoin_largest`,
   single-column.
2. **Better: consolidate.** Since both helpers now do the same thing, route the HML and Habitat
   joins through `_sjoin_largest` and delete `_sjoin_nearest_polygon` — leaving **one** point-based
   join helper so a slow polygon-polygon path can't lurk again. (If you keep both, make them share
   the same point-based core.)
3. **Preserve the Brief 13 A2 behaviour** around the HML call — the loud `rch_pt` populate-rate
   report and `make_valid` hygiene must stay.

This is consistent with the representative-point decision already taken (Jack, 2026-06-20): for the
large right polygons here (HML waterbodies ~1,905 features; Habitat network zones), the containing-
representative-point assignment agrees with the old "first intersecting polygon" extremely closely,
and is arguably more principled (the old "first match" among intersecting polygons was arbitrary).
Not bit-exact, but within the same rep-point tolerance already accepted for `_sjoin_largest`.

## Verification
- `python scripts/run_pipeline.py --all --aoi dev` — **bunds stage-2 drops from ~7.3 h to
  seconds/minutes**; full run completes in well under an hour (dissolve fast from Brief 14 +
  supplementary now fast).
- `rch_pt` and `prio_hb` populate rates / value distributions match the prior run within rep-point
  tolerance (HML still ~tracks its ~14% AOI coverage; report the breakdown as A2 does).
- Other six layers unchanged within FP tolerance (counts/areas/`tot_prio`); geometry valid,
  EPSG:27700, no empties.

## Then
Proceed to the gated full-STW run (Brief 13 Part D): regenerate WB-union AOI →
`fetch_and_cache_remote_datasets.py --aoi <full AOI> --force` (long, dense-OGC, resumable) →
`run_pipeline.py --all --aoi full` → validity/coverage checks (parity N/A — R reference is Avon-only).
With both the dissolve (Brief 14) and the supplementary join now point-based, the full-STW **compute**
should be tractable; the dense-OGC **fetch** remains the main wall-clock cost.

## Docs + commit
- Note in `docs/methodology/06_pipeline_architecture.md` that **all** supplementary joins are now
  representative-point (one helper); update CONTRIBUTING.md status. `git diff` after `src/` edits.

Commit message:
```
Point-ify the HML/Habitat supplementary join (bunds stage-2: 7.3h -> minutes)

Brief 13 made _sjoin_largest representative-point but left _sjoin_nearest_polygon
doing a full polygon-polygon sjoin; on 199,512 bund polygons the HML (rch_pt)
and Habitat (prio_hb) joins took ~7.3h (hidden by an overnight run). Consolidate
onto one representative-point join helper so no polygon-polygon path remains.
Consistent with the approved rep-point method; populate rates/distributions
match the prior run within tolerance. Loud rch_pt reporting + make_valid kept.
```
