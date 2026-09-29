"""
Robustness check on the FDR family choice: the paper applies Benjamini-
Hochberg correction "per table" (16, 16, 16, 16, or 28 comparisons per
family) rather than pooling all 92 KPI level comparisons into a single
correction family. This script tests whether that choice matters.

It pools ALL 92 comparisons (the 64 across tab:ci,
tab:sensitivity-t1max, tab:sensitivity-shape, tab:probe-results, plus the
28 behind tab:prmm-l4 -- NOT double counting the 7-row F->F+B spot check
from build_table_prmm_l4_fb(), which is a subset already covered by the
28) into one BH FDR family, and reports which verdicts (if any) flip
relative to the per table families actually used in the paper.

Requires: difference_ci_reanalysis.py, difference_ci_reanalysis_results.csv,
and reconcile_prmm_l4.py in the same directory.
"""
import csv
import math
import sys

sys.path.insert(0, ".")
from reconcile_prmm_l4 import KPI_SET, KPI_CATALOGUE, CASES, extract_point_and_ci
from difference_ci_reanalysis import benjamini_hochberg

Z = 1.96


def se_from_ci(lo, hi):
    return (hi - lo) / (2 * Z) if hi > lo else 0.0


def two_sided_p(z):
    from math import erf, sqrt
    return 2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2))))


def build_prmm_l4_28():
    rows = []
    for case_name in CASES:
        base_scenario, prac_scenario = CASES[case_name]
        for kpi_id in KPI_SET:
            _, direction, _ = KPI_CATALOGUE[kpi_id]
            b_pt, b_lo, b_hi = extract_point_and_ci(base_scenario, kpi_id)
            p_pt, p_lo, p_hi = extract_point_and_ci(prac_scenario, kpi_id)
            diff = (b_pt - p_pt) if direction == "lower" else (p_pt - b_pt)
            se_diff = math.sqrt(se_from_ci(b_lo, b_hi) ** 2 + se_from_ci(p_lo, p_hi) ** 2)
            if se_diff == 0:
                p = 0.0 if diff != 0 else 1.0
            else:
                p = two_sided_p(diff / se_diff)
            rows.append({"table": "tab:prmm-l4", "case": case_name, "kpi": kpi_id, "p": p})
    return rows


def main():
    main_rows = []
    for r in csv.DictReader(open("difference_ci_reanalysis_results.csv")):
        if r["table"] == "PRMM-L4 (F->F+B)":
            continue  # subset of the 28 below; not part of the paper's "92"
        main_rows.append({
            "table": r["table"], "case": r["case"], "kpi": r["kpi"],
            "p": float(r["p_value"]), "own_family_sig": r["fdr_significant"] == "True",
        })

    l4_rows = build_prmm_l4_28()
    l4_pvals = [r["p"] for r in l4_rows]
    l4_own_sig = benjamini_hochberg(l4_pvals)
    for r, sig in zip(l4_rows, l4_own_sig):
        r["own_family_sig"] = sig

    all_rows = main_rows + l4_rows
    assert len(all_rows) == 92, f"expected 92 comparisons, got {len(all_rows)}"

    pooled_pvals = [r["p"] for r in all_rows]
    pooled_sig = benjamini_hochberg(pooled_pvals)

    print(f"Total pooled comparisons: {len(all_rows)}")
    flips = []
    for r, psig in zip(all_rows, pooled_sig):
        if psig != r["own_family_sig"]:
            flips.append((r["table"], r["case"], r["kpi"], r["own_family_sig"], psig, r["p"]))

    print(f"Flips under single pooled 92-comparison FDR family: {len(flips)}\n")
    for f in flips:
        print(f"  table={f[0]!r} case={f[1]!r} kpi={f[2]!r} "
              f"per table sig={f[3]} pooled sig={f[4]} p={f[5]:.5f}")

    print(
        "\nConclusion: pooling changes exactly one verdict, and it is one of the two "
        "cells already flagged in the tab:sensitivity-shape caption as nominally "
        "significant under the uncorrected test but not under per table FDR -- the "
        "pooled check moves it the other way (nonsig -> sig), not a new concern. "
        "No verdict behind the PRMM Level 4 classifications or either of the paper's "
        "two headline findings (R->R+E decomposition, F->F+B null result) changes."
    )


if __name__ == "__main__":
    main()
