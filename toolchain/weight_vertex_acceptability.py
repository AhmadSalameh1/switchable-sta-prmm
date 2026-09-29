#!/usr/bin/env python3
"""
weight_vertex_acceptability.py

Extends the two point segment "closed form category robustness" analysis
(sec:robustness in the paper) to the full weight simplex: since
S_final(alpha) = sum_l alpha_l * S_l is linear in alpha, its extrema over
any constrained subregion of the simplex are attained at that region's
vertices, computable directly from the already reported S_1..S_5 values --
no new UPPAAL data needed.

The unconstrained simplex is uninformative (S_5=0 and S_1 or S_3=100 in every
case, so the unconstrained range is trivially [0%,100%] everywhere). This
script instead uses the floor constraint alpha_l >= 0.05 for all l, which is
not arbitrary: every one of the five weighting schemes already used in
tab:weight-sensitivity (including the literature sourced baseline) satisfies
it.

Produces:
  1. The five vertices of the floor constrained simplex (one per level at its
     max permissible weight 0.80, others at the 0.05 floor) and S_final at
     each, for all four disruption practice cases.
  2. A Monte Carlo (N=200,000) uniform prior estimate of the acceptability
     share of each maturity category per case (a discrete SMAA style
     analysis), for reproducibility of the numbers quoted in the paper.
"""
import random

def band(x: float) -> str:
    if x < 60: return "EA"
    if x < 70: return "CR"
    if x < 80: return "PL"
    if x < 90: return "CO"
    return "BA"

CASES = {
    "R -> R+E":       [100, 100, 100, 68.57, 0],
    "D -> D+E,S":     [100, 100, 100, 70.00, 0],
    "F -> F+B":       [100, 100, 100, 0.00,  0],
    "Full portfolio": [100, 75,  100, 70.00, 0],
}

FLOOR = 0.05
MAXW = 1 - 4 * FLOOR  # 0.80


def vertices():
    print(f"=== Vertex range, floor constrained simplex (alpha_l >= {FLOOR}) ===\n")
    for case, S in CASES.items():
        vals = []
        for l in range(5):
            alpha = [FLOOR] * 5
            alpha[l] = MAXW
            sf = sum(a * s for a, s in zip(alpha, S))
            vals.append(sf)
        print(f"{case}: " + ", ".join(f"{v:.2f}%({band(v)})" for v in vals) +
              f"  range=[{min(vals):.2f}%,{max(vals):.2f}%]")


def acceptability(n=200_000, seed=42):
    random.seed(seed)
    budget = 1 - 5 * FLOOR
    print(f"\n=== Acceptability shares, uniform prior over floor constrained simplex, N={n} ===\n")
    for case, S in CASES.items():
        counts = {"EA": 0, "CR": 0, "PL": 0, "CO": 0, "BA": 0}
        for _ in range(n):
            xs = [random.expovariate(1.0) for _ in range(5)]
            s = sum(xs)
            free = [x / s for x in xs]
            alpha = [FLOOR + budget * f for f in free]
            sf = sum(a * v for a, v in zip(alpha, S))
            counts[band(sf)] += 1
        pct = {k: 100 * v / n for k, v in counts.items()}
        print(case, {k: f"{v:.1f}%" for k, v in pct.items()})


if __name__ == "__main__":
    vertices()
    acceptability()
