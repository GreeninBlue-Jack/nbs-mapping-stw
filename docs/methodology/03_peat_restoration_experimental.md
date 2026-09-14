# Peat Restoration NbS — Experimental Scaffold

**Date:** 2026-04-28  
**Author:** Jack Beard / Green in Blue  
**Status (2026-09-14):** Current — peat is an **experimental, opt-in** 7th layer (run with
`--include-experimental`) and **IS in the delivered set**: 17,667 features, 11,251.5 ha, over
89 water bodies (`peat_restoration_full_prioritised_20260730.gpkg`). It is a **grip/gully
erosion screen** (Brief 19), not the NERR149/depth method the original scaffold below describes.
The go/no-go was resolved 2026-05-20 (activated). See doc 06 for the delivered method and doc 10
for the delivered configuration.

---

## Overview

`peat_restoration` is a 7th NbS type, added alongside the six from the original R methodology.
It is **opt-in at run time** via the `--include-experimental` flag on `run_area.py` /
`run_full_tiled.py`, and it is included in the delivered `20260730` set. (`INCLUDE_EXPERIMENTAL`
in `src/datasets.py` now gates only the dataset-audit script; the pipeline runners use their own
`--include-experimental` flag.) The method is the grip/gully erosion screen described under
"Erosion/drainage screening" below — the NERR149 depth-threshold scaffold in this document is
retained as historical context and is **not** the delivered method.

The type is not present in the original Warwickshire Avon R workflow. It has been added
because:

1. **STW is a named partner in Moor Resilience 2030**, a £25 million programme targeting
   peatland restoration across the Severn Trent operating area (Peak District uplands
   and associated catchments). Mapping restorable peat is a direct business need.
2. **Natural England published the England Peat Map in May 2025.** This dataset did not
   exist when the original R methodology was designed and provides, for the first time, a
   nationally consistent, open-data foundation for peat extent, depth, condition, and
   degradation mapping.
3. **NERR149 (Natural England Research Report 149)** provides a nationally recognised
   three-step framework for identifying restorable peat, which the methodology below
   follows directly.

---

## Methodology: Erosion/drainage screening (grips + gullies) — FINAL (Jack 2026-07-11)

**This supersedes the earlier NERR149 three-step vegetation/depth method** (retained below
under "Superseded method" for provenance). After GIS inspection of the England Peat Map
signals over the STW uplands, peat restoration **opportunity** is now mapped from the two
clean, intervention-relevant erosion/drainage signals only:

1. **Load** `England Peat Map — Upland Grips` (artificial drainage ditches) and
   `England Peat Map — Upland Gullies` (peat erosion channels) — both dense **small polygons**,
   loaded per tile bbox-clipped to the haloed WB like every other layer.
2. **Concatenate** the two.
3. **Buffer 10 m** (config `peat_buffer_m`) then **`dissolve_connected`** → coherent
   restoration corridors/blobs. This buffer+dissolve is *also* the performance fix: it
   collapses the thousands of tiny grip/gully fragments per tile into a handful of blobs, so
   the layer runs in **seconds/tile** with no special overlay optimisation.
4. **Subtract a PEAT-SPECIFIC constraint** (`subtract_mask`) and **`clip_to_aoi`** to the exact
   WB. Peat is constrained by **physical infrastructure only** — roads (10 m), rail (20 m),
   surface water, and SPZ (1/1c/2) — **but NOT the CEH land-cover mask** the other six layers
   use (Brief 22, 2026-07-28). The CEH mask excludes bog (class 11), i.e. the peat this layer is
   mapping, so applying it would crop away the very ground being assessed. Built via
   `build_constraints_layer(aoi, include_ceh=False)`; the other six layers keep the full generic
   constraint including CEH.
5. Write stage-1; it then flows through the standard **supplementary + prioritisation**
   stages like every other layer. (`tot_prio`'s land-use/ALC inputs are only weakly meaningful
   for peat but harmless — left as-is unless Matt asks for peat-specific scoring.)

### Rationale — why erosion-only

- **Dry vegetation dropped.** Calluna/Molinia/Eriophorum bog is wall-to-wall across the
  uplands, so veg-based flagging identifies essentially the **whole Peak District** as
  "priority" — useless for prioritisation.
- **Bare peat dropped.** The spectral "bare peat" class picks out dark-toned vegetation
  (shadowed/burnt Calluna) as false positives more often than not.
- **Haggs dropped.** Too fragmented — produces a bitty, unreadable output.
- **Grips + gullies kept.** The two unambiguous, intervention-relevant signals
  (grip-blocking, gully-blocking) — they become the opportunity layer.

This is deliberately an **upland erosion/drainage restoration screening map**, aligned with
STW's **Moor Resilience 2030** driver — **not** a full peat-condition map, and it does not
attempt lowland/agricultural fen (which shows as land-use, not erosion). **Output requires
site validation.**

### Decisions applied (Brief 19; veto if wrong)

