"""
Main effects estimation for the 12-run Plackett-Burman (PB12) screening
design over the paper's 8 flags (R,D,Q,F,E,A,S,B), specified in
pb12_design.py and executed as the 11 nonbaseline rows deposited under
results/raw_traces/, at the paper's standard severity (duration=50) and
the standard N=50/T=800 convention, one seed per row (screening designs
use a single run per design point, not replicates -- unlike the F/B
severity sweep, which specifically needed replicates to pool). Row 12
(all flags off) coincides with the paper's own canonical baseline data,
already on file, so no 12th run was needed.

This script:
  1. Extracts the mean and SE for each of 4 load bearing KPIs (matching
     Table tab:ci's convention) from each of the 12 raw trace folders.
  2. Computes each flag's main effect via the standard PB12 contrast
     formula: effect_j = (2/N) * sum(sign_{j,run} * y_run), N=12.
  3. Propagates each run's own known SE into a proper SE (and 95% CI) on
     the main effect itself: since the contrast coefficients are all +-1,
     Var(effect_j) = (2/N)^2 * sum(SE_run^2) under independence across the
     12 separately seeded runs.
  4. Applies the paper's standard FDR (Benjamini-Hochberg) correction to
     the resulting p values, one family per KPI (8 flags), consistent with
     the per table FDR convention already used throughout the paper
     (Section sec:ci).

Raw data: results/raw_traces/Supply Chain V11.4.1_<flags>_queries_traces/
(11 new PB12 folders) and .../Supply Chain V11.4.1_queries_traces baseline/
(Run 12, preexisting, the paper's own canonical baseline).
"""
import glob
import math
import re

# PB12 design matrix: 12 runs x 8 flags (R,D,Q,F,E,A,S,B), +1/-1 coded.
# Generator row cyclically shifted 11 times, plus an all low 12th row.
FLAGS = ["R", "D", "Q", "F", "E", "A", "S", "B"]

DESIGN = {
    1:  {"R": +1, "D": +1, "Q": -1, "F": +1, "E": +1, "A": +1, "S": -1, "B": -1},
    2:  {"R": -1, "D": +1, "Q": +1, "F": -1, "E": +1, "A": +1, "S": +1, "B": -1},
    3:  {"R": +1, "D": -1, "Q": +1, "F": +1, "E": -1, "A": +1, "S": +1, "B": +1},
    4:  {"R": -1, "D": +1, "Q": -1, "F": +1, "E": +1, "A": -1, "S": +1, "B": +1},
    5:  {"R": -1, "D": -1, "Q": +1, "F": -1, "E": +1, "A": +1, "S": -1, "B": +1},
    6:  {"R": -1, "D": -1, "Q": -1, "F": +1, "E": -1, "A": +1, "S": +1, "B": -1},
    7:  {"R": +1, "D": -1, "Q": -1, "F": -1, "E": +1, "A": -1, "S": +1, "B": +1},
    8:  {"R": +1, "D": +1, "Q": -1, "F": -1, "E": -1, "A": +1, "S": -1, "B": +1},
    9:  {"R": +1, "D": +1, "Q": +1, "F": -1, "E": -1, "A": -1, "S": +1, "B": -1},
    10: {"R": -1, "D": +1, "Q": +1, "F": +1, "E": -1, "A": -1, "S": -1, "B": +1},
    11: {"R": +1, "D": -1, "Q": +1, "F": +1, "E": +1, "A": -1, "S": -1, "B": -1},
    12: {"R": -1, "D": -1, "Q": -1, "F": -1, "E": -1, "A": -1, "S": -1, "B": -1},
}

RUN_FOLDERS = {
    1:  "Supply Chain V11.4.1_DD_DR_DF_PE_PA_queries_traces",
    2:  "Supply Chain V11.4.1_DD_DQ_PE_PA_PS_queries_traces",
    3:  "Supply Chain V11.4.1_DR_DQ_DF_PA_PS_PB_queries_traces",
    4:  "Supply Chain V11.4.1_DD_DF_PE_PS_PB_queries_traces",
    5:  "Supply Chain V11.4.1_DQ_PE_PA_PB_queries_traces",
    6:  "Supply Chain V11.4.1_DF_PA_PS_queries_traces",
    7:  "Supply Chain V11.4.1_DR_PE_PS_PB_queries_traces",
    8:  "Supply Chain V11.4.1_DD_DR_PA_PB_queries_traces",
    9:  "Supply Chain V11.4.1_DD_DR_DQ_PS_queries_traces",
    10: "Supply Chain V11.4.1_DD_DQ_DF_PB_queries_traces",
    11: "Supply Chain V11.4.1_DR_DQ_DF_PE_queries_traces",
    12: "Supply Chain V11.4.1_queries_traces baseline",
}

