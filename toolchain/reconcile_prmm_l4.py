#!/usr/bin/env python3
"""
CI CONSISTENT recomputation of PRMM Level 4 (S4) scores for the four cases in
the paper's Table tab:prmm-l4, plus the derived Table tab:weight-sensitivity.

WHY THIS SCRIPT EXISTS (v2 / CI overlap revision)
--------------------------------------------------
The prior reconciliation pass (see docs/audit_prmm_l4_reconciliation.md, and
the point estimate sign logic preserved below as `compute_case_point_estimate`
for comparison) classified each KPI as "improved" / "worsened" purely from the
SIGN of the raw point estimate percentage difference between baseline and
practice. A manual spot check caught that this is methodologically
inconsistent with the rest of the paper: every OTHER table (tab:ci,
tab:sensitivity-t1max, tab:sensitivity-shape, tab:probe-results) uses the
paper's own stated significance test -- 95% CI overlap -- to decide whether a
difference between two UPPAAL statistical model checking runs is real or
noise. PRMM Level 4 was the only table using the weaker, noise sensitive
point estimate sign test.

Concretely: for R->R+E, KPI Q1 (service_ratio_pct), baseline Pr 95% CI =
[0.728607, 0.823049], practice (R+E) Pr 95% CI = [0.705295, 0.800645]. These
overlap substantially. The point estimates (0.778481 vs 0.755287, a -2.98%
move) make Q1 look like a "worsening" under the old rule, but the CIs show
this is statistical noise, not a real effect.

THIS SCRIPT (default / primary mode): reclassifies every one of the 28
KPI x case cells (Q1-Q7 x 4 cases) using CI overlap as the significance test,
consistent with the paper's own stated methodology, and recomputes
avg_strength / S4_strength_pct / coverage_pct / S4_final accordingly. The
previous point estimate sign method is retained (function
`compute_case_point_estimate` + `PRIOR_RECONCILIATION_RAW`) purely as a
documented comparison baseline; it is NOT the default output.

KPI SET AND CASE DEFINITIONS (unchanged from the prior reconciliation;
see docs/audit_prmm_l4_reconciliation.md Sec 1 for the full justification)
---------------------------------------------------------------------------
KPI set = {Q1, Q2, Q3, Q4, Q5, Q6, Q7} (the "broad union" of every [KPI]
query carrying >=1 [DK:...] tag), applied identically to all four cases:

    R -> R+E          baseline = R            practice = R + E
    D -> D+E,S        baseline = D            practice = D + E,S
    F -> F+B          baseline = F            practice = F + B
    Full portfolio    baseline = R,D,Q,F      practice = R,D,Q,F + E,A,S,B

RAW DATA SOURCE (point estimates AND 95% CIs)
-----------------------------------------------
Reextracted directly from the raw verifyta trace .txt files in
results/raw_traces/<scenario>/00N_..._1.txt for this script (queries 001-007
== Q1-Q7 in model file order), NOT copied from any prior audit or from the
transcribed values CSV. Two report formats appear:

  * Probability queries (Q1 only): "(<sat>/<total> runs) Pr(<> ...) in
    [<lo>,<hi>] (95% CI)". Point estimate = sat/total (verified to
    reproduce the CSV's transcribed "value" column exactly, e.g.
    246/316 = 0.778481 for R's Q1 -- the CI midpoint does NOT reproduce this
    and is not used).
  * Estimate queries (Q2-Q7): "(N runs) E(max|min) = <value> +/- <margin>
    (95% CI)" -> CI = [value-margin, value+margin]. A small number of cells
    are deterministic / degenerate and print "E(max) = ~= 0" with no +/-
    term at all (e.g. Q7 / max_stockout_duration under R+E) -- these are
    treated as a degenerate interval [0, 0] at point estimate 0.

FORMULAS
--------
improvement_pct (direction=lower)  = (baseline_pt - practice_pt) / |baseline_pt| * 100
improvement_pct (direction=higher) = (practice_pt - baseline_pt) / |baseline_pt| * 100

strength_score(pct):  pct<=0 -> 0, 0<pct<5 -> 1, 5<=pct<10 -> 2,
                       10<=pct<15 -> 3, 15<=pct<20 -> 4, pct>=20 -> 5

CI OVERLAP SIGNIFICANCE TEST (replaces point estimate sign, for BOTH strength
and coverage)
------------------------------------------------------------------------------
Let [b_lo, b_hi] = baseline's reported 95% CI, [p_lo, p_hi] = practice's.
Overlap := b_lo <= p_hi AND p_lo <= b_hi.

  1. Overlap == True
        -> "no significant change" (statistical noise either way).
        strength = 0. Does NOT count as a "significant worsening"
        (see judgment call discussion below and in the companion report).
        Coverage: does not pass (see below -- this is the judgment call).

  2. Overlap == False AND practice's point estimate is on the KPI's
     improving side (practice CI entirely beyond baseline CI in the
     improving direction)
        -> "significant improvement". strength = strength_score(pct).
        Coverage: passes iff pct > TOLERANCE (0.5), same threshold as
        before -- this additional check is kept so that a CI significant
        but economically negligible improvement still cannot pass
        coverage, exactly mirroring the old rule's intent.

  3. Overlap == False AND practice's point estimate is on the worsening
     side
        -> "significant worsening" (a genuine, statistically supported
        regression, unlike case 1). strength = 0. Coverage: fails.

JUDGMENT CALL: how "no significant change" (case 1) should be scored
----------------------------------------------------------------------
The paper's methods text defines coverage as "the percentage of L3 KPIs with
improvement > tolerance". Under the old point estimate method this was a
single unambiguous test. Once "improvement" itself is redefined as requiring
statistical significance (to fix the Q1 problem), a KPI whose CIs overlap has
NO confirmed improvement -- by construction its point estimate direction is
noise -- so it cannot honestly be counted as "improvement > tolerance".
Three interpretations were considered (see the full discussion in
docs/audit_prmm_l4_ci_reconciliation.md Sec 3):

  (a) Treat "no significant change" as equivalent to "worsening" (strength 0,
      *and* explicitly counted as a failure/regression). Rejected: this
      overstates the finding -- Q1 in R->R+E did not get worse, it is simply
      not proven to have improved. Calling it a "worsening" would just move
      the same methodological error (treating noise as a real signal) to the
      opposite sign.
  (b) Treat "no significant change" as a "soft pass" for coverage (give it
      partial or full credit) on the theory that a nonnegative point
      estimate is still evidence, however weak, of improvement. Rejected:
      this reintroduces exactly the point estimate sensitivity the fix is
      meant to remove, and is not what "improvement > tolerance" means once
      "improvement" requires significance.
  (c) [ADOPTED] Treat "no significant change" as strength = 0 AND as NOT
      counting toward coverage (i.e., coverage = % of KPIs with a
      *confirmed, significant* improvement exceeding tolerance), while
      explicitly and separately not classifying it as a "worsening" in any
      of the report's prose or per KPI labels. This is the option most
      consistent with the paper's own coverage definition (coverage requires
      a demonstrated "improvement > tolerance"; an overlapping CI cannot
      demonstrate that) and with the paper's own significance methodology
      used everywhere else (an overlapping CI is treated as "no evidence of
      a difference", never as "evidence of the opposite difference").

This is implemented below: `passes_coverage` is False for both
"no significant change" and "significant worsening" cells, but the
`classification` string distinguishes them, and every downstream report
must keep that distinction in its prose (a "coverage failure" here is not
synonymous with "this KPI got worse").
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
import glob
import json
import os
import re

TOLERANCE = 0.5  # percentage points, per task instructions (unchanged)

RAW_TRACES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "results", "raw_traces",
)

# ---------------------------------------------------------------------------
# KPI catalogue: query id -> (label, direction, trace file query number)
# ---------------------------------------------------------------------------
KPI_CATALOGUE: Dict[str, Tuple[str, str, str]] = {
    "Q1": ("service_ratio_pct (>=95%)", "higher", "001"),
    "Q2": ("avg_lead_time", "lower", "002"),
    "Q3": ("max_safe_stock_recovery_time", "lower", "003"),
    "Q4": ("max_latent_production_blocked_time", "lower", "004"),
    "Q5": ("max_production_blocked_time", "lower", "005"),
    "Q6": ("defect_rate_pct", "lower", "006"),
    "Q7": ("max_stockout_duration", "lower", "007"),
}
KPI_SET: List[str] = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7"]

# ---------------------------------------------------------------------------
# Case definitions: case name -> (baseline scenario dir suffix, practice
# scenario dir suffix), where each suffix is the part after
# "Supply Chain V11.4.1_queries_traces " in results/raw_traces/.
# ---------------------------------------------------------------------------
CASES: Dict[str, Tuple[str, str]] = {
    "R -> R+E": ("R", "R + E"),
    "D -> D+E,S": ("D", "D + E,S"),
    "F -> F+B": ("F", "F + B"),
    "Full portfolio": ("R,D,Q,F", "R,D,Q,F + E,A,S,B"),
}


# ---------------------------------------------------------------------------
# Raw trace extraction: point estimate + 95% CI for a given scenario/KPI.
# ---------------------------------------------------------------------------
def _scenario_dir(scenario: str) -> str:
    return os.path.join(RAW_TRACES_DIR, f"Supply Chain V11.4.1_queries_traces {scenario}")


def _find_query_file(scenario: str, qnum: str) -> str:
    matches = glob.glob(os.path.join(_scenario_dir(scenario), f"{qnum}_*.txt"))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected exactly 1 match for {scenario}/{qnum}_*.txt, got {matches}")
    return matches[0]


def extract_point_and_ci(scenario: str, kpi_id: str) -> Tuple[float, float, float]:
    """Returns (point_estimate, ci_lo, ci_hi) read directly from the raw
    verifyta trace file for this scenario/KPI."""
    _, _, qnum = KPI_CATALOGUE[kpi_id]
    path = _find_query_file(scenario, qnum)
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()

    if qnum == "001":  # probability query (Q1 only)
        m_ci = re.search(r"Pr\([^)]*\)\s*in\s*\[([\-0-9.eE]+)\s*,\s*([\-0-9.eE]+)\]", text)
        m_runs = re.search(r"\((\d+)\s*/\s*(\d+)\s*runs\)", text)
        if not (m_ci and m_runs):
            raise ValueError(f"could not parse probability query in {path}")
        lo, hi = float(m_ci.group(1)), float(m_ci.group(2))
        sat, total = int(m_runs.group(1)), int(m_runs.group(2))
        point = sat / total
        return point, lo, hi

    # estimate query (Q2-Q7): "E(max|min) = <val> +/- <margin> (95% CI)"
    m = re.search(r"E\((?:max|min)\)\s*=\s*([\-0-9.eE]+)\s*(?:\xb1|\+/-|±)\s*([\-0-9.eE]+)", text)
    if m:
        val = float(m.group(1))
        margin = float(m.group(2))
        return val, val - margin, val + margin

    # degenerate case: "E(max) = ~= 0" (no +/- term at all)
    m = re.search(r"E\((?:max|min)\)\s*=\s*[≈~]?\s*([\-0-9.eE]+)\s*$", text, re.MULTILINE)
    if m:
        val = float(m.group(1))
        return val, val, val

    raise ValueError(f"could not parse estimate query in {path}")


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------
@dataclass
class KpiResult:
    kpi_id: str
    label: str
    direction: str
    baseline_pt: float
    baseline_ci: Tuple[float, float]
    practice_pt: float
    practice_ci: Tuple[float, float]
    overlap: bool
    improvement_pct: float
    classification: str  # "significant improvement" | "significant worsening" | "no significant change"
    strength: int
    passes_coverage: bool


@dataclass
class CaseResult:
    case: str
    kpis: List[KpiResult] = field(default_factory=list)
    avg_strength: float = 0.0
    s4_strength_pct: float = 0.0
    coverage_pct: float = 0.0
    s4_final: float = 0.0


def strength_score(pct: float) -> int:
    if pct <= 0:
        return 0
    elif pct < 5:
        return 1
    elif pct < 10:
        return 2
    elif pct < 15:
        return 3
    elif pct < 20:
        return 4
    else:
        return 5


def _ci_overlap(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> bool:
    return a_lo <= b_hi and b_lo <= a_hi


def compute_case(case_name: str) -> CaseResult:
    """PRIMARY / DEFAULT method: CI overlap consistent classification."""
    result = CaseResult(case=case_name)
    base_scenario, prac_scenario = CASES[case_name]
    for kpi_id in KPI_SET:
        label, direction, _ = KPI_CATALOGUE[kpi_id]
        b_pt, b_lo, b_hi = extract_point_and_ci(base_scenario, kpi_id)
        p_pt, p_lo, p_hi = extract_point_and_ci(prac_scenario, kpi_id)

        if direction == "lower":
            pct = (b_pt - p_pt) / abs(b_pt) * 100.0
        else:
            pct = (p_pt - b_pt) / abs(b_pt) * 100.0

        ov = _ci_overlap(b_lo, b_hi, p_lo, p_hi)

        if ov:
            classification = "no significant change (CI overlap)"
            strength = 0
            passes = False
        else:
            if direction == "lower":
                sig_improve = p_hi < b_lo
            else:
                sig_improve = p_lo > b_hi
            if sig_improve:
                classification = "significant improvement"
                strength = strength_score(pct)
                passes = pct > TOLERANCE
            else:
                classification = "significant worsening"
                strength = 0
                passes = False

        result.kpis.append(
            KpiResult(
                kpi_id, label, direction,
                b_pt, (b_lo, b_hi), p_pt, (p_lo, p_hi),
                ov, pct, classification, strength, passes,
            )
        )

    n = len(result.kpis)
    result.avg_strength = sum(k.strength for k in result.kpis) / n
    result.s4_strength_pct = result.avg_strength / 5.0 * 100.0
    result.coverage_pct = sum(1 for k in result.kpis if k.passes_coverage) / n * 100.0
    result.s4_final = 0.5 * result.coverage_pct + 0.5 * result.s4_strength_pct
    return result


# ---------------------------------------------------------------------------
# COMPARISON MODE (not the default): the prior reconciliation's
# point estimate sign method, preserved verbatim for side by side comparison.
# ---------------------------------------------------------------------------
PRIOR_RECONCILIATION_RAW: Dict[str, Dict[str, Tuple[float, float]]] = {
    "R -> R+E": {
        "Q1": (0.778481, 0.755287), "Q2": (10.68, 9.54), "Q3": (214.62, 8.66),
        "Q4": (611.02, 17.52), "Q5": (617.6, 16.96), "Q6": (1.72, 1.62), "Q7": (55.92, 0.0),
    },
    "D -> D+E,S": {
        "Q1": (0.84556, 0.776025), "Q2": (10.24, 8.56), "Q3": (190.22, 12.22),
        "Q4": (614.76, 52.32), "Q5": (621.84, 37.52), "Q6": (1.66, 1.86), "Q7": (46.68, 0.76),
    },
    "F -> F+B": {
        "Q1": (0.759878, 0.765432), "Q2": (10.06, 10.02), "Q3": (142.54, 142.58),
        "Q4": (589.24, 604.7), "Q5": (594.18, 606.06), "Q6": (1.78, 1.72), "Q7": (42.24, 39.6),
    },
    "Full portfolio": {
        "Q1": (0.747774, 0.765432), "Q2": (11.06, 8.86), "Q3": (216.58, 39.88),
        "Q4": (599.86, 23.64), "Q5": (606.12, 38.82), "Q6": (1.84, 1.6), "Q7": (71.54, 4.52),
    },
}


def compute_case_point_estimate(case_name: str) -> CaseResult:
    """Comparison only reproduction of the PRIOR (point estimate sign)
    reconciliation method. Not used for the primary output."""
    result = CaseResult(case=case_name)
    values = PRIOR_RECONCILIATION_RAW[case_name]
    for kpi_id in KPI_SET:
        label, direction, _ = KPI_CATALOGUE[kpi_id]
        baseline, practice = values[kpi_id]
        if direction == "lower":
            pct = (baseline - practice) / abs(baseline) * 100.0
        else:
            pct = (practice - baseline) / abs(baseline) * 100.0
        strength = strength_score(pct)
        passes = pct > TOLERANCE
        classification = "improved" if pct > 0 else "worsened"
        result.kpis.append(
            KpiResult(kpi_id, label, direction, baseline, (float("nan"), float("nan")),
                      practice, (float("nan"), float("nan")), False, pct, classification, strength, passes)
        )
    n = len(result.kpis)
    result.avg_strength = sum(k.strength for k in result.kpis) / n
    result.s4_strength_pct = result.avg_strength / 5.0 * 100.0
    result.coverage_pct = sum(1 for k in result.kpis if k.passes_coverage) / n * 100.0
    result.s4_final = 0.5 * result.coverage_pct + 0.5 * result.s4_strength_pct
    return result


# ---------------------------------------------------------------------------
# Reference values for comparison
# ---------------------------------------------------------------------------
PAPER_ORIGINAL_S4_FINAL = {
    "R -> R+E": 85.7, "D -> D+E,S": 82.0, "F -> F+B": 56.7, "Full portfolio": 88.6,
}
PRIOR_RECONCILIATION_S4_FINAL = {
    "R -> R+E": 78.6, "D -> D+E,S": 70.0, "F -> F+B": 28.6, "Full portfolio": 90.0,
}


def print_case_table(result: CaseResult) -> None:
    print(f"\n=== Case: {result.case} (CI overlap method) ===")
    header = (f"{'KPI':4} {'Label':36} {'Dir':7} {'Base pt':>10} {'Base CI':>22} "
              f"{'Prac pt':>10} {'Prac CI':>22} {'Ovlp':5} {'Impr%':>8} {'Class':28} {'Str':4} {'Pass':5}")
    print(header)
    print("-" * len(header))
    for k in result.kpis:
        base_ci = f"[{k.baseline_ci[0]:.4f},{k.baseline_ci[1]:.4f}]"
        prac_ci = f"[{k.practice_ci[0]:.4f},{k.practice_ci[1]:.4f}]"
        print(
            f"{k.kpi_id:4} {k.label:36} {k.direction:7} {k.baseline_pt:10.4f} {base_ci:>22} "
            f"{k.practice_pt:10.4f} {prac_ci:>22} {str(k.overlap):5} {k.improvement_pct:8.2f} "
            f"{k.classification:28} {k.strength:4d} {str(k.passes_coverage):5}"
        )
    print("-" * len(header))
    print(f"avg_strength (0-5)   : {result.avg_strength:.4f}")
    print(f"S4_strength_pct      : {result.s4_strength_pct:.2f}%")
    print(f"coverage_pct         : {result.coverage_pct:.2f}%")
    print(f"S4_final             : {result.s4_final:.2f}%")


def main() -> Dict[str, CaseResult]:
    results: Dict[str, CaseResult] = {}
    for case_name in CASES:
        result = compute_case(case_name)
        results[case_name] = result
        print_case_table(result)
        prior_pe = compute_case_point_estimate(case_name)
        print(f"\nPaper original S4_final               : {PAPER_ORIGINAL_S4_FINAL[case_name]:.1f}%")
        print(f"Prior (point estimate) reconciliation  : {PRIOR_RECONCILIATION_S4_FINAL[case_name]:.1f}%  "
              f"(rederived here: {prior_pe.s4_final:.2f}%)")
        print(f"NEW (CI overlap consistent) S4_final   : {result.s4_final:.2f}%")

    print("\n\n================ SUMMARY: CORRECTED tab:prmm-l4 (CI overlap method) ================")
    print(f"{'Case':16} {'AvgStrength':11} {'S4_strength%':13} {'Coverage%':10} {'S4_final%':10} "
          f"{'Paper orig%':11} {'Prior recon%':12}")
    for case_name, result in results.items():
        print(
            f"{case_name:16} {result.avg_strength:11.2f} {result.s4_strength_pct:13.2f} "
            f"{result.coverage_pct:10.2f} {result.s4_final:10.2f} "
            f"{PAPER_ORIGINAL_S4_FINAL[case_name]:11.1f} {PRIOR_RECONCILIATION_S4_FINAL[case_name]:12.1f}"
        )
    return results


# ---------------------------------------------------------------------------
# tab:weight-sensitivity, recomputed against the CI overlap consistent S4.
# ---------------------------------------------------------------------------
WEIGHT_SCHEMES: Dict[str, Tuple[float, float, float, float, float]] = {
    "Baseline": (0.05, 0.10, 0.25, 0.30, 0.30),
    "Equal": (0.20, 0.20, 0.20, 0.20, 0.20),
    "Front-loaded": (0.30, 0.25, 0.20, 0.15, 0.10),
    "Back-loaded": (0.05, 0.05, 0.15, 0.35, 0.40),
    "L3-emphasis": (0.10, 0.15, 0.35, 0.20, 0.20),
}

S1_S2_S3_S5 = {
    "R -> R+E": (100.0, 100.0, 100.0, 0.0),
    "D -> D+E,S": (100.0, 100.0, 100.0, 0.0),
    "F -> F+B": (100.0, 100.0, 100.0, 0.0),
    "Full portfolio": (100.0, 75.0, 100.0, 0.0),
}


def band(score: float) -> str:
    if score >= 90:
        return "Excellence"
    elif score >= 80:
        return "CO"
    elif score >= 70:
        return "PL"
    elif score >= 60:
        return "CR"
    else:
        return "EA"


def compute_weight_sensitivity(results: Dict[str, CaseResult]) -> None:
    print("\n\n================ SUMMARY: CORRECTED tab:weight-sensitivity (CI overlap S4) ================")
    header = f"{'Scheme':14} " + " ".join(f"{c:20}" for c in CASES)
    print(header)
    for scheme_name, (a1, a2, a3, a4, a5) in WEIGHT_SCHEMES.items():
        row_cells = []
        for case_name in CASES:
            s1, s2, s3, s5 = S1_S2_S3_S5[case_name]
            s4 = results[case_name].s4_final
            score = a1 * s1 + a2 * s2 + a3 * s3 + a4 * s4 + a5 * s5
            row_cells.append(f"{score:6.2f}% {band(score):>10}")
        print(f"{scheme_name:14} " + " ".join(f"{c:20}" for c in row_cells))


if __name__ == "__main__":
    results = main()
    compute_weight_sensitivity(results)