- **≥40 cm depth gate: DROPPED** for this screening layer — grips/gullies are on peat by
  dataset definition. This retires `scripts/preprocess_peat_depth.py`, the enriched-extent
  file, and the per-tile depth-hash fallback from the pipeline (the depth datasets stay in the
  registry, harmless, but are no longer wired in). *Flag to Matt:* no "true peat ≥40 cm"
  refinement in this map. Reinstating it is a one-line filter but pulls `preprocess_peat_depth`
  back in.
- **Constraints: PHYSICAL only** — roads/rail/surface water/SPZ kept, but the **CEH land-cover
  mask is dropped** for peat (Brief 22): it excludes bog class 11, the peat the layer maps, so
  keeping it cropped away legitimate opportunity. (Earlier this layer used the full generic
  constraint; that over-cropped the peat.)

---

## Superseded method: NERR149 three-step (vegetation/depth) — retired 2026-07-11

Retained for provenance only; **not implemented**. The original design gated on Peaty Soil
Extent + predicted depth ≥ 40 cm (Step 1), flagged degradation from bare peat / grips /
gullies / haggs / dry vegetation (Step 2, OR logic), and excluded intact wet bog + active
restoration (Step 3, AND NOT). A brief intermediate variant (Brief 19, 2026-07-13) replaced
the exact Step-2 area-intersection with a whole-parcel degradation *flag* to escape an
intractable overlay; that too is superseded by the erosion-only method above. The vegetation
class assignments below are no longer used.

---

## Resolved follow-ups

| Item | Resolution |
|---|---|
| Dry / wet peat vegetation class codes | **Resolved 2026-06-04**, then **moot from Brief 19 (2026-07-xx)** — the delivered grip/gully erosion screen uses no vegetation classification at all. |
| Peat depth confidence encoding | **Moot (Brief 19)** — the delivered method does not use the depth or depth-confidence rasters; `scripts/preprocess_peat_depth.py` and the enriched-extent file are retired from the pipeline. |
| STW / Moor Resilience 2030 restoration polygons | **Not received** — the STW data share did not arrive; there is no registry entry and it is not used in the delivered model. |
| Stakeholder go/no-go for client delivery | **Resolved 2026-05-20** — activated per Matt Palmer bi-weekly; peat is in the delivered set (opt-in). |

---

## Vegetation Classification — Resolved 2026-06-04

Step 2 ("dry / degraded vegetation") and Step 3 ("intact wet bog vegetation") both filter
the `England Peat Map — Vegetation and Land Cover on Peaty Soils` layer on its
`veg_class` attribute. Two class sets must therefore be defined: `DRY_PEAT_VEG_CLASSES`
(include) and `WET_BOG_VEG_CLASSES` (exclude).

### Methodology basis

The classification follows the ecological framing used in NERR149 (Natural England Research
Report 149) and consistent with the Living England habitat-condition framework that the NE
England Peat Map vegetation layer is derived from. The principles:

- **Sphagnum presence is the diagnostic marker of intact peat-forming vegetation.** Any
  community where sphagnum-dominated, wet-mire, or active-bog signatures are present is
  treated as INTACT and excluded from the restoration-opportunity set.
- **Heather / Calluna dominance without sphagnum, on peaty soil, indicates dry-modified bog**
  — historically a wet sphagnum community that has dried and shifted to ericoid dominance.
  These are restoration candidates.
- **Agricultural land cover on peaty soil** (improved grassland, arable, drained dry acid
  grassland) is by definition degraded peat and is a restoration candidate.
- **Bare peat, bracken, and grass-heath mosaic** are degradation signatures and are
  restoration candidates. Bare peat is also captured separately as a Step 2 signal via
  the dedicated Bare Peaty Soil layer.

### Phase 1 class assignments

**`DRY_PEAT_VEG_CLASSES`** (include as restoration candidate):

- `dry_modified_bog` — ericoid-dominated former bog with no sphagnum
- `calluna_dwarf_shrub_heath` — Calluna-dominated dwarf shrub heath on peaty soil
- `agricultural_improved_grassland` — improved grassland on peat
- `arable` — cultivated land on peat
- `dry_acid_grassland` — acid grassland without sphagnum indicators
- `bracken` — Pteridium-dominated (degradation indicator)
- `bare_peat` — included for completeness (also captured via dedicated layer)
- `grass_heath_mosaic_degraded` — mixed dry grass/heath mosaic on peat

**`WET_BOG_VEG_CLASSES`** (exclude — intact, leave alone):

- `active_blanket_bog` — actively forming sphagnum-dominated blanket bog
- `active_raised_bog` — actively forming raised bog
- `wet_modified_bog` — bog that has been modified but retains wet conditions and sphagnum
- `wet_heath_erica_sphagnum` — Erica tetralix / Sphagnum communities
- `sphagnum_dominated_mire` — any community dominated by sphagnum
- `cottongrass_wet_mire` — Eriophorum communities with sphagnum / wet conditions

