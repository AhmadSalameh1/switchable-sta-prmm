"""
Constructs the 12-run Plackett-Burman design matrix over this paper's 8
Boolean flags (R, D, Q, F, E, A, S, B) and verifies it is orthogonal, as a
ready to execute specification for the screening design used in
Supplementary Material Section S1. Pure combinatorics -- no model execution
involved.

Reproduces the design table (tab:s-pb12) in the Supplementary Material.
"""
import numpy as np

# Standard 12-run Plackett-Burman generator row for up to 11 factors.
GEN = [1, 1, -1, 1, 1, 1, -1, -1, -1, 1, -1]
FLAGS = ["R", "D", "Q", "F", "E", "A", "S", "B"]


def build_pb12():
    rows = []
    g = GEN[:]
    for _ in range(11):
        rows.append(g[:])
        g = [g[-1]] + g[:-1]  # cyclic shift right
    rows.append([-1] * 11)   # 12th row: all low (Baseline)
    return np.array(rows)


def main():
    M = build_pb12()
    assert M.shape == (12, 11)

    col_sums = M.sum(axis=0)
    assert (col_sums == 0).all(), "Design is not balanced"

    dots = M.T @ M
    off_diag = dots - np.diag(np.diag(dots))
    assert np.abs(off_diag).max() == 0, "Design is not orthogonal"

    design = M[:, :8]  # restrict to our 8 flags
    print("Verified: 12x8 sub design is balanced (column sums = 0) and "
          "pairwise orthogonal (all off diagonal dot products = 0).\n")
    for i, row in enumerate(design):
        combo = [FLAGS[j] for j in range(8) if row[j] == 1]
        label = ", ".join(combo) if combo else "(none -- Baseline)"
        print(f"Run {i + 1:2d}: {label}")


if __name__ == "__main__":
    main()
