#!/usr/bin/env python3
"""
Parametric bootstrap propagating KPI level SMC sampling uncertainty through
the Level 4 (S4) strength bucket assignment into S_final and the resulting
maturity category, for the four disruption practice pairs of Table
tab:prmm-l4. Addresses the gap that S4_final's reported percentages
(68.6/70.0/0.0/70.0) and the downstream category labels of Table
tab:weight-sensitivity are point estimates with no propagated uncertainty,
even though every input KPI is itself an SMC estimate with a reported margin.

METHOD
------
For each of the 7 scored KPIs in a case, extract (point, ci_lo, ci_hi) for
both the baseline and practice scenario from the raw verifyta traces
(identical extraction as reconcile_prmm_l4.py). Approximate each side's
standard error as SE = (ci_hi - ci_lo) / (2*1.96), the same Gaussian
approximation the paper itself uses throughout for its significance test
(Section "Statistical model checking and significance criterion"),
including for Pr(.) queries (Q1), where this is already disclosed as an
approximation.

Draw B=20,000 bootstrap replicates. In each replicate, resample
baseline_boot ~ Normal(point, SE) and practice_boot ~ Normal(point, SE)
independently for every KPI, recompute the improvement percentage,
reclassify significance using the SAME difference CI test as the paper
(|diff| / sqrt(SE_b^2 + SE_p^2) > 1.96, direction aware), assign the
strength bucket, and aggregate into S4_final for that replicate using the
paper's own formula (0.5*coverage + 0.5*strength). Combine with the FIXED
(nonrandom) structural S1/S2/S3/S5 scores for that case (these are
deterministic pass/fail checks against the model's own tagging, not
subject to SMC sampling noise) and the baseline PRMM weights to get
S_final and its maturity category for that replicate.

Report: 95% percentile interval on S4_final and on S_final (baseline
weights), and the empirical probability of each maturity category across
the B replicates, for each case.
"""
from __future__ import annotations
import numpy as np
from reconcile_prmm_l4 import (
    extract_point_and_ci, CASES, KPI_CATALOGUE, KPI_SET, strength_score, TOLERANCE,
)

np.random.seed(20260928)
B = 20000

ALPHA = (0.05, 0.10, 0.25, 0.30, 0.30)  # baseline weights a1..a5

# Fixed structural scores (S1, S2, S3, S5) per case, per Section "Levels 1,2,3,5"
STRUCTURAL = {
    "R -> R+E": (100.0, 100.0, 100.0, 0.0),
    "D -> D+E,S": (100.0, 100.0, 100.0, 0.0),
    "F -> F+B": (100.0, 100.0, 100.0, 0.0),
    "Full portfolio": (100.0, 75.0, 100.0, 0.0),
}

CATEGORY_BANDS = [
    (0, 60, "Early Awareness"),
    (60, 70, "Conceptual Readiness"),
    (70, 80, "Practice-Linked Resilience"),
    (80, 90, "Continuous Optimization"),
    (90, 101, "Benchmark-Aligned Excellence"),
]


def categorize(score: float) -> str:
    for lo, hi, name in CATEGORY_BANDS:
        if lo <= score < hi:
            return name
    return CATEGORY_BANDS[-1][2]


def kpi_inputs(case_name: str):
    base_scenario, prac_scenario = CASES[case_name]
    out = []
    for kpi_id in KPI_SET:
        label, direction, _ = KPI_CATALOGUE[kpi_id]
        b_pt, b_lo, b_hi = extract_point_and_ci(base_scenario, kpi_id)
        p_pt, p_lo, p_hi = extract_point_and_ci(prac_scenario, kpi_id)
        se_b = max((b_hi - b_lo) / (2 * 1.96), 1e-12)
        se_p = max((p_hi - p_lo) / (2 * 1.96), 1e-12)
        out.append((direction, b_pt, se_b, p_pt, se_p))
    return out


def bootstrap_case(case_name: str):
    inputs = kpi_inputs(case_name)
    s1, s2, s3, s5 = STRUCTURAL[case_name]
    n = len(inputs)
    s4_finals = np.empty(B)
    s_finals = np.empty(B)
    cats = []

    # Pregenerate all draws vectorized per KPI for speed
    boot_b = np.empty((n, B))
    boot_p = np.empty((n, B))
    for i, (direction, b_pt, se_b, p_pt, se_p) in enumerate(inputs):
        boot_b[i] = np.random.normal(b_pt, se_b, B)
        boot_p[i] = np.random.normal(p_pt, se_p, B)

    for j in range(B):
        strengths = []
        passes = 0
        for i, (direction, b_pt, se_b, p_pt, se_p) in enumerate(inputs):
            bb = boot_b[i, j]
            bp = boot_p[i, j]
            se_diff = (se_b ** 2 + se_p ** 2) ** 0.5
            diff = (bb - bp) if direction == "lower" else (bp - bb)  # improving direction positive
            z = diff / se_diff if se_diff > 0 else 0.0
            if direction == "lower":
                pct = (bb - bp) / abs(bb) * 100.0 if bb != 0 else 0.0
            else:
                pct = (bp - bb) / abs(bb) * 100.0 if bb != 0 else 0.0
            sig_improve = z > 1.96
            if sig_improve:
                s = strength_score(pct)
                p_ok = pct > TOLERANCE
            else:
                s = 0
                p_ok = False
            strengths.append(s)
            passes += 1 if p_ok else 0
        avg_strength = sum(strengths) / n
        s4_strength_pct = avg_strength / 5.0 * 100.0
        coverage_pct = passes / n * 100.0
        s4_final = 0.5 * coverage_pct + 0.5 * s4_strength_pct
        s4_finals[j] = s4_final
        s_final = ALPHA[0] * s1 + ALPHA[1] * s2 + ALPHA[2] * s3 + ALPHA[3] * s4_final + ALPHA[4] * s5
        s_finals[j] = s_final
        cats.append(categorize(s_final))

    return s4_finals, s_finals, cats


if __name__ == "__main__":
    for case in CASES:
        s4f, sf, cats = bootstrap_case(case)
        lo4, hi4 = np.percentile(s4f, [2.5, 97.5])
        lo, hi = np.percentile(sf, [2.5, 97.5])
        from collections import Counter
        cat_counts = Counter(cats)
        total = len(cats)
        print(f"\n=== {case} ===")
        print(f"S4_final: point={s4f.mean():.1f}%  95% bootstrap CI=[{lo4:.1f}, {hi4:.1f}]")
        print(f"S_final (baseline weights): mean={sf.mean():.1f}%  95% bootstrap CI=[{lo:.1f}, {hi:.1f}]")
        for cat_name in ["Early Awareness", "Conceptual Readiness", "Practice-Linked Resilience",
                         "Continuous Optimization", "Benchmark-Aligned Excellence"]:
            pct = 100.0 * cat_counts.get(cat_name, 0) / total
            if pct > 0:
                print(f"    P(category = {cat_name}) = {pct:.1f}%")
