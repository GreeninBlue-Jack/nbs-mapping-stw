# config/

Editable YAML configuration for the NbS pipeline. Change behaviour here — no code edit.
See `RUNBOOK.md` (repo root) for worked examples.

| File | What it controls | Edit to… |
|---|---|---|
| `nbs/<layer>.yaml` | per-NbS-layer stage-1 parameters + **source dataset names** (`opportunity_dataset`, `flood_dataset`, …) | swap a layer's input dataset; change a stage-1 parameter (buffer, min-area) |
| `supplementary.yaml` | ordered list of attribute joins added to every opportunity feature | **add / remove a supplementary layer** (dataset + `rename`/`column_match` + `make_valid`/`on_fail`/`report`) |
| `prioritisation.yaml` | prioritisation *wiring* (active score keys, combine rule, exclusions, HML recharge lookup) | change which sub-scores are combined |
| `prioritisation_scores.yaml` | the editable **score tables** (each sub-score in `[0,1]`; `tot_prio` = mean of active sub-scores) | **re-weight** prioritisation |

Dataset **definitions** (URLs, access methods, coverage) live in `src/datasets.py` (the single
source of truth), not here — config files reference datasets by their registry `name`.
