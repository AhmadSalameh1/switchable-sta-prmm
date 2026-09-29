#!/usr/bin/env python3
"""
fb_per_kpi_mde.py

Computes the minimum detectable effect (MDE, 80% power, alpha=0.05 two sided,
independent samples formula) separately for each of the seven PRMM Level 4
KPIs in the F->F+B comparison, instead of relying on one "representative" KPI
(production blocked time) as a stand in for the rest.

Reuses the trace parsing and MDE formula already implemented in
difference_ci_reanalysis.py (Comparison.build_table_prmm_l4_fb, compute_mde).
"""
import sys
sys.path.insert(0, ".")
from difference_ci_reanalysis import build_table_prmm_l4_fb, compute_mde

def main():
    fb7 = build_table_prmm_l4_fb()
    print(f"{'KPI':<34}{'obs |diff|':>11}{'MDE (80% power)':>18}{'obs < MDE?':>12}")
    for c in fb7:
        se_diff, mde_abs, mde_pct = compute_mde(c)
        obs_diff = abs(c.after.value - c.before.value)
        below = obs_diff < mde_abs
        print(f"{c.kpi:<34}{obs_diff:>11.4g}{mde_abs:>18.4g}{str(below):>12}")
    print()
    print("All seven observed differences fall below their own KPI specific MDE:",
          all(abs(c.after.value - c.before.value) < compute_mde(c)[1] for c in fb7))

if __name__ == "__main__":
    main()
