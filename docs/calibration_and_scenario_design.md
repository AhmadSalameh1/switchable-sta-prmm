# Calibration and Scenario Design Notes

These notes support the Methodology / Experimental Design sections of the paper. Full context lives in the paper itself; this file exists so the `docs/` folder in this repository isn't empty.

## Calibration

The model's structural and stochastic parameters are grounded in a real ERPsim session rather than chosen arbitrarily. Most directly, N_CUST = 71 is not an illustrative round number: it is the exact customer count of the `normal_2` run of the publicly available ERPsim fraud-detection dataset (Tritscher et al., 2022, arXiv:2206.04460), in which the participating group "served the market of the 71 large resellers within ERPsim" over one simulated fiscal year.

The remaining structural constants and the model's throughput were tuned by running the model for a duration matched to the real session's play time and adjusting timing and batch parameters until the simulated output volume approximated the real session's recorded output over the same duration — a trial-and-error calibration against observed throughput, not a formal statistical fit. This calibration is deliberately qualitative: transport-duration parameters (T1_MIN=8, T1_MAX=16) were not fitted to individually observed order-to-delivery durations, since the available transaction records do not expose purchase-order-to-goods-receipt document linkage at that granularity.

Separately, the choice of gamma-shaped, rather than uniform, stochastic timing throughout the model is qualitatively supported by the real session's own inter-transaction timing: gaps between consecutive AA-F12 (finished product) goods-issue transactions in the `normal_2` log are strongly right-skewed (median 1s, mean 16.3s, over a ~390-minute session), consistent with a gamma-family distribution rather than a uniform or normal spread. The correspondence is at the level of distribution shape and aggregate throughput, not exact parameter values; this scope is stated explicitly as the calibration's transferability boundary.

## Scenario design

Eight independently togglable Boolean flags (four disruptions, four practices) yield 2^8 = 256 possible configurations. The eleven scenarios used here are a deliberately small, purposively selected subset, not a full or fractional factorial design in the classical DOE sense, chosen to test three distinct properties rather than to sample the configuration space broadly:

1. **Isolation** (5 scenarios: Baseline, R, D, Q, F) — establishes the reference behaviour and each disruption's individual footprint in isolation, with no confounding from other active flags.
2. **Matched mitigation** (4 scenarios: R+E, D+E,S, F+B, R,Q+E) — tests whether each practice measurably counters the disruption it targets. Three are clean one-to-one pairings; the fourth, R,Q+E, deliberately tests a matched practice (E) under compounded stress (an added, unrelated quality shock) rather than in isolation.
3. **Worst-case stacking** (2 scenarios: R,D,Q,F and R,D,Q,F+E,A,S,B) — tests the fully stacked disruption case with no mitigation, and with the full four-practice portfolio active.

Known asymmetry: quality shock (Q) has no dedicated matched practice among the four (E, A, S, B target R, R, D, F respectively), so Q's mitigation is only ever tested in combination (R,Q+E), never in a clean matched pair — a property of the disruption/practice taxonomy chosen for the case study, not an oversight in scenario selection.

### Proposed false-positive activation probes (not yet run)

| Probe scenario | Flag enabled | Tests |
|---|---|---|
| E without R | `ENABLE_P_EMERGENCY_RAW_REPLENISHMENT` | Spurious activation with no raw shortage? |
| A without R | `ENABLE_P_ADAPTIVE_RAW_SAFETY_STOCK` | Same, for adaptive safety stock |
| S without D | `ENABLE_P_DEMAND_SURGE_CAPACITY` | Spurious activation with no demand shock? |
| B without F | `ENABLE_P_BACKUP_FINISHED_GOODS_TRUCK` | Spurious activation with no transport delay? |
