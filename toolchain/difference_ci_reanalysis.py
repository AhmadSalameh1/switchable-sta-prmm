#!/usr/bin/env python3
"""
difference_ci_reanalysis.py

Reanalyzes the paper's significance claims using a direct difference of means /
difference of proportions confidence interval, instead of the paper's original
"do the two separate 95% CIs overlap?" heuristic.

Background
----------
Two peer reviewers (reliability engineering and operations research journals)
flagged that CI overlap is a well known *conservative* substitute for a direct
test of the difference (Payton, Greenstone & Schenker 2003; Schenker & Gentleman
2001): two 95% CIs can fail to overlap only when the true difference is quite
large relative to its own standard error, which means CI overlap has LOWER power
than the direct test -- it can call a real, statistically significant effect
"not significant". The worry raised was specifically about the paper's headline
finding that F -> F+B shows "no statistically confirmed effect on any KPI",
which currently drives a PRMM Level-4 score of exactly 0.0% for that case.

This script:
  1. Parses every raw verifyta trace file involved in the paper's four main
     results tables (tab:ci, tab:sensitivity-t1max, tab:sensitivity-shape,
     tab:probe-results) plus the 7-KPI F->F+B comparison behind the PRMM
     Level-4 table, recovering point estimate, standard error, and N directly
     from the trace text (not from any prerounded paper table).
  2. Recomputes each comparison two ways:
       (a) OLD method: do the two reported 95% CIs overlap?
       (b) NEW method: 95% CI of the difference (diff +/- 1.96 * SE_diff),
           using SE_diff = sqrt(SE1^2 + SE2^2) for independent samples.
  3. Applies Benjamini-Hochberg FDR correction within each table's family of
     tests (since this is an exploratory panel of many comparisons).
  4. Computes a post hoc Minimum Detectable Effect (MDE) at 80% power for a
     representative N=50 estimate query KPI comparison.

Per run / per replicate data availability
------------------------------------------
Every raw trace file in results/raw_traces/ was inspected. UPPAAL's verifyta
was run with default (nonverbose) SMC output: each file reports only the
FINAL aggregate result for the whole batch of N runs --
  - probability queries: "(sat/total runs) Pr(<> ...) in [lo,hi] (95% CI)"
  - estimate queries:    "(N runs) E(max/min) = value +/- margin (95% CI)"
    (or "E(max/min) = ~ value" with implicit zero margin when every run
    produced the identical value)
No per run / per replicate trace lines, and no verbose per iteration value
dump, appear anywhere in the corpus -- the "Throughput: ... Load: N runs[K"
lines are verifyta's own progress meter (runs remaining in the batch), not
per run results. So only aggregate mean/margin/N (or sat/total) are available,
exactly the "expected case" the task anticipated. This also means no
per seed paired differences can be recovered even for the CRN based
sensitivity sweep: the sweep trace files carry the same UPPAAL *master* seed
as their reference run (confirmed below), which is necessary but not
sufficient to reconstruct 50 individual paired differences from aggregate
output alone. All SE_diff calculations below therefore use the conservative
independent samples formula, which is flagged explicitly wherever CRN pairing
was confirmed (see CRN_PAIRED_CELLS below).

Usage
-----
    python3 difference_ci_reanalysis.py
Prints all comparisons to stdout and writes a machine readable CSV next to
this script (difference_ci_reanalysis_results.csv).
"""

import csv
import math
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

# ----------------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACES_DIR = os.path.join(REPO_ROOT, "results", "raw_traces")
OUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "difference_ci_reanalysis_results.csv")

Z95 = 1.959963985  # two sided 95% normal critical value
Z80_POWER = 0.841621  # one sided z for 80% power (beta = 0.20)


# ----------------------------------------------------------------------------
# Trace parsing
# ----------------------------------------------------------------------------

