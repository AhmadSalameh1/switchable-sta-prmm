"""
Derives the structural ceiling on S_final: with S5 hardcoded to 0 throughout
this paper's toolchain (Level 5 -- benchmarking -- is not implemented),
S_final = sum(alpha_l * S_l)
is mechanically capped at 100*(1-alpha_5) regardless of how strong the
S1-S4 evidence is, since S5's term is always alpha_5 * 0 = 0.

This script verifies that ceiling for every weighting scheme used in
Table tab:weight-sensitivity, and confirms none of this paper's actual
baseline weight scores come close to testing it.
"""

SCHEMES = {
    "Baseline":     (0.05, 0.10, 0.25, 0.30, 0.30),
    "Equal":        (0.20, 0.20, 0.20, 0.20, 0.20),
    "Front-loaded": (0.30, 0.25, 0.20, 0.15, 0.10),
    "Back-loaded":  (0.05, 0.05, 0.15, 0.35, 0.40),
    "L3-emphasis":  (0.10, 0.15, 0.35, 0.20, 0.20),
}

# Actual baseline S_final values reported in Table tab:weight-sensitivity
BASELINE_SCORES = {
    "R -> R+E": 60.6,
    "D -> D+E,S": 61.0,
    "F -> F+B": 40.0,
    "Full-portfolio": 58.5,
}

BANDS = [
    (0, 59, "Early Awareness"),
    (60, 69, "Conceptual Readiness"),
    (70, 79, "Practice-Linked Resilience"),
    (80, 89, "Continuous Optimization"),
    (90, 100, "Benchmark-Aligned Excellence"),
]


def band_for(score):
    for lo, hi, name in BANDS:
        if lo <= score <= hi:
            return name
    return "out of range"


def main():
    print("Ceiling on S_final = 100*(1 - alpha_5), given S5 = 0 always:\n")
    for name, alphas in SCHEMES.items():
        a1, a2, a3, a4, a5 = alphas
        assert abs(sum(alphas) - 1.0) < 1e-9, f"{name} weights do not sum to 1"
        ceiling = 100 * (1 - a5)
        # cross check via direct max evidence substitution
        ceiling_direct = a1 * 100 + a2 * 100 + a3 * 100 + a4 * 100 + a5 * 0
        assert abs(ceiling - ceiling_direct) < 1e-9
        unreachable_bands = [nm for lo, hi, nm in BANDS if lo > ceiling]
        print(f"  {name:14s} alpha_5={a5:.2f}  ceiling={ceiling:5.1f}%  "
              f"unreachable bands: {unreachable_bands if unreachable_bands else 'none'}")

    print("\nActual baseline weight scores reported in this paper (Table tab:weight-sensitivity):")
    baseline_ceiling = 100 * (1 - SCHEMES["Baseline"][4])
    for case, score in BASELINE_SCORES.items():
        headroom = baseline_ceiling - score
        print(f"  {case:20s} {score:5.1f}%  ({band_for(score)})  "
              f"headroom to ceiling ({baseline_ceiling:.0f}%): {headroom:.1f} points")

    print(
        f"\nConclusion: under baseline weights (ceiling={baseline_ceiling:.0f}%), Continuous "
        "Optimization (80-89) and Benchmark Aligned Excellence (90-100) are categorically "
        "unreachable while S5=0, but no case in this paper's actual results comes anywhere "
        "close to that ceiling, so it does not change any reported category label -- it is "
        "a structural fact about the scoring scheme, not an error in the reported scores."
    )


if __name__ == "__main__":
    main()
