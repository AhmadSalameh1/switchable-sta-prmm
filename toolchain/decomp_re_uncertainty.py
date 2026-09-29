#!/usr/bin/env python3
"""
decomp_re_uncertainty.py

Propagates uncertainty through the R->R+E additive decomposition
(tab:decomp-re in the paper). The decomposition reuses four already reported
cells (Baseline, R, E without R, R+E) as point estimates; this script adds a
confidence interval on the residual and on the "E's effect explains ~100% of
the total gap" attribution ratio, which the point estimates alone don't carry.

Residual = Observed(R+E) - Predicted, where Predicted = Baseline + effR + effE
         = R + E_without_R - Baseline
This is a linear combination of four independent samples with coefficients
(+1, -1, -1, +1) on (R+E, R, E_without_R, Baseline), so its variance is just
the sum of the four inputs' own variances -- computed analytically.

Ratio = effE / (Observed - Baseline) shares the same Baseline draw in both
numerator and denominator, so it is NOT independent across the two -- this
is propagated via Monte Carlo (500,000 draws), redrawing Baseline once per
iteration and reusing it in both effE and the total gap, which correctly
captures that shared randomness (a naive independent ratio formula would not).
"""
import math
import random

Z = 1.96
N = 500_000

# (kpi, baseline, se_base, R, se_R, E_without_R, se_Ewo, R+E, se_RE)
DATA = {
    "Safe stock recovery time":       (148.04, 10.674685943272575, 214.62, 11.147041561582572, 8.58, 0.1900540024463766, 8.66, 0.22993942921864455),
    "Active production blocked time": (605.06, 7.269368268519486,  617.6,  4.586176107720673,  16.82, 0.6973648548955353, 16.96, 0.7739325883582499),
    "Stockout duration":              (35.9,   2.912017794041251, 55.92,  2.562710355108898,  0.0,  0.0,                 0.0,  0.0),
    "Minimum availability":           (95.24,  0.4486577338817785, 93.18, 0.412929526355557,  100.0, 0.0,                100.0, 0.0),
}


def main():
    random.seed(7)
    print(f"{'KPI':<32}{'residual':>10}{'SE':>9}{'95% CI':>22}{'sig?':>6}{'ratio%':>9}{'ratio 95% CI':>20}")
    for kpi, (base, se_base, R, se_R, Ewo, se_Ewo, RE, se_RE) in DATA.items():
        eff_r = R - base
        eff_e = Ewo - base
        predicted = base + eff_r + eff_e
        residual = RE - predicted
        se_resid = math.sqrt(se_RE**2 + se_R**2 + se_Ewo**2 + se_base**2)
        lo, hi = residual - Z * se_resid, residual + Z * se_resid
        sig = not (lo <= 0 <= hi)

        ratios = []
        for _ in range(N):
            b = random.gauss(base, se_base) if se_base > 0 else base
            r = random.gauss(R, se_R) if se_R > 0 else R
            ew = random.gauss(Ewo, se_Ewo) if se_Ewo > 0 else Ewo
            re = random.gauss(RE, se_RE) if se_RE > 0 else RE
            gap = re - b
            e_eff = ew - b
            if abs(gap) > 1e-9:
                ratios.append(100 * e_eff / gap)
        ratios.sort()
        r_lo = ratios[int(0.025 * len(ratios))]
        r_hi = ratios[int(0.975 * len(ratios))]
        point_ratio = 100 * eff_e / (RE - base) if (RE - base) != 0 else float("nan")

        print(f"{kpi:<32}{residual:>10.2f}{se_resid:>9.3f}[{lo:>8.2f},{hi:>7.2f}]{str(sig):>6}"
              f"{point_ratio:>8.1f}%  [{r_lo:>6.1f}%,{r_hi:>6.1f}%]")


if __name__ == "__main__":
    main()