@dataclass
class QueryResult:
    kind: str            # 'prob' or 'est'
    value: float
    se: float
    n: int
    ci_lo: float
    ci_hi: float
    sat: Optional[int] = None
    seed: Optional[str] = None
    path: str = ""


PROB_RE = re.compile(r"\((\d+)/(\d+)\s*runs\)\s*Pr\(.*?\)\s*in\s*\[([\-\d.eE]+),\s*([\-\d.eE]+)\]")
EST_RE = re.compile(r"\((\d+)\s*runs\)\s*E\((?:max|min)\)\s*=\s*([\-\d.eE]+)\s*[±+/-]+\s*([\-\d.eE]+)")
EST_ZEROVAR_RE = re.compile(r"\((\d+)\s*runs\)\s*E\((?:max|min)\)\s*=\s*[≈~]\s*([\-\d.eE]+)")
SEED_RE = re.compile(r"Seed is (\d+)")


def parse_trace(path: str) -> QueryResult:
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()

    seed_m = SEED_RE.search(text)
    seed = seed_m.group(1) if seed_m else None

    m = PROB_RE.search(text)
    if m:
        sat, tot = int(m.group(1)), int(m.group(2))
        p = sat / tot
        se = math.sqrt(p * (1 - p) / tot) if tot > 0 else 0.0
        ci_lo, ci_hi = float(m.group(3)), float(m.group(4))
        return QueryResult(kind="prob", value=p, se=se, n=tot,
                            ci_lo=ci_lo, ci_hi=ci_hi, sat=sat, seed=seed, path=path)

    m = EST_RE.search(text)
    if m:
        n = int(m.group(1))
        val = float(m.group(2))
        margin = float(m.group(3))
        se = margin / Z95
        return QueryResult(kind="est", value=val, se=se, n=n,
                            ci_lo=val - margin, ci_hi=val + margin, seed=seed, path=path)

    m = EST_ZEROVAR_RE.search(text)
    if m:
        n = int(m.group(1))
        val = float(m.group(2))
        return QueryResult(kind="est", value=val, se=0.0, n=n,
                            ci_lo=val, ci_hi=val, seed=seed, path=path)

    raise ValueError(f"Could not parse SMC result out of {path}")


def find_file(folder: str, idx: str, suffix: str) -> str:
    """Locate the trace file for query index `idx` (e.g. '003') and run
    suffix (e.g. '1', '2', '3') inside `folder` (relative to TRACES_DIR)."""
    d = os.path.join(TRACES_DIR, folder)
    prefix = f"{idx}_"
    tail = f"_{suffix}.txt"
    matches = [fn for fn in os.listdir(d) if fn.startswith(prefix) and fn.endswith(tail)]
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected exactly 1 match for {prefix}*{tail} in {d}, got {matches}")
    return os.path.join(d, matches[0])


def load(folder: str, idx: str, suffix: str = "1") -> QueryResult:
    return parse_trace(find_file(folder, idx, suffix))


# ----------------------------------------------------------------------------
# Statistics
# ----------------------------------------------------------------------------

def normal_sf(z: float) -> float:
    """Survival function (1 - CDF) of the standard normal, via erf."""
    return 0.5 * math.erfc(z / math.sqrt(2))


def two_sided_p(z: float) -> float:
    return 2 * normal_sf(abs(z))


@dataclass
class Comparison:
    table: str
    case: str
    kpi: str
    before: QueryResult
    after: QueryResult
    note: str = ""

    def ci_overlap_significant(self) -> bool:
        """OLD method: significant iff the two 95% CIs do NOT overlap."""
        return (self.before.ci_hi < self.after.ci_lo) or (self.after.ci_hi < self.before.ci_lo)

    def diff_ci(self):
        diff = self.after.value - self.before.value
        se_diff = math.sqrt(self.before.se ** 2 + self.after.se ** 2)
        if se_diff == 0:
            z = math.inf if diff != 0 else 0.0
            p = 0.0 if diff != 0 else 1.0
            lo = hi = diff
        else:
            z = diff / se_diff
            p = two_sided_p(z)
            lo = diff - Z95 * se_diff
            hi = diff + Z95 * se_diff
        return diff, se_diff, lo, hi, z, p

    def new_significant(self) -> bool:
        _, _, lo, hi, _, _ = self.diff_ci()
        return not (lo <= 0 <= hi)


