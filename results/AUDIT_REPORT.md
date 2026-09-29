# Independent Audit Report — Switchable STA + PRMM SMC Results

**Scope:** every numeric claim in `tab:ci`, `tab:probe-results`, `tab:sensitivity-t1max`, and `tab:sensitivity-shape` in `Paper1_Draft_Sections.tex`, cross-checked against an independent reparse of the raw `verifyta` `.txt` trace files under `results/raw_traces/`, plus a full reparse-vs-existing-CSV cross-check for every `*_queries_values.csv` in the repo.

**Method:** `toolchain/audit_results.py` reimplements the exact parsing regexes (`PROB_RE`, `EST_RE`, `EST_APPROX_RE`, `SEED_RE`) and functions (`parse_probability`, `parse_estimate`, `parse_trace`) from `toolchain/uppaal_query_runner_gui_v3_PRMM_dual_scoring.py`, applies them directly to the raw trace files on disk (no GUI, no dependency on any existing CSV), extracts every numeric table cell from the paper's `.tex` source with a small regex-based LaTeX table parser (not hand-transcription), and independently recomputes the paper's own stated significance criterion — **non-overlapping 95% CIs ⇒ statistically significant** — for every before/after, probe-vs-baseline, and sweep-vs-reference comparison the paper labels significant or not.

Regression tests for the two previously-fixed parser bugs (discarded CI margins on estimate queries; deterministic/zero-variance queries silently exported as `0`) live in `toolchain/test_audit_results.py` — **11/11 pass** (see below).

Nothing in this repo or the paper was modified to produce this report. `audit_results.py` only reads; this Markdown file and nothing else was written as output.

## Unit test results (`toolchain/test_audit_results.py`)

```
test_non_overlapping_is_significant (test_audit_results.TestCIOverlapSignificance) ... ok
test_overlapping_is_not_significant (test_audit_results.TestCIOverlapSignificance) ... ok
test_touching_bounds_count_as_overlap (test_audit_results.TestCIOverlapSignificance) ... ok
test_zero_width_ci_identical_overlap (test_audit_results.TestCIOverlapSignificance) ... ok
test_zero_width_ci_no_overlap (test_audit_results.TestCIOverlapSignificance) ... ok
test_deterministic_min_availability (test_audit_results.TestDeterministicValueNoMargin) ... ok
test_deterministic_value_with_approx_symbol (test_audit_results.TestDeterministicValueNoMargin) ... ok
test_ascii_plus_minus_variant (test_audit_results.TestNormalEstimateWithMargin) ... ok
test_estimate_with_plus_minus_margin (test_audit_results.TestNormalEstimateWithMargin) ... ok
test_probability_query_parses_value_and_ci (test_audit_results.TestProbabilityQuery) ... ok
test_seed_is_captured (test_audit_results.TestSeedCapture) ... ok

Ran 11 tests in 0.002s

OK
```

## Sanity check on the audit script itself

Before trusting a "clean" result, the audit script was run against a **deliberately corrupted copy** of the paper's `.tex` (one `tab:ci` value changed from `214.62` to `999.99`, and one `tab:sensitivity-shape` CI margin changed from `±25.00` to `±0.01`). The script correctly flagged both injected errors as `VALUE_MISMATCH` and left every untouched check `OK` — confirming the audit logic actually discriminates rather than rubber-stamping. That corrupted copy was a scratch file outside the repo and has been discarded; no repo or paper file was touched.

## KPI index verification (query filename → KPI name)

The four "load-bearing KPIs" used throughout the paper are query index `003` (Safe stock recovery time), `005` (Active production blocked time — **not** `004`, which is a separate "latent" blocked-time query), `007` (Stockout duration), and `012` (Minimum availability). This mapping was confirmed empirically before running the full audit, by reparsing `results/raw_traces/Supply Chain V11.4.1_queries_traces R/` query 003/005/007/012 and matching the reparsed numbers 1:1 against the paper's stated "R → R+E, before" row (`214.62±21.85`, `617.60±8.99`, `55.92±5.02`, `93.18±0.81`) — an exact match, confirming both the index→KPI mapping and (as a side effect) the first row of `tab:ci`.

## Sweep-folder suffix mapping (T1_MAX / demand-shock-shape sensitivity tables)

The sweep folders (`_baseline_`, `_DR_PE_`, `_DD_`, `_DD_PE_PS_`) hold multiple runs' trace files with `_1`/`_2`/`_3` suffixes per query, but **the numeric suffix is not a consistent parameter-value key across folders**: direct inspection during this audit found suffix `_1` is the low sweep point (T1_MAX=12) in the `_baseline_` folder, but suffix `_2` is the low sweep point (T1_MAX=12) in the `_DR_PE_` folder (`_baseline_` has suffixes `{1,3}`; `_DR_PE_` has suffixes `{2,3}`; `_DD_` and `_DD_PE_PS_` have suffixes `{1,2}`). The reference run (T1_MAX=16 / shape=1.0) for each sweep is **not** stored in the sweep folder at all — it is the single-suffix trace already sitting in the corresponding main scenario folder (`..._queries_traces baseline`, `..._queries_traces R + E`, `..._queries_traces D`, `..._queries_traces D + E,S`).

