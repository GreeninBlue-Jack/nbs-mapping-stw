# Brief 19 — Finalise peat, fix the core EWCS truncation, run

**Author:** Jack Beard
**For:** development
**Status:** ready to execute — single source of truth; do the tasks in order
**Status (2026-09-14):** executed 2026-07-10 to 2026-07-23 — EWCS truncation fix and peat finalised as a grip/gully erosion screen. Note that Task B1 (locking the peat vegetation classes) was itself superseded later in this same brief by the erosion-only method, which uses no vegetation classification at all.
**Continues:** Brief 18 (Gate C complete). Do NOT redo Brief 18 tasks A–C.

## Context

Brief 18 got through Gate C: the review fixes are committed, the corrected core deliverable is `outputs/<nbs>/<nbs>_full_<stage>_20260706.gpkg` (six core layers), and the peat layer was proven to run but is (a) too slow to ship as-is and (b) had two open ecology calls. Those calls are now **decided by Jack — do not reopen or run them as sensitivities**. This brief: (A) resolve the core EWCS truncation risk that the peat run exposed, (B) finalise + optimise peat and run it.

Two standing decisions from Brief 18 remain in force: **ALC stays Post-1988** and **`tot_prio` keeps `skipna` + `n_prio_scores`**. Do not change either. Work on a branch; do not push until Jack signs off.

---

## Peat method — SUPERSEDED to erosion-only (Jack, 2026-07-11, after GIS inspection)

Ignore any earlier "LOCKED veg assignments", the dry/wet `Veg_Class` sets, the Eriophorum/fen calls, and the whole-parcel degradation flag (Path B). All dropped. GIS inspection showed the vegetation approach flags essentially the whole Peak District (wall-to-wall Calluna/Molinia), which is not a *priority* map. **Peat opportunity is now defined by two erosion/drainage signals only — see Task B.**

---

## Task A — Fix the core EWCS truncation (do this FIRST; it gates the core deliverable)

The peat run surfaced that the pre-fix ArcGIS pagination silently one-paged any layer over its page cap. The `20260706` core layers were **re-merged, not re-computed**, so their tile computes date from the June run — **before** the pagination fix. Two core layers are ArcGIS-sourced and therefore at risk:

- **EWCS (England Woodland Creation Sensitivity)** — `max_record_count = 1000`. Feeds `woodland_planting` opportunity AND the `wood_s` label. Any WB tile with >1000 EWCS polygons was truncated → **under-counted woodland opportunity**. This is the prime suspect for woodland's surprisingly low full-STW count.
- **HML recharge** — `max_record_count = 2000`, waterbody-scale (few per tile). Lower risk, but if any tile exceeded 2000, some features wrongly got null `rch_pt` → `rch_prio` default 0.0 → slightly deflated `tot_prio` there.

**Do:**
1. Audit the June per-tile fetch logs (and/or re-probe) for any EWCS fetch that returned exactly 1000, or any HML fetch that returned exactly 2000 — i.e. hit the cap.
2. If **none** hit the cap: the core `20260706` set is confirmed clean; record that finding and move on.
3. If **any** did: with the fixed pagination, re-fetch + recompute **only the affected tiles**, for `woodland_planting` (opportunity + supplementary `wood_s`) and — if HML was capped — the affected supplementary `rch_pt`/`rch_prio` on the affected layers. Re-merge only the affected layer(s) into a fresh dated set; leave the five unaffected core layers as `20260706`.

**Gate A:** report the cap-hit audit result and, if a fix was needed, the before/after woodland (and any rch_pt) counts. This determines whether `20260706` is final or superseded for woodland. Report to Jack.

---

## Task B — Peat opportunity = buffered grips + gullies (final approach, Jack 2026-07-11)

GIS inspection settled the peat method. Map opportunity from the two unambiguous erosion/drainage signals only; drop the vegetation layer, bare peat, and haggs entirely.

**Rationale (record in `docs/methodology/03_peat_restoration_experimental.md`, replacing the NERR149 three-step section):**
- **Dry-veg dropped** — Calluna/Molinia/Eriophorum bog is wall-to-wall across the uplands, so veg-based flagging identifies the whole Peak District as "priority" — useless for prioritisation.
- **Bare peat dropped** — the spectral "bare peat" class picks out dark-toned vegetation (shadowed/burnt Calluna) as false positives more often than not.
- **Haggs dropped** — too fragmented; produces a bitty, unreadable output.
- **Grips (drainage ditches) + gullies (erosion channels)** are the two clean, intervention-relevant signals (grip-blocking, gully-blocking). They become the opportunity layer.
- This is deliberately an **upland erosion/drainage restoration screening map**, aligned with STW's Moor Resilience 2030 driver — NOT a full peat-condition map, and it does not attempt lowland/agricultural fen (which shows as land-use, not erosion). Output requires site validation.

