#!/usr/bin/env python3
"""
Extends the difference CI + FDR reanalysis (already applied to tab:ci,
tab:sensitivity-t1max, tab:sensitivity-shape, tab:probe-results, and spot
checked for F->F+B) to the REMAINING three PRMM Level 4 cases (R->R+E,
D->D+E,S, Full portfolio), which reconcile_prmm_l4.py still classifies with
pure CI overlap. This checks whether Section sec:ci's claim ("this same
criterion [difference CI, FDR corrected] is used throughout Section results")
is actually true for tab:prmm-l4 / tab:weight-sensitivity, or whether those
two tables are a silent exception.
"""
import sys, math
sys.path.insert(0, ".")
from reconcile_prmm_l4 import (
    KPI_SET, KPI_CATALOGUE, CASES, extract_point_and_ci, _ci_overlap,
    strength_score, TOLERANCE,
)

Z = 1.96

def se_from_ci(lo, hi):
    return (hi - lo) / (2 * Z) if hi > lo else 0.0

rows = []
for case_name in CASES:
    base_scenario, prac_scenario = CASES[case_name]
    for kpi_id in KPI_SET:
        label, direction, _ = KPI_CATALOGUE[kpi_id]
        b_pt, b_lo, b_hi = extract_point_and_ci(base_scenario, kpi_id)
        p_pt, p_lo, p_hi = extract_point_and_ci(prac_scenario, kpi_id)

        if direction == "lower":
            pct = (b_pt - p_pt) / abs(b_pt) * 100.0 if b_pt != 0 else 0.0
            diff = b_pt - p_pt  # positive = improvement
        else:
            pct = (p_pt - b_pt) / abs(b_pt) * 100.0 if b_pt != 0 else 0.0
            diff = p_pt - b_pt

        overlap = _ci_overlap(b_lo, b_hi, p_lo, p_hi)

        se_b = se_from_ci(b_lo, b_hi)
        se_p = se_from_ci(p_lo, p_hi)
        se_diff = math.sqrt(se_b**2 + se_p**2)
        if se_diff == 0:
            # degenerate case: both sides zero. Significant iff diff != 0.
            diffci_significant = diff != 0
            z = float("inf") if diff != 0 else 0.0
        else:
            z = diff / se_diff
            diffci_significant = abs(z) >= Z

        rows.append(dict(
            case=case_name, kpi=kpi_id, label=label, direction=direction,
            baseline=b_pt, practice=p_pt, pct=pct, diff=diff, se_diff=se_diff, z=z,
            overlap=overlap, ci_overlap_significant=(not overlap),
            diffci_significant=diffci_significant,
        ))

# BH FDR across this table's full family (28 comparisons), matching the
# convention used for every other table in the paper.
pvals = []
for r in rows:
    if r["se_diff"] == 0:
        p = 0.0 if r["diff"] != 0 else 1.0
    else:
        # two sided normal p value
        from math import erf, sqrt
        p = 2 * (1 - 0.5 * (1 + erf(abs(r["z"]) / sqrt(2))))
    r["p"] = p
    pvals.append(p)

m = len(pvals)
order = sorted(range(m), key=lambda i: pvals[i])
fdr_flag = [False] * m
prev = 0.0
for rank, idx in enumerate(order, start=1):
    thresh = rank / m * 0.05
    if pvals[idx] <= thresh:
        prev = max(prev, rank)
for rank, idx in enumerate(order, start=1):
    if rank <= prev:
        fdr_flag[idx] = True
for i, r in enumerate(rows):
    r["fdr_significant"] = fdr_flag[i]

print(f"{'case':<16}{'kpi':<5}{'label':<38}{'pct':>8}{'overlapSig':>11}{'diffSig':>9}{'FDRsig':>7}{'FLIP':>6}")
flips = 0
for r in rows:
    flip = r["ci_overlap_significant"] != r["fdr_significant"]
    if flip:
        flips += 1
    print(f"{r['case']:<16}{r['kpi']:<5}{r['label'][:36]:<38}{r['pct']:8.2f}{str(r['ci_overlap_significant']):>11}{str(r['diffci_significant']):>9}{str(r['fdr_significant']):>7}{'<--' if flip else '':>6}")

print(f"\nTotal comparisons: {m}, flips (CI overlap sig != FDR diffCI sig): {flips}")

# Now recompute coverage/strength/S4 per case under the FDR diffCI criterion
print("\n=== Recomputed S4 under difference CI + FDR (vs current CI overlap) ===")
by_case = {}
for r in rows:
    by_case.setdefault(r["case"], []).append(r)

for case_name, krows in by_case.items():
    strengths = []
    passes = []
    for r in krows:
        if r["fdr_significant"] and r["diff"] > 0:  # improvement, direction aware via diff sign convention above
            s = strength_score(r["pct"])
            p = r["pct"] > TOLERANCE
        else:
            s = 0
            p = False
        strengths.append(s)
        passes.append(p)
    avg_strength = sum(strengths) / len(strengths)
    s4_strength = avg_strength / 5 * 100
    coverage = sum(passes) / len(passes) * 100
    s4_final = 0.5 * coverage + 0.5 * s4_strength
    print(f"{case_name}: coverage={coverage:.2f}% strength={s4_strength:.2f}% S4_final={s4_final:.2f}%")
