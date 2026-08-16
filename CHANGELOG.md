# Changelog

This file records substantive changes to the toolchain and model, with the reasoning behind each one, so the history is legible without having to reconstruct it from commit diffs. Cosmetic/typo fixes to `README.md`, `CITATION.cff`, and the license files are not repeated here; see the git log for those.

## Toolchain correctness and usability fixes (2026-08-12)

All four changes below touch `toolchain/uppaal_query_runner.py`, `toolchain/uppaal_query_runner_gui_v3_PRMM_dual_scoring.py`, and/or `toolchain/uppaal_query_runner_gui_v6.py`. They were made while preparing to run the false-positive probe scenarios (task 6) and were verified with `python3 -m py_compile` on all three files after each change.

### 1. Fixed a bug that silently discarded confidence intervals for estimate-type queries

**File:** `uppaal_query_runner_gui_v3_PRMM_dual_scoring.py`, `parse_estimate()`.

`verifyta` reports estimate queries (e.g. `E[<=800;50](max: ...)`) as a point value plus a `+/-` margin at 95% CI, like `8.66 +/- 0.450673 (95% CI)`. The regex already captured that margin into a group named `err`, but the code that built the `ParsedTrace` result never read `err` — it hardcoded `ci_low=""` and `ci_high=""`. Every estimate-type query exported through the GUI's "extracted trace CSV" therefore had empty CI columns, even though the margin was present in the raw trace text the whole time.

Fixed by computing `ci_low = value - err` and `ci_high = value + err` and writing those into the CSV. Verified against a real trace file: `8.66 ± 0.450673` now correctly produces `ci_low=8.20933, ci_high=9.11067`.

### 2. Reduced the fixed delay between verifyta runs from 20-30s to 10s

