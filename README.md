# Switchable STA Supply Chain Resilience Model + PRMM Evidence Binding

Reproducibility artifact for: *[paper title/citation to be added on acceptance]*, Ahmad Salameh, SYMME Laboratory, Université Savoie Mont Blanc.

This repository accompanies the internship report "Modelling and Analysis of Supply Chain Resilience Using Stochastic Timed Automata" and the resulting journal article. It contains the UPPAAL model, the Python evaluation toolchain, and the full experimental results (point estimates, 95% confidence intervals, and raw `verifyta` traces) for all eleven scenario configurations.

## Repository structure

```
model/
  Supply Chain V11.4.1.xml       UPPAAL model: 12 templates, 8 Boolean ENABLE_* flags
                                  (4 disruptions x 4 resilience practices), 17-query
                                  SMC battery embedded in the model file.

toolchain/
  uppaal_query_runner.py                          Core: extracts queries from the model,
                                                    runs them via verifyta, exports CSV.
  uppaal_query_runner_gui_v3_PRMM_dual_scoring.py  Base GUI: query runner, Enable Switches
                                                    panel, PRMM maturity scoring engine.
  uppaal_query_runner_gui_v6.py                    Extends v3: proportional Level 4
                                                    (improvement strength) scoring,
                                                    baseline/practice comparison heat map.

results/
  Paper1_Full_Results_With_CI.csv   All 11 scenarios x 17 queries, with point estimate,
                                     95% CI bounds, margin, and run count for each cell.
  raw_traces/                       Raw verifyta output for every one of the 187
                                     (scenario x query) runs, one .txt per run, plus a
                                     per-scenario summary CSV. Primary source data that
                                     Paper1_Full_Results_With_CI.csv was parsed from.

docs/
  (calibration notes, scenario design rationale -- see paper for full text)
```

## Requirements

- UPPAAL 5.x with `verifyta` on PATH (or pass `--verifyta /path/to/verifyta`).
- Python 3.9+, with `tkinter` and `Pillow` for the GUI tools.

## Reproducing the results

Command-line (no GUI), single scenario:

```bash
python toolchain/uppaal_query_runner.py \
  --model "model/Supply Chain V11.4.1.xml" \
  --verifyta /path/to/verifyta \
  --output results/queries.csv
```

To reproduce a specific one of the 11 reported scenarios, edit the `ENABLE_D_*` /
`ENABLE_P_*` boolean declarations in the model's global declarations block to match
the scenario's active flags (see Table 6.1 / Table A.3 in the paper), then run the
command above. The GUI tools (`uppaal_query_runner_gui_v3...py` / `_v6.py`) do this
interactively via the Enable Switches panel and additionally run the PRMM maturity
scoring pipeline.

## Scenario configurations (flags)

| Scenario | Active flags |
|---|---|
| Baseline | none |
| R | ENABLE_D_RAW_SHORTAGE |
| D | ENABLE_D_DEMAND_SHOCK |
| Q | ENABLE_D_QUALITY_SHOCK |
| F | ENABLE_D_FINISHED_TRANSPORT_DELAY |
| R + E | ENABLE_D_RAW_SHORTAGE, ENABLE_P_EMERGENCY_RAW_REPLENISHMENT |
| D + E,S | ENABLE_D_DEMAND_SHOCK, ENABLE_P_EMERGENCY_RAW_REPLENISHMENT, ENABLE_P_DEMAND_SURGE_CAPACITY |
| F + B | ENABLE_D_FINISHED_TRANSPORT_DELAY, ENABLE_P_BACKUP_FINISHED_GOODS_TRUCK |
| R,Q + E | ENABLE_D_RAW_SHORTAGE, ENABLE_D_QUALITY_SHOCK, ENABLE_P_EMERGENCY_RAW_REPLENISHMENT |
| R,D,Q,F | all four ENABLE_D_* |
| R,D,Q,F + E,A,S,B | all four ENABLE_D_* and all four ENABLE_P_* |

Query battery: 17 queries per scenario, N=50 runs per estimate query, horizon T=800 time units (see paper Table B.1 / Appendix B for full formulas).

## Citing this repository

See `CITATION.cff`. If you use this model, toolchain, or data, please cite both the repository (via its Zenodo DOI, minted on first tagged release) and the associated paper.

## License

Code (`toolchain/`): MIT License -- see `LICENSE`.
Model and data (`model/`, `results/`): CC-BY-4.0 -- see `LICENSE-DATA.md`.

## Contact

Ahmad Salameh, SYMME Laboratory, Université Savoie Mont Blanc.
Supervisors: S. Himmiche, J.-L. Maire, J.-F. Jimenez.