### What is intentionally NOT in either set

- **Coniferous plantation on peat** — these are forest-to-bog restoration candidates, parked
  as a Phase 2 extension per the proposal document. Including them in `DRY_PEAT_VEG_CLASSES`
  would incorrectly flag forested land as open-ground restoration opportunity. They are
  handled by a separate Phase 2 workflow if/when forest-to-bog is activated.
- **Broadleaved woodland on peat** — uncommon and typically reflects naturally wet/carr
  woodland, not a restoration candidate.
- **Built-up area / urban / road / railway** — already excluded by the CEH LCM constraint
  mask (`mode in (20, 21, 11, 1)`).

### Verification required at first pipeline run

The class names above are descriptive labels matching the categories in NE England Peat
Map metadata. The exact attribute values used in the fetched `veg_class` field may be
encoded as:

- Numeric codes (1–N) requiring a label lookup
- Compact strings (e.g. `"DMB"`, `"WHE"`) requiring expansion
- Verbose strings differing in case or punctuation from the labels above

When the Vegetation and Land Cover layer is first fetched (via
`scripts/fetch_and_cache_remote_datasets.py --include-experimental`), the pipeline
maintainer must:

1. Inspect distinct values of `veg_class` against the AOI.
2. Map the actual values to the conceptual sets above.
3. Update `DRY_PEAT_VEG_CLASSES` and `WET_BOG_VEG_CLASSES` in `src/datasets.py` to use
   the actual attribute values.
4. Log the mapping in a follow-up commit referencing this section.

### Actual value mapping — Resolved 2026-07-08 (Brief 18 C3)

First real fetch of the layer over the STW AOI: **517,233 features**, column **`Veg_Class`**
(capitalised — the pipeline resolves it case-insensitively now; the old exact-`veg_class`
match silently no-oped both Step 2 and Step 3). The mapping lives in
`config/nbs/peat_restoration.yaml` (config since Brief 17, not `src/datasets.py`).
15 distinct classes, by frequency:

Assignments **LOCKED 2026-07-08 (Brief 19 B1 — Jack's committed decision, not a sensitivity):**

| Veg_Class | Features | Assignment | Note |
|---|---:|---|---|
| Eriophorum Bog | 111,385 | **DRY (include)** | LOCKED — EPM separates "Sphagnum Bog" as the intact class, so Eriophorum Bog is Sphagnum-subordinate by construction; cottongrass dominance is a drying/degradation signature; screening layer, false-positive cheaper than dropping the largest class. |
| Calluna Bog | 85,068 | DRY (include) | heather = dry-modified bog |
| Molinia Bog | 79,031 | DRY (include) | purple moor-grass = drying indicator |
| Bare Peat | 57,110 | DRY (include) | also a dedicated Step 2 signal |
| Dry Grass and Scrub Bog | 56,971 | DRY (include) | dry grass/scrub on peat |
| Short Fen Vegetation | 26,044 | **DRY (include)** | LOCKED — fen restoration (drained lowland fen) is a major carbon opportunity; bog-centric NERR149 signals would otherwise silently drop it. |
| Scrub and Tree Fen | 22,727 | **DRY (include)** | LOCKED — wooded carr fen; distinct restoration route → flagged for Matt to sanity-check. |
| Arable and Horticultural | 21,006 | DRY (include) | cultivated peat |
| Tall Fen Vegetation | 20,553 | **DRY (include)** | LOCKED — fen, as above. |
| Sphagnum Bog | 19,407 | **WET (exclude)** | the only exclude — Sphagnum-present = intact peat-forming |
| Other Grassland | 7,577 | DRY (include) | improved/agricultural grassland on peat |
| Built-up Areas and Gardens | 3,955 | neither | excluded via CEH constraint |
| Water | 3,390 | neither | non-peat |
| Broadleaved Woodland | 2,032 | neither | not a candidate (wet carr) |
| Conifer Woodland | 977 | neither | Phase 2 forest-to-bog |

### Required caveats (Brief 19 B1)

- **This peat layer is a SCREENING output requiring site validation, not a work order.**
  Including Eriophorum Bog and all fen classes means a minority of intact/wet/recovering
  ground (wet *E. angustifolium*, intact/SSSI fen) will surface as opportunity. This is the
  accepted cost of not silently dropping degraded peat, and is caught at site validation.
  Intact Sphagnum-present ground stays protected (Sphagnum Bog is the sole Step-3 exclusion).
- **"Scrub and Tree Fen" is wooded carr fen** — included here as degraded fen peat, but its
  restoration route differs from open-ground fen. Flagged for Matt (Severn Trent) to
  sanity-check as a distinct sub-class; the merge QA reports its area separately.
- Depth-confidence RMSE is populated for only 165/51,049 polygons, so the depth-confidence
  filter stays deferred (depth-mean ≥ 40 cm filter is applied and engages).

This was the only remaining step before the peat restoration filter is operational.