**Files:** `uppaal_query_runner.py` (`run_verifyta_for_queries`, was 20s) and `uppaal_query_runner_gui_v3_PRMM_dual_scoring.py` (the GUI's own multi-run loop, was 30s), plus the two UI strings that displayed those old numbers ("(default 1, 30 seconds between runs)" label and the "30 seconds delay between runs" log line).

The delay exists to let RAM settle between verifyta subprocess invocations. It was set conservatively at 20-30s originally; reduced to 10s at your request to speed up batches of runs without reintroducing the RAM pressure it was added to avoid.

### 3. Added automatic scenario-identifying tags to filenames and CSV rows

**File:** `uppaal_query_runner_gui_v3_PRMM_dual_scoring.py`.

Previously, output files were named generically (e.g. `Supply Chain V11.4.1_queries.csv`) regardless of which `ENABLE_D_*`/`ENABLE_P_*` flags were active, so distinguishing one scenario's export from another required manually renaming files or folders after each run (this is why the pre-existing `results/raw_traces/` subfolders have hand-added scenario names like `Supply Chain V11.4.1_queries_traces R + E`).

Added `scenario_tag_from_model_text()`, which reads the model's current flag values and builds a tag like `DR_PE` — `D`+letter for each active disruption, `P`+letter for each active practice, in the paper's canonical D,R,Q,F / E,A,S,B order (e.g. Raw Shortage + Emergency Replenishment = `DR_PE`; nothing active = `baseline`). This tag is now:
- embedded in the output CSV filename and trace folder name (via `_default_output_csv_for_model`), so each scenario's run is self-naming, and
- written as a `scenario_tag` column in every row of the exported CSV (`ParsedTrace.scenario_tag`, added to `write_trace_csv`'s fieldnames), so the identity survives even if a file gets moved or renamed later.

### 4. Added random seed capture to exports

**File:** `uppaal_query_runner_gui_v3_PRMM_dual_scoring.py`.

`verifyta` prints the RNG seed it used for each run (`Seed is <number>`) in its raw output, but this was never extracted. Added `SEED_RE` and wired it into `parse_trace()`, so the seed is now captured into a new `seed` column in the exported CSV (`ParsedTrace.seed`). This doesn't change SMC's statistical interpretation (results are still meant to be read as confidence-interval estimates, not single-seed point values) but it makes any individual run's traces exactly replayable if ever needed. Verified against a real trace file (seed `1780486213` extracted correctly).

## Results now save automatically into `results/` (2026-08-12)

Previously, both the query-runner GUI and the PRMM evaluation/scoring tab wrote their output next to the model file, i.e. into `model/`, which mixed run outputs in with the model itself and required manually moving files into `results/` afterward.

**File:** `uppaal_query_runner_gui_v3_PRMM_dual_scoring.py`, `_default_output_csv_for_model()`.
Query-run CSVs and their raw-trace folders now default to `results/raw_traces/<model>_<tag>_queries[_traces]/` (the scenario tag from item 3 above is embedded in the folder name, so no manual renaming is needed going forward). Falls back to saving beside the model file if the model isn't inside the expected `model/` ↔ `results/` repo layout.

**File:** `uppaal_query_runner_gui_v6.py`, new `_prmm_reports_dir()` method, used by the existing `make_prmm_report_filename()` / `make_prmm_comparison_filename()` calls.
PRMM evaluation reports (`PRMM Evaluation (<timestamp>).md`) and comparison records (`PRMM Comparison Records (<timestamp>).json`) now default to a new `results/prmm_reports/` folder, with the same repo-layout fallback as above.

## Second parser bug: deterministic/zero-variance queries silently exported as 0 (2026-08-14)

**File:** `uppaal_query_runner_gui_v3_PRMM_dual_scoring.py`, `parse_estimate()`.

`verifyta` reports estimate queries two ways: the usual `(50 runs) E(...) = 8.66 +/- 0.45 (95% CI)` form (handled by `EST_RE`), and a second form for queries with zero variance across all runs, `(50 runs) E(...) = ~ 100` (no `+/-` margin at all, printed with a `~` where CI would go). `parse_estimate()` only tried `EST_RE`; when that didn't match, it returned `None` and the caller fell back to exporting `0`, silently overwriting the real deterministic value. Found by direct comparison of a probe run's raw trace text against its exported CSV: minimum-availability came out as `0` when the trace file plainly showed `100`.

Fixed by adding `EST_APPROX_RE`, a fallback regex that matches the `~`/no-margin form, with `ci_low = ci_high = value` when there's no error term to split. `parse_estimate()` now tries `EST_RE` first, then `EST_APPROX_RE`.

This bug predates this batch of fixes and had already silently zeroed out some values in the original 11-scenario battery (e.g. scenario `R`'s raw-shortage-event count read `0` instead of the true `2`). Rather than re-run UPPAAL, all 11 scenario `*_values.csv` files were regenerated in place from their existing raw `.txt` trace files, using a standalone script (`reparse_old_scenarios.py`, not part of the repo — mirrors `parse_estimate`/`parse_probability` exactly) that reparses without touching verifyta. The separately-built `results/Paper1_Full_Results_With_CI.csv` used a different, already-correct parser and was unaffected.

## Common random numbers (CRN) seed replay, for paired sensitivity comparisons (2026-08-15)

**Files:** `uppaal_query_runner.py` (`run_verifyta_for_queries`), `uppaal_query_runner_gui_v3_PRMM_dual_scoring.py`.

Added an optional `seeds` parameter to `run_verifyta_for_queries()`: when provided, each query is run with verifyta's `-r <seed>` flag instead of letting it pick a random seed. `parse_trace()` already captured each run's seed into a `seed` CSV column (see the seed-capture fix above), so a reference run's seeds can be replayed exactly against a perturbed model. This removes independent-seed noise from parameter-sensitivity comparisons: two runs that differ only in one changed constant (e.g. `T1_MAX`) now differ only because of that constant, not because they also drew different random numbers.

Exposed in the GUI as a new "Reference seeds CSV" field in the Query Runner tab (`browse_reference_seeds()`, `_load_reference_seeds()`); if the CSV is missing, missing the `seed` column, or has fewer seed values than selected queries, the run is refused with an explicit error rather than silently falling back to random seeds. Used for the 8-run `T1_MAX` (12/16/20) and demand-shock-shape (0.5/1.0/2.0) sensitivity sweep documented in the "New results" section below.

## Calibration tab: live model-constant editing from the GUI (2026-08-15)

**Files:** `uppaal_query_runner_gui_v3_PRMM_dual_scoring.py`, `model/Supply Chain V11.4.1.xml`.

Previously, changing a calibration constant (`T1_MAX`, `N_CUST`, the demand-shock gamma parameters, the query horizon) meant hand-editing the model XML. Added a new "Calibration" tab (between Enable Switches and PRMM Evaluation) that reads and writes a whitelisted set of `const int`/`const double` declarations (`CALIBRATION_VARS`) plus the query-horizon bound, scoped strictly to the `<queries>` block so horizon edits can't accidentally touch an unrelated numeric literal elsewhere in the file.

This required pulling the demand-shock gamma parameters (previously inline literals inside `demand_shock_pct_sample()`/`demand_shock_duration_sample()`) out into named consts — `DEMAND_SHOCK_PCT_SHAPE`, `DEMAND_SHOCK_PCT_SCALE`, `DEMAND_SHOCK_DURATION_SHAPE`, `DEMAND_SHOCK_DURATION_SCALE` — in `model/Supply Chain V11.4.1.xml`. This is behavior-preserving (same values, `random_gamma(1.0, 2.0)` → `random_gamma(DEMAND_SHOCK_PCT_SHAPE, DEMAND_SHOCK_PCT_SCALE)` with `DEMAND_SHOCK_PCT_SHAPE = 1.0`, `DEMAND_SHOCK_PCT_SCALE = 2.0`, etc.) and only exists so the Calibration tab has a named constant to point at.

## New results: false-positive probes and parameter sensitivity sweep (2026-08-14 to 2026-08-16)

**Folders in `results/raw_traces/`:** `Supply Chain V11.4.1_PE_queries_traces/`, `_PA_`, `_PS_`, `_PB_` (the four false-positive probes: each practice flag run alone with its corresponding disruption switched off — E and A without R, S without D, B without F); plus new run data added into the `_baseline_`, `_DR_PE_`, `_DD_`, and `_DD_PE_PS_` trace folders (T1_MAX ∈ {12,16,20} under Baseline and R+E flags; demand-shock shape ∈ {0.5,1.0,2.0} under D and D+E,S flags — each pair CRN-replayed against the same reference seeds so only the swept constant differs between runs; multiple runs' trace files coexist in these folders with `_1`/`_2`/`_3` suffixes per query).

Methodology and results for both are written up in the paper draft, not repeated here.

## Model configuration (not a toolchain change)

`model/Supply Chain V11.4.1.xml` is also modified in this batch, but only in one substantive place: `ENABLE_D_RAW_SHORTAGE` was flipped from `true` to `false`, leaving `ENABLE_P_EMERGENCY_RAW_REPLENISHMENT` as the only active flag. This is the "E without R" false-positive probe scenario from task 6 (Emergency Raw Replenishment active with no Raw Shortage disruption to respond to), set up via the GUI's Enable Switches panel, not a manual edit. The diff against the previous commit looks much larger than that single flag flip because the GUI's save path re-serializes the file with LF line endings, while the previously committed copy had CRLF endings; `git diff --ignore-all-space` confirms the only real content change is the one flag.