def benjamini_hochberg(pvals):
    """Return boolean array: True if the hypothesis survives BH FDR at q=0.05."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    thresh_rank = -1
    for rank, i in enumerate(order, start=1):
        crit = (rank / m) * 0.05
        if pvals[i] <= crit:
            thresh_rank = rank
    keep = [False] * m
    if thresh_rank >= 0:
        for rank, i in enumerate(order, start=1):
            if rank <= thresh_rank:
                keep[i] = True
    return keep


# ----------------------------------------------------------------------------
# CRN pairing check (reported, not used to shrink SE -- see module docstring)
# ----------------------------------------------------------------------------

CRN_PAIRED_CELLS = []  # filled in at runtime by check_crn_pairing()


def check_crn_pairing():
    """Compares master UPPAAL seeds between each sensitivity sweep arm and its
    reference run. Same seed => same underlying RNG stream => true CRN pairing
    *is possible* in principle (though we cannot exploit it without per run
    values). Different seed => that arm is NOT CRN paired, contradicting the
    paper's blanket CRN claim for that cell."""
    cells = [
        ("sensitivity-t1max", "Baseline", "T1_MAX=12", "Supply Chain V11.4.1_baseline_queries_traces", "1",
         "Supply Chain V11.4.1_queries_traces baseline", "1"),
        ("sensitivity-t1max", "Baseline", "T1_MAX=20", "Supply Chain V11.4.1_baseline_queries_traces", "3",
         "Supply Chain V11.4.1_queries_traces baseline", "1"),
        ("sensitivity-t1max", "R+E", "T1_MAX=12", "Supply Chain V11.4.1_DR_PE_queries_traces", "2",
         "Supply Chain V11.4.1_queries_traces R + E", "1"),
        ("sensitivity-t1max", "R+E", "T1_MAX=20", "Supply Chain V11.4.1_DR_PE_queries_traces", "3",
         "Supply Chain V11.4.1_queries_traces R + E", "1"),
        ("sensitivity-shape", "D", "shape=0.5", "Supply Chain V11.4.1_DD_queries_traces", "1",
         "Supply Chain V11.4.1_queries_traces D", "1"),
        ("sensitivity-shape", "D", "shape=2.0", "Supply Chain V11.4.1_DD_queries_traces", "2",
         "Supply Chain V11.4.1_queries_traces D", "1"),
        ("sensitivity-shape", "D+E,S", "shape=0.5", "Supply Chain V11.4.1_DD_PE_PS_queries_traces", "1",
         "Supply Chain V11.4.1_queries_traces D + E,S", "1"),
        ("sensitivity-shape", "D+E,S", "shape=2.0", "Supply Chain V11.4.1_DD_PE_PS_queries_traces", "2",
         "Supply Chain V11.4.1_queries_traces D + E,S", "1"),
    ]
    results = []
    for table, case, point, folder_a, suf_a, folder_ref, suf_ref in cells:
        a = load(folder_a, "003", suf_a)  # query 003 = safe stock recovery time, always present
        ref = load(folder_ref, "003", suf_ref)
        paired = (a.seed is not None and a.seed == ref.seed)
        results.append((table, case, point, paired, a.seed, ref.seed))
        CRN_PAIRED_CELLS.append((table, case, point, paired))
    return results


# ----------------------------------------------------------------------------
# Table 1: tab:ci -- Confidence Intervals on the KPI Results (4 cases x 4 KPIs)
# ----------------------------------------------------------------------------