Because of this, `audit_results.py` does **not** assume a suffix→parameter mapping. For each sweep row it reparses both non-reference trace files in the sweep folder and assigns them to the paper's "low"/"high" columns by whichever pairing minimizes total value+margin error (trying both permutations of the 2 candidates) — i.e. the mapping is discovered from the data itself, not asserted. The report below states which suffix was matched to which column for full traceability. Every one of these matches turned out to have a near-zero residual (paper value and reparsed value agree to the displayed 2 decimal places), so the discovered mapping is unambiguous, not a forced best-of-two fit.

### `tab:ci` — 32 checks — CLEAN

| Location | Verdict | Detail |
|---|---|---|
| R -> R+E / Safe stock recovery time / before | OK | paper=214.62±21.85 matches reparsed 214.62±21.848 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces R/003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_1.txt) |
| R -> R+E / Safe stock recovery time / after | OK | paper=8.66±0.45 matches reparsed 8.66±0.4506 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces R + E/003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_1.txt) |
| R -> R+E / Active production blocked time / before | OK | paper=617.6±8.99 matches reparsed 617.6±8.9890 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces R/005_estimate_E_800_50_max_max_production_blocked_time_live_all_1.txt) |
| R -> R+E / Active production blocked time / after | OK | paper=16.96±1.52 matches reparsed 16.96±1.5169 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces R + E/005_estimate_E_800_50_max_max_production_blocked_time_live_all_1.txt) |
| R -> R+E / Stockout duration / before | OK | paper=55.92±5.02 matches reparsed 55.92±5.0228 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces R/007_estimate_E_800_50_max_max_stockout_duration_live_all_1.txt) |
| R -> R+E / Stockout duration / after | OK | paper=0.0±None matches reparsed 0.0±0.0 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces R + E/007_estimate_E_800_50_max_max_stockout_duration_live_all_1.txt) |
| R -> R+E / Minimum availability / before | OK | paper=93.18±0.81 matches reparsed 93.18±0.8093 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces R/012_estimate_E_800_50_min_min_availability_pct_all_1.txt) |
| R -> R+E / Minimum availability / after | OK | paper=100.0±None matches reparsed 100.0±0.0 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces R + E/012_estimate_E_800_50_min_min_availability_pct_all_1.txt) |
| D -> D+E,S / Safe stock recovery time / before | OK | paper=190.22±25.18 matches reparsed 190.22±25.1819 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces D/003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_1.txt) |
| D -> D+E,S / Safe stock recovery time / after | OK | paper=12.22±4.92 matches reparsed 12.22±4.9191 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces D + E,S/003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_1.txt) |
| D -> D+E,S / Active production blocked time / before | OK | paper=621.84±9.85 matches reparsed 621.84±9.8460 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces D/005_estimate_E_800_50_max_max_production_blocked_time_live_all_1.txt) |
| D -> D+E,S / Active production blocked time / after | OK | paper=37.52±9.95 matches reparsed 37.52±9.9488 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces D + E,S/005_estimate_E_800_50_max_max_production_blocked_time_live_all_1.txt) |
| D -> D+E,S / Stockout duration / before | OK | paper=46.68±6.4 matches reparsed 46.68±6.3975 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces D/007_estimate_E_800_50_max_max_stockout_duration_live_all_1.txt) |
| D -> D+E,S / Stockout duration / after | OK | paper=0.76±1.53 matches reparsed 0.76±1.5272 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces D + E,S/007_estimate_E_800_50_max_max_stockout_duration_live_all_1.txt) |
| D -> D+E,S / Minimum availability / before | OK | paper=94.2±0.78 matches reparsed 94.2±0.7830 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces D/012_estimate_E_800_50_min_min_availability_pct_all_1.txt) |
| D -> D+E,S / Minimum availability / after | OK | paper=99.82±0.32 matches reparsed 99.82±0.3231 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces D + E,S/012_estimate_E_800_50_min_min_availability_pct_all_1.txt) |
| F -> F+B / Safe stock recovery time / before | OK | paper=142.54±15.7 matches reparsed 142.54±15.6969 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces F/003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_1.txt) |
| F -> F+B / Safe stock recovery time / after | OK | paper=142.58±15.61 matches reparsed 142.58±15.6060 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces F + B/003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_1.txt) |
| F -> F+B / Active production blocked time / before | OK | paper=594.18±11.98 matches reparsed 594.18±11.9759 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces F/005_estimate_E_800_50_max_max_production_blocked_time_live_all_1.txt) |
| F -> F+B / Active production blocked time / after | OK | paper=606.06±12.06 matches reparsed 606.06±12.0619 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces F + B/005_estimate_E_800_50_max_max_production_blocked_time_live_all_1.txt) |
| F -> F+B / Stockout duration / before | OK | paper=42.24±5.56 matches reparsed 42.24±5.5597 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces F/007_estimate_E_800_50_max_max_stockout_duration_live_all_1.txt) |
| F -> F+B / Stockout duration / after | OK | paper=39.6±5.42 matches reparsed 39.6±5.4173 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces F + B/007_estimate_E_800_50_max_max_stockout_duration_live_all_1.txt) |
| F -> F+B / Minimum availability / before | OK | paper=95.0±0.66 matches reparsed 95.0±0.6597 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces F/012_estimate_E_800_50_min_min_availability_pct_all_1.txt) |
| F -> F+B / Minimum availability / after | OK | paper=94.86±0.75 matches reparsed 94.86±0.7463 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces F + B/012_estimate_E_800_50_min_min_availability_pct_all_1.txt) |
| R,D,Q,F -> +E,A,S,B / Safe stock recovery time / before | OK | paper=216.58±22.33 matches reparsed 216.58±22.3310 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces R,D,Q,F/003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_1.txt) |
| R,D,Q,F -> +E,A,S,B / Safe stock recovery time / after | OK | paper=39.88±6.51 matches reparsed 39.88±6.5130 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces R,D,Q,F + E,A,S,B/003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_1.txt) |
| R,D,Q,F -> +E,A,S,B / Active production blocked time / before | OK | paper=606.12±10.76 matches reparsed 606.12±10.7599 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces R,D,Q,F/005_estimate_E_800_50_max_max_production_blocked_time_live_all_1.txt) |
| R,D,Q,F -> +E,A,S,B / Active production blocked time / after | OK | paper=38.82±10.98 matches reparsed 38.82±10.9769 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces R,D,Q,F + E,A,S,B/005_estimate_E_800_50_max_max_production_blocked_time_live_all_1.txt) |
| R,D,Q,F -> +E,A,S,B / Stockout duration / before | OK | paper=71.54±5.72 matches reparsed 71.54±5.7192 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces R,D,Q,F/007_estimate_E_800_50_max_max_stockout_duration_live_all_1.txt) |
| R,D,Q,F -> +E,A,S,B / Stockout duration / after | OK | paper=4.52±2.14 matches reparsed 4.52±2.1439 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces R,D,Q,F + E,A,S,B/007_estimate_E_800_50_max_max_stockout_duration_live_all_1.txt) |
| R,D,Q,F -> +E,A,S,B / Minimum availability / before | OK | paper=91.78±0.88 matches reparsed 91.78±0.8807 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces R,D,Q,F/012_estimate_E_800_50_min_min_availability_pct_all_1.txt) |
| R,D,Q,F -> +E,A,S,B / Minimum availability / after | OK | paper=99.66±0.27 matches reparsed 99.66±0.2730 (file: results/raw_traces/Supply Chain V11.4.1_queries_traces R,D,Q,F + E,A,S,B/012_estimate_E_800_50_min_min_availability_pct_all_1.txt) |

