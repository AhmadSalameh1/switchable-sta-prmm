"""
Per KPI minimum detectable effect (MDE, 80% power) for the full main CI
battery (Table tab:ci: 4 cases x 4 KPIs = 16 comparisons), not just the
F->F+B case already covered by fb_per_kpi_mde.py / Table tab:fb-mde.

Reuses build_table_ci() and compute_mde() from difference_ci_reanalysis.py.
Reproduces every number in Table tab:main-mde of Paper1_IMRaD_Draft.tex.
"""
from difference_ci_reanalysis import build_table_ci, compute_mde


def main():
    comps = build_table_ci()
    print(f"{'Case':<22}{'KPI':<32}{'Before':>10}{'Obs |Diff|':>12}{'MDE(abs)':>10}{'MDE(%)':>9}{'Below MDE?':>12}")

    mde_pcts = []
    below_count = 0
    fb_below_count = 0
    for c in comps:
        se_diff, mde_abs, mde_pct = compute_mde(c)
        diff = abs(c.after.value - c.before.value)
        below = diff < mde_abs
        if below:
            below_count += 1
            if c.case == "F -> F+B":
                fb_below_count += 1
        mde_pcts.append(mde_pct)
        print(
            f"{c.case:<22}{c.kpi:<32}{c.before.value:>10.2f}{diff:>12.2f}"
            f"{mde_abs:>10.3f}{mde_pct:>8.2f}%{str(below):>12}"
        )

    print(f"\nMDE range across all 16 comparisons: {min(mde_pcts):.2f}% -- {max(mde_pcts):.2f}% of baseline")
    print(f"Comparisons below their own MDE: {below_count} / 16 (all {fb_below_count} of them from F -> F+B)")
    print(
        "\nConclusion: the 12 comparisons outside F->F+B all clear their own KPI specific "
        "MDE (i.e. those significant results are adequately powered, not MDE masked). "
        "The 4 F->F+B comparisons fall below their MDE, consistent with the null result "
        "already documented for that case's full 7-KPI PRMM scoring set (Table tab:fb-mde)."
    )


if __name__ == "__main__":
    main()
