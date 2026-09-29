"""
Concordance check for the paper's shared Gaussian difference test formula,
which is only an approximation for Pr(...) probability queries, since
verifyta's Clopper-Pearson intervals for those queries are not themselves
Gaussian. This script provides a more exact treatment (Newcombe's method
for the difference of two independent binomial proportions) rather than
relying on disclosure of the approximation alone.

Scope check first: of the 8 KPI queries scored per scenario (Section
sec:prmm-sourcing's S4 KPI set, 7 named KPIs + minimum availability),
only ONE -- service_ratio_pct -- is a Pr(...) query; every other KPI
(lead time, safe stock recovery time, production blocked times, defect
rate, stockout duration, minimum availability) is an E(max/min) estimate
query with a genuinely Gaussian/CLT based interval. So the approximation
only actually matters for service_ratio_pct comparisons -- 4 of this
paper's 92 KPI level comparisons (one per disruption practice pair:
R->R+E, D->D+E,S, F->F+B, full portfolio), all of them part of the 28
comparisons behind Table tab:prmm-l4.

This script extracts the exact (k successes / n runs) pair verifyta
reports for service_ratio_pct in each of the 8 relevant scenario trace
folders (4 "before" + 4 "after" states), then compares two difference CI
constructions for each of the 4 pairs:
  1. The paper's actual method: convert each side's Clopper-Pearson
     margin to an implied Gaussian SE (margin/1.96), then
     Delta +/- 1.96*sqrt(SE1^2+SE2^2).
  2. Newcombe's (1998) hybrid score method for the difference of two
     independent proportions, built from two Wilson score intervals --
     a standard, more accurate closed form alternative to the Wald/
     Gaussian approximation, and the specific method reviewers named.

No new simulation is used -- the (k, n) pairs are read directly from the
already deposited raw verifyta trace files.
"""
import math
import re
import glob


def extract_kn(trace_dir):
    files = glob.glob(f"{trace_dir}/*service_ratio*.txt")
    text = open(files[0], errors="ignore").read()
    m = re.search(r"\((\d+)/(\d+) runs\)", text)
    return int(m.group(1)), int(m.group(2))


def wilson(x, n, z=1.96):
    p = x / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    hw = (z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / denom
    return center - hw, center + hw, p


def newcombe_diff(x1, n1, x2, n2, z=1.96):
    l1, u1, p1 = wilson(x1, n1, z)
    l2, u2, p2 = wilson(x2, n2, z)
    diff = p1 - p2
    lower = diff - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    upper = diff + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return diff, lower, upper


def gaussian_diff_from_cp(x1, n1, cp1, x2, n2, cp2, z=1.96):
    p1, p2 = x1 / n1, x2 / n2
    se1 = (cp1[1] - cp1[0]) / 2 / z
    se2 = (cp2[1] - cp2[0]) / 2 / z
    diff = p1 - p2
    se = math.sqrt(se1**2 + se2**2)
    return diff, diff - z * se, diff + z * se


PAIRS = {
    "R -> R+E": ("Supply Chain V11.4.1_queries_traces R",
                 "Supply Chain V11.4.1_queries_traces R + E"),
    "D -> D+E,S": ("Supply Chain V11.4.1_queries_traces D",
                   "Supply Chain V11.4.1_queries_traces D + E,S"),
    "F -> F+B": ("Supply Chain V11.4.1_queries_traces F",
                 "Supply Chain V11.4.1_queries_traces F + B"),
    "Full-portfolio": ("Supply Chain V11.4.1_queries_traces R,D,Q,F",
                        "Supply Chain V11.4.1_queries_traces R,D,Q,F + E,A,S,B"),
}


def main(base="../results/raw_traces"):
    for name, (before, after) in PAIRS.items():
        x1, n1 = extract_kn(f"{base}/{before}")
        x2, n2 = extract_kn(f"{base}/{after}")
        # Recover verifyta's own reported CP interval by parsing the trace directly
        def cp_interval(d):
            files = glob.glob(f"{d}/*service_ratio*.txt")
            text = open(files[0], errors="ignore").read()
            m = re.search(r"\[([\d.]+),([\d.]+)\] \(95% CI\)", text)
            return float(m.group(1)), float(m.group(2))

        cp1 = cp_interval(f"{base}/{before}")
        cp2 = cp_interval(f"{base}/{after}")

        gdiff, glo, ghi = gaussian_diff_from_cp(x1, n1, cp1, x2, n2, cp2)
        ndiff, nlo, nhi = newcombe_diff(x1, n1, x2, n2)
        gsig = not (glo <= 0 <= ghi)
        nsig = not (nlo <= 0 <= nhi)
        print(f"{name}: ({x1}/{n1}) -> ({x2}/{n2})")
        print(f"  paper's Gaussian approx diff CI: {gdiff:+.4f} [{glo:+.4f},{ghi:+.4f}] sig={gsig}")
        print(f"  Newcombe diff CI:                {ndiff:+.4f} [{nlo:+.4f},{nhi:+.4f}] sig={nsig}")
        print(f"  verdicts match: {gsig == nsig}\n")


if __name__ == "__main__":
    main()