# The 4 load bearing KPIs used in Table tab:ci.
QUERIES = {
    "003": "Safe-stock recovery time",
    "005": "Production-blocked time (active)",
    "007": "Stockout duration",
    "012": "Minimum availability",
}


def extract_estimate(fpath):
    text = open(fpath, errors="ignore").read()
    m = re.search(r"\((\d+) runs\) E\((?:max|min)\) = [^0-9\-]*([\-0-9.]+)\s*\xb1\s*([0-9.]+) \(95% CI\)", text)
    if m:
        return float(m.group(2)), float(m.group(3)) / 1.96
    # degenerate case: no +/- margin, all replications hit an identical value
    m = re.search(r"\((\d+) runs\) E\((?:max|min)\) = [^0-9\-]*([\-0-9.]+)\s*$", text, re.M)
    if m:
        return float(m.group(2)), 0.0
    m = re.search(r"\((\d+)/(\d+) runs\) Pr\(.*?\) in \[([\-0-9.]+),([\-0-9.]+)\]", text)
    if m:
        k, n, lo, hi = int(m.group(1)), int(m.group(2)), float(m.group(3)), float(m.group(4))
        return k / n, (hi - lo) / 2 / 1.96
    return None, None


def get_run_value(folder, qid, base="../results/raw_traces"):
    matches = glob.glob(f"{base}/{folder}/{qid}_*.txt")
    matches = [m for m in matches if not re.search(r"_[23]\.txt$", m)]  # exclude noncanonical replicates
    if not matches:
        raise FileNotFoundError(f"No file for query {qid} in {folder}")
    mean, se = extract_estimate(matches[0])
    if mean is None:
        raise ValueError(f"Could not parse {matches[0]}")
    return mean, se


def normal_p(z):
    return 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))


def bh_fdr(pvals, alpha=0.05):
    n = len(pvals)
    order = sorted(range(n), key=lambda i: pvals[i])
    max_rank_sig = 0
    for rank, i in enumerate(order, start=1):
        if pvals[i] <= (rank / n) * alpha:
            max_rank_sig = rank
    sig = [False] * n
    for rank, i in enumerate(order, start=1):
        sig[i] = rank <= max_rank_sig
    return sig


def main():
    N = 12
    for qid, name in QUERIES.items():
        means, ses = {}, {}
        for run in range(1, 13):
            m, se = get_run_value(RUN_FOLDERS[run], qid)
            means[run], ses[run] = m, se

        effects, effect_ses = {}, {}
        for flag in FLAGS:
            eff = (2.0 / N) * sum(DESIGN[run][flag] * means[run] for run in range(1, 13))
            var = (2.0 / N) ** 2 * sum(ses[run] ** 2 for run in range(1, 13))
            effects[flag] = eff
            effect_ses[flag] = math.sqrt(var)

        pvals = []
        for flag in FLAGS:
            se = effect_ses[flag]
            z = effects[flag] / se if se > 0 else float("inf")
            pvals.append(normal_p(z))
        fdr_sig = bh_fdr(pvals)

        print(f"\n=== {name} (query {qid}) ===")
        print(f"{'Flag':6s} {'Effect':>12s} {'SE':>10s} {'95% CI':>24s} {'p':>10s} {'FDR sig':>8s}")
        for flag, p, sig in zip(FLAGS, pvals, fdr_sig):
            eff, se = effects[flag], effect_ses[flag]
            lo, hi = eff - 1.96 * se, eff + 1.96 * se
            print(f"{flag:6s} {eff:12.3f} {se:10.3f} [{lo:10.3f},{hi:9.3f}] {p:10.4f} {str(sig):>8s}")


if __name__ == "__main__":
    main()
