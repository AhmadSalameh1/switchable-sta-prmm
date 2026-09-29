"""
Robustness check for the F->F+B null result: FG_TRANSPORT_DELAY_DURATION
doubled from 50 to 100 (period and trip time left unchanged), F and F+B each
rerun 3 times (3 independent seeds) with the same 17-query battery at
N=50/T=800, to test whether the baseline severity null is a genuine absence
of effect or a power artifact at the original disruption magnitude.

This script pools each scenario's 3 replicates via inverse variance weighted
fixed effect meta analysis (justified because each replicate is an
independent SMC estimate of the same underlying quantity under the same
model/parameters, differing only in random seed), then runs the same
FDR corrected difference CI significance test used throughout the paper
(Section sec:ci) on the pooled estimates.

Raw data: results/raw_traces/Supply Chain V11.4.1_DF_queries_traces/ (F,
duration=100, 3 replicates) and .../Supply Chain V11.4.1_DF_PB_queries_traces/
(F+B, duration=100, 3 replicates).
"""
import glob
import math
import re

QUERIES = {
    "001": "Service ratio (Pr)",
    "002": "Average lead time",
    "003": "Safe-stock recovery time",
    "004": "Latent production-blocked time",
    "005": "Production-blocked time (active)",
    "006": "Defect rate",
    "007": "Stockout duration",
    "012": "Minimum availability",
}


def extract_estimate(fpath):
    text = open(fpath, errors="ignore").read()
    m = re.search(r"\((\d+) runs\) E\((?:max|min)\) = ([\-0-9.]+) . ([0-9.]+) \(95% CI\)", text)
    if m:
        return float(m.group(2)), float(m.group(3)) / 1.96
    m = re.search(r"\((\d+)/(\d+) runs\) Pr\(.*?\) in \[([\-0-9.]+),([\-0-9.]+)\]", text)
    if m:
        k, n, lo, hi = int(m.group(1)), int(m.group(2)), float(m.group(3)), float(m.group(4))
        return k / n, (hi - lo) / 2 / 1.96
    return None, None


def pooled_estimate(folder, qid):
    means, ses = [], []
    for rep in ("1", "2", "3"):
        matches = glob.glob(f"{folder}/{qid}_*_{rep}.txt")
        if not matches:
            continue
        mean, se = extract_estimate(matches[0])
        if mean is None:
            continue
        means.append(mean)
        ses.append(se)
    weights = [1 / se**2 for se in ses]
    pooled_mean = sum(w * m for w, m in zip(weights, means)) / sum(weights)
    pooled_se = math.sqrt(1 / sum(weights))
    return pooled_mean, pooled_se, len(means)


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


def main(base="../results/raw_traces"):
    f_folder = f"{base}/Supply Chain V11.4.1_DF_queries_traces"
    fb_folder = f"{base}/Supply Chain V11.4.1_DF_PB_queries_traces"

    rows = []
    for qid, name in QUERIES.items():
        f_mean, f_se, f_n = pooled_estimate(f_folder, qid)
        fb_mean, fb_se, fb_n = pooled_estimate(fb_folder, qid)
        diff = fb_mean - f_mean
        se = math.sqrt(f_se**2 + fb_se**2)
        lo, hi = diff - 1.96 * se, diff + 1.96 * se
        z = diff / se
        p = normal_p(z)
        mde = (1.96 + 0.8416) * se
        rows.append((name, f_mean, f_se, fb_mean, fb_se, diff, lo, hi, p, mde))

    pvals = [r[8] for r in rows]
    fdr_sig = bh_fdr(pvals)

    print(f"{'KPI':35s} {'F (pooled)':>12s} {'F+B (pooled)':>13s} {'Delta':>9s} {'95% CI':>20s} {'FDR sig':>8s}")
    for (name, fm, fse, bm, bse, diff, lo, hi, p, mde), sig in zip(rows, fdr_sig):
        print(f"{name:35s} {fm:12.3f} {bm:13.3f} {diff:9.3f} [{lo:8.3f},{hi:7.3f}] {str(sig):>8s}")


if __name__ == "__main__":
    main()
