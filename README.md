# Switchable STA Supply Chain Resilience Model + PRMM Evidence Binding

<!-- TODO (Ahmad): replace with the real Zenodo badge once the final DOI exists, e.g.
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg)](https://doi.org/10.5281/zenodo.XXXXXXX)
-->

Reproducibility artifact by Ahmad Salameh and Sara Himmiche, SYMME Laboratory, Université Savoie Mont Blanc. The formal citation for the associated journal article will be added here once it is accepted; until then, cite this repository directly (see "Citing this repository" below).

**Keywords:** supply chain resilience, stochastic timed automata, statistical model checking, UPPAAL SMC, process maturity model, internal validity, reproducibility, discrete event simulation

This repository presents the current, final state of the model, toolchain, and results supporting the paper. Earlier revision history (successive development notes, superseded paper drafts, internal audit trail) is kept in a separate, private archive repository rather than here; contact the author if you need access to it.

This repository accompanies the internship report "Modelling and Analysis of Supply Chain Resilience Using Stochastic Timed Automata" and the resulting journal article. It provides a switchable **Stochastic Timed Automata (STA)** model of supply chain resilience, analyzed through **Statistical Model Checking (SMC)** in UPPAAL, together with a Python toolchain that binds the resulting quantitative evidence to a **Process Resilience Maturity Model (PRMM)** score. Concretely, it contains the UPPAAL model, the Python evaluation toolchain, and the full experimental results (point estimates, 95% confidence intervals, and raw `verifyta` traces) for: the eleven main scenario configurations; four spurious activation probes; an eight run parameter sensitivity sweep; a 12 run Plackett–Burman (PB12) screen over all eight flags; and a three replicate severity doubling robustness check for the F/F+B comparison (see "Scenario configurations" and the two subsequent sections below). It also contains a set of standalone reanalysis scripts, added across several revision rounds, that recompute every reported statistic directly from the raw `verifyta` traces rather than from any intermediate transcription (see "Toolchain: analysis/reanalysis scripts" below).

## Repository structure

```
model/
  Supply Chain V11.4.1.xml       UPPAAL model: 12 templates, 8 Boolean ENABLE_* flags
                                  (4 disruptions x 4 resilience practices), 17 query
                                  SMC battery embedded in the model file.

toolchain/
  uppaal_query_runner.py                          Core: extracts queries from the model,
                                                    runs them via verifyta, exports CSV.
  uppaal_query_runner_gui_v3_PRMM_dual_scoring.py  Base GUI: query runner, Enable Switches
                                                    panel, PRMM maturity scoring engine.
  uppaal_query_runner_gui_v6.py                    Extends v3: proportional Level 4
                                                    (improvement strength) scoring,
                                                    baseline/practice comparison heat map.

                  v3 also provides a Calibration tab for live editing model constants
                  (T1_MAX, N_CUST, demand shock gamma parameters, query horizon) without
                  hand editing the XML, and a "Reference seeds CSV" field in the Query
                  Runner tab for common random numbers (CRN) seed replay -- pointing a
                  run at a prior run's captured seeds so a paired sensitivity comparison
                  differs only in the swept constant, not in independent RNG noise.

  Analysis and reanalysis scripts (added across revision rounds; each recomputes
  its result directly from results/raw_traces/, not from any intermediate
  CSV, and each is independently runnable, e.g. `python3 toolchain/<script>.py`
  from inside toolchain/):
    difference_ci_reanalysis.py       Canonical FDR corrected difference CI
                                       significance test (Comparison, diff_ci(),
                                       benjamini_hochberg()) used by every other
                                       script below and by the paper's own
                                       significance criterion.
    reconcile_prmm_l4.py              PRMM Level 4 (S4) scoring, CI overlap
                                       consistent, for the four main cases
                                       (paper Table tab:prmm-l4).
    matched_kpi_l4.py                 Matched KPI only variant of the above
                                       (paper Table tab:matched-kpi), restricted
                                       per case to disruption tagged KPIs only.
    s4_bootstrap.py                   Parametric bootstrap propagating KPI level
                                       sampling uncertainty into S4_final/S_final
                                       (Supplementary Material Section S9).
    prmm_l4_diffci_concordance_check.py  Confirms the CI overlap and point
                                       estimate sign classifications agree on
                                       all 28 KPI x case cells.
    newcombe_concordance_check.py     Newcombe's method concordance check for
                                       the 4 Pr(.)-query comparisons (Supp. S2).
    pooled_fdr_family_check.py        Pooled 92 comparison family FDR robustness
                                       check (Supp. S3).
    degenerate_ci_breakdown.py        Breakdown SE stress test for degenerate
                                       CIs near a hard floor/ceiling (Supp. S4).
    main_battery_mde.py, fb_per_kpi_mde.py   Per KPI minimum detectable effect
                                       tables for the main battery and F->F+B
                                       respectively (Supp. S5, paper Table
                                       tab:fb-mde).
    weight_vertex_acceptability.py    Closed form weight simplex vertex range +
                                       Monte Carlo acceptability share analysis
                                       (Supp. S6).
    s5_ceiling_derivation.py          Derives the S5=0 structural ceiling on
                                       S_final under the baseline weights.
    pb12_design.py, pb12_main_effects.py   PB12 design construction/orthogonality
                                       check, and main effects estimation from
                                       the executed PB12 runs (Supp. S1).
    fb_severity_sweep.py              Inverse variance pooling of the F/F+B
                                       severity doubling replicates (paper
                                       Table tab:fb-severity).
    decomp_re_uncertainty.py          Monte Carlo propagation of E's background
                                       effect share of the R->R+E gap (paper
                                       Table tab:decomp-re).
    tractability_evidence.py          Extracts SMC throughput/query count
                                       tractability evidence for C2 directly
                                       from the raw traces and model file.
    audit_results.py, test_audit_results.py   Regression tests for the two
                                       historical parser bugs documented in
                                       these scripts' own comments.

results/
  Paper1_Full_Results_With_CI.csv   All 11 main scenarios x 17 queries, with point
                                     estimate, 95% CI bounds, margin, and run count for
                                     each cell.
  raw_traces/                       Raw verifyta output for every scenario x query run,
                                     one .txt per run, plus a per scenario summary CSV.
                                     Primary source data that Paper1_Full_Results_With_CI.csv
                                     was parsed from. 391 files across 19 folders cover the
                                     main battery, the spurious activation probes, and the
                                     parameter sensitivity sweep specifically:
                                       - 11 folders `_queries_traces <scenario>` (17 files
                                         each = 187): the main CI battery.
                                       - 4 folders `_PE_`, `_PA_`, `_PS_`, `_PB_` (17 files
                                         each = 68): the spurious activation probes.
                                       - 4 folders `_baseline_`, `_DR_PE_`, `_DD_`, and
                                         `_DD_PE_PS_` (34 files each = 136): the CRN paired
                                         parameter sensitivity sweep, distinguished by
                                         `_1`/`_2`/`_3` trace file suffixes per query (the
                                         suffix is a per folder run counter, not a global
                                         parameter value code -- see `results/AUDIT_REPORT.md`).
                                     A further 289 files across 13 folders, added in later
                                     revision rounds, are not part of the 391 file figure the
                                     paper's Data and Code Availability section reports (that
                                     figure is scoped specifically to the main battery, probes,
                                     and sensitivity sweep) but are deposited here alongside it
                                     and documented in the Supplementary Material:
                                       - 11 folders named by flag letter tag (e.g. `_DD_DR_DF_PE_PA_`,
                                         one per PB12 design row; 17 files each = 187): the
                                         12 run Plackett–Burman screen (Supplementary Section S1;
                                         the 12th row is the already deposited Baseline folder,
                                         reused rather than rerun).
                                       - 2 folders `_DF_` and `_DF_PB_` (51 files each = 102,
                                         `_1`/`_2`/`_3` suffixes = three independent seed
                                         replicates): the F/F+B severity doubling robustness
                                         check at FG_TRANSPORT_DELAY_DURATION=100 (paper Table
                                         tab:fb-severity, Supplementary Section S7).
                                     391 + 187 + 102 = 680 raw trace files in total.
```

## Requirements

- UPPAAL 5.0.0 (rev. 714BA9DB36F49691, June 2023) or compatible, with the `verifyta` command line tool on PATH (or pass `--verifyta /path/to/verifyta`). Built with TIGA/Stratego support enabled.
- Python 3.9+, with `tkinter` and `Pillow` (`pip install pillow`) for the GUI tools.

## Reproducing the results

Command line (no GUI), single scenario:

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
means all four disruptions active, met with the full four practice portfolio.

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

### Spurious activation probes

Four additional scenarios test whether a practice flag produces an effect even with no matching disruption active (a spurious effect would indicate the practice's model logic isn't properly gated on its disruption):

| Scenario | Active flags |
|---|---|
| E without R | ENABLE_P_EMERGENCY_RAW_REPLENISHMENT only |
| A without R | ENABLE_P_ADAPTIVE_RAW_SAFETY_STOCK only |
| S without D | ENABLE_P_DEMAND_SURGE_CAPACITY only |
| B without F | ENABLE_P_BACKUP_FINISHED_GOODS_TRUCK only |

Results and interpretation are in the paper (Section "Spurious activation probes").

### Parameter sensitivity sweep

Eight CRN paired runs test two calibration uncertainty parameters -- `T1_MAX` (12/16/20) and the demand shock gamma shape `DEMAND_SHOCK_PCT_SHAPE` (0.5/1.0/2.0) -- each under two matched flag combinations (Baseline/R+E for `T1_MAX`; D/D+E,S for the shape parameter), replayed against a fixed reference run's seeds so only the swept constant differs between paired runs. `N_CUST`/`N_STORE` were deliberately excluded from this sweep: they're fixed by the source ERPsim dataset, not free/estimated calibration parameters, so testing sensitivity to them wouldn't answer the same question. Results are written up in the paper's Calibration section.

### Plackett–Burman (PB12) screen

A 12 run Plackett–Burman design over all 8 flags (R, D, Q, F, E, A, S, B), estimating every flag's main effect from 12 runs instead of the 256 a full factorial would require. One of the 12 rows (all flags off) coincides with the already deposited Baseline folder, so only 11 new scenarios were run; each is deposited under a flag letter tag folder in `results/raw_traces/` (e.g. `Supply Chain V11.4.1_DD_DR_DF_PE_PA_queries_traces` for the row enabling D, R, F, E, A). Design construction, orthogonality verification, and main effects estimation are in `toolchain/pb12_design.py` and `toolchain/pb12_main_effects.py`. Full design table, results, and the Resolution III aliasing caveat are in the paper's Supplementary Material, Section S1.

### F/F+B severity doubling robustness check

`FG_TRANSPORT_DELAY_DURATION` doubled from 50 to 100 (period and disrupted trip time constants unchanged), with F and F+B each rerun three times at independent seeds under the doubled window, deposited in `results/raw_traces/Supply Chain V11.4.1_DF_queries_traces/` and `..._DF_PB_queries_traces/` (three replicates distinguished by `_1`/`_2`/`_3` trace file suffixes per query, same convention as the parameter sensitivity sweep). Pooling via `toolchain/fb_severity_sweep.py`; results in the paper's Table `tab:fb-severity` and Supplementary Material Section S7 (Cochran's Q heterogeneity check across the three replicates).

## Citing this repository

See `CITATION.cff`. If you use this model, toolchain, or data, please cite both the repository (DOI: see `CITATION.cff` -- pending, to be filled in once the final version's Zenodo archive is published) and the associated paper.

## License

Code (`toolchain/`): MIT License -- see `LICENSE`.
Model and data (`model/`, `results/`): CC BY 4.0 -- see `LICENSE-DATA.md`.

## Contact

Ahmad Salameh, SYMME Laboratory, Université Savoie Mont Blanc. ORCID: [0009-0003-1662-0554](https://orcid.org/0009-0003-1662-0554).
Sara Himmiche, SYMME Laboratory, Université Savoie Mont Blanc.
Additional supervision: J.-L. Maire, J.-F. Jimenez.
