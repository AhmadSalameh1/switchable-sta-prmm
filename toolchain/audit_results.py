#!/usr/bin/env python3
"""Independent audit of the switchable-STA-PRMM SMC results.

WHAT THIS SCRIPT DOES
----------------------
1. Reimplements (verbatim, regex for regex) the raw trace parsing logic from
   `toolchain/uppaal_query_runner_gui_v3_PRMM_dual_scoring.py` --
   `PROB_RE`, `EST_RE`, `EST_APPROX_RE`, `SEED_RE`, `parse_probability()`,
   `parse_estimate()`, `parse_trace()` -- so every raw `verifyta` .txt trace
   file under `results/raw_traces/` can be reparsed completely independently
   of the GUI (which needs a Tkinter display we don't have here), using the
   exact same rules that produced the numbers in the paper and in the
   existing `*_values.csv` files. This deliberately rederives the point
   estimate and 95% CI for every query in every scenario folder from the raw
   text, rather than trusting any existing CSV.

2. Cross checks the freshly reparsed numbers against every existing
   `*_values.csv` file sitting next to the raw traces (this revalidates that
   the two known historical parser bugs -- discarded CI margins, and
   deterministic "~"-format values silently exported as 0 -- are not present
   anywhere in the currently committed CSVs).

3. Extracts every numeric claim from four tables in the paper draft
   (`tab:ci`, `tab:probe-results`, `tab:sensitivity-t1max`,
   `tab:sensitivity-shape`) with a small regex based LaTeX table parser (not
   hand transcription), maps each row to the raw trace folder(s) it was
   computed from, and flags any mismatch between the paper's stated value/CI
   and the value/CI recomputed here from the raw traces.

4. Independently reruns the paper's own significance criterion -- two 95%
   CIs are "significant"/"different" if and only if they do not overlap --
   for every comparison the paper labels significant or not (the tab:ci
   before/after pairs, the tab:probe-results probe versus baseline pairs, and the
   two sensitivity sweep tables' sweep versus reference pairs), and flags any
   disagreement with the paper's stated verdict (asterisks in the sweep/probe
   tables, and the tab:ci prose paragraph).

Nothing is written back to any results CSV, the model file, or the paper. The
only output is a report printed to stdout, structured so `results/AUDIT_REPORT.md`
can be built directly from it (see `toolchain/run_audit.sh`-style usage in the
project README / task instructions -- this script itself only audits and
prints; assembling the .md file is a separate, explicit step so this script
stays a pure, side effect free auditor).

Usage:
    python3 audit_results.py [--repo PATH] [--paper PATH]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ===========================================================================
# 1. PARSING LOGIC -- copied verbatim from
#    toolchain/uppaal_query_runner_gui_v3_PRMM_dual_scoring.py (lines ~38-376)
#    Comments below the regexes reproduce that file's own comments about the
#    two historical bugs, so the regression coverage is traceable to source.
# ===========================================================================

PROB_RE = re.compile(
    r"\((?P<success>\d+)\/(?P<runs>\d+) runs\)\s+Pr\((?P<formula>.*?)\)\s+in\s+"
    r"\[(?P<low>[-+0-9.eE]+),(?P<high>[-+0-9.eE]+)\]\s+\((?P<ci_pct>[^)]+)\)",
    re.IGNORECASE,
)

EST_RE = re.compile(
    r"\((?P<runs>\d+) runs\)\s+E\((?P<stat>.*?)\)\s*=\s*"
    r"(?P<value>[-+0-9.eE]+)\s+±\s+(?P<err>[-+0-9.eE]+)\s+\((?P<ci_pct>[^)]+)\)",
    re.IGNORECASE,
)

EST_APPROX_RE = re.compile(
    r"(?:\((?P<runs>\d+) runs\)\s+)?E\((?P<stat>.*?)\)\s*=\s*(?:≈\s*)?"
    r"(?P<value>[-+0-9.eE]+)(?:\s+±\s+(?P<err>[-+0-9.eE]+))?",
    re.IGNORECASE,
)

SEED_RE = re.compile(r"Seed is (?P<seed>\d+)", re.IGNORECASE)


@dataclass
class ParsedTrace:
    query_name: str
    value: str
    runs: str = ""
    ci_low: str = ""
    ci_high: str = ""
    trace_file: str = ""
    seed: str = ""

    @property
    def value_f(self) -> Optional[float]:
        try:
            return float(self.value)
        except (TypeError, ValueError):
            return None

    @property
    def ci_low_f(self) -> Optional[float]:
        try:
            return float(self.ci_low)
        except (TypeError, ValueError):
            return None

    @property
    def ci_high_f(self) -> Optional[float]:
        try:
            return float(self.ci_high)
        except (TypeError, ValueError):
            return None


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def parse_probability(text: str) -> Optional[ParsedTrace]:
    match = PROB_RE.search(text)
    if not match:
        return None

    success = int(match.group("success"))
    runs = int(match.group("runs"))
    low = match.group("low")
    high = match.group("high")

    try:
        probability = success / runs if runs else 0.0
        value = f"{probability:.6f}".rstrip("0").rstrip(".")
    except Exception:
        value = f"{success}/{runs}"

    return ParsedTrace(
        query_name="probability query",
        value=value,
        runs=str(runs),
        ci_low=low,
        ci_high=high,
    )


def parse_estimate(text: str) -> Optional[ParsedTrace]:
    match = EST_RE.search(text)
    if match:
        runs = match.group("runs")
        value = match.group("value").strip()

        # Bug #1 (fixed 2026-08-12): the `err` group -- the +/- margin verifyta
        # reports for estimate queries -- was captured by the regex but never
        # read when building the result, so ci_low/ci_high were always left
        # empty for every estimate type query. Regression covered by
        # test_audit_results.py::test_normal_estimate_with_margin.
        ci_low = ""
        ci_high = ""
        try:
            value_f = float(value)
            err_f = float(match.group("err"))
            ci_low = f"{value_f - err_f:.6g}"
            ci_high = f"{value_f + err_f:.6g}"
        except (TypeError, ValueError):
            pass

        return ParsedTrace(
            query_name="estimate query",
            value=value,
            runs=runs,
            ci_low=ci_low,
            ci_high=ci_high,
        )

    # Bug #2 (fixed 2026-08-14): verifyta reports deterministic / degenerate
    # estimate queries in a different format with no +/- margin at all, e.g.
    # "(50 runs) E(min) = ~ 100" instead of "... = 100 +/- 0.45 (95% CI)".
    # EST_RE requires the +/- margin and never matches these lines; the old
    # code returned None here and the caller fell back to a hardcoded '0',
    # silently corrupting any nonzero deterministic value. Regression covered
    # by test_audit_results.py::test_deterministic_value_no_margin.
    approx_match = EST_APPROX_RE.search(text)
    if not approx_match:
        return None

    runs = approx_match.group("runs") or ""
    value = approx_match.group("value").strip()

    ci_low = ""
    ci_high = ""
    err_group = approx_match.group("err")
    try:
        value_f = float(value)
        if err_group is not None:
            err_f = float(err_group)
            ci_low = f"{value_f - err_f:.6g}"
            ci_high = f"{value_f + err_f:.6g}"
        else:
            # No +/- margin means verifyta observed zero variance across all
            # runs: the value itself is the exact, deterministic result.
            ci_low = f"{value_f:.6g}"
            ci_high = f"{value_f:.6g}"
    except (TypeError, ValueError):
        pass

    return ParsedTrace(
        query_name="estimate query",
        value=value,
        runs=runs,
        ci_low=ci_low,
        ci_high=ci_high,
    )


def clean_query_name_from_filename(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"_\d+$", "", stem)
    stem = re.sub(r"^\d+_", "", stem)
    stem = stem.replace("__", "_")
    pretty = stem.replace("_", " ").strip()
    return pretty or path.stem


def parse_trace(path: Path) -> ParsedTrace:
    text = read_text(path)
    parsed = parse_probability(text) or parse_estimate(text)
    if parsed is None:
        lower = text.lower()
        value = "Run Fail" if ("error" in lower or "failed" in lower) else "0"
        parsed = ParsedTrace(
            query_name=clean_query_name_from_filename(path),
            value=value,
            runs="",
            ci_low="",
            ci_high="",
        )
    else:
        parsed.query_name = clean_query_name_from_filename(path)

    seed_match = SEED_RE.search(text)
    if seed_match:
        parsed.seed = seed_match.group("seed")

    parsed.trace_file = str(path)
    return parsed


# ===========================================================================
# 2. RAW TRACE DISCOVERY
# ===========================================================================

TRACE_FILENAME_RE = re.compile(r"^(?P<index>\d{3})_.*_(?P<suffix>\d+)\.txt$")

# The four "load bearing KPIs" used throughout the paper, keyed by the
# 3-digit query index prefix used in every raw trace filename (verified by
# inspecting the trace text directly -- see AUDIT_REPORT.md's "KPI index
# verification" section for the check that pins each index to a KPI name).
KPI_INDEX = {
    "003": "Safe stock recovery time",
    "005": "Active production blocked time",
    "007": "Stockout duration",
    "012": "Minimum availability",
}


def discover_traces(folder: Path) -> Dict[str, Dict[str, ParsedTrace]]:
    """Return {query_index: {suffix: ParsedTrace}} for every .txt trace file
    directly inside `folder` (nonrecursive)."""
    out: Dict[str, Dict[str, ParsedTrace]] = {}
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.txt")):
        m = TRACE_FILENAME_RE.match(path.name)
        if not m:
            continue
        index = m.group("index")
        suffix = m.group("suffix")
        out.setdefault(index, {})[suffix] = parse_trace(path)
    return out


def kpi_value(folder_traces: Dict[str, Dict[str, ParsedTrace]], kpi_index: str,
              suffix: Optional[str] = None) -> Optional[ParsedTrace]:
    """Return the ParsedTrace for a KPI index in a folder that has exactly one
    suffix (the common case for the 11 main scenarios and 4 probes), or for a
    specific requested suffix."""
    by_suffix = folder_traces.get(kpi_index, {})
    if suffix is not None:
        return by_suffix.get(suffix)
    if len(by_suffix) == 1:
        return next(iter(by_suffix.values()))
    return None


# ===========================================================================
# 3. LATEX TABLE EXTRACTION
# ===========================================================================

def load_tex(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def extract_tabular_body(tex: str, label: str) -> str:
    """Return the raw text between the nearest preceding \\begin{tabular} and
    the matching \\end{tabular} for a given \\label{...}."""
    label_pos = tex.index(r"\label{%s}" % label)
    tab_start = tex.rindex(r"\begin{tabular}", 0, label_pos)
    tab_end = tex.index(r"\end{tabular}", tab_start)
    return tex[tab_start:tab_end]


CELL_RE = re.compile(
    r"\\\(\s*(?P<value>[-+0-9.]+)\s*(?:\\pm\s*(?P<err>[-+0-9.]+))?\s*\\\)"
    r"(?P<sig>\\textsuperscript\{\*\})?"
)


def parse_cell(cell: str) -> Optional[Tuple[float, Optional[float], bool]]:
    """Parse a table cell like '\\(214.62 \\pm 21.85\\)' or '\\(0.00\\)',
    optionally followed by '\\textsuperscript{*}'. Returns
    (value, margin_or_None, significant_flag)."""
    m = CELL_RE.search(cell)
    if not m:
        return None
    value = float(m.group("value"))
    err = float(m.group("err")) if m.group("err") is not None else None
    sig = m.group("sig") is not None
    return (value, err, sig)


def strip_latex_wrappers(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\\textbf\{(.*)\}$", r"\1", s)
    s = s.replace(r"\to", "->").replace(r"\(", "").replace(r"\)", "")
    s = s.replace("$", "")
    return s.strip()


def split_row(line: str) -> List[str]:
    line = line.strip()
    if line.endswith(r"\\"):
        line = line[:-2]
    return [c.strip() for c in line.split("&")]


@dataclass
class CIRow:
    case: str
    kpi: str
    before: Tuple[float, Optional[float], bool]
    after: Tuple[float, Optional[float], bool]


def extract_tab_ci(tex: str) -> List[CIRow]:
    body = extract_tabular_body(tex, "tab:ci")
    rows: List[CIRow] = []
    current_case = None
    for raw_line in body.splitlines():
        line = raw_line.strip()
        m = re.match(r"\\multirow\{\d+\}\{\*\}\{(.+)\}\s*$", line)
        if m:
            current_case = strip_latex_wrappers(m.group(1))
            continue
        if line.startswith("&") and current_case:
            cells = split_row(line)
            if len(cells) < 4:
                continue
            kpi = strip_latex_wrappers(cells[1])
            before = parse_cell(cells[2])
            after = parse_cell(cells[3])
            if before is None or after is None:
                continue
            rows.append(CIRow(current_case, kpi, before, after))
    return rows


@dataclass
class ProbeRow:
    kpi: str
    baseline: Tuple[float, Optional[float], bool]
    probe_name: str
    probe: Tuple[float, Optional[float], bool]


def extract_tab_probe_results(tex: str) -> List[ProbeRow]:
    body = extract_tabular_body(tex, "tab:probe-results")
    rows: List[ProbeRow] = []
    current_cols: Optional[List[str]] = None
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line in (r"\toprule", r"\midrule", r"\bottomrule"):
            continue
        if line.startswith(r"\textbf{KPI}"):
            cells = split_row(line)
            current_cols = [strip_latex_wrappers(c) for c in cells]
            continue
        if current_cols is None:
            continue
        cells = split_row(line)
        if len(cells) < 4:
            continue
        kpi = strip_latex_wrappers(cells[0])
        baseline = parse_cell(cells[1])
        probe1 = parse_cell(cells[2])
        probe2 = parse_cell(cells[3])
        if baseline is None or probe1 is None or probe2 is None:
            continue
        rows.append(ProbeRow(kpi, baseline, current_cols[2], probe1))
        rows.append(ProbeRow(kpi, baseline, current_cols[3], probe2))
    return rows


@dataclass
class SweepRow:
    subcase: str
    kpi: str
    low: Tuple[float, Optional[float], bool]
    ref: Tuple[float, Optional[float], bool]
    high: Tuple[float, Optional[float], bool]


def extract_sweep_table(tex: str, label: str) -> List[SweepRow]:
    body = extract_tabular_body(tex, label)
    rows: List[SweepRow] = []
    current_sub = None
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line in (r"\toprule", r"\midrule", r"\bottomrule"):
            continue
        m = re.match(r"\\multicolumn\{4\}\{l\}\{\\emph\{(.+)\}\}", line)
        if m:
            current_sub = strip_latex_wrappers(m.group(1))
            continue
        if line.startswith(r"\textbf{KPI}") or "\\textbf{shape}" in line or line.startswith(r"\textbf"):
            # header row -- skip (columns are fixed per table)
            continue
        if current_sub is None:
            continue
        cells = split_row(line)
        if len(cells) < 4:
            continue
        kpi = strip_latex_wrappers(cells[0])
        low = parse_cell(cells[1])
        ref = parse_cell(cells[2])
        high = parse_cell(cells[3])
        if low is None or ref is None or high is None:
            continue
        rows.append(SweepRow(current_sub, kpi, low, ref, high))
    return rows


# ===========================================================================
# 4. CI OVERLAP SIGNIFICANCE TEST
# ===========================================================================

def ci_bounds(value: float, err: Optional[float]) -> Tuple[float, float]:
    if err is None:
        return (value, value)
    return (value - err, value + err)


def overlaps(a: Tuple[float, float], b: Tuple[float, float]) -> bool:
    a_lo, a_hi = min(a), max(a)
    b_lo, b_hi = min(b), max(b)
    return a_lo <= b_hi and b_lo <= a_hi


def significant(a: Tuple[float, Optional[float]], b: Tuple[float, Optional[float]]) -> bool:
    """True iff the two CIs do NOT overlap (the paper's stated criterion)."""
    a_val, a_err = a
    b_val, b_err = b
    return not overlaps(ci_bounds(a_val, a_err), ci_bounds(b_val, b_err))


# ===========================================================================
# 5. FOLDER MAPS -- ties paper case labels to results/raw_traces/ folder names
# ===========================================================================

def build_folder_maps(raw_traces_dir: Path) -> Dict[str, Path]:
    names = [
        "Supply Chain V11.4.1_queries_traces baseline",
        "Supply Chain V11.4.1_queries_traces R",
        "Supply Chain V11.4.1_queries_traces D",
        "Supply Chain V11.4.1_queries_traces Q",
        "Supply Chain V11.4.1_queries_traces F",
        "Supply Chain V11.4.1_queries_traces R + E",
        "Supply Chain V11.4.1_queries_traces D + E,S",
        "Supply Chain V11.4.1_queries_traces F + B",
        "Supply Chain V11.4.1_queries_traces R,Q + E",
        "Supply Chain V11.4.1_queries_traces R,D,Q,F",
        "Supply Chain V11.4.1_queries_traces R,D,Q,F + E,A,S,B",
        "Supply Chain V11.4.1_PE_queries_traces",
        "Supply Chain V11.4.1_PA_queries_traces",
        "Supply Chain V11.4.1_PS_queries_traces",
        "Supply Chain V11.4.1_PB_queries_traces",
        "Supply Chain V11.4.1_baseline_queries_traces",
        "Supply Chain V11.4.1_DR_PE_queries_traces",
        "Supply Chain V11.4.1_DD_queries_traces",
        "Supply Chain V11.4.1_DD_PE_PS_queries_traces",
    ]
    out = {}
    for n in names:
        p = raw_traces_dir / n
        out[n] = p
        if not p.is_dir():
            print(f"WARNING: expected raw trace folder not found: {p}", file=sys.stderr)
    return out


CI_CASE_FOLDERS = {
    "R -> R+E": ("Supply Chain V11.4.1_queries_traces R", "Supply Chain V11.4.1_queries_traces R + E"),
    "D -> D+E,S": ("Supply Chain V11.4.1_queries_traces D", "Supply Chain V11.4.1_queries_traces D + E,S"),
    "F -> F+B": ("Supply Chain V11.4.1_queries_traces F", "Supply Chain V11.4.1_queries_traces F + B"),
    "R,D,Q,F -> +E,A,S,B": ("Supply Chain V11.4.1_queries_traces R,D,Q,F", "Supply Chain V11.4.1_queries_traces R,D,Q,F + E,A,S,B"),
}

PROBE_FOLDERS = {
    "Baseline": "Supply Chain V11.4.1_queries_traces baseline",
    "E without R": "Supply Chain V11.4.1_PE_queries_traces",
    "A without R": "Supply Chain V11.4.1_PA_queries_traces",
    "S without D": "Supply Chain V11.4.1_PS_queries_traces",
    "B without F": "Supply Chain V11.4.1_PB_queries_traces",
}

T1MAX_SWEEP = {
    "Baseline (unmitigated)": ("Supply Chain V11.4.1_queries_traces baseline", "Supply Chain V11.4.1_baseline_queries_traces"),
    "R+E (matched mitigation)": ("Supply Chain V11.4.1_queries_traces R + E", "Supply Chain V11.4.1_DR_PE_queries_traces"),
}

SHAPE_SWEEP = {
    "D (unmitigated)": ("Supply Chain V11.4.1_queries_traces D", "Supply Chain V11.4.1_DD_queries_traces"),
    "D+E,S (matched mitigation)": ("Supply Chain V11.4.1_queries_traces D + E,S", "Supply Chain V11.4.1_DD_PE_PS_queries_traces"),
}


# ===========================================================================
# 6. AUDIT LOGIC
# ===========================================================================

TOL_ABS = 0.02     # absolute tolerance for value/margin comparisons (rounding)
TOL_REL = 0.002    # relative tolerance (0.2%) on top of the absolute one


def close(a: float, b: float) -> bool:
    return abs(a - b) <= max(TOL_ABS, TOL_REL * max(abs(a), abs(b)))


@dataclass
class Finding:
    table: str
    location: str
    kind: str          # "value_mismatch" | "significance_mismatch" | "ok" | "csv_mismatch" | "parse_note"
    detail: str


def audit_tab_ci(tex: str, folders: Dict[str, Path], findings: List[Finding],
                  parsed_cache: Dict[str, Dict[str, Dict[str, ParsedTrace]]]) -> None:
    rows = extract_tab_ci(tex)
    if not rows:
        findings.append(Finding("tab:ci", "-", "parse_note", "Could not extract any rows from tab:ci -- LaTeX structure may have changed."))
        return
    for row in rows:
        case_folders = CI_CASE_FOLDERS.get(row.case)
        if case_folders is None:
            findings.append(Finding("tab:ci", row.case, "parse_note", f"No folder mapping for case '{row.case}' -- check CI_CASE_FOLDERS."))
            continue
        before_folder, after_folder = case_folders
        kpi_idx = next((idx for idx, name in KPI_INDEX.items() if name == row.kpi), None)
        if kpi_idx is None:
            findings.append(Finding("tab:ci", f"{row.case} / {row.kpi}", "parse_note", "KPI name did not match KPI_INDEX map."))
            continue

        for folder_name, claimed, label in ((before_folder, row.before, "before"), (after_folder, row.after, "after")):
            traces = parsed_cache.setdefault(folder_name, discover_traces(folders[folder_name]))
            pt = kpi_value(traces, kpi_idx)
            loc = f"{row.case} / {row.kpi} / {label}"
            if pt is None or pt.value_f is None:
                findings.append(Finding("tab:ci", loc, "parse_note", f"Could not obtain a single reparsed value from {folder_name} (ambiguous or missing suffix)."))
                continue
            claimed_val, claimed_err, _sig = claimed
            actual_val = pt.value_f
            actual_err = None
            if pt.ci_low_f is not None and pt.ci_high_f is not None:
                actual_err = (pt.ci_high_f - pt.ci_low_f) / 2.0
            ok_val = close(claimed_val, actual_val)
            ok_err = (claimed_err is None and (actual_err is None or actual_err < 1e-9)) or \
                     (claimed_err is not None and actual_err is not None and close(claimed_err, actual_err))
            if ok_val and ok_err:
                findings.append(Finding("tab:ci", loc, "ok", f"paper={claimed_val}±{claimed_err} matches reparsed {actual_val}±{actual_err} (file: {pt.trace_file})"))
            else:
                findings.append(Finding(
                    "tab:ci", loc, "value_mismatch",
                    f"paper claims {claimed_val} ± {claimed_err}, reparsed raw trace gives {actual_val} ± {actual_err} "
                    f"(file: {pt.trace_file})"))

    # Significance paragraph: R->R+E, D->D+E,S, R,D,Q,F->+E,A,S,B all significant;
    # F->F+B all not significant, per Section 5 "Formal significance criterion".
    expected_sig = {
        "R -> R+E": True,
        "D -> D+E,S": True,
        "F -> F+B": False,
        "R,D,Q,F -> +E,A,S,B": True,
    }
    for row in rows:
        exp = expected_sig.get(row.case)
        if exp is None:
            continue
        b_val, b_err, _ = row.before
        a_val, a_err, _ = row.after
        actual_sig = significant((b_val, b_err), (a_val, a_err))
        loc = f"{row.case} / {row.kpi} (significance, from paper's own printed CIs)"
        if actual_sig == exp:
            findings.append(Finding("tab:ci-significance", loc, "ok", f"expected {'significant' if exp else 'not significant'}, recomputed CI-overlap test agrees"))
        else:
            findings.append(Finding("tab:ci-significance", loc, "significance_mismatch",
                                     f"paper's prose claims {'significant' if exp else 'not significant'} for this case, "
                                     f"but the CI-overlap test on the paper's own printed before/after CIs gives "
                                     f"{'significant' if actual_sig else 'not significant'}"))


def audit_tab_probe_results(tex: str, folders: Dict[str, Path], findings: List[Finding],
                             parsed_cache: Dict[str, Dict[str, Dict[str, ParsedTrace]]]) -> None:
    rows = extract_tab_probe_results(tex)
    if not rows:
        findings.append(Finding("tab:probe-results", "-", "parse_note", "Could not extract any rows -- LaTeX structure may have changed."))
        return
    baseline_folder = PROBE_FOLDERS["Baseline"]
    for row in rows:
        probe_folder = PROBE_FOLDERS.get(row.probe_name)
        if probe_folder is None:
            findings.append(Finding("tab:probe-results", f"{row.kpi} / {row.probe_name}", "parse_note", "No folder mapping for probe name."))
            continue
        kpi_idx = next((idx for idx, name in KPI_INDEX.items() if name == row.kpi), None)
        if kpi_idx is None:
            findings.append(Finding("tab:probe-results", f"{row.kpi} / {row.probe_name}", "parse_note", "KPI name mismatch."))
            continue

        for folder_name, claimed, label in ((baseline_folder, row.baseline, "baseline"), (probe_folder, row.probe, row.probe_name)):
            traces = parsed_cache.setdefault(folder_name, discover_traces(folders[folder_name]))
            pt = kpi_value(traces, kpi_idx)
            loc = f"{row.kpi} / {label}"
            if pt is None or pt.value_f is None:
                findings.append(Finding("tab:probe-results", loc, "parse_note", f"Could not obtain reparsed value from {folder_name}."))
                continue
            claimed_val, claimed_err, _sig = claimed
            actual_val = pt.value_f
            actual_err = (pt.ci_high_f - pt.ci_low_f) / 2.0 if pt.ci_low_f is not None and pt.ci_high_f is not None else None
            ok_val = close(claimed_val, actual_val)
            ok_err = (claimed_err is None and (actual_err is None or actual_err < 1e-9)) or \
                     (claimed_err is not None and actual_err is not None and close(claimed_err, actual_err))
            if ok_val and ok_err:
                findings.append(Finding("tab:probe-results", loc, "ok", f"paper={claimed_val}±{claimed_err} matches reparsed {actual_val}±{actual_err}"))
            else:
                findings.append(Finding("tab:probe-results", loc, "value_mismatch",
                                         f"paper claims {claimed_val} ± {claimed_err}, reparsed gives {actual_val} ± {actual_err} (file: {pt.trace_file})"))

        # significance check: baseline vs probe, using the paper's own printed cells
        b_val, b_err, _ = row.baseline
        p_val, p_err, p_sig_claimed = row.probe
        actual_sig = significant((b_val, b_err), (p_val, p_err))
        loc = f"{row.kpi} / {row.probe_name} (significance)"
        if actual_sig == p_sig_claimed:
            findings.append(Finding("tab:probe-results-significance", loc, "ok",
                                     f"paper marks {'*' if p_sig_claimed else 'no marker'}, CI-overlap test agrees ({'significant' if actual_sig else 'not significant'})"))
        else:
            findings.append(Finding("tab:probe-results-significance", loc, "significance_mismatch",
                                     f"paper marks {'significant (*)' if p_sig_claimed else 'not significant (no marker)'}, "
                                     f"but CI-overlap test on paper's own printed CIs gives {'significant' if actual_sig else 'not significant'}"))


def audit_sweep_table(tex: str, label: str, folder_map: Dict[str, Tuple[str, str]],
                       folders: Dict[str, Path], findings: List[Finding],
                       parsed_cache: Dict[str, Dict[str, Dict[str, ParsedTrace]]],
                       table_name: str) -> None:
    rows = extract_sweep_table(tex, label)
    if not rows:
        findings.append(Finding(table_name, "-", "parse_note", "Could not extract any rows -- LaTeX structure may have changed."))
        return
    for row in rows:
        pair = folder_map.get(row.subcase)
        if pair is None:
            findings.append(Finding(table_name, f"{row.subcase} / {row.kpi}", "parse_note", "No folder mapping for sub-case label."))
            continue
        ref_folder, sweep_folder = pair
        kpi_idx = next((idx for idx, name in KPI_INDEX.items() if name == row.kpi), None)
        if kpi_idx is None:
            findings.append(Finding(table_name, f"{row.subcase} / {row.kpi}", "parse_note", "KPI name mismatch."))
            continue

        ref_traces = parsed_cache.setdefault(ref_folder, discover_traces(folders[ref_folder]))
        ref_pt = kpi_value(ref_traces, kpi_idx)
        loc_ref = f"{row.subcase} / {row.kpi} / ref"
        if ref_pt is None or ref_pt.value_f is None:
            findings.append(Finding(table_name, loc_ref, "parse_note", f"Could not obtain reparsed reference value from {ref_folder}."))
            continue
        claimed_val, claimed_err, _ = row.ref
        actual_err = (ref_pt.ci_high_f - ref_pt.ci_low_f) / 2.0 if ref_pt.ci_low_f is not None and ref_pt.ci_high_f is not None else None
        if close(claimed_val, ref_pt.value_f) and ((claimed_err is None and (actual_err is None or actual_err < 1e-9)) or (claimed_err is not None and actual_err is not None and close(claimed_err, actual_err))):
            findings.append(Finding(table_name, loc_ref, "ok", f"reference matches: paper {claimed_val}±{claimed_err} == reparsed {ref_pt.value_f}±{actual_err}"))
        else:
            findings.append(Finding(table_name, loc_ref, "value_mismatch",
                                     f"paper reference claims {claimed_val} ± {claimed_err}, reparsed {ref_folder} gives {ref_pt.value_f} ± {actual_err}"))

        # The sweep folder holds 2 extra runs (the two nonreference sweep
        # points) whose trace file numeric _N suffix is NOT a reliable
        # parameter value key across folders (verified by direct inspection:
        # e.g. suffix "_1" is the low sweep point in the baseline T1_MAX
        # sweep folder, but suffix "_2" is the low point in the R+E T1_MAX
        # sweep folder -- these are a per folder run counter, not a global
        # parameter value code). We therefore identify
        # "low" vs "high" by nearest value assignment against the paper's own
        # claimed low/high cells, trying both permutations of the two sweep
        # files and keeping whichever assignment minimizes total error - then
        # flagging a mismatch if even the best assignment doesn't fit within
        # tolerance.
        sweep_traces = parsed_cache.setdefault(sweep_folder, discover_traces(folders[sweep_folder]))
        by_suffix = sweep_traces.get(kpi_idx, {})
        candidates = [(suf, pt) for suf, pt in by_suffix.items() if pt.value_f is not None]
        if len(candidates) != 2:
            findings.append(Finding(table_name, f"{row.subcase} / {row.kpi} / sweep",
                                     "parse_note", f"Expected exactly 2 non-reference sweep trace files in {sweep_folder} for query {kpi_idx}, found {len(candidates)}."))
            continue

        (suf_a, pt_a), (suf_b, pt_b) = candidates
        low_val, low_err, low_sig = row.low
        high_val, high_err, high_sig = row.high

        def err_of(pt: ParsedTrace) -> Optional[float]:
            return (pt.ci_high_f - pt.ci_low_f) / 2.0 if pt.ci_low_f is not None and pt.ci_high_f is not None else None

        def score(pt_low: ParsedTrace, pt_high: ParsedTrace) -> float:
            e_low = err_of(pt_low) or 0.0
            e_high = err_of(pt_high) or 0.0
            return abs(pt_low.value_f - low_val) + abs(pt_high.value_f - high_val) + \
                   abs(e_low - (low_err or 0.0)) + abs(e_high - (high_err or 0.0))

        score_ab = score(pt_a, pt_b)   # a=low, b=high
        score_ba = score(pt_b, pt_a)   # b=low, a=high
        if score_ab <= score_ba:
            assigned_low, assigned_high = pt_a, pt_b
            assigned_low_suf, assigned_high_suf = suf_a, suf_b
        else:
            assigned_low, assigned_high = pt_b, pt_a
            assigned_low_suf, assigned_high_suf = suf_b, suf_a

        for label_txt, claimed_v, claimed_e, claimed_sig, pt, suf in (
            ("low", low_val, low_err, low_sig, assigned_low, assigned_low_suf),
            ("high", high_val, high_err, high_sig, assigned_high, assigned_high_suf),
        ):
            loc = f"{row.subcase} / {row.kpi} / {label_txt} (matched to suffix _{suf})"
            actual_e = err_of(pt)
            ok_val = close(claimed_v, pt.value_f)
            ok_err = (claimed_e is None and (actual_e is None or actual_e < 1e-9)) or \
                     (claimed_e is not None and actual_e is not None and close(claimed_e, actual_e))
            if ok_val and ok_err:
                findings.append(Finding(table_name, loc, "ok", f"paper {claimed_v}±{claimed_e} matches reparsed {pt.value_f}±{actual_e} (file: {pt.trace_file})"))
            else:
                findings.append(Finding(table_name, loc, "value_mismatch",
                                         f"paper claims {claimed_v} ± {claimed_e}, best-matched raw trace ({pt.trace_file}) reparses to {pt.value_f} ± {actual_e}"))

            # significance vs reference
            actual_sig = significant((claimed_v, claimed_e), (row.ref[0], row.ref[1]))
            # NB: also recompute using the *reparsed* values (independent of
            # whether the paper's printed cell itself is right), for a fully
            # from raw data significance check.
            actual_sig_from_raw = significant((pt.value_f, actual_e), (ref_pt.value_f, actual_err))
            sigloc = f"{row.subcase} / {row.kpi} / {label_txt} (significance)"
            if actual_sig == claimed_sig and actual_sig_from_raw == claimed_sig:
                findings.append(Finding(table_name + "-significance", sigloc, "ok",
                                         f"paper marks {'*' if claimed_sig else 'no marker'}; CI-overlap on both paper cells and raw-reparsed cells agrees"))
            else:
                findings.append(Finding(table_name + "-significance", sigloc, "significance_mismatch",
                                         f"paper marks {'significant (*)' if claimed_sig else 'not significant (no marker)'}; "
                                         f"CI-overlap on paper's printed cells = {'significant' if actual_sig else 'not significant'}, "
                                         f"CI-overlap on raw-reparsed cells = {'significant' if actual_sig_from_raw else 'not significant'}"))


# ===========================================================================
# 7. CROSS CHECK AGAINST EXISTING *_values.csv FILES
# ===========================================================================

def audit_existing_csvs(raw_traces_dir: Path, findings: List[Finding]) -> None:
    """For every folder that has its own '*_queries_values.csv' sitting next
    to the raw traces, compare each CSV row's trace_file, value, ci_low,
    ci_high against a fresh reparse of that exact trace file. Historically
    this is where a stale/buggy CSV would be caught even if it doesn't
    directly feed a paper table."""
    for folder in sorted(raw_traces_dir.iterdir()):
        if not folder.is_dir():
            continue
        csvs = list(folder.glob("*_queries_values.csv"))
        for csv_path in csvs:
            with csv_path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    trace_file = row.get("trace_file", "")
                    if not trace_file:
                        continue
                    trace_path = (csv_path.parent / trace_file).resolve() if not Path(trace_file).is_absolute() else Path(trace_file)
                    if not trace_path.is_file():
                        # trace_file paths recorded on another machine (e.g.
                        # /Users/ahmadsalameh/... ) won't resolve here --
                        # fall back to matching by filename within the folder.
                        candidate = folder / Path(trace_file).name
                        trace_path = candidate if candidate.is_file() else None
                    if trace_path is None or not trace_path.is_file():
                        findings.append(Finding("csv-cross-check", f"{csv_path.name}:{row.get('query_name','?')}",
                                                 "parse_note", f"Could not locate trace file '{trace_file}' referenced by CSV to reparse it."))
                        continue
                    fresh = parse_trace(trace_path)
                    mismatches = []
                    for field_name in ("value", "ci_low", "ci_high"):
                        old = (row.get(field_name) or "").strip()
                        new = (getattr(fresh, field_name) or "").strip()
                        if old == new:
                            continue
                        try:
                            if old != "" and new != "" and close(float(old), float(new)):
                                continue
                        except ValueError:
                            pass
                        mismatches.append(f"{field_name}: csv='{old}' reparsed='{new}'")
                    loc = f"{csv_path.relative_to(raw_traces_dir)} :: {row.get('query_name', '?')}"
                    if mismatches:
                        findings.append(Finding("csv-cross-check", loc, "csv_mismatch", "; ".join(mismatches)))
                    else:
                        findings.append(Finding("csv-cross-check", loc, "ok", "CSV matches fresh reparse of its own trace file"))


# ===========================================================================
# 8. MAIN
# ===========================================================================

def find_default_paper(repo: Path) -> Optional[Path]:
    candidates = [
        repo.parent / "outputs" / "Paper1_Draft_Sections.tex",
        repo.parent / "Paper1_Draft" / "Paper1_Draft_Sections.tex",
        repo / "Paper1_Draft_Sections.tex",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent,
                     help="Path to the switchable-sta-prmm repo root (default: parent of toolchain/)")
    ap.add_argument("--paper", type=Path, default=None,
                     help="Path to Paper1_Draft_Sections.tex (default: auto-detected near --repo)")
    ap.add_argument("--csv-cross-check", action="store_true",
                     help="Also cross-check every existing *_queries_values.csv against a fresh reparse of its own trace files")
    args = ap.parse_args()

    repo = args.repo
    raw_traces_dir = repo / "results" / "raw_traces"
    paper_path = args.paper or find_default_paper(repo)

    if not raw_traces_dir.is_dir():
        print(f"ERROR: raw traces directory not found: {raw_traces_dir}", file=sys.stderr)
        return 2
    if paper_path is None or not paper_path.is_file():
        print(f"ERROR: could not locate Paper1_Draft_Sections.tex (looked near {repo})", file=sys.stderr)
        return 2

    print(f"Repo:  {repo}")
    print(f"Paper: {paper_path}")
    print(f"Raw traces: {raw_traces_dir}")
    print()

    tex = load_tex(paper_path)
    folders = build_folder_maps(raw_traces_dir)
    parsed_cache: Dict[str, Dict[str, Dict[str, ParsedTrace]]] = {}
    findings: List[Finding] = []

    audit_tab_ci(tex, folders, findings, parsed_cache)
    audit_tab_probe_results(tex, folders, findings, parsed_cache)
    audit_sweep_table(tex, "tab:sensitivity-t1max", T1MAX_SWEEP, folders, findings, parsed_cache, "tab:sensitivity-t1max")
    audit_sweep_table(tex, "tab:sensitivity-shape", SHAPE_SWEEP, folders, findings, parsed_cache, "tab:sensitivity-shape")

    if args.csv_cross_check:
        audit_existing_csvs(raw_traces_dir, findings)

    # ---- print report ----
    by_table: Dict[str, List[Finding]] = {}
    for f in findings:
        by_table.setdefault(f.table, []).append(f)

    total = len(findings)
    n_ok = sum(1 for f in findings if f.kind == "ok")
    n_bad = sum(1 for f in findings if f.kind in ("value_mismatch", "significance_mismatch", "csv_mismatch"))
    n_note = sum(1 for f in findings if f.kind == "parse_note")

    print("=" * 100)
    print(f"AUDIT SUMMARY: {total} checks -- {n_ok} OK, {n_bad} MISMATCHES, {n_note} notes/unresolved")
    print("=" * 100)
    print()

    for table, items in by_table.items():
        n_bad_t = sum(1 for f in items if f.kind in ("value_mismatch", "significance_mismatch", "csv_mismatch"))
        n_note_t = sum(1 for f in items if f.kind == "parse_note")
        verdict = "CLEAN" if n_bad_t == 0 and n_note_t == 0 else ("ISSUES FOUND" if n_bad_t else "INCOMPLETE (see notes)")
        print(f"--- {table} : {verdict} ({len(items)} checks, {n_bad_t} mismatches, {n_note_t} notes) ---")
        for f in items:
            if f.kind == "ok":
                continue
            print(f"  [{f.kind.upper()}] {f.location}: {f.detail}")
        print()

    if n_bad == 0 and n_note == 0:
        print("VERDICT: No discrepancies found. Every checked paper value and significance verdict matches an "
              "independent reparse of the raw verifyta trace files.")
    else:
        print("VERDICT: See mismatches/notes above.")

    return 0 if (n_bad == 0 and n_note == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
