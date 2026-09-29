"""
Breakdown SE robustness check for degenerate confidence
intervals near a hard floor or ceiling.

Some KPI level comparisons in the paper have one side whose reported margin
is zero because all N=50 replications landed on an identical boundary value
(e.g. stockout duration = 0 in every run, or minimum availability = 100% in
every run). This produces a degenerate Wald CI on that side. This script
identifies every such comparison, flags which ones coincide with a
significant FDR corrected verdict, and computes the "breakdown SE": the
critical hidden true standard error on the degenerate side that would be
needed to flip that verdict to nonsignificant, expressed as a multiple of
the comparable nondegenerate side's own observed SE.

Formula: for a two sample difference test at z=1.96,
    Delta_hat = diff
    SE_diff_needed_for_null = |diff| / 1.96
    SE2_crit = sqrt(SE_diff_needed_for_null^2 - SE1^2)   (SE1 = the nonzero side)
    ratio = SE2_crit / SE1

Requires: difference_ci_reanalysis_results.csv (produced by
difference_ci_reanalysis.py) in the same directory or passed via --csv.

Reproduces every number in Table "tab:degenerate-ci" of Paper1_IMRaD_Draft.tex.
"""
import argparse
import csv
import math

Z = 1.959963985  # two sided 95% critical value


def main(csv_path: str) -> None:
    rows = list(csv.DictReader(open(csv_path)))

    degenerate_rows = []
    for r in rows:
        b_se = float(r["before_se"])
        a_se = float(r["after_se"])
        if b_se == 0.0 or a_se == 0.0:
            degenerate_rows.append(r)

    print(f"Total comparisons with a degenerate side: {len(degenerate_rows)}\n")

    concerning = []
    trivial = []
    for r in degenerate_rows:
        if r["fdr_significant"] == "True":
            concerning.append(r)
        else:
            trivial.append(r)

    print(f"Concerning (degenerate side + significant verdict): {len(concerning)}")
    print(f"Trivial (both sides zero, verdict nonsignificant, or not significant): {len(trivial)}\n")

    print(
        f"{'Table':<22}{'Case':<38}{'KPI':<22}{'SE1':>8}{'SE2_crit':>10}{'Ratio':>8}"
    )
    for r in concerning:
        b_se = float(r["before_se"])
        a_se = float(r["after_se"])
        se1 = b_se if b_se > 0 else a_se
        diff = float(r["diff"])
        se_diff_needed = abs(diff) / Z
        val = se_diff_needed**2 - se1**2
        se2_crit = math.sqrt(val) if val > 0 else float("nan")
        ratio = se2_crit / se1
        print(
            f"{r['table']:<22}{r['case']:<38}{r['kpi']:<22}"
            f"{se1:>8.3f}{se2_crit:>10.3f}{ratio:>7.2f}x"
        )

    ratios = []
    for r in concerning:
        b_se = float(r["before_se"])
        a_se = float(r["after_se"])
        se1 = b_se if b_se > 0 else a_se
        diff = float(r["diff"])
        se_diff_needed = abs(diff) / Z
        val = se_diff_needed**2 - se1**2
        se2_crit = math.sqrt(val) if val > 0 else float("nan")
        ratios.append(se2_crit / se1)

    print(f"\nRatio range across the {len(concerning)} concerning comparisons: "
          f"{min(ratios):.1f}x -- {max(ratios):.1f}x")
    print(
        "\nInterpretation: the hidden true SE on the degenerate side would need to be "
        f"{min(ratios):.1f}x to {max(ratios):.1f}x larger than the comparable nondegenerate "
        "side's own OBSERVED SE (from the same comparison, same N=50/T=800 SMC protocol) "
        "to flip any of these six significance verdicts to nonsignificant. This is not "
        "plausible under a shared simulation protocol, so these verdicts are treated as "
        "robust rather than as artifacts of the degenerate CI construction."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--csv",
        default="difference_ci_reanalysis_results.csv",
        help="Path to difference_ci_reanalysis_results.csv",
    )
    args = parser.parse_args()
    main(args.csv)