### `tab:ci-significance` — 16 checks — CLEAN

| Location | Verdict | Detail |
|---|---|---|
| R -> R+E / Safe stock recovery time (significance, from paper's own printed CIs) | OK | expected significant, recomputed CI-overlap test agrees |
| R -> R+E / Active production blocked time (significance, from paper's own printed CIs) | OK | expected significant, recomputed CI-overlap test agrees |
| R -> R+E / Stockout duration (significance, from paper's own printed CIs) | OK | expected significant, recomputed CI-overlap test agrees |
| R -> R+E / Minimum availability (significance, from paper's own printed CIs) | OK | expected significant, recomputed CI-overlap test agrees |
| D -> D+E,S / Safe stock recovery time (significance, from paper's own printed CIs) | OK | expected significant, recomputed CI-overlap test agrees |
| D -> D+E,S / Active production blocked time (significance, from paper's own printed CIs) | OK | expected significant, recomputed CI-overlap test agrees |
| D -> D+E,S / Stockout duration (significance, from paper's own printed CIs) | OK | expected significant, recomputed CI-overlap test agrees |
| D -> D+E,S / Minimum availability (significance, from paper's own printed CIs) | OK | expected significant, recomputed CI-overlap test agrees |
| F -> F+B / Safe stock recovery time (significance, from paper's own printed CIs) | OK | expected not significant, recomputed CI-overlap test agrees |
| F -> F+B / Active production blocked time (significance, from paper's own printed CIs) | OK | expected not significant, recomputed CI-overlap test agrees |
| F -> F+B / Stockout duration (significance, from paper's own printed CIs) | OK | expected not significant, recomputed CI-overlap test agrees |
| F -> F+B / Minimum availability (significance, from paper's own printed CIs) | OK | expected not significant, recomputed CI-overlap test agrees |
| R,D,Q,F -> +E,A,S,B / Safe stock recovery time (significance, from paper's own printed CIs) | OK | expected significant, recomputed CI-overlap test agrees |
| R,D,Q,F -> +E,A,S,B / Active production blocked time (significance, from paper's own printed CIs) | OK | expected significant, recomputed CI-overlap test agrees |
| R,D,Q,F -> +E,A,S,B / Stockout duration (significance, from paper's own printed CIs) | OK | expected significant, recomputed CI-overlap test agrees |
| R,D,Q,F -> +E,A,S,B / Minimum availability (significance, from paper's own printed CIs) | OK | expected significant, recomputed CI-overlap test agrees |

### `tab:probe-results` — 32 checks — CLEAN

| Location | Verdict | Detail |
|---|---|---|
| Safe stock recovery time / baseline | OK | paper=148.04±20.92 matches reparsed 148.04±20.9219 |
| Safe stock recovery time / E without R | OK | paper=8.58±0.37 matches reparsed 8.58±0.3725 |
| Safe stock recovery time / baseline | OK | paper=148.04±20.92 matches reparsed 148.04±20.9219 |
| Safe stock recovery time / A without R | OK | paper=98.86±17.57 matches reparsed 98.86±17.5671 |
| Active production blocked time / baseline | OK | paper=605.06±14.25 matches reparsed 605.06±14.2479 |
| Active production blocked time / E without R | OK | paper=16.82±1.37 matches reparsed 16.82±1.3668 |
| Active production blocked time / baseline | OK | paper=605.06±14.25 matches reparsed 605.06±14.2479 |
| Active production blocked time / A without R | OK | paper=489.62±17.39 matches reparsed 489.62±17.393 |
| Stockout duration / baseline | OK | paper=35.9±5.71 matches reparsed 35.9±5.7075 |
| Stockout duration / E without R | OK | paper=0.0±None matches reparsed 0.0±0.0 |
| Stockout duration / baseline | OK | paper=35.9±5.71 matches reparsed 35.9±5.7075 |
| Stockout duration / A without R | OK | paper=20.68±5.18 matches reparsed 20.68±5.1819 |
| Minimum availability / baseline | OK | paper=95.24±0.88 matches reparsed 95.24±0.8793 |
| Minimum availability / E without R | OK | paper=100.0±None matches reparsed 100.0±0.0 |
| Minimum availability / baseline | OK | paper=95.24±0.88 matches reparsed 95.24±0.8793 |
| Minimum availability / A without R | OK | paper=97.98±0.63 matches reparsed 97.98±0.6328 |
| Safe stock recovery time / baseline | OK | paper=148.04±20.92 matches reparsed 148.04±20.9219 |
| Safe stock recovery time / S without D | OK | paper=140.38±16.19 matches reparsed 140.38±16.1870 |
| Safe stock recovery time / baseline | OK | paper=148.04±20.92 matches reparsed 148.04±20.9219 |
| Safe stock recovery time / B without F | OK | paper=161.04±20.62 matches reparsed 161.04±20.622 |
| Active production blocked time / baseline | OK | paper=605.06±14.25 matches reparsed 605.06±14.2479 |
| Active production blocked time / S without D | OK | paper=616.38±11.18 matches reparsed 616.38±11.1799 |
| Active production blocked time / baseline | OK | paper=605.06±14.25 matches reparsed 605.06±14.2479 |
| Active production blocked time / B without F | OK | paper=613.94±10.8 matches reparsed 613.94±10.7969 |
| Stockout duration / baseline | OK | paper=35.9±5.71 matches reparsed 35.9±5.7075 |
| Stockout duration / S without D | OK | paper=34.42±4.76 matches reparsed 34.42±4.7573 |
| Stockout duration / baseline | OK | paper=35.9±5.71 matches reparsed 35.9±5.7075 |
| Stockout duration / B without F | OK | paper=38.14±5.54 matches reparsed 38.14±5.5414 |
| Minimum availability / baseline | OK | paper=95.24±0.88 matches reparsed 95.24±0.8793 |
| Minimum availability / S without D | OK | paper=95.64±0.74 matches reparsed 95.64±0.7437 |
| Minimum availability / baseline | OK | paper=95.24±0.88 matches reparsed 95.24±0.8793 |
| Minimum availability / B without F | OK | paper=95.96±0.67 matches reparsed 95.96±0.6719 |

### `tab:probe-results-significance` — 16 checks — CLEAN

| Location | Verdict | Detail |
|---|---|---|
| Safe stock recovery time / E without R (significance) | OK | paper marks *, CI-overlap test agrees (significant) |
| Safe stock recovery time / A without R (significance) | OK | paper marks *, CI-overlap test agrees (significant) |
| Active production blocked time / E without R (significance) | OK | paper marks *, CI-overlap test agrees (significant) |
| Active production blocked time / A without R (significance) | OK | paper marks *, CI-overlap test agrees (significant) |
| Stockout duration / E without R (significance) | OK | paper marks *, CI-overlap test agrees (significant) |
| Stockout duration / A without R (significance) | OK | paper marks *, CI-overlap test agrees (significant) |
| Minimum availability / E without R (significance) | OK | paper marks *, CI-overlap test agrees (significant) |
| Minimum availability / A without R (significance) | OK | paper marks *, CI-overlap test agrees (significant) |
| Safe stock recovery time / S without D (significance) | OK | paper marks no marker, CI-overlap test agrees (not significant) |
| Safe stock recovery time / B without F (significance) | OK | paper marks no marker, CI-overlap test agrees (not significant) |
| Active production blocked time / S without D (significance) | OK | paper marks no marker, CI-overlap test agrees (not significant) |
| Active production blocked time / B without F (significance) | OK | paper marks no marker, CI-overlap test agrees (not significant) |
| Stockout duration / S without D (significance) | OK | paper marks no marker, CI-overlap test agrees (not significant) |
| Stockout duration / B without F (significance) | OK | paper marks no marker, CI-overlap test agrees (not significant) |
| Minimum availability / S without D (significance) | OK | paper marks no marker, CI-overlap test agrees (not significant) |
| Minimum availability / B without F (significance) | OK | paper marks no marker, CI-overlap test agrees (not significant) |

### `tab:sensitivity-t1max` — 24 checks — CLEAN

| Location | Verdict | Detail |
|---|---|---|
| Baseline (unmitigated) / Safe stock recovery time / ref | OK | reference matches: paper 148.04±20.92 == reparsed 148.04±20.9219 |
| Baseline (unmitigated) / Safe stock recovery time / low (matched to suffix _1) | OK | paper 8.52±0.38 matches reparsed 8.52±0.3775 (file: results/raw_traces/Supply Chain V11.4.1_baseline_queries_traces/003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_1.txt) |
| Baseline (unmitigated) / Safe stock recovery time / high (matched to suffix _3) | OK | paper 418.56±28.94 matches reparsed 418.56±28.9359 (file: results/raw_traces/Supply Chain V11.4.1_baseline_queries_traces/003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_3.txt) |
| Baseline (unmitigated) / Active production blocked time / ref | OK | reference matches: paper 605.06±14.25 == reparsed 605.06±14.2479 |
| Baseline (unmitigated) / Active production blocked time / low (matched to suffix _1) | OK | paper 104.06±6.05 matches reparsed 104.06±6.0471 (file: results/raw_traces/Supply Chain V11.4.1_baseline_queries_traces/005_estimate_E_800_50_max_max_production_blocked_time_live_all_1.txt) |
| Baseline (unmitigated) / Active production blocked time / high (matched to suffix _3) | OK | paper 724.42±2.06 matches reparsed 724.42±2.0590 (file: results/raw_traces/Supply Chain V11.4.1_baseline_queries_traces/005_estimate_E_800_50_max_max_production_blocked_time_live_all_3.txt) |
| Baseline (unmitigated) / Stockout duration / ref | OK | reference matches: paper 35.9±5.71 == reparsed 35.9±5.7075 |
| Baseline (unmitigated) / Stockout duration / low (matched to suffix _1) | OK | paper 0.0±None matches reparsed 0.0±0.0 (file: results/raw_traces/Supply Chain V11.4.1_baseline_queries_traces/007_estimate_E_800_50_max_max_stockout_duration_live_all_1.txt) |
| Baseline (unmitigated) / Stockout duration / high (matched to suffix _3) | OK | paper 178.48±6.41 matches reparsed 178.48±6.4140 (file: results/raw_traces/Supply Chain V11.4.1_baseline_queries_traces/007_estimate_E_800_50_max_max_stockout_duration_live_all_3.txt) |
| Baseline (unmitigated) / Minimum availability / ref | OK | reference matches: paper 95.24±0.88 == reparsed 95.24±0.8793 |
| Baseline (unmitigated) / Minimum availability / low (matched to suffix _1) | OK | paper 100.0±None matches reparsed 100.0±0.0 (file: results/raw_traces/Supply Chain V11.4.1_baseline_queries_traces/012_estimate_E_800_50_min_min_availability_pct_all_1.txt) |
| Baseline (unmitigated) / Minimum availability / high (matched to suffix _3) | OK | paper 76.46±0.92 matches reparsed 76.46±0.9190 (file: results/raw_traces/Supply Chain V11.4.1_baseline_queries_traces/012_estimate_E_800_50_min_min_availability_pct_all_3.txt) |
| R+E (matched mitigation) / Safe stock recovery time / ref | OK | reference matches: paper 8.66±0.45 == reparsed 8.66±0.4506 |
| R+E (matched mitigation) / Safe stock recovery time / low (matched to suffix _2) | OK | paper 8.68±0.4 matches reparsed 8.68±0.3996 (file: results/raw_traces/Supply Chain V11.4.1_DR_PE_queries_traces/003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_2.txt) |
| R+E (matched mitigation) / Safe stock recovery time / high (matched to suffix _3) | OK | paper 10.26±0.48 matches reparsed 10.26±0.4797 (file: results/raw_traces/Supply Chain V11.4.1_DR_PE_queries_traces/003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_3.txt) |
| R+E (matched mitigation) / Active production blocked time / ref | OK | reference matches: paper 16.96±1.52 == reparsed 16.96±1.5169 |
| R+E (matched mitigation) / Active production blocked time / low (matched to suffix _2) | OK | paper 3.28±0.7 matches reparsed 3.28±0.6962 (file: results/raw_traces/Supply Chain V11.4.1_DR_PE_queries_traces/005_estimate_E_800_50_max_max_production_blocked_time_live_all_2.txt) |
| R+E (matched mitigation) / Active production blocked time / high (matched to suffix _3) | OK | paper 54.56±3.79 matches reparsed 54.56±3.7899 (file: results/raw_traces/Supply Chain V11.4.1_DR_PE_queries_traces/005_estimate_E_800_50_max_max_production_blocked_time_live_all_3.txt) |
| R+E (matched mitigation) / Stockout duration / ref | OK | reference matches: paper 0.0±None == reparsed 0.0±0.0 |
| R+E (matched mitigation) / Stockout duration / low (matched to suffix _2) | OK | paper 0.0±None matches reparsed 0.0±0.0 (file: results/raw_traces/Supply Chain V11.4.1_DR_PE_queries_traces/007_estimate_E_800_50_max_max_stockout_duration_live_all_2.txt) |
| R+E (matched mitigation) / Stockout duration / high (matched to suffix _3) | OK | paper 0.0±None matches reparsed 0.0±0.0 (file: results/raw_traces/Supply Chain V11.4.1_DR_PE_queries_traces/007_estimate_E_800_50_max_max_stockout_duration_live_all_3.txt) |
| R+E (matched mitigation) / Minimum availability / ref | OK | reference matches: paper 100.0±None == reparsed 100.0±0.0 |
| R+E (matched mitigation) / Minimum availability / low (matched to suffix _2) | OK | paper 100.0±None matches reparsed 100.0±0.0 (file: results/raw_traces/Supply Chain V11.4.1_DR_PE_queries_traces/012_estimate_E_800_50_min_min_availability_pct_all_2.txt) |
| R+E (matched mitigation) / Minimum availability / high (matched to suffix _3) | OK | paper 100.0±None matches reparsed 100.0±0.0 (file: results/raw_traces/Supply Chain V11.4.1_DR_PE_queries_traces/012_estimate_E_800_50_min_min_availability_pct_all_3.txt) |

### `tab:sensitivity-t1max-significance` — 16 checks — CLEAN

| Location | Verdict | Detail |
|---|---|---|
| Baseline (unmitigated) / Safe stock recovery time / low (significance) | OK | paper marks *; CI-overlap on both paper cells and raw-reparsed cells agrees |
| Baseline (unmitigated) / Safe stock recovery time / high (significance) | OK | paper marks *; CI-overlap on both paper cells and raw-reparsed cells agrees |
| Baseline (unmitigated) / Active production blocked time / low (significance) | OK | paper marks *; CI-overlap on both paper cells and raw-reparsed cells agrees |
| Baseline (unmitigated) / Active production blocked time / high (significance) | OK | paper marks *; CI-overlap on both paper cells and raw-reparsed cells agrees |
| Baseline (unmitigated) / Stockout duration / low (significance) | OK | paper marks *; CI-overlap on both paper cells and raw-reparsed cells agrees |
| Baseline (unmitigated) / Stockout duration / high (significance) | OK | paper marks *; CI-overlap on both paper cells and raw-reparsed cells agrees |
| Baseline (unmitigated) / Minimum availability / low (significance) | OK | paper marks *; CI-overlap on both paper cells and raw-reparsed cells agrees |
| Baseline (unmitigated) / Minimum availability / high (significance) | OK | paper marks *; CI-overlap on both paper cells and raw-reparsed cells agrees |
| R+E (matched mitigation) / Safe stock recovery time / low (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| R+E (matched mitigation) / Safe stock recovery time / high (significance) | OK | paper marks *; CI-overlap on both paper cells and raw-reparsed cells agrees |
| R+E (matched mitigation) / Active production blocked time / low (significance) | OK | paper marks *; CI-overlap on both paper cells and raw-reparsed cells agrees |
| R+E (matched mitigation) / Active production blocked time / high (significance) | OK | paper marks *; CI-overlap on both paper cells and raw-reparsed cells agrees |
| R+E (matched mitigation) / Stockout duration / low (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| R+E (matched mitigation) / Stockout duration / high (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| R+E (matched mitigation) / Minimum availability / low (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| R+E (matched mitigation) / Minimum availability / high (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |

### `tab:sensitivity-shape` — 24 checks — CLEAN

| Location | Verdict | Detail |
|---|---|---|
| D (unmitigated) / Safe stock recovery time / ref | OK | reference matches: paper 190.22±25.18 == reparsed 190.22±25.1819 |
| D (unmitigated) / Safe stock recovery time / low (matched to suffix _1) | OK | paper 160.38±27.33 matches reparsed 160.38±27.3259 (file: results/raw_traces/Supply Chain V11.4.1_DD_queries_traces/003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_1.txt) |
| D (unmitigated) / Safe stock recovery time / high (matched to suffix _2) | OK | paper 185.0±25.0 matches reparsed 185.0±25.0039 (file: results/raw_traces/Supply Chain V11.4.1_DD_queries_traces/003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_2.txt) |
| D (unmitigated) / Active production blocked time / ref | OK | reference matches: paper 621.84±9.85 == reparsed 621.84±9.8460 |
| D (unmitigated) / Active production blocked time / low (matched to suffix _1) | OK | paper 601.32±11.29 matches reparsed 601.32±11.2900 (file: results/raw_traces/Supply Chain V11.4.1_DD_queries_traces/005_estimate_E_800_50_max_max_production_blocked_time_live_all_1.txt) |
| D (unmitigated) / Active production blocked time / high (matched to suffix _2) | OK | paper 608.56±8.59 matches reparsed 608.56±8.5939 (file: results/raw_traces/Supply Chain V11.4.1_DD_queries_traces/005_estimate_E_800_50_max_max_production_blocked_time_live_all_2.txt) |
| D (unmitigated) / Stockout duration / ref | OK | reference matches: paper 46.68±6.4 == reparsed 46.68±6.3975 |
| D (unmitigated) / Stockout duration / low (matched to suffix _1) | OK | paper 48.22±6.23 matches reparsed 48.22±6.2325 (file: results/raw_traces/Supply Chain V11.4.1_DD_queries_traces/007_estimate_E_800_50_max_max_stockout_duration_live_all_1.txt) |
| D (unmitigated) / Stockout duration / high (matched to suffix _2) | OK | paper 51.42±7.59 matches reparsed 51.42±7.5855 (file: results/raw_traces/Supply Chain V11.4.1_DD_queries_traces/007_estimate_E_800_50_max_max_stockout_duration_live_all_2.txt) |
| D (unmitigated) / Minimum availability / ref | OK | reference matches: paper 94.2±0.78 == reparsed 94.2±0.7830 |
| D (unmitigated) / Minimum availability / low (matched to suffix _1) | OK | paper 93.66±1.01 matches reparsed 93.66±1.0086 (file: results/raw_traces/Supply Chain V11.4.1_DD_queries_traces/012_estimate_E_800_50_min_min_availability_pct_all_1.txt) |
| D (unmitigated) / Minimum availability / high (matched to suffix _2) | OK | paper 94.3±0.79 matches reparsed 94.3±0.7899 (file: results/raw_traces/Supply Chain V11.4.1_DD_queries_traces/012_estimate_E_800_50_min_min_availability_pct_all_2.txt) |
| D+E,S (matched mitigation) / Safe stock recovery time / ref | OK | reference matches: paper 12.22±4.92 == reparsed 12.22±4.9191 |
| D+E,S (matched mitigation) / Safe stock recovery time / low (matched to suffix _1) | OK | paper 12.4±4.88 matches reparsed 12.4±4.8847 (file: results/raw_traces/Supply Chain V11.4.1_DD_PE_PS_queries_traces/003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_1.txt) |
| D+E,S (matched mitigation) / Safe stock recovery time / high (matched to suffix _2) | OK | paper 17.38±8.73 matches reparsed 17.38±8.7316 (file: results/raw_traces/Supply Chain V11.4.1_DD_PE_PS_queries_traces/003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_2.txt) |
| D+E,S (matched mitigation) / Active production blocked time / ref | OK | reference matches: paper 37.52±9.95 == reparsed 37.52±9.9488 |
| D+E,S (matched mitigation) / Active production blocked time / low (matched to suffix _1) | OK | paper 54.78±17.62 matches reparsed 54.78±17.6224 (file: results/raw_traces/Supply Chain V11.4.1_DD_PE_PS_queries_traces/005_estimate_E_800_50_max_max_production_blocked_time_live_all_1.txt) |
| D+E,S (matched mitigation) / Active production blocked time / high (matched to suffix _2) | OK | paper 34.66±7.99 matches reparsed 34.66±7.9856 (file: results/raw_traces/Supply Chain V11.4.1_DD_PE_PS_queries_traces/005_estimate_E_800_50_max_max_production_blocked_time_live_all_2.txt) |
| D+E,S (matched mitigation) / Stockout duration / ref | OK | reference matches: paper 0.76±1.53 == reparsed 0.76±1.5272 |
| D+E,S (matched mitigation) / Stockout duration / low (matched to suffix _1) | OK | paper 0.7±1.1 matches reparsed 0.7±1.0988 (file: results/raw_traces/Supply Chain V11.4.1_DD_PE_PS_queries_traces/007_estimate_E_800_50_max_max_stockout_duration_live_all_1.txt) |
| D+E,S (matched mitigation) / Stockout duration / high (matched to suffix _2) | OK | paper 1.1±1.57 matches reparsed 1.1±1.5663 (file: results/raw_traces/Supply Chain V11.4.1_DD_PE_PS_queries_traces/007_estimate_E_800_50_max_max_stockout_duration_live_all_2.txt) |
| D+E,S (matched mitigation) / Minimum availability / ref | OK | reference matches: paper 99.82±0.32 == reparsed 99.82±0.3231 |
| D+E,S (matched mitigation) / Minimum availability / low (matched to suffix _1) | OK | paper 99.78±0.31 matches reparsed 99.78±0.3108 (file: results/raw_traces/Supply Chain V11.4.1_DD_PE_PS_queries_traces/012_estimate_E_800_50_min_min_availability_pct_all_1.txt) |
| D+E,S (matched mitigation) / Minimum availability / high (matched to suffix _2) | OK | paper 99.98±0.04 matches reparsed 99.98±0.0400 (file: results/raw_traces/Supply Chain V11.4.1_DD_PE_PS_queries_traces/012_estimate_E_800_50_min_min_availability_pct_all_2.txt) |

### `tab:sensitivity-shape-significance` — 16 checks — CLEAN

| Location | Verdict | Detail |
|---|---|---|
| D (unmitigated) / Safe stock recovery time / low (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| D (unmitigated) / Safe stock recovery time / high (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| D (unmitigated) / Active production blocked time / low (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| D (unmitigated) / Active production blocked time / high (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| D (unmitigated) / Stockout duration / low (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| D (unmitigated) / Stockout duration / high (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| D (unmitigated) / Minimum availability / low (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| D (unmitigated) / Minimum availability / high (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| D+E,S (matched mitigation) / Safe stock recovery time / low (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| D+E,S (matched mitigation) / Safe stock recovery time / high (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| D+E,S (matched mitigation) / Active production blocked time / low (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| D+E,S (matched mitigation) / Active production blocked time / high (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| D+E,S (matched mitigation) / Stockout duration / low (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| D+E,S (matched mitigation) / Stockout duration / high (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| D+E,S (matched mitigation) / Minimum availability / low (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |
| D+E,S (matched mitigation) / Minimum availability / high (significance) | OK | paper marks no marker; CI-overlap on both paper cells and raw-reparsed cells agrees |

### `csv-cross-check` (existing `*_queries_values.csv` vs fresh reparse of their own referenced trace file) — 323 checks — CLEAN

All existing `*_queries_values.csv` files across all 19 raw_traces folders were reparsed row-by-row from their own referenced trace file and compared against the CSV's stored value/ci_low/ci_high. No discrepancies found.


## Final Verdicts

| Table | Checks | Verdict |
|---|---|---|
| `tab:ci` (value + margin, 4 cases × 4 KPIs × before/after) | 32 | **CLEAN** |
| `tab:ci` significance (CI-overlap re-test of the "Formal significance criterion" paragraph) | 16 | **CLEAN** |
| `tab:probe-results` (value + margin, Baseline + 4 probes × 4 KPIs) | 32 | **CLEAN** |
| `tab:probe-results` significance (asterisk vs recomputed CI-overlap) | 16 | **CLEAN** |
| `tab:sensitivity-t1max` (value + margin, T1_MAX ∈ {12,16,20} × 2 flag combos × 4 KPIs) | 24 | **CLEAN** |
| `tab:sensitivity-t1max` significance (asterisk vs recomputed CI-overlap, both on paper's own cells and on raw-reparsed cells) | 16 | **CLEAN** |
| `tab:sensitivity-shape` (value + margin, shape ∈ {0.5,1.0,2.0} × 2 flag combos × 4 KPIs) | 24 | **CLEAN** |
| `tab:sensitivity-shape` significance ("no cell differs significantly" claim) | 16 | **CLEAN** |
| `csv-cross-check` (every existing `*_queries_values.csv` row vs a fresh reparse of its own referenced trace file, all 19 raw_traces folders) | 323 | **CLEAN** |
| **Total** | **499** | **0 mismatches, 0 unresolved notes** |

## Overall Conclusion

No discrepancies were found anywhere in scope. Every point estimate and 95% CI margin printed in `Paper1_Draft_Sections.tex` for Tables `tab:ci`, `tab:probe-results`, `tab:sensitivity-t1max`, and `tab:sensitivity-shape` was independently reproduced by reparsing the raw `verifyta` trace text directly from disk, using logic copied from the toolchain rather than trusting any existing CSV. Every significance verdict the paper states or implies (the `tab:ci` prose paragraph, the `tab:probe-results` asterisks, and both sensitivity tables' asterisks/no-asterisk claims) was independently reproduced by a from-scratch, non-overlapping-95%-CI significance test. The existing `*_queries_values.csv` files across all 19 raw-trace folders (11 main scenarios, 4 false-positive probes, 4 sweep folders) also all matched a fresh reparse of their own referenced trace files, meaning neither of the two historical parser bugs (discarded CI margins; deterministic-value-exported-as-0) is present in any currently committed CSV.

This is a clean, positive audit result: it does not find new problems, it corroborates that the two previously-found-and-fixed bugs were fixed everywhere they mattered, and that the paper's four results tables are traceable, value-for-value, back to the raw SMC output.

### Caveats / things this audit does **not** cover
- `tab:prmm-l4` and `tab:weight-sensitivity` were **not** included: their numbers (average improvement-strength score, `S_4` percentages, weighted final scores) are *derived quantities* computed from the KPI values by the V6 tool's PRMM scoring formulas, not verifyta trace values themselves. Auditing those would require re-implementing the scoring formulas (`score_kpi_effectiveness_cell` / `score_prmm_maturity_cell` in `uppaal_query_runner_gui_v3_PRMM_dual_scoring.py`) end-to-end from the raw KPI values, which is a materially different and larger task than reparsing raw traces; the paper's own text (Section "PRMM Level 4 ...", Caveat paragraph) already flags this table as needing independent confirmation for the same reason. Recommended as a follow-up audit.
- The `Formal significance criterion` re-test for `tab:ci` recomputes overlap from the paper's own *printed* CIs (which this audit already confirmed exactly match the raw traces), rather than re-deriving it a second time independently from the raw traces for that specific table — the `tab:sensitivity-*` significance checks do both (paper cells and raw-reparsed cells) and both agreed in every case, which is corroborating evidence that re-deriving `tab:ci` significance from raw traces directly would give the same answer.
- This audit trusts `verifyta`'s own reported CI margins (it does not re-derive a CI from a raw distribution of per-run values, since individual per-run raw values are not present in the trace text — only the aggregate `E(...) = value ± margin (95% CI)`/`Pr(...) in [low,high] (95% CI)` line verifyta itself prints). Auditing verifyta's own SMC statistics engine is out of scope.
