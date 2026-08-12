# Switchable STA Supply Chain Resilience Model + PRMM Evidence Binding

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21893262.svg)](https://doi.org/10.5281/zenodo.21893262)

Reproducibility artifact by Ahmad Salameh, SYMME Laboratory, Université Savoie Mont Blanc. The formal citation for the associated journal article will be added here once it is accepted; until then, cite this repository directly (see "Citing this repository" below).

This repository accompanies the internship report "Modelling and Analysis of Supply Chain Resilience Using Stochastic Timed Automata" and the resulting journal article. It provides a switchable **Stochastic Timed Automata (STA)** model of supply chain resilience, analyzed through **Statistical Model Checking (SMC)** in UPPAAL, together with a Python toolchain that binds the resulting quantitative evidence to a **Process Resilience Maturity Model (PRMM)** score. Concretely, it contains the UPPAAL model, the Python evaluation toolchain, and the full experimental results (point estimates, 95% confidence intervals, and raw `verifyta` traces) for all eleven scenario configurations.

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
  calibration_and_scenario_design.md   Calibration methodology and the 11-scenario
                                        design rationale (condensed; see the paper
                                        for the full text).
```

## Requirements

- UPPAAL 5.0.0 (rev. 714BA9DB36F49691, June 2023) or compatible, with the `verifyta` command-line tool on PATH (or pass `--verifyta /path/to/verifyta`). Built with TIGA/Stratego support enabled.
- Python 3.9+, with `tkinter` and `Pillow` (`pip install pillow`) for the GUI tools.

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
the scenario's active flags (see Table 6.1 / Table A.3 in the internship report,
renumbered in the journal article), then run the command above.

GUI tools (interactive Enable Switches panel + PRMM maturity scoring pipeline):

```bash
cd toolchain
python uppaal_query_runner_gui_v6.py
```

Run these from *inside* the `toolchain/` directory (or add it to `PYTHONPATH`) --
`uppaal_query_runner_gui_v6.py` imports `uppaal_query_runner_gui_v3_PRMM_dual_scoring.py`
and `uppaal_query_runner.py` as sibling modules, so launching it from the repo root
will raise `ModuleNotFoundError`.

## Disruptions and practices

The model implements four disruptions and four resilience practices, each controlled
by its own `ENABLE_*` Boolean flag and referred to by a single letter in scenario
names throughout this repository and the paper:

| Letter | Full name | Flag |
|---|---|---|
| D | Demand Shock | `ENABLE_D_DEMAND_SHOCK` |
| R | Raw Shortage | `ENABLE_D_RAW_SHORTAGE` |
| Q | Quality Shock | `ENABLE_D_QUALITY_SHOCK` |
| F | Finished (goods) Transport Delay | `ENABLE_D_FINISHED_TRANSPORT_DELAY` |
| E | Emergency Raw Replenishment | `ENABLE_P_EMERGENCY_RAW_REPLENISHMENT` |
| A | Adaptive Raw Safety Stock | `ENABLE_P_ADAPTIVE_RAW_SAFETY_STOCK` |
| S | Demand Surge Capacity | `ENABLE_P_DEMAND_SURGE_CAPACITY` |
| B | Backup Finished Goods Truck | `ENABLE_P_BACKUP_FINISHED_GOODS_TRUCK` |

The first four (D, R, Q, F) are disruptions; the last four (E, A, S, B) are the
resilience practices that mitigate them. A scenario name like `R + E` means
Raw Shortage mitigated by Emergency Raw Replenishment; `R,D,Q,F + E,A,S,B`
means all four disruptions active, met with the full four-practice portfolio.

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

See `CITATION.cff`. If you use this model, toolchain, or data, please cite both the repository (DOI: [10.5281/zenodo.21893262](https://doi.org/10.5281/zenodo.21893262), v1.0.0) and the associated paper.

## License

Code (`toolchain/`): MIT License -- see `LICENSE`.
Model and data (`model/`, `results/`): CC-BY-4.0 -- see `LICENSE-DATA.md`.

## Contact

Ahmad Salameh, SYMME Laboratory, Université Savoie Mont Blanc.
Supervisors: S. Himmiche, J.-L. Maire, J.-F. Jimenez.