**New `peat_restoration.run` chain (replace the whole Step 1/2/3 body):**
1. Load **`England Peat Map — Upland Grips`** + **`England Peat Map — Upland Gullies`** (per tile, bbox-clipped to the haloed WB, exactly as the other layers load). NB both are dense **small polygons** (not lines).
2. Concatenate the two into one GeoDataFrame.
3. **Buffer 10 m** (config `peat_buffer_m: 10`), then `dissolve_connected` → coherent restoration polygons. **The buffer+dissolve is also the performance fix:** it collapses the dense fragment count (thousands of tiny gully slivers per tile) into a handful of blobs, so the whole thing is seconds/tile with no special optimisation.
4. Subtract the **generic constraints** (`subtract_mask`) and `clip_to_aoi` to the exact WB — same as the other six layers (keeps opportunity off roads/reservoirs/urban; cheap).
5. Write stage-1 opportunity. It then flows through the standard supplementary + prioritisation stages like every other layer (schema-consistent; `tot_prio`'s land-use/ALC inputs are weakly meaningful for peat but harmless — leave as-is unless Matt asks for peat-specific scoring).

**Config:** reduce `config/nbs/peat_restoration.yaml` to just `grips_dataset`, `gullies_dataset`, and `peat_buffer_m: 10`. Remove `bare_peat_dataset`, `haggs_dataset`, `vegetation_dataset`, all veg-class lists, `peaty_extent_dataset`, and `peat_depth_min_cm`.

**Removed machinery (retire, don't leave dead code):** the vegetation fetch + veg-class config; the wet-bog Step-3 exclusion; **the peaty-soil-extent + ≥40 cm depth gate**, which means `scripts/preprocess_peat_depth.py`, the enriched-extent file, and the H2 per-tile hash fallback are **no longer used by `peat_restoration`** (grips/gullies are on peat by dataset definition; the "true peat ≥40 cm" refinement is dropped for this screening layer — note it for Matt). `scripts/check_peat_step2_optim.py` is moot — retire it. Keep the peat *depth* datasets in the registry (harmless) but they're no longer wired into the pipeline.

**Two choices flagged (defaults applied — veto if wrong):**
- Depth ≥40 cm gate: **dropped** (removes the entire depth/enriched-file machinery and the recurring H2 fallback warning). Reinstating it is a one-line filter but pulls `preprocess_peat_depth` back in.
- Generic constraints: **kept** for consistency with the other layers; drop only if Jack wants the raw buffered erosion footprint.

### B-run — gated peat run (`--include-experimental`)
Peat-only; the six core layers are final and must not be recomputed.
- **Gate B-a — compute smoke:** run a small `--only-tiles` set over Peak District **upland** tiles (where grips/gullies exist). Confirm 0 `error:`/0 `FAILED`; sample tile valid (EPSG:27700, `is_valid.all()`, geometry sane — buffered corridors/blobs, not slivers); and log the buffer+dissolve fragment collapse (features in → out). Report; proceed on Jack's OK.
- **Gate B-b — full peat run:** all tiles. Any `FAILED`/`error:` investigated before merge (the C1 discipline). Report done/empty/error per tile (most lowland tiles will legitimately be `empty:` — no grips/gullies there).
- **Gate B-c — merge + QA:** merge peat; `is_valid.all()`, EPSG:27700; report total peat opportunity area (ha) + feature count, and eyeball that the total is a modest, plausible fraction of STW upland peat (buffered grip/gully corridors, not whole moors). Flag for a QGIS visual check before Matt sees it.

---

## Acceptance criteria

- Core: EWCS/HML cap-hit audit done; `20260706` either confirmed final or woodland (and any rch_pt) re-merged for the affected tiles only.
- Peat: `peat_restoration` rewritten to buffered grips+gullies (10 m) → dissolve → constraints → clip; vegetation/bare-peat/haggs/depth machinery retired; doc 03 replaced with the erosion-only rationale; runs seconds/tile; peat merged with total area + feature count reported and flagged for a QGIS visual check.
- No silent failures: every empty labelled `empty:`, every error surfaced with a traceback + `FAILED` marker.
- Nothing pushed until Jack signs off.

## Explicitly out of scope / do not do

- Do NOT reintroduce the vegetation layer, bare peat, haggs, the whole-parcel flag, or the ≥40 cm depth gate — the erosion-only method in Task B is final.
- Do NOT switch ALC to Provisional, or `tot_prio` to strict NA propagation.
- Do NOT recompute the five non-woodland core layers — `20260706` is final for them.
- Do NOT push or commit deliverable metadata until sign-off.
- Do NOT "improve" methodology silently — flag any new deviation to Jack per CONTRIBUTING.md.