# KPI query indices shared by tab:ci, tab:sensitivity-*, tab:probe-results
KPI4 = [("003", "Safe stock recovery time"),
        ("005", "Active production blocked time"),
        ("007", "Stockout duration"),
        ("012", "Minimum availability")]

# All 7 KPIs used in the PRMM Level-4 scoring
KPI7 = [("001", "Service ratio"),
        ("002", "Avg lead time"),
        ("003", "Safe-stock recovery time"),
        ("004", "Latent production-blocked time"),
        ("005", "Production-blocked time"),
        ("006", "Defect rate"),
        ("007", "Stockout duration")]

MAIN_CASES = [
    ("R -> R+E", "Supply Chain V11.4.1_queries_traces R", "Supply Chain V11.4.1_queries_traces R + E"),
    ("D -> D+E,S", "Supply Chain V11.4.1_queries_traces D", "Supply Chain V11.4.1_queries_traces D + E,S"),
    ("F -> F+B", "Supply Chain V11.4.1_queries_traces F", "Supply Chain V11.4.1_queries_traces F + B"),
    ("R,D,Q,F -> +E,A,S,B", "Supply Chain V11.4.1_queries_traces R,D,Q,F",
     "Supply Chain V11.4.1_queries_traces R,D,Q,F + E,A,S,B"),
]


def build_table_ci():
    comps = []
    for case, before_folder, after_folder in MAIN_CASES:
        for idx, kpi in KPI4:
            before = load(before_folder, idx, "1")
            after = load(after_folder, idx, "1")
            comps.append(Comparison("tab:ci", case, kpi, before, after))
    return comps


def build_table_prmm_l4_fb():
    """The 7-KPI F->F+B comparison underlying the PRMM Level-4 table."""
    comps = []
    for idx, kpi in KPI7:
        before = load("Supply Chain V11.4.1_queries_traces F", idx, "1")
        after = load("Supply Chain V11.4.1_queries_traces F + B", idx, "1")
        comps.append(Comparison("PRMM-L4 (F->F+B)", "F -> F+B", kpi, before, after))
    return comps


# ----------------------------------------------------------------------------
# Table 2: tab:sensitivity-t1max (2 flag combos x 4 KPIs x 2 nonref values)
# ----------------------------------------------------------------------------

def build_table_t1max():
    comps = []
    combos = [
        ("Baseline", "Supply Chain V11.4.1_queries_traces baseline", "1",
         [("Supply Chain V11.4.1_baseline_queries_traces", "1", "T1_MAX=12"),
          ("Supply Chain V11.4.1_baseline_queries_traces", "3", "T1_MAX=20")]),
        ("R+E", "Supply Chain V11.4.1_queries_traces R + E", "1",
         [("Supply Chain V11.4.1_DR_PE_queries_traces", "2", "T1_MAX=12"),
          ("Supply Chain V11.4.1_DR_PE_queries_traces", "3", "T1_MAX=20")]),
    ]
    for case, ref_folder, ref_suffix, points in combos:
        for pt_folder, pt_suffix, pt_label in points:
            for idx, kpi in KPI4:
                ref = load(ref_folder, idx, ref_suffix)
                pt = load(pt_folder, idx, pt_suffix)
                comps.append(Comparison("tab:sensitivity-t1max", f"{case} ({pt_label} vs ref16)", kpi, ref, pt))
    return comps


def build_table_shape():
    comps = []
    combos = [
        ("D", "Supply Chain V11.4.1_queries_traces D", "1",
         [("Supply Chain V11.4.1_DD_queries_traces", "1", "shape=0.5"),
          ("Supply Chain V11.4.1_DD_queries_traces", "2", "shape=2.0")]),
        ("D+E,S", "Supply Chain V11.4.1_queries_traces D + E,S", "1",
         [("Supply Chain V11.4.1_DD_PE_PS_queries_traces", "1", "shape=0.5"),
          ("Supply Chain V11.4.1_DD_PE_PS_queries_traces", "2", "shape=2.0")]),
    ]
    for case, ref_folder, ref_suffix, points in combos:
        for pt_folder, pt_suffix, pt_label in points:
            for idx, kpi in KPI4:
                ref = load(ref_folder, idx, ref_suffix)
                pt = load(pt_folder, idx, pt_suffix)
                comps.append(Comparison("tab:sensitivity-shape", f"{case} ({pt_label} vs ref1.0)", kpi, ref, pt))
    return comps


