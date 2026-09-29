#!/usr/bin/env python3
"""
Matched KPI only variant of PRMM Level 4 (S4) scoring, restricted to
disruption matched KPIs per case (per the model's own [DK:*] tags), as
raised as an unresolved question in the paper's Section on S4 scoring
details ("a scoring variant restricted only to disruption matched KPIs
was not computed separately in this paper"). Reuses reconcile_prmm_l4.py's
compute_case() (identical CI overlap significance test, identical raw trace
extraction), just reaggregating the per KPI cells already computed there
into a smaller, case specific KPI subset.

KPI -> disruption key tags, read directly from the deposited UPPAAL model's
query comments (model/Supply Chain V11.4.1.xml, lines ~2119-2163):
  Q1 service_ratio:               [DK:DS][DK:QS]
  Q2 avg_lead_time:               [DK:DS][DK:FTD]
  Q3 safe_stock_recovery_time:    [DK:RS]
  Q4 latent_production_blocked:   [DK:RS]
  Q5 active_production_blocked:   [DK:RS] (also [GK:RES], general resilience)
  Q6 defect_rate:                 [DK:QS]
  Q7 stockout_duration:           [DK:FTD] (also [GK:RES])

Case -> disruption -> matched KPI subset:
  R -> R+E        (Raw Shortage, RS)     -> Q3, Q4, Q5
  D -> D+E,S      (Demand Shock, DS)     -> Q1, Q2
  F -> F+B        (Transport Delay, FTD) -> Q2, Q7
  Full portfolio  (RS+DS+QS+FTD, all)    -> Q1-Q7 (all 7; identical to the
                                             uniform KPI set result already
                                             reported in Table tab:prmm-l4)
"""
from __future__ import annotations
from reconcile_prmm_l4 import compute_case, CASES, KPI_CATALOGUE

MATCHED_KPIS = {
    "R -> R+E": ["Q3", "Q4", "Q5"],
    "D -> D+E,S": ["Q1", "Q2"],
    "F -> F+B": ["Q2", "Q7"],
    "Full portfolio": ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7"],
}


def matched_only(case_name: str):
    full = compute_case(case_name)
    keep_ids = set(MATCHED_KPIS[case_name])
    kpis = [k for k in full.kpis if k.kpi_id in keep_ids]
    n = len(kpis)
    avg_strength = sum(k.strength for k in kpis) / n
    s4_strength_pct = avg_strength / 5.0 * 100.0
    coverage_pct = sum(1 for k in kpis if k.passes_coverage) / n * 100.0
    s4_final = 0.5 * coverage_pct + 0.5 * s4_strength_pct
    return kpis, avg_strength, s4_strength_pct, coverage_pct, s4_final


if __name__ == "__main__":
    print(f"{'Case':16} {'N_matched':10} {'AvgStr':8} {'S4_strength%':13} {'Coverage%':10} {'S4_final%':10}")
    for case in CASES:
        kpis, avg_s, s4s, cov, s4f = matched_only(case)
        print(f"{case:16} {len(kpis):10} {avg_s:8.3f} {s4s:13.1f} {cov:10.1f} {s4f:10.1f}")
        for k in kpis:
            print(f"    {k.kpi_id} {k.label:36} pct={k.improvement_pct:7.2f} class={k.classification:28} str={k.strength}")