# ----------------------------------------------------------------------------
# Table 4: tab:probe-results (4 probes x 4 KPIs, vs Baseline)
# ----------------------------------------------------------------------------

def build_table_probes():
    comps = []
    probes = [
        ("E without R", "Supply Chain V11.4.1_PE_queries_traces"),
        ("A without R", "Supply Chain V11.4.1_PA_queries_traces"),
        ("S without D", "Supply Chain V11.4.1_PS_queries_traces"),
        ("B without F", "Supply Chain V11.4.1_PB_queries_traces"),
    ]
    for probe_name, folder in probes:
        for idx, kpi in KPI4:
            baseline = load("Supply Chain V11.4.1_queries_traces baseline", idx, "1")
            probe = load(folder, idx, "1")
            comps.append(Comparison("tab:probe-results", probe_name, kpi, baseline, probe))
    return comps


# ----------------------------------------------------------------------------
# MDE at 80% power, representative KPI
# ----------------------------------------------------------------------------

def compute_mde(comp: Comparison):
    """MDE for a two independent sample comparison at N (per arm) = comp's N,
    alpha=0.05 two sided, power=0.80, using the observed SE of each arm as the
    plug in estimate of the (assumed roughly equal) population SE."""
    se_diff = math.sqrt(comp.before.se ** 2 + comp.after.se ** 2)
    mde_abs = (Z95 + Z80_POWER) * se_diff
    mde_pct_of_before = 100 * mde_abs / comp.before.value if comp.before.value else float("nan")
    return se_diff, mde_abs, mde_pct_of_before


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    crn = check_crn_pairing()
    print("=" * 100)
    print("CRN pairing check (master UPPAAL seed identical between sweep arm and its reference)")
    print("=" * 100)
    for table, case, point, paired, seed_a, seed_ref in crn:
        flag = "PAIRED (same seed)" if paired else "*** NOT PAIRED (different seed) ***"
        print(f"  {table:22s} {case:10s} {point:12s} -> {flag}  (arm seed={seed_a}, ref seed={seed_ref})")
    print()

    all_comps = []
    all_comps += build_table_ci()
    all_comps += build_table_t1max()
    all_comps += build_table_shape()
    all_comps += build_table_probes()
    fb7 = build_table_prmm_l4_fb()
    all_comps += fb7

    # Group by table for FDR correction (exploratory family = one table)
    by_table = {}
    for c in all_comps:
        by_table.setdefault(c.table, []).append(c)

    rows = []
    for table, comps in by_table.items():
        pvals = []
        results = []
        for c in comps:
            diff, se_diff, lo, hi, z, p = c.diff_ci()
            old_sig = c.ci_overlap_significant()
            new_sig = c.new_significant()
            pvals.append(p)
            results.append((c, diff, se_diff, lo, hi, z, p, old_sig, new_sig))
        fdr_keep = benjamini_hochberg(pvals)
        for (c, diff, se_diff, lo, hi, z, p, old_sig, new_sig), survives in zip(results, fdr_keep):
            fdr_sig = new_sig and survives
            flip = (old_sig != new_sig)
            rows.append(dict(
                table=c.table, case=c.case, kpi=c.kpi,
                before_value=c.before.value, before_se=c.before.se, before_n=c.before.n,
                after_value=c.after.value, after_se=c.after.se, after_n=c.after.n,
                diff=diff, se_diff=se_diff, ci_diff_lo=lo, ci_diff_hi=hi, z=z, p_value=p,
                old_ci_overlap_significant=old_sig,
                new_diff_ci_significant=new_sig,
                fdr_significant=fdr_sig,
                flips_verdict=flip,
            ))

    # Write CSV
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # Print summary per table
    for table in by_table:
        trows = [r for r in rows if r["table"] == table]
        n_old_sig = sum(r["old_ci_overlap_significant"] for r in trows)
        n_new_sig = sum(r["new_diff_ci_significant"] for r in trows)
        n_fdr_sig = sum(r["fdr_significant"] for r in trows)
        n_flip = sum(r["flips_verdict"] for r in trows)
        print("=" * 100)
        print(f"TABLE: {table}  ({len(trows)} comparisons)")
        print(f"  old CI overlap significant: {n_old_sig}")
        print(f"  new diff CI significant:    {n_new_sig}")
        print(f"  new diff CI + BH FDR sig.:  {n_fdr_sig}")
        print(f"  verdict flips (old != new): {n_flip}")
        for r in trows:
            if r["flips_verdict"]:
                print(f"    FLIP: {r['case']} / {r['kpi']}: old={r['old_ci_overlap_significant']} "
                      f"new={r['new_diff_ci_significant']} (diff={r['diff']:.4g}, "
                      f"95% CI of diff=[{r['ci_diff_lo']:.4g}, {r['ci_diff_hi']:.4g}], p={r['p_value']:.4g})")
    print()

    print("=" * 100)
    print("F -> F+B, all 7 PRMM Level-4 KPIs, detail")
    print("=" * 100)
    for r in rows:
        if r["table"] == "PRMM-L4 (F->F+B)":
            print(f"  {r['kpi']:32s} before={r['before_value']:.4g} (se={r['before_se']:.4g}, n={r['before_n']})  "
                  f"after={r['after_value']:.4g} (se={r['after_se']:.4g}, n={r['after_n']})  "
                  f"diff={r['diff']:+.4g}  95% CI diff=[{r['ci_diff_lo']:.4g}, {r['ci_diff_hi']:.4g}]  "
                  f"p={r['p_value']:.4g}  old_sig={r['old_ci_overlap_significant']}  "
                  f"new_sig={r['new_diff_ci_significant']}  fdr_sig={r['fdr_significant']}")
    any_new_sig = any(r["new_diff_ci_significant"] for r in rows if r["table"] == "PRMM-L4 (F->F+B)")
    any_fdr_sig = any(r["fdr_significant"] for r in rows if r["table"] == "PRMM-L4 (F->F+B)")
    print()
    print(f"  ==> Any KPI newly significant under diff CI (uncorrected)? {any_new_sig}")
    print(f"  ==> Any KPI newly significant after BH FDR correction?     {any_fdr_sig}")
    print()

    # MDE: representative KPI/comparison = F vs F+B, "Production blocked time" (N=50 per arm, estimate query)
    print("=" * 100)
    print("Minimum Detectable Effect (MDE) at 80% power, N=50 per arm")
    print("=" * 100)
    rep = next(c for c in fb7 if c.kpi == "Production-blocked time")
    se_diff, mde_abs, mde_pct = compute_mde(rep)
    print(f"  Representative comparison: F -> F+B, Production blocked time")
    print(f"  Before: {rep.before.value:.4g} (SE={rep.before.se:.4g}, N={rep.before.n})")
    print(f"  After:  {rep.after.value:.4g} (SE={rep.after.se:.4g}, N={rep.after.n})")
    print(f"  SE_diff (independent samples) = {se_diff:.4g}")
    print(f"  MDE (80% power, alpha=0.05 two sided) = (1.96+0.8416) * SE_diff = {mde_abs:.4g} absolute units")
    print(f"  MDE as % of the 'before' point estimate = {mde_pct:.2f}%")
    print()
    print(f"Wrote detailed results to {OUT_CSV}")


if __name__ == "__main__":
    main()
