#!/usr/bin/env python3
"""Simple Tkinter GUI for `uppaal_query_runner.py` and trace CSV extraction.

Features:
- select an UPPAAL XML model file
- choose output CSV path
- choose `verifyta` executable
- run queries live and show the new results
- live log and table view of query status/result text
- extract trace files to CSV with query values

Run:
    python uppaal_query_runner_gui_v3.py
"""
import csv
import glob
import os
import re
import threading
import time
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from dataclasses import dataclass
from typing import Iterable, List, Optional

try:
    import uppaal_query_runner as uqr
except Exception:
    uqr = None


# ============================================================================
# Trace CSV Extractor Integration
# ============================================================================

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

MEAN_RE = re.compile(r"mean\s*=\s*(?P<value>[-+0-9.eE]+)", re.IGNORECASE)

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

ENABLE_CONST_RE = re.compile(
    r"^\s*const\s+bool\s+(?P<name>ENABLE_[A-Za-z0-9_]+)\s*=\s*(?P<value>true|false)\s*;.*$"
)

RESULT_BLOCK_RE = re.compile(r"\n?\s*<result\b[^>]*>.*?</result>\s*", re.DOTALL)
RESULT_SELF_CLOSING_RE = re.compile(r"\n?\s*<result\b[^>]*/>\s*")


@dataclass
class ParsedTrace:
    query_name: str
    value: str
    runs: str = ""
    ci_low: str = ""
    ci_high: str = ""
    trace_file: str = ""


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _run_parser_examples():
    examples = [
        {
            'name': 'estimate approx min',
            'raw': '(50 runs) E(min) = ≈ 100',
            'result_text': '',
            'query_type': 'estimate',
            'expected_value': 100.0,
        },
        {
            'name': 'estimate approx max',
            'raw': '(50 runs) E(max) = ≈ 0',
            'result_text': '',
            'query_type': 'estimate',
            'expected_value': 0.0,
        },
        {
            'name': 'estimate with plus-minus',
            'raw': '(50 runs) E(max) = 10.58 ± 0.14 (95% CI)',
            'result_text': '',
            'query_type': 'estimate',
            'expected_value': 10.58,
        },
        {
            'name': 'mean line',
            'raw': 'Values in [100,100] mean=100 steps=1: 50',
            'result_text': '',
            'query_type': 'estimate',
            'expected_value': 100.0,
        },
        {
            'name': 'ansi control in result_text',
            'raw': 'Values in [100,100] mean=100 steps=1: 50',
            'result_text': '\x1b[2K -- Formula is satisfied.',
            'query_type': 'estimate',
            'expected_value': 100.0,
        },
    ]

    checker = App.__new__(App)
    for item in examples:
        value, _kind, _method = checker._extract_numeric_value_from_text(
            item['raw'],
            item['result_text'],
            item['query_type'],
        )
        if value != item['expected_value']:
            raise AssertionError(
                f"Example '{item['name']}' failed: expected {item['expected_value']}, got {value}"
            )


def _run_scoring_examples():
    app = App.__new__(App)
    app.prmm_k_tolerance = lambda kind: 0.5
    app._kpi_tolerance = lambda kind: 0.005 if kind == 'probability' else 0.5

    kpi_examples = [
        ({'mapping_exists': True, 'practice_exists_in_model': True, 'kpi_query_exists': True, 'activation_required': False, 'activation_status': 'confirmed_active', 'baseline_value': 10, 'practice_value': 14, 'improvement': 4, 'tolerance': 0.5}, 4),
        ({'mapping_exists': True, 'practice_exists_in_model': True, 'kpi_query_exists': True, 'activation_required': False, 'activation_status': 'confirmed_active', 'baseline_value': 10, 'practice_value': 10.2, 'improvement': 0.2, 'tolerance': 0.5}, 3),
        ({'mapping_exists': True, 'practice_exists_in_model': True, 'kpi_query_exists': True, 'activation_required': True, 'activation_status': 'confirmed_inactive', 'baseline_value': 10, 'practice_value': 14, 'improvement': 4, 'tolerance': 0.5}, 2),
        ({'mapping_exists': True, 'practice_exists_in_model': True, 'kpi_query_exists': True, 'activation_required': False, 'activation_status': 'confirmed_active', 'baseline_value': None, 'practice_value': 14, 'improvement': None, 'tolerance': 0.5}, 0),
    ]
    for evidence, expected in kpi_examples:
        score, _reason = app.score_kpi_effectiveness_cell(evidence)
        if score != expected:
            raise AssertionError(f'KPI example failed: expected {expected}, got {score}')

    prmm_examples = [
        ({'mapping_exists': False, 'practice_exists_in_model': True, 'kpi_query_exists': True, 'activation_required': False, 'activation_status': 'not_required', 'baseline_value': 1, 'practice_value': 2}, 0),
        ({'mapping_exists': True, 'practice_exists_in_model': False, 'kpi_query_exists': True, 'activation_required': False, 'activation_status': 'not_required', 'baseline_value': 1, 'practice_value': 2}, 1),
        ({'mapping_exists': True, 'practice_exists_in_model': True, 'kpi_query_exists': True, 'activation_required': True, 'activation_status': 'confirmed_inactive', 'baseline_value': 1, 'practice_value': 2}, 2),
        ({'mapping_exists': True, 'practice_exists_in_model': True, 'kpi_query_exists': True, 'activation_required': False, 'activation_status': 'confirmed_active', 'baseline_value': None, 'practice_value': None}, 3),
        ({'mapping_exists': True, 'practice_exists_in_model': True, 'kpi_query_exists': True, 'activation_required': False, 'activation_status': 'confirmed_active', 'baseline_value': 1, 'practice_value': 2}, 4),
    ]
    for evidence, expected in prmm_examples:
        score, _reason = app.score_prmm_maturity_cell(evidence)
        if score != expected:
            raise AssertionError(f'PRMM example failed: expected {expected}, got {score}')


def clean_query_name_from_filename(path: Path) -> str:
    """Create a readable query name from the trace filename."""
    stem = path.stem
    stem = re.sub(r"_\d+$", "", stem)
    stem = re.sub(r"^\d+_", "", stem)
    stem = stem.replace("__", "_")
    pretty = stem.replace("_", " ").strip()
    return pretty or path.stem


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
    if not match:
        return None

    runs = match.group("runs")
    value = match.group("value").strip()

    return ParsedTrace(
        query_name="estimate query",
        value=value,
        runs=runs,
        ci_low="",
        ci_high="",
    )


def parse_trace(path: Path) -> ParsedTrace:
    text = read_text(path)
    parsed = parse_probability(text) or parse_estimate(text)
    if parsed is None:
        lower = text.lower()
        value = 'Run Fail' if ('error' in lower or 'failed' in lower) else '0'
        parsed = ParsedTrace(
            query_name=clean_query_name_from_filename(path),
            value=value,
            runs="",
            ci_low="",
            ci_high="",
        )
    else:
        parsed.query_name = clean_query_name_from_filename(path)

    parsed.trace_file = str(path)
    return parsed


def expand_inputs(inputs: Iterable[str], recursive: bool = False) -> List[Path]:
    paths: List[Path] = []
    for item in inputs:
        p = Path(item)
        if p.is_file():
            paths.append(p)
        elif p.is_dir():
            if recursive:
                paths.extend(sorted(x for x in p.rglob("*.txt") if x.is_file()))
            else:
                paths.extend(sorted(x for x in p.glob("*.txt") if x.is_file()))
        else:
            if any(ch in item for ch in ["*", "?", "["]):
                matches = sorted(Path(p) for p in glob.glob(item))
                paths.extend([x for x in matches if x.is_file()])
    
    seen = set()
    unique = []
    for p in paths:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def write_trace_csv(rows: List[ParsedTrace], out_path: Path) -> None:
    fieldnames = ["query_name", "value", "runs", "ci_low", "ci_high", "trace_file"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: getattr(row, k) for k in fieldnames})


# ============================================================================
# GUI Application
# ============================================================================


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('UPPAAL Query Runner v3')
        self.geometry('980x740')
        self.queries = []
        self.status_var = tk.StringVar(value='Ready')
        self.enable_status_var = tk.StringVar(value='Select a model to load ENABLE_* switches')
        self.enable_flag_vars = {}

        notebook = ttk.Notebook(self)
        notebook.pack(fill='both', expand=True, padx=8, pady=8)

        self.runner_tab = ttk.Frame(notebook)
        self.flags_tab = ttk.Frame(notebook)
        self.prmm_tab = ttk.Frame(notebook)
        notebook.add(self.runner_tab, text='Query Runner')
        notebook.add(self.flags_tab, text='Enable Switches')
        notebook.add(self.prmm_tab, text='PRMM Evaluation')

        self._build_runner_tab()
        self._build_flags_tab()
        self._build_prmm_tab()

    def _build_runner_tab(self):
        frm = ttk.Frame(self.runner_tab)
        frm.pack(fill='both', expand=True, padx=8, pady=8)

        # Model selection
        row = ttk.Frame(frm)
        row.pack(fill='x', pady=4)
        ttk.Label(row, text='Model file:').pack(side='left')
        self.model_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.model_var, width=70).pack(side='left', padx=6)
        ttk.Button(row, text='Browse', command=self.browse_model).pack(side='left')
        ttk.Button(row, text='Load Queries', command=self.load_queries).pack(side='left', padx=6)

        # verifyta
        row3 = ttk.Frame(frm)
        row3.pack(fill='x', pady=4)
        ttk.Label(row3, text='verifyta:').pack(side='left')
        self.verifyta_var = tk.StringVar(value=self._default_verifyta())
        ttk.Entry(row3, textvariable=self.verifyta_var, width=70).pack(side='left', padx=6)
        ttk.Button(row3, text='Browse', command=self.browse_verifyta).pack(side='left')

        # Control buttons
        btn_row = ttk.Frame(frm)
        btn_row.pack(fill='x', pady=8)
        self.run_btn = ttk.Button(btn_row, text='Run Selected Query', command=self.run_selected)
        self.run_btn.pack(side='left')
        ttk.Button(btn_row, text='Run All Queries', command=self.run_all).pack(side='left', padx=8)
        ttk.Button(btn_row, text='Erase Query Results (XML)', command=self.erase_saved_traces).pack(side='left', padx=8)
        ttk.Button(btn_row, text='Quit', command=self.quit).pack(side='left', padx=8)

        # Number of runs
        runs_frame = ttk.Frame(frm)
        runs_frame.pack(fill='x', pady=4)
        ttk.Label(runs_frame, text='Number of Runs:').pack(side='left')
        self.runs_var = tk.StringVar(value='1')
        ttk.Entry(runs_frame, textvariable=self.runs_var, width=5).pack(side='left', padx=6)
        ttk.Label(runs_frame, text='(default 1, 30 seconds between runs)').pack(side='left')

        # Query list
        q_frame = ttk.Frame(frm)
        q_frame.pack(fill='both', expand=True, pady=6)
        ttk.Label(q_frame, text='Queries:').pack(anchor='w')
        q_inner = ttk.Frame(q_frame)
        q_inner.pack(fill='both', expand=True)
        self.query_list = tk.Listbox(q_inner, selectmode='extended', height=8)
        self.query_list.pack(side='left', fill='both', expand=True)
        q_scroll = ttk.Scrollbar(q_inner, orient='vertical', command=self.query_list.yview)
        q_scroll.pack(side='right', fill='y')
        self.query_list.configure(yscrollcommand=q_scroll.set)

        # Treeview for queries
        tv_frame = ttk.Frame(frm)
        tv_frame.pack(fill='both', expand=True)
        cols = ('run_no', 'run_timestamp', 'index', 'query_type', 'formula', 'status', 'trace_file')
        self.tree = ttk.Treeview(tv_frame, columns=cols, show='headings')
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=140 if c not in ('formula', 'trace_file') else 320, anchor='w')
        self.tree.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(tv_frame, orient='vertical', command=self.tree.yview)
        scrollbar.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scrollbar.set)

        # Log area
        log_frame = ttk.Frame(frm)
        log_frame.pack(fill='x', pady=6)
        ttk.Label(log_frame, text='Log:').pack(anchor='w')
        self.log = tk.Text(log_frame, height=6, state='disabled')
        self.log.pack(fill='x')

        status_row = ttk.Frame(frm)
        status_row.pack(fill='x')
        ttk.Label(status_row, text='Status:').pack(side='left')
        ttk.Label(status_row, textvariable=self.status_var).pack(side='left', padx=6)

    def _build_flags_tab(self):
        root = ttk.Frame(self.flags_tab)
        root.pack(fill='both', expand=True, padx=8, pady=8)

        top = ttk.Frame(root)
        top.pack(fill='x', pady=4)
        ttk.Label(top, text='ENABLE_* switches from selected model file').pack(side='left')
        ttk.Button(top, text='Refresh', command=self.load_enable_flags).pack(side='right')

        status = ttk.Frame(root)
        status.pack(fill='x', pady=2)
        ttk.Label(status, textvariable=self.enable_status_var).pack(side='left')

        container = ttk.Frame(root)
        container.pack(fill='both', expand=True, pady=6)

        self.flags_canvas = tk.Canvas(container, borderwidth=0, highlightthickness=0)
        self.flags_canvas.pack(side='left', fill='both', expand=True)

        self.flags_scrollbar = ttk.Scrollbar(container, orient='vertical', command=self.flags_canvas.yview)
        self.flags_scrollbar.pack(side='right', fill='y')
        self.flags_canvas.configure(yscrollcommand=self.flags_scrollbar.set)

        self.flags_inner = ttk.Frame(self.flags_canvas)
        self.flags_window = self.flags_canvas.create_window((0, 0), window=self.flags_inner, anchor='nw')

        self.flags_inner.bind(
            '<Configure>',
            lambda _e: self.flags_canvas.configure(scrollregion=self.flags_canvas.bbox('all')),
        )
        self.flags_canvas.bind(
            '<Configure>',
            lambda e: self.flags_canvas.itemconfigure(self.flags_window, width=e.width),
        )

    def _default_verifyta(self):
        candidates = [
            r'C:\Program Files\UPPAAL-5.0.0\app\bin\verifyta.exe',
            r'C:\Program Files (x86)\UPPAAL-5.0.0\app\bin\verifyta.exe',
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        return 'verifyta'

    def browse_model(self):
        p = filedialog.askopenfilename(title='Select UPPAAL model', filetypes=[('XML files','*.xml'),('All files','*.*')])
        if p:
            self.model_var.set(p)
            self.load_queries()
            self.load_enable_flags()
            self.refresh_prmm_sources()

    def browse_verifyta(self):
        p = filedialog.askopenfilename(title='Select verifyta executable', filetypes=[('Executables','verifyta.exe;verifyta'),('All files','*.*')])
        if p:
            self.verifyta_var.set(p)

    def _parse_queries(self, model):
        import xml.etree.ElementTree as ET
        if uqr is not None:
            return uqr.extract_queries(model)

        tree = ET.parse(model)
        root = tree.getroot()
        queries = []
        for i, q in enumerate(root.findall('.//queries/query')):
            formula = (q.find('formula').text or '').strip() if q.find('formula') is not None else ''
            comment = (q.find('comment').text or '').strip() if q.find('comment') is not None else ''
            queries.append({'index': i + 1, 'formula': formula, 'comment': comment})
        return queries

    def _trace_dir_for_output(self, out_path):
        base = os.path.splitext(os.path.basename(out_path))[0]
        return os.path.join(os.path.dirname(os.path.abspath(out_path)), f'{base}_traces')

    def load_queries(self):
        model = self.model_var.get()
        if not model or not os.path.isfile(model):
            return
        try:
            self.queries = self._parse_queries(model)
            self.query_list.delete(0, 'end')
            for q in self.queries:
                label = f"{q.get('index')}. {q.get('formula', '')}"
                comment = (q.get('comment') or '').strip()
                if comment:
                    label += f"   // {comment}"
                self.query_list.insert('end', label)
            self.append_log(f'Loaded {len(self.queries)} queries from model')
            self.refresh_prmm_sources()
        except Exception as e:
            self.append_log('Failed to load queries: ' + str(e))
            messagebox.showerror('Error', f'Failed to load queries:\n{e}')

    def load_enable_flags(self):
        for w in self.flags_inner.winfo_children():
            w.destroy()
        self.enable_flag_vars = {}

        model = self.model_var.get()
        if not model or not os.path.isfile(model):
            self.enable_status_var.set('Select a valid model file first.')
            return

        try:
            lines = read_text(Path(model)).splitlines()
            parsed = []
            for idx, line in enumerate(lines, start=1):
                m = ENABLE_CONST_RE.match(line)
                if m:
                    parsed.append((idx, m.group('name'), m.group('value').lower() == 'true'))

            if not parsed:
                self.enable_status_var.set('No ENABLE_* const bool lines found in this model.')
                return

            self.enable_status_var.set(f'Found {len(parsed)} ENABLE_* switch(es). Toggle any switch to update the XML file.')

            # Group flags by prefix: DISRUPTIONS (ENABLE_D_), PRACTICES (ENABLE_P_), and Others
            disruptions = []
            practices = []
            others = []
            for line_no, name, is_enabled in parsed:
                if name.startswith('ENABLE_D_'):
                    disruptions.append((line_no, name, is_enabled))
                elif name.startswith('ENABLE_P_'):
                    practices.append((line_no, name, is_enabled))
                else:
                    others.append((line_no, name, is_enabled))

            def _make_group(title, items):
                if not items:
                    return None
                grp = ttk.LabelFrame(self.flags_inner, text=title)
                grp.pack(fill='x', pady=6, padx=4, anchor='nw')
                for line_no, name, is_enabled in items:
                    row = ttk.Frame(grp)
                    row.pack(fill='x', pady=2, padx=4)
                    ttk.Label(row, text=self._display_name(name), width=55, anchor='w').pack(side='left', padx=(4, 8))
                    ttk.Label(row, text=f'line {line_no}', width=10, anchor='w').pack(side='left')

                    var = tk.BooleanVar(value=is_enabled)
                    self.enable_flag_vars[name] = var
                    chk = ttk.Checkbutton(
                        row,
                        text='Enabled',
                        variable=var,
                        command=lambda n=name, v=var: self._on_toggle_enable(n, v),
                    )
                    chk.pack(side='left', padx=8)
                return grp

            # Create groups in desired order
            _make_group('Disruptions', disruptions)
            _make_group('Practices', practices)
            if others:
                _make_group('Other ENABLE_* switches', others)

        except Exception as e:
            self.enable_status_var.set(f'Failed to read ENABLE_* switches: {e}')

    def _on_toggle_enable(self, flag_name, var):
        desired = var.get()
        try:
            self._set_enable_flag(flag_name, desired)
            self.append_log(f'{flag_name} set to {str(desired).lower()}')
        except Exception as e:
            var.set(not desired)
            messagebox.showerror('Failed to update model', str(e))

    def _set_enable_flag(self, flag_name, enabled):
        model = self.model_var.get()
        if not model or not os.path.isfile(model):
            raise RuntimeError('Select a valid model file first.')

        path = Path(model)
        text = read_text(path)
        target = 'true' if enabled else 'false'
        pattern = re.compile(
            rf'(^\s*const\s+bool\s+{re.escape(flag_name)}\s*=\s*)(true|false)(\s*;.*)$',
            re.MULTILINE,
        )

        updated_text, count = pattern.subn(lambda m: f"{m.group(1)}{target}{m.group(3)}", text, count=1)
        if count == 0:
            raise RuntimeError(f'Could not find declaration for {flag_name}.')

        if updated_text != text:
            path.write_text(updated_text, encoding='utf-8')

    def _build_prmm_tab(self):
        """Build the PRMM setup area plus independent KPI and PRMM scoring tabs."""
        container = ttk.Frame(self.prmm_tab)
        container.pack(fill='both', expand=True, padx=8, pady=8)

        self.prmm_canvas = tk.Canvas(container, borderwidth=0, highlightthickness=0)
        self.prmm_canvas.pack(side='left', fill='both', expand=True)
        prmm_scrollbar = ttk.Scrollbar(container, orient='vertical', command=self.prmm_canvas.yview)
        prmm_scrollbar.pack(side='right', fill='y')
        self.prmm_canvas.configure(yscrollcommand=prmm_scrollbar.set)

        outer = ttk.Frame(self.prmm_canvas)
        self.prmm_canvas_window = self.prmm_canvas.create_window((0, 0), window=outer, anchor='nw')
        outer.bind('<Configure>', lambda _e: self.prmm_canvas.configure(scrollregion=self.prmm_canvas.bbox('all')))
        self.prmm_canvas.bind('<Configure>', lambda e: self.prmm_canvas.itemconfigure(self.prmm_canvas_window, width=e.width))

        def _on_mousewheel(event):
            self.prmm_canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')

        self.prmm_canvas.bind('<Enter>', lambda _e: self.prmm_canvas.bind_all('<MouseWheel>', _on_mousewheel))
        self.prmm_canvas.bind('<Leave>', lambda _e: self.prmm_canvas.unbind_all('<MouseWheel>'))

        header = ttk.Frame(outer)
        header.pack(fill='x', pady=4)
        ttk.Label(header, text='PRMM Evaluation Setup', font=('Arial', 12, 'bold')).pack(side='left')
        ttk.Button(header, text='Refresh Sources', command=self.refresh_prmm_sources).pack(side='right', padx=4)

        info_frm = ttk.LabelFrame(outer, text='Model Information & Disruptions/Practices Status')
        info_frm.pack(fill='x', pady=6)
        self.prmm_info_text = tk.Text(info_frm, height=8, state='disabled')
        self.prmm_info_text.pack(fill='x', padx=4, pady=4)

        map_frm = ttk.LabelFrame(outer, text='User-defined D / P / K Relationships')
        map_frm.pack(fill='x', pady=6)

        maps_top = ttk.Frame(map_frm)
        maps_top.pack(fill='x', padx=4, pady=4)

        dp_box = ttk.LabelFrame(maps_top, text='Disruption -> Practice')
        dp_box.pack(side='left', fill='both', expand=True, padx=4)
        dp_lists = ttk.Frame(dp_box)
        dp_lists.pack(fill='both', expand=True, padx=4, pady=4)
        left_dp = ttk.Frame(dp_lists)
        left_dp.pack(side='left', fill='both', expand=True, padx=(0, 4))
        ttk.Label(left_dp, text='Disruptions (D)').pack(anchor='w')
        self.prmm_d_listbox = tk.Listbox(left_dp, selectmode='extended', height=8, exportselection=False)
        self.prmm_d_listbox.pack(fill='both', expand=True)
        right_dp = ttk.Frame(dp_lists)
        right_dp.pack(side='left', fill='both', expand=True, padx=(4, 0))
        ttk.Label(right_dp, text='Practices (P)').pack(anchor='w')
        self.prmm_p_listbox = tk.Listbox(right_dp, selectmode='extended', height=8, exportselection=False)
        self.prmm_p_listbox.pack(fill='both', expand=True)
        dp_btns = ttk.Frame(dp_box)
        dp_btns.pack(fill='x', padx=4, pady=(0, 4))
        ttk.Button(dp_btns, text='Map D -> P', command=self.add_dp_mapping).pack(side='left')
        ttk.Button(dp_btns, text='Clear D -> P', command=self.clear_dp_mappings).pack(side='left', padx=6)
        dp_meta = ttk.Frame(dp_box)
        dp_meta.pack(fill='x', padx=4, pady=(0, 4))
        ttk.Button(dp_meta, text='Set activation from selected K', command=self.set_practice_activation_query).pack(side='left')
        ttk.Button(dp_meta, text='Clear activation for selected P', command=self.clear_practice_activation_query).pack(side='left', padx=6)

        kp_box = ttk.LabelFrame(maps_top, text='KPI / Query -> Disruptions + Practices')
        kp_box.pack(side='left', fill='both', expand=True, padx=4)
        kp_lists = ttk.Frame(kp_box)
        kp_lists.pack(fill='both', expand=True, padx=4, pady=4)
        left_kp = ttk.Frame(kp_lists)
        left_kp.pack(side='left', fill='both', expand=True, padx=(0, 4))
        ttk.Label(left_kp, text='Queries (K)').pack(anchor='w')
        self.prmm_k_listbox = tk.Listbox(left_kp, selectmode='extended', height=8, exportselection=False)
        self.prmm_k_listbox.pack(fill='both', expand=True)
        self.prmm_k_listbox.bind('<<ListboxSelect>>', self._on_prmm_k_select)
        right_kp = ttk.Frame(kp_lists)
        right_kp.pack(side='left', fill='both', expand=True, padx=(4, 0))
        ttk.Label(right_kp, text='Select Disruptions (D)').pack(anchor='w')
        self.prmm_k_d_listbox = tk.Listbox(right_kp, selectmode='extended', height=4, exportselection=False)
        self.prmm_k_d_listbox.pack(fill='both', expand=True)
        ttk.Label(right_kp, text='Select Practices/Groups (P)').pack(anchor='w', pady=(4, 0))
        self.prmm_k_p_listbox = tk.Listbox(right_kp, selectmode='extended', height=4, exportselection=False)
        self.prmm_k_p_listbox.pack(fill='both', expand=True)
        kp_btns = ttk.Frame(kp_box)
        kp_btns.pack(fill='x', padx=4, pady=(0, 4))
        ttk.Button(kp_btns, text='Map K -> D/P', command=self.add_k_mapping).pack(side='left')
        ttk.Button(kp_btns, text='Clear K mappings', command=self.clear_k_mappings).pack(side='left', padx=6)
        kp_meta = ttk.Frame(kp_box)
        kp_meta.pack(fill='x', padx=4, pady=(0, 4))
        ttk.Button(kp_meta, text='K: Higher is better', command=lambda: self.set_k_direction('higher')).pack(side='left')
        ttk.Button(kp_meta, text='K: Lower is better', command=lambda: self.set_k_direction('lower')).pack(side='left', padx=6)

        group_box = ttk.LabelFrame(map_frm, text='Practice Groups (Combined Scenarios)')
        group_box.pack(fill='x', pady=6)
        group_top = ttk.Frame(group_box)
        group_top.pack(fill='x', padx=4, pady=4)
        ttk.Label(group_top, text='Group name:').pack(side='left')
        self.prmm_group_name_var = tk.StringVar()
        ttk.Entry(group_top, textvariable=self.prmm_group_name_var, width=35).pack(side='left', padx=6)
        ttk.Button(group_top, text='Add/Update Group', command=self.add_practice_group).pack(side='left', padx=6)
        ttk.Button(group_top, text='Remove Group', command=self.remove_practice_group).pack(side='left')
        group_lists = ttk.Frame(group_box)
        group_lists.pack(fill='x', padx=4, pady=(0, 4))
        group_left = ttk.Frame(group_lists)
        group_left.pack(side='left', fill='both', expand=True, padx=(0, 6))
        ttk.Label(group_left, text='Include practices').pack(anchor='w')
        group_left_list = ttk.Frame(group_left)
        group_left_list.pack(fill='both', expand=True)
        self.prmm_group_practices_listbox = tk.Listbox(group_left_list, selectmode='extended', height=10, exportselection=False)
        self.prmm_group_practices_listbox.pack(side='left', fill='both', expand=True)
        group_left_scroll = ttk.Scrollbar(group_left_list, orient='vertical', command=self.prmm_group_practices_listbox.yview)
        group_left_scroll.pack(side='right', fill='y')
        self.prmm_group_practices_listbox.configure(yscrollcommand=group_left_scroll.set)
        group_right = ttk.Frame(group_lists)
        group_right.pack(side='left', fill='both', expand=True)
        ttk.Label(group_right, text='Defined groups').pack(anchor='w')
        self.prmm_groups_listbox = tk.Listbox(group_right, selectmode='browse', height=10, exportselection=False)
        self.prmm_groups_listbox.pack(fill='both', expand=True)
        self.prmm_groups_listbox.bind('<<ListboxSelect>>', self._on_group_select)

        summary_frm = ttk.LabelFrame(outer, text='Mapping Summary')
        summary_frm.pack(fill='x', pady=6)
        self.prmm_mapping_text = tk.Text(summary_frm, height=9, state='disabled')
        self.prmm_mapping_text.pack(fill='x', padx=4, pady=4)

        self.prmm_eval_notebook = ttk.Notebook(outer)
        self.prmm_eval_notebook.pack(fill='both', expand=True, pady=6)
        self.kpi_eval_tab = ttk.Frame(self.prmm_eval_notebook)
        self.prmm_maturity_tab = ttk.Frame(self.prmm_eval_notebook)
        self.prmm_eval_notebook.add(self.kpi_eval_tab, text='KPI Effectiveness Evaluation')
        self.prmm_eval_notebook.add(self.prmm_maturity_tab, text='PRMM Maturity Evaluation')

        self._build_kpi_effectiveness_tab()
        self._build_prmm_maturity_tab()

        self.prmm_d_items = []
        self.prmm_p_items = []
        self.prmm_k_items = []
        self.prmm_dp_map = {}
        self.prmm_k_map = {}
        self.prmm_k_dir_map = {}
        self.prmm_p_activation_map = {}
        self.prmm_k_query_map = {}
        self.prmm_p_groups = {}
        self.prmm_level_scopes = {level: set() for level in range(1, 6)}
        self.refresh_prmm_sources()

    def _build_kpi_effectiveness_tab(self):
        frame = ttk.Frame(self.kpi_eval_tab)
        frame.pack(fill='both', expand=True, padx=8, pady=8)

        header = ttk.Frame(frame)
        header.pack(fill='x', pady=4)
        ttk.Label(header, text='KPI Effectiveness Evaluation', font=('Arial', 12, 'bold')).pack(side='left')
        ttk.Button(header, text='Run KPI Effectiveness Evaluation', command=self.calculate_kpi_effectiveness).pack(side='right', padx=4)
        ttk.Button(header, text='Export KPI Effectiveness Report', command=self.export_kpi_effectiveness_report).pack(side='right', padx=4)

        summary = ttk.LabelFrame(frame, text='KPI Effectiveness Summary')
        summary.pack(fill='x', pady=6)
        self.kpi_effectiveness_summary_var = tk.StringVar(value='KPI Effectiveness Score: —')
        self.kpi_effectiveness_level_vars = {level: tk.StringVar(value='—') for level in range(1, 6)}
        ttk.Label(summary, textvariable=self.kpi_effectiveness_summary_var).pack(anchor='w', padx=4, pady=2)
        for level in range(1, 6):
            ttk.Label(summary, textvariable=self.kpi_effectiveness_level_vars[level]).pack(anchor='w', padx=4)
        self.kpi_effectiveness_counts_var = tk.StringVar(value='Evaluated cells: —')
        self.kpi_effectiveness_report_var = tk.StringVar(value='Report path: —')
        ttk.Label(summary, textvariable=self.kpi_effectiveness_counts_var).pack(anchor='w', padx=4, pady=(4, 0))
        ttk.Label(summary, textvariable=self.kpi_effectiveness_report_var).pack(anchor='w', padx=4, pady=(0, 4))

        activation_box = ttk.LabelFrame(frame, text='Activation Status')
        activation_box.pack(fill='x', padx=4, pady=4)
        activation_cols = ('query', 'value', 'status')
        self.kpi_activation_table = ttk.Treeview(activation_box, columns=activation_cols, show='headings', height=4)
        for col in activation_cols:
            self.kpi_activation_table.heading(col, text=col)
            self.kpi_activation_table.column(col, anchor='w', width=280 if col == 'query' else 120)
        self.kpi_activation_table.pack(fill='x', padx=4, pady=4)

        results_box = ttk.LabelFrame(frame, text='KPI Results')
        results_box.pack(fill='both', expand=True, padx=4, pady=4)
        result_cols = ('kpi', 'clean_kpi', 'direction', 'baseline', 'practice', 'improvement', 'score', 'result')
        self.kpi_results_table = ttk.Treeview(results_box, columns=result_cols, show='headings', height=10)
        for col in result_cols:
            self.kpi_results_table.heading(col, text=col)
            width = 260 if col == 'clean_kpi' else 120 if col in ('baseline', 'practice', 'improvement') else 140 if col == 'result' else 90
            self.kpi_results_table.column(col, anchor='w', width=width)
        self.kpi_results_table.pack(fill='both', expand=True, padx=4, pady=4)

        rec_box = ttk.LabelFrame(frame, text='Recommendations for Improvement')
        rec_box.pack(fill='both', expand=True, pady=6)
        self.kpi_recommendations_text = tk.Text(rec_box, height=8, state='disabled', wrap='word')
        self.kpi_recommendations_text.pack(fill='both', expand=True, padx=4, pady=4)

    def _build_prmm_maturity_tab(self):
        frame = ttk.Frame(self.prmm_maturity_tab)
        frame.pack(fill='both', expand=True, padx=8, pady=8)

        header = ttk.Frame(frame)
        header.pack(fill='x', pady=4)
        ttk.Label(header, text='PRMM Maturity Evaluation', font=('Arial', 12, 'bold')).pack(side='left')
        ttk.Button(header, text='Run PRMM Maturity Evaluation', command=self.calculate_prmm_maturity).pack(side='right', padx=4)
        ttk.Button(header, text='Export PRMM Maturity Report', command=self.export_prmm_maturity_report).pack(side='right', padx=4)

        summary = ttk.LabelFrame(frame, text='PRMM Summary')
        summary.pack(fill='x', pady=6)
        self.prmm_summary_matrix_var = tk.StringVar(value='S1 diagnostic score: —')
        self.prmm_summary_weighted_var = tk.StringVar(value='Weighted PRMM final score: —')
        self.prmm_summary_category_var = tk.StringVar(value='Maturity category: —')
        self.prmm_summary_activation_var = tk.StringVar(value='Activation status: —')
        self.prmm_summary_counts_var = tk.StringVar(value='Evaluated cells: —')
        self.prmm_summary_report_var = tk.StringVar(value='Report path: —')
        ttk.Label(summary, textvariable=self.prmm_summary_matrix_var).pack(anchor='w', padx=4, pady=2)
        ttk.Label(summary, textvariable=self.prmm_summary_weighted_var).pack(anchor='w', padx=4, pady=2)
        ttk.Label(summary, textvariable=self.prmm_summary_category_var).pack(anchor='w', padx=4, pady=2)
        ttk.Label(summary, textvariable=self.prmm_summary_activation_var).pack(anchor='w', padx=4, pady=2)
        ttk.Label(summary, textvariable=self.prmm_summary_counts_var).pack(anchor='w', padx=4, pady=(4, 0))
        ttk.Label(summary, textvariable=self.prmm_summary_report_var).pack(anchor='w', padx=4, pady=(0, 4))

        level_box = ttk.LabelFrame(frame, text='Maturity Scores by Level')
        level_box.pack(fill='x', pady=6)
        self.prmm_level_vars = {level: tk.StringVar(value='—') for level in range(1, 6)}
        for level in range(1, 6):
            row = ttk.Frame(level_box)
            row.pack(fill='x', pady=2, padx=4)
            ttk.Label(row, text=f'Level {level}:', width=12).pack(side='left')
            ttk.Label(row, textvariable=self.prmm_level_vars[level], width=60).pack(side='left', padx=8)

        activation_box = ttk.LabelFrame(frame, text='Activation Status')
        activation_box.pack(fill='x', padx=4, pady=4)
        activation_cols = ('query', 'value', 'status')
        self.prmm_activation_table = ttk.Treeview(activation_box, columns=activation_cols, show='headings', height=4)
        for col in activation_cols:
            self.prmm_activation_table.heading(col, text=col)
            self.prmm_activation_table.column(col, anchor='w', width=280 if col == 'query' else 120)
        self.prmm_activation_table.pack(fill='x', padx=4, pady=4)

        results_box = ttk.LabelFrame(frame, text='KPI Results')
        results_box.pack(fill='both', expand=True, padx=4, pady=4)
        result_cols = ('kpi', 'clean_kpi', 'direction', 'baseline', 'practice', 'improvement', 'score', 'result')
        self.prmm_results_table = ttk.Treeview(results_box, columns=result_cols, show='headings', height=10)
        for col in result_cols:
            self.prmm_results_table.heading(col, text=col)
            width = 260 if col == 'clean_kpi' else 120 if col in ('baseline', 'practice', 'improvement') else 140 if col == 'result' else 90
            self.prmm_results_table.column(col, anchor='w', width=width)
        self.prmm_results_table.pack(fill='both', expand=True, padx=4, pady=4)

        rec_box = ttk.LabelFrame(frame, text='Recommendations for Improvement')
        rec_box.pack(fill='both', expand=True, pady=6)
        self.prmm_recommendations_text = tk.Text(rec_box, height=8, state='disabled', wrap='word')
        self.prmm_recommendations_text.pack(fill='both', expand=True, padx=4, pady=4)

    def _display_name(self, name):
        if not name:
            return ''
        for prefix in ('ENABLE_D_', 'ENABLE_P_', 'P_'):
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        cleaned = name.replace('_', ' ').strip().lower()
        return cleaned.title() if cleaned else name

    def _display_name_with_code(self, name):
        if not name:
            return ''
        return f"{self._display_name(name)} ({name})"

    def _clean_kpi_name(self, k_name):
        query = self.prmm_k_query_map.get(k_name, {})
        comment = (query.get('comment') or '').strip()
        formula = (query.get('formula') or '').strip()
        text = comment or formula or k_name

        prob_match = re.search(r'Pr\[[^\]]*\]\s*\((.*)\)', text)
        if prob_match:
            text = prob_match.group(1)
        else:
            est_match = re.search(r'\(\s*(?:min|max)\s*:\s*([^\)]+)\)', text)
            if est_match:
                text = est_match.group(1)

        text = text.replace('&&', 'and').replace('||', 'or').replace('<>', '')
        text = re.sub(r'\b_pct\b', '%', text, flags=re.IGNORECASE)
        text = text.replace('_', ' ').replace('()', '')
        text = re.sub(r'\s+', ' ', text).strip()

        words = []
        for token in text.split(' '):
            words.append(token.capitalize() if token.isalpha() else token)
        return ' '.join(words)

    def _format_number(self, value):
        if value is None:
            return ''
        if isinstance(value, (int, float)):
            text = f"{value:.6f}".rstrip('0').rstrip('.')
            return text
        return str(value)

    def _format_improvement(self, value):
        if value is None:
            return ''
        if isinstance(value, (int, float)):
            sign = '+' if value > 0 else ''
            text = f"{value:.6f}".rstrip('0').rstrip('.')
            return f"{sign}{text}"
        return str(value)

    def _update_prmm_dashboard(self, score_data):
        cells = score_data.get('cell_results', [])
        scores = [cell.get('score', 0) for cell in cells]
        total_cells = len(cells)
        sum_scores = sum(score for score in scores if isinstance(score, (int, float)))
        max_score = total_cells * 5
        matrix_effectiveness = (sum_scores / max_score) * 100.0 if max_score else 0.0

        def pct_at_or_above(threshold):
            return (sum(1 for score in scores if score >= threshold) / total_cells) * 100.0 if total_cells else 0.0

        l1 = pct_at_or_above(1)
        l2 = pct_at_or_above(2)
        l3 = pct_at_or_above(3)
        l4 = pct_at_or_above(4)
        l5 = pct_at_or_above(5)
        weighted_prmm = 0.05 * l1 + 0.10 * l2 + 0.25 * l3 + 0.30 * l4 + 0.30 * l5

        improved = sum(1 for cell in cells if cell.get('score', 0) >= 4)
        not_improved = total_cells - improved
        category = self.maturity_category_var.get() or '—'

        self.prmm_summary_matrix_var.set(f"Matrix effectiveness score: {matrix_effectiveness:.1f}%")
        self.prmm_summary_weighted_var.set(f"Weighted PRMM final score: {weighted_prmm:.1f}%")
        self.prmm_summary_category_var.set(f"Maturity category: {category}")
        self.prmm_summary_improved_var.set(f"Improved KPIs: {improved} / {total_cells}")
        self.prmm_summary_not_improved_var.set(f"Not improved KPIs: {not_improved} / {total_cells}")

        activation_rows = {}
        for cell in cells:
            entries = cell.get('activation_queries') or cell.get('activation_query')
            if not entries:
                continue
            if isinstance(entries, dict):
                entries = [entries]
            for entry in entries:
                formula = entry.get('formula') or ''
                value = entry.get('parsed_value')
                activation_rows[formula] = value

        activation_status = 'N/A'
        if activation_rows:
            activation_status = 'PASS' if all(v is not None and v > 0 for v in activation_rows.values()) else 'FAIL'
        self.prmm_summary_activation_var.set(f"Activation status: {activation_status}")

        for item in self.prmm_activation_table.get_children():
            self.prmm_activation_table.delete(item)
        for formula, value in sorted(activation_rows.items()):
            status = 'PASS' if value is not None and value > 0 else 'FAIL'
            self.prmm_activation_table.insert('', 'end', values=(formula, self._format_number(value), status))

        for item in self.prmm_results_table.get_children():
            self.prmm_results_table.delete(item)

        for cell in cells:
            k_name = cell.get('k_name', '')
            kpi_code_match = re.match(r'^(Q\d+)', k_name)
            kpi_code = kpi_code_match.group(1) if kpi_code_match else k_name
            clean_name = self._clean_kpi_name(k_name)
            direction = cell.get('direction', '')
            baseline = self._format_number(cell.get('baseline_value'))
            practice = self._format_number(cell.get('practice_value'))
            improvement = self._format_improvement(cell.get('improvement'))
            score = cell.get('score', '')
            result = 'Improved' if isinstance(score, (int, float)) and score >= 4 else 'Not improved'
            self.prmm_results_table.insert('', 'end', values=(
                kpi_code,
                clean_name,
                direction,
                baseline,
                practice,
                improvement,
                score,
                result,
            ))

    def refresh_prmm_sources(self):
        """Load disruptions, practices, and queries into the PRMM mapping controls."""
        if not hasattr(self, 'prmm_d_listbox'):
            return

        model = self.model_var.get()
        if not model or not os.path.isfile(model):
            self._set_prmm_status('Select a valid model file to load D/P sources.')
            return

        text = read_text(Path(model))
        enable_patterns = re.findall(r'const\s+bool\s+(ENABLE_[DP]_\w+)\s*=\s*(true|false)', text)
        disruptions = [name for name, _val in enable_patterns if name.startswith('ENABLE_D_')]
        practices = [name for name, _val in enable_patterns if name.startswith('ENABLE_P_')]
        group_names = sorted(self.prmm_p_groups.keys())

        self.prmm_d_items = disruptions
        self.prmm_base_practices = practices
        self.prmm_p_items = practices + group_names
        self.prmm_k_items = []

        self.prmm_d_listbox.delete(0, 'end')
        self.prmm_p_listbox.delete(0, 'end')
        self.prmm_k_listbox.delete(0, 'end')
        self.prmm_k_d_listbox.delete(0, 'end')
        self.prmm_k_p_listbox.delete(0, 'end')

        for item in disruptions:
            self.prmm_d_listbox.insert('end', self._display_name(item))
        for item in practices:
            self.prmm_p_listbox.insert('end', self._display_name(item))
        for item in group_names:
            self.prmm_p_listbox.insert('end', self._display_name(item))

        # The related panes are the actual pick lists for the mapping step.
        # They always show all available D/P items so the user can choose the
        # relationships for the selected K item(s).
        for item in disruptions:
            self.prmm_k_d_listbox.insert('end', self._display_name(item))
        for item in practices:
            self.prmm_k_p_listbox.insert('end', self._display_name(item))
        for item in group_names:
            self.prmm_k_p_listbox.insert('end', self._display_name(item))

        self.prmm_group_practices_listbox.delete(0, 'end')
        for item in self.prmm_base_practices:
            self.prmm_group_practices_listbox.insert('end', self._display_name(item))
        self._refresh_group_listbox()

        self.prmm_k_query_map = {}
        if self.queries:
            for q in self.queries:
                label = f"Q{q.get('index', '')}: {q.get('formula', '')}"
                comment = (q.get('comment') or '').strip()
                if comment:
                    label += f" // {comment}"
                self.prmm_k_items.append(label)
                self.prmm_k_query_map[label] = q
                self.prmm_k_listbox.insert('end', label)

        if not self.prmm_dp_map:
            self.prmm_dp_map = {name: set() for name in disruptions}
        else:
            for name in disruptions:
                self.prmm_dp_map.setdefault(name, set())

        if not self.prmm_k_map:
            self.prmm_k_map = {label: {'d': set(), 'p': set()} for label in self.prmm_k_items}
        else:
            for label in self.prmm_k_items:
                self.prmm_k_map.setdefault(label, {'d': set(), 'p': set()})

        for label in self.prmm_k_items:
            self.prmm_k_dir_map.setdefault(label, 'higher')

        for practice in self.prmm_p_items:
            self.prmm_p_activation_map.setdefault(practice, [])

        self._update_prmm_mapping_summary()
        self._set_prmm_status(f'Loaded {len(disruptions)} D items, {len(practices)} P items, {len(self.prmm_k_items)} K items.')
        self._on_prmm_k_select()

    def _refresh_group_listbox(self):
        self.prmm_groups_listbox.delete(0, 'end')
        for name in sorted(self.prmm_p_groups.keys()):
            members = ', '.join(self._display_name(p) for p in self.prmm_p_groups.get(name, []))
            display_name = self._display_name(name)
            display = f"{display_name}: {members}" if members else display_name
            self.prmm_groups_listbox.insert('end', display)

    def _on_group_select(self, _event=None):
        selection = self.prmm_groups_listbox.curselection()
        if not selection:
            return
        idx = selection[0]
        names = sorted(self.prmm_p_groups.keys())
        if idx >= len(names):
            return
        group_name = names[idx]
        self.prmm_group_name_var.set(group_name)
        practices = self.prmm_p_groups.get(group_name, [])
        self._select_listbox_items(self.prmm_group_practices_listbox, practices, self.prmm_base_practices)

    def add_practice_group(self):
        name = (self.prmm_group_name_var.get() or '').strip()
        if not name:
            messagebox.showwarning('Missing name', 'Provide a group name first.')
            return
        if name in self.prmm_p_items and name not in self.prmm_p_groups:
            messagebox.showwarning('Name conflict', 'Group name conflicts with an existing practice.')
            return

        practices = self._selected_items(self.prmm_group_practices_listbox, self.prmm_base_practices)
        if not practices:
            messagebox.showwarning('No practices', 'Select at least one practice to include in the group.')
            return

        self.prmm_p_groups[name] = sorted(set(practices))
        self.refresh_prmm_sources()
        self.append_log(f'Added practice group {name} with {len(practices)} practice(s)')

    def remove_practice_group(self):
        name = (self.prmm_group_name_var.get() or '').strip()
        if not name:
            messagebox.showwarning('Missing name', 'Select or enter a group name to remove.')
            return
        if name not in self.prmm_p_groups:
            messagebox.showwarning('Not found', 'No such practice group exists.')
            return
        del self.prmm_p_groups[name]
        self.refresh_prmm_sources()
        self.append_log(f'Removed practice group {name}')

    def _selected_items(self, listbox, source_items):
        indices = listbox.curselection()
        return [source_items[i] for i in indices if 0 <= i < len(source_items)]

    def _select_listbox_items(self, listbox, items, source_items):
        listbox.selection_clear(0, 'end')
        wanted = set(items)
        for idx, item in enumerate(source_items):
            if item in wanted:
                listbox.selection_set(idx)

    def _on_prmm_k_select(self, _event=None):
        """When a K item is selected, show its current mapped D/P relations."""
        if not hasattr(self, 'prmm_k_listbox'):
            return

        selected_k = self._selected_items(self.prmm_k_listbox, self.prmm_k_items)
        if not selected_k:
            self.prmm_k_d_listbox.selection_clear(0, 'end')
            self.prmm_k_p_listbox.selection_clear(0, 'end')
            return

        related_d = set()
        related_p = set()
        for k in selected_k:
            rel = self.prmm_k_map.get(k, {'d': set(), 'p': set()})
            related_d.update(rel.get('d', set()))
            related_p.update(rel.get('p', set()))

        self._select_listbox_items(self.prmm_k_d_listbox, related_d, self.prmm_d_items)
        self._select_listbox_items(self.prmm_k_p_listbox, related_p, self.prmm_p_items)

    def add_dp_mapping(self):
        d_items = self._selected_items(self.prmm_d_listbox, self.prmm_d_items)
        p_items = self._selected_items(self.prmm_p_listbox, self.prmm_p_items)
        if not d_items or not p_items:
            messagebox.showwarning('Select items', 'Select at least one disruption and one practice.')
            return

        for d in d_items:
            self.prmm_dp_map.setdefault(d, set()).update(p_items)

        self._update_prmm_mapping_summary()
        self.append_log(f'Mapped {len(d_items)} D item(s) to {len(p_items)} P item(s)')

    def clear_dp_mappings(self):
        self.prmm_dp_map = {name: set() for name in self.prmm_d_items}
        self._update_prmm_mapping_summary()

    def add_k_mapping(self):
        k_items = self._selected_items(self.prmm_k_listbox, self.prmm_k_items)
        d_items = self._selected_items(self.prmm_k_d_listbox, self.prmm_d_items)
        p_items = self._selected_items(self.prmm_k_p_listbox, self.prmm_p_items)

        if not k_items:
            messagebox.showwarning('Select items', 'Select at least one query/K item.')
            return
        if not d_items or not p_items:
            messagebox.showwarning('Select items', 'Select at least one related disruption and one related practice.')
            return

        for k in k_items:
            self.prmm_k_map.setdefault(k, {'d': set(), 'p': set()})
            self.prmm_k_map[k]['d'].update(d_items)
            self.prmm_k_map[k]['p'].update(p_items)

        self._update_prmm_mapping_summary()
        self.append_log(f'Mapped {len(k_items)} K item(s) to {len(d_items)} D item(s) and {len(p_items)} P item(s)')

    def clear_k_mappings(self):
        self.prmm_k_map = {label: {'d': set(), 'p': set()} for label in self.prmm_k_items}
        self._update_prmm_mapping_summary()

    def set_k_direction(self, direction):
        k_items = self._selected_items(self.prmm_k_listbox, self.prmm_k_items)
        if not k_items:
            messagebox.showwarning('Select items', 'Select at least one query/K item.')
            return
        for k in k_items:
            self.prmm_k_dir_map[k] = direction
        self._update_prmm_mapping_summary()

    def set_k_benchmark_flag(self):
        messagebox.showinfo('Disabled', 'Benchmark/optimization flags are disabled in this version.')

    def set_practice_activation_query(self):
        practices = self._selected_items(self.prmm_p_listbox, self.prmm_p_items)
        k_items = self._selected_items(self.prmm_k_listbox, self.prmm_k_items)
        if not practices:
            messagebox.showwarning('Select items', 'Select at least one practice (P).')
            return
        if not k_items:
            messagebox.showwarning('Select items', 'Select a query (K) to use as activation counter.')
            return
        activation_k = list(k_items)
        for p in practices:
            self.prmm_p_activation_map[p] = activation_k
        self._update_prmm_mapping_summary()

    def clear_practice_activation_query(self):
        practices = self._selected_items(self.prmm_p_listbox, self.prmm_p_items)
        if not practices:
            messagebox.showwarning('Select items', 'Select at least one practice (P).')
            return
        for p in practices:
            self.prmm_p_activation_map[p] = []
        self._update_prmm_mapping_summary()

    def _set_prmm_status(self, msg):
        self.after(0, lambda: self.enable_status_var.set(msg))

    def _update_prmm_mapping_summary(self):
        lines = []
        lines.append('Practice groups:\n')
        if not self.prmm_p_groups:
            lines.append('  (none)\n')
        else:
            for group_name in sorted(self.prmm_p_groups):
                members = ', '.join(self._display_name(p) for p in self.prmm_p_groups.get(group_name, []))
                lines.append(f'  {self._display_name(group_name)}: {members}\n')

        lines.append('\nD -> P mappings:\n')
        if not any(self.prmm_dp_map.values()):
            lines.append('  (none)\n')
        else:
            for d in sorted(self.prmm_dp_map):
                practices = sorted(self.prmm_dp_map.get(d, set()))
                if practices:
                    label = self._display_name(d)
                    practice_labels = ', '.join(self._display_name(p) for p in practices)
                    lines.append(f'  {label}: {practice_labels}\n')

        lines.append('\nPractice activation queries:\n')
        any_activation = any(self.prmm_p_activation_map.get(p) for p in self.prmm_p_items)
        if not any_activation:
            lines.append('  (none)\n')
        else:
            for p in sorted(self.prmm_p_items):
                activation = self.prmm_p_activation_map.get(p) or []
                if activation:
                    lines.append(f'  {self._display_name(p)}: {", ".join(activation)}\n')

        lines.append('\nK -> D/P mappings:\n')
        if not any(v['d'] or v['p'] for v in self.prmm_k_map.values()):
            lines.append('  (none)\n')
        else:
            for k in sorted(self.prmm_k_map):
                rel = self.prmm_k_map.get(k, {'d': set(), 'p': set()})
                if rel['d'] or rel['p']:
                    direction = self.prmm_k_dir_map.get(k, 'higher')
                    d_labels = ', '.join(self._display_name(d) for d in sorted(rel['d']))
                    p_labels = ', '.join(self._display_name(p) for p in sorted(rel['p']))
                    lines.append(
                        f"  {k}: D[{d_labels}]  P[{p_labels}] dir={direction}\n"
                    )

        self.prmm_mapping_text.configure(state='normal')
        self.prmm_mapping_text.delete('1.0', 'end')
        self.prmm_mapping_text.insert('end', ''.join(lines))
        self.prmm_mapping_text.configure(state='disabled')

    def _status_from_activation_count(self, activation_count, has_activation_queries):
        if not has_activation_queries:
            return 'not_required'
        if activation_count is None:
            return 'unknown'
        if activation_count > 0:
            return 'confirmed_active'
        return 'confirmed_inactive'

    def _is_query_effectively_available(self, evidence):
        return evidence.get('kpi_query_exists') and evidence.get('baseline_value') is not None and evidence.get('practice_value') is not None

    def score_kpi_effectiveness_cell(self, evidence):
        if not evidence.get('mapping_exists'):
            return 0, 'no mapping exists'
        if not evidence.get('practice_exists_in_model') or not evidence.get('kpi_query_exists'):
            return 1, 'practice/query not implemented'
        activation_status = evidence.get('activation_status', 'not_required')
        if activation_status in ('confirmed_inactive', 'unknown') and evidence.get('activation_required', False):
            return 2, 'practice not activated'
        if evidence.get('baseline_value') is None or evidence.get('practice_value') is None:
            return 0, 'no valid KPI value'
        improvement = evidence.get('improvement')
        if improvement is None:
            return 0, 'improvement unavailable'
        if improvement <= evidence.get('tolerance', 0):
            return 3, 'no significant KPI improvement beyond tolerance'
        return 4, 'KPI improved beyond tolerance'

    def score_prmm_maturity_cell(self, evidence):
        if not evidence.get('mapping_exists'):
            return 0, 'not recognized'
        if not evidence.get('practice_exists_in_model') or not evidence.get('kpi_query_exists'):
            return 1, 'recognized informally but not operational'
        activation_status = evidence.get('activation_status', 'not_required')
        if activation_status in ('confirmed_inactive', 'unknown') and evidence.get('activation_required', False):
            return 2, 'documented, not applied'
        if evidence.get('baseline_value') is None or evidence.get('practice_value') is None:
            return 3, 'applied but not monitored'
        return 4, 'applied with KPIs'

    def _collect_prmm_cell_evidence(self, base_text, disruptions, practices, verifyta_path):
        def practice_exists(name):
            return name in practices or name in self.prmm_p_groups

        evidence_rows = []
        scenario_details = []
        skipped_items = []
        scenario_cache = {}
        activation_cache = {}
        baseline_runs = 0
        practice_runs = 0
        query_executions = 0
        kpi_query_executions = 0
        activation_query_executions = 0
        cache_hits = 0
        cache_misses = 0
        skipped_cells = 0

        valid_cells = []
        dp_pairs = {}
        for k_name, rel in self.prmm_k_map.items():
            d_related = sorted(rel.get('d', set()))
            p_related = sorted(rel.get('p', set()))
            if not d_related or not p_related:
                skipped_items.append({'item': k_name, 'reason': 'missing D or P mapping', 'excluded_from_denominator': True})
                continue
            query = self.prmm_k_query_map.get(k_name)
            if not query:
                skipped_items.append({'item': k_name, 'reason': 'query not found for K mapping', 'excluded_from_denominator': True})
                continue
            for d_name in d_related:
                for p_name in p_related:
                    valid_cells.append((k_name, d_name, p_name, query))
                    dp_pairs.setdefault((d_name, p_name), []).append(k_name)

        with tempfile.TemporaryDirectory(prefix='prmm_eval_') as tmpdir:
            baseline_context = {}

            def _run_and_cache_query(scenario_type, d_name, p_name, model_path, query):
                nonlocal cache_misses, query_executions, kpi_query_executions
                cache_key = (scenario_type, d_name) if scenario_type == 'baseline' else (scenario_type, d_name, p_name)
                scenario_bucket = scenario_cache.setdefault(cache_key, {})
                q_index = query.get('index')
                if q_index in scenario_bucket:
                    return scenario_bucket[q_index]
                cache_misses += 1
                row = self._run_single_query(verifyta_path, model_path, query)
                value, kind, method = self._extract_numeric_value(row)
                query_executions += 1
                kpi_query_executions += 1
                scenario_bucket[q_index] = {
                    'row': row,
                    'value': value,
                    'kind': kind,
                    'parse_method': method,
                    'result_line': row.get('result_text'),
                }
                return scenario_bucket[q_index]

            def _get_cached_query(scenario_type, d_name, p_name, query):
                nonlocal cache_hits
                cache_key = (scenario_type, d_name) if scenario_type == 'baseline' else (scenario_type, d_name, p_name)
                q_index = query.get('index')
                bucket = scenario_cache.get(cache_key, {})
                if q_index in bucket:
                    cache_hits += 1
                    return bucket[q_index]
                return None

            def _run_and_cache_activation(d_name, p_name, model_path, activation_query):
                nonlocal cache_misses, query_executions, activation_query_executions
                cache_key = (d_name, p_name, activation_query.get('index'))
                if cache_key in activation_cache:
                    return activation_cache[cache_key]
                cache_misses += 1
                row = self._run_single_query(verifyta_path, model_path, activation_query)
                value, _kind, method = self._extract_numeric_value(row)
                query_executions += 1
                activation_query_executions += 1
                activation_cache[cache_key] = {
                    'row': row,
                    'value': value,
                    'parse_method': method,
                    'result_line': row.get('result_text'),
                }
                return activation_cache[cache_key]

            for d_name in sorted(disruptions):
                self.append_log(f'PRMM: evaluating baseline for {d_name}')
                baseline_text = self._build_model_variant_text_multi(base_text, d_name, [])
                baseline_path = self._write_model_variant(tmpdir, f'baseline_{d_name}.xml', baseline_text)
                baseline_runs += 1
                baseline_enable_d, baseline_enable_p = self._extract_enable_states(baseline_text)
                baseline_context[d_name] = {
                    'baseline_path': baseline_path,
                    'baseline_enable_d': baseline_enable_d,
                    'baseline_enable_p': baseline_enable_p,
                    'baseline_name': f'baseline_{d_name}',
                }
                for k_name in sorted({k for (k, d, _p, _q) in valid_cells if d == d_name}):
                    query = self.prmm_k_query_map.get(k_name)
                    if query:
                        _run_and_cache_query('baseline', d_name, None, baseline_path, query)

            for (d_name, p_name), k_names in sorted(dp_pairs.items()):
                enabled_practices = list(self.prmm_p_groups.get(p_name, [p_name]))
                if not practice_exists(p_name):
                    for k_name in k_names:
                        evidence_rows.append({
                            'k_name': k_name, 'd_name': d_name, 'p_name': p_name,
                            'mapping_exists': True, 'practice_exists_in_model': False, 'kpi_query_exists': True,
                            'activation_required': False, 'activation_status': 'not_required', 'activation_count': None,
                            'baseline_value': None, 'practice_value': None, 'baseline_kind': None, 'practice_kind': None,
                            'baseline_raw_output': '', 'practice_raw_output': '', 'baseline_result_text': '', 'practice_result_text': '',
                            'parse_method': 'missing practice', 'parse_error': 'practice not in model', 'direction': self.prmm_k_dir_map.get(k_name, 'higher'),
                            'tolerance': self._kpi_tolerance('numeric'), 'warnings': ['practice not in model'],
                            'cache_metadata': {'baseline': False, 'practice': False, 'activation': False},
                            'activation_query_labels': self.prmm_p_activation_map.get(p_name, []),
                        })
                        skipped_cells += 1
                        skipped_items.append({'item': f'{k_name} / {d_name} / {p_name}', 'reason': 'practice not in model', 'excluded_from_denominator': True})
                    continue

                baseline_info = baseline_context[d_name]
                practice_text = self._build_model_variant_text_multi(base_text, d_name, enabled_practices)
                practice_path = self._write_model_variant(tmpdir, f'practice_{d_name}_{p_name}.xml', practice_text)
                practice_runs += 1
                practice_enable_d, practice_enable_p = self._extract_enable_states(practice_text)

                scenario_details.append({
                    'd_name': d_name,
                    'p_name': p_name,
                    'p_group': p_name if p_name in self.prmm_p_groups else None,
                    'practice_enabled_practices': enabled_practices,
                    'baseline_name': baseline_info['baseline_name'],
                    'practice_name': f'practice_{d_name}_{p_name}',
                    'baseline_enable_d': baseline_info['baseline_enable_d'],
                    'baseline_enable_p': baseline_info['baseline_enable_p'],
                    'practice_enable_d': practice_enable_d,
                    'practice_enable_p': practice_enable_p,
                    'baseline_path': baseline_info['baseline_path'],
                    'practice_path': practice_path,
                })

                for k_name in sorted(set(k_names)):
                    query = self.prmm_k_query_map.get(k_name)
                    if not query:
                        evidence_rows.append({
                            'k_name': k_name, 'd_name': d_name, 'p_name': p_name, 'mapping_exists': True,
                            'practice_exists_in_model': True, 'kpi_query_exists': False, 'activation_required': False,
                            'activation_status': 'not_required', 'activation_count': None, 'baseline_value': None, 'practice_value': None,
                            'baseline_kind': None, 'practice_kind': None, 'baseline_raw_output': '', 'practice_raw_output': '',
                            'baseline_result_text': '', 'practice_result_text': '', 'parse_method': 'missing query', 'parse_error': 'query not found',
                            'direction': self.prmm_k_dir_map.get(k_name, 'higher'), 'tolerance': self._kpi_tolerance('numeric'), 'warnings': ['query missing'],
                            'cache_metadata': {'baseline': False, 'practice': False, 'activation': False}, 'activation_query_labels': self.prmm_p_activation_map.get(p_name, []),
                        })
                        skipped_cells += 1
                        skipped_items.append({'item': f'{k_name} / {d_name} / {p_name}', 'reason': 'query missing', 'excluded_from_denominator': True})
                        continue

                    baseline_entry = _get_cached_query('baseline', d_name, None, query)
                    if baseline_entry is None:
                        baseline_entry = _run_and_cache_query('baseline', d_name, None, baseline_info['baseline_path'], query)
                    practice_entry = _run_and_cache_query('practice', d_name, p_name, practice_path, query)
                    activation_labels = self.prmm_p_activation_map.get(p_name) or []
                    if isinstance(activation_labels, str):
                        activation_labels = [activation_labels]
                    activation_entries = []
                    activation_values = []
                    for activation_label in activation_labels:
                        activation_query = self.prmm_k_query_map.get(activation_label)
                        if not activation_query:
                            continue
                        cached_activation = _run_and_cache_activation(d_name, p_name, practice_path, activation_query)
                        activation_entries.append({
                            'label': activation_label,
                            'index': activation_query.get('index'),
                            'formula': activation_query.get('formula'),
                            'parsed_value': cached_activation.get('value'),
                            'parse_method': cached_activation.get('parse_method'),
                            'raw_output': cached_activation.get('row', {}).get('raw_output'),
                            'result_text': cached_activation.get('row', {}).get('result_text'),
                        })
                        activation_values.append(cached_activation.get('value'))

                    activation_count = min([v for v in activation_values if v is not None], default=None) if activation_values else None
                    activation_required = bool(activation_labels)
                    activation_status = self._status_from_activation_count(activation_count, activation_required)
                    baseline_row = baseline_entry.get('row', {})
                    practice_row = practice_entry.get('row', {})
                    baseline_value = baseline_entry.get('value')
                    practice_value = practice_entry.get('value')
                    baseline_kind = baseline_entry.get('kind')
                    practice_kind = practice_entry.get('kind')
                    parse_method = practice_entry.get('parse_method') or baseline_entry.get('parse_method')
                    parse_error = None if baseline_value is not None and practice_value is not None else 'unable to parse numeric KPI'
                    direction = self.prmm_k_dir_map.get(k_name, 'higher')
                    tolerance = self._kpi_tolerance(practice_kind or baseline_kind)
                    improvement = self._calculate_improvement(baseline_value, practice_value, direction)
                    warnings = self._detect_suspicious_value(query.get('formula', ''), practice_value, practice_kind, baseline_value, practice_value)
                    evidence_rows.append({
                        'k_name': k_name,
                        'd_name': d_name,
                        'p_name': p_name,
                        'mapping_exists': True,
                        'practice_exists_in_model': True,
                        'kpi_query_exists': True,
                        'baseline_query_label': baseline_row.get('formula') or query.get('formula'),
                        'practice_query_label': practice_row.get('formula') or query.get('formula'),
                        'activation_query_labels': activation_labels,
                        'activation_queries': activation_entries,
                        'baseline_raw_output': baseline_row.get('raw_output', ''),
                        'practice_raw_output': practice_row.get('raw_output', ''),
                        'baseline_result_text': baseline_row.get('result_text', ''),
                        'practice_result_text': practice_row.get('result_text', ''),
                        'baseline_value': baseline_value,
                        'practice_value': practice_value,
                        'baseline_kind': baseline_kind,
                        'practice_kind': practice_kind,
                        'parse_method': parse_method,
                        'parse_error': parse_error,
                        'direction': direction,
                        'tolerance': tolerance,
                        'improvement': improvement,
                        'activation_count': activation_count,
                        'activation_status': activation_status,
                        'activation_required': activation_required,
                        'practice_query_exists': True,
                        'baseline_query_exists': True,
                        'warnings': warnings,
                        'cache_metadata': {
                            'baseline_cached': baseline_entry is not None,
                            'practice_cached': practice_entry is not None,
                            'activation_cached': bool(activation_entries),
                            'cache_hits': cache_hits,
                            'cache_misses': cache_misses,
                        },
                        'baseline_query': baseline_row,
                        'practice_query': practice_row,
                    })

        return {
            'cells': evidence_rows,
            'scenario_details': scenario_details,
            'skipped_items': skipped_items,
            'counts': {
                'baseline_runs': baseline_runs,
                'practice_runs': practice_runs,
                'query_executions': query_executions,
                'kpi_query_executions': kpi_query_executions,
                'activation_query_executions': activation_query_executions,
                'cache_hits': cache_hits,
                'cache_misses': cache_misses,
                'skipped_cells': skipped_cells,
                'evaluated_cells': len(evidence_rows),
                'unique_d_baselines': len(baseline_context),
                'unique_dp_practices': len(dp_pairs),
            },
        }

    def _aggregate_kpi_effectiveness_results(self, evidence_rows):
        cells = []
        for evidence in evidence_rows:
            score, reason = self.score_kpi_effectiveness_cell(evidence)
            cell = dict(evidence)
            cell['score'] = score
            cell['reason'] = reason
            cells.append(cell)

        scores = [cell.get('score', 0) for cell in cells]
        evaluated_cells = len(cells)
        total_score = sum(score for score in scores if isinstance(score, (int, float)))
        final_effectiveness_score = (total_score / (evaluated_cells * 5.0) * 100.0) if evaluated_cells else 0.0

        def pct_at_or_above(threshold):
            return (sum(1 for score in scores if score >= threshold) / evaluated_cells) * 100.0 if evaluated_cells else 0.0

        result = {
            'cells': cells,
            'evaluated_cells': evaluated_cells,
            'skipped_cells': sum(1 for cell in cells if cell.get('score') in (0, 1)),
            'final_effectiveness_score': final_effectiveness_score,
            'level_scores': {
                1: pct_at_or_above(1),
                2: pct_at_or_above(2),
                3: pct_at_or_above(3),
                4: pct_at_or_above(4),
                5: 0.0,
            },
        }
        return result

    def _aggregate_prmm_maturity_results(self, evidence_rows):
        cells = []
        for evidence in evidence_rows:
            score, reason = self.score_prmm_maturity_cell(evidence)
            cell = dict(evidence)
            cell['score'] = score
            cell['reason'] = reason
            cell['gate_L1_recognized'] = bool(evidence.get('mapping_exists'))
            cell['gate_L2_implemented'] = bool(
                evidence.get('mapping_exists')
                and evidence.get('practice_exists_in_model')
                and evidence.get('kpi_query_exists')
            )
            activation_status = evidence.get('activation_status', 'not_required')
            cell['gate_L3_applied_monitored'] = bool(
                cell['gate_L2_implemented']
                and activation_status in ('confirmed_active', 'not_required')
                and evidence.get('baseline_value') is not None
                and evidence.get('practice_value') is not None
            )
            cell['gate_L4_improved_or_optimized'] = bool(
                cell['gate_L3_applied_monitored']
                and evidence.get('improvement') is not None
                and evidence.get('improvement') > evidence.get('tolerance', 0)
            )
            cell['gate_L5_benchmark'] = False
            cells.append(cell)

        evaluated_cells = len(cells)
        def pct_from_gate(gate_name):
            return (sum(1 for cell in cells if cell.get(gate_name)) / evaluated_cells) * 100.0 if evaluated_cells else 0.0

        diagnostic_scores = {
            1: pct_from_gate('gate_L1_recognized'),
            2: pct_from_gate('gate_L2_implemented'),
            3: pct_from_gate('gate_L3_applied_monitored'),
            4: pct_from_gate('gate_L4_improved_or_optimized'),
            5: 0.0,
        }
        cascaded = {1: diagnostic_scores[1], 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
        if cascaded[1] >= 60:
            cascaded[2] = diagnostic_scores[2]
        if cascaded[2] >= 60:
            cascaded[3] = diagnostic_scores[3]
        if cascaded[3] >= 60:
            cascaded[4] = diagnostic_scores[4]
        if cascaded[4] >= 60:
            cascaded[5] = 0.0
        weighted_prmm = 0.05 * cascaded[1] + 0.10 * cascaded[2] + 0.25 * cascaded[3] + 0.30 * cascaded[4] + 0.30 * cascaded[5]
        if weighted_prmm >= 90:
            category = 'Benchmark-Aligned Excellence'
        elif weighted_prmm >= 80:
            category = 'Continuous Optimization'
        elif weighted_prmm >= 70:
            category = 'Practice-Linked Resilience'
        elif weighted_prmm >= 60:
            category = 'Conceptual Readiness'
        else:
            category = 'Early Awareness'
        return {
            'cells': cells,
            'evaluated_cells': evaluated_cells,
            'final_weighted_prmm': weighted_prmm,
            'diagnostic_scores': diagnostic_scores,
            'cascaded_scores': cascaded,
            'category': category,
            'gate_definitions': {
                1: 'recognition coverage',
                2: 'implementation/documentation coverage',
                3: 'applied and monitored with KPIs',
                4: 'improvement/optimization evidence beyond tolerance',
                5: 'benchmark/excellence not implemented yet',
            },
        }

    def _update_kpi_effectiveness_dashboard(self, summary):
        self.kpi_effectiveness_summary_var.set(f"KPI Effectiveness Score: {summary['final_effectiveness_score']:.1f}%")
        for level in range(1, 6):
            score = summary['level_scores'][level]
            if level == 5:
                self.kpi_effectiveness_level_vars[level].set('Level 5: 0.0% NOT IMPLEMENTED - Score 5 / benchmark-based effectiveness is not implemented yet.')
            else:
                status = 'PASS' if score >= 60 else 'FAIL'
                self.kpi_effectiveness_level_vars[level].set(f'Level {level}: {score:.1f}% {status}')
        self.kpi_effectiveness_counts_var.set(f"Evaluated cells: {summary['evaluated_cells']} | Skipped cells: {summary['skipped_cells']}")
        self.kpi_effectiveness_report_var.set(getattr(self, 'last_kpi_effectiveness_report_path', 'Report path: —'))
        for item in self.kpi_activation_table.get_children():
            self.kpi_activation_table.delete(item)
        for item in self.kpi_results_table.get_children():
            self.kpi_results_table.delete(item)
        for cell in summary['cells']:
            for activation in cell.get('activation_queries') or []:
                self.kpi_activation_table.insert('', 'end', values=(activation.get('formula'), self._format_number(activation.get('parsed_value')), self._status_from_activation_count(activation.get('parsed_value'), True)))
            self.kpi_results_table.insert('', 'end', values=(
                cell.get('k_name'),
                self._clean_kpi_name(cell.get('k_name')),
                cell.get('direction'),
                self._format_number(cell.get('baseline_value')),
                self._format_number(cell.get('practice_value')),
                self._format_improvement(cell.get('improvement')),
                cell.get('score'),
                'Improved' if cell.get('score', 0) >= 4 else 'Not improved',
            ))

    def _update_prmm_maturity_dashboard(self, summary):
        self.prmm_summary_matrix_var.set(f"S1 recognition coverage: {summary['diagnostic_scores'][1]:.1f}%")
        self.prmm_summary_weighted_var.set(f"Weighted PRMM final score: {summary['final_weighted_prmm']:.1f}%")
        self.prmm_summary_category_var.set(f"Maturity category: {summary['category']}")
        self.prmm_summary_activation_var.set('Activation status: see per-cell results')
        self.prmm_summary_counts_var.set(f"Evaluated cells: {summary['evaluated_cells']}")
        self.prmm_summary_report_var.set(getattr(self, 'last_prmm_maturity_report_path', 'Report path: —'))
        for level in range(1, 6):
            diagnostic = summary['diagnostic_scores'][level]
            cascaded = summary['cascaded_scores'][level]
            if level == 5:
                self.prmm_level_vars[level].set('S5: benchmark/excellence not implemented yet | 0.0%')
            else:
                status = 'PASS' if diagnostic >= 60 else 'FAIL'
                labels = summary.get('gate_definitions', {})
                self.prmm_level_vars[level].set(f"S{level}: {labels.get(level, '')} | diagnostic {diagnostic:.1f}% | cascaded {cascaded:.1f}% | {status}")
        for item in self.prmm_activation_table.get_children():
            self.prmm_activation_table.delete(item)
        for item in self.prmm_results_table.get_children():
            self.prmm_results_table.delete(item)
        for cell in summary['cells']:
            activation_entries = cell.get('activation_queries') or []
            if activation_entries:
                for activation in activation_entries:
                    self.prmm_activation_table.insert('', 'end', values=(activation.get('formula'), self._format_number(activation.get('parsed_value')), self._status_from_activation_count(activation.get('parsed_value'), True)))
            self.prmm_results_table.insert('', 'end', values=(
                cell.get('k_name'),
                self._clean_kpi_name(cell.get('k_name')),
                cell.get('direction'),
                self._format_number(cell.get('baseline_value')),
                self._format_number(cell.get('practice_value')),
                self._format_improvement(cell.get('improvement')),
                cell.get('score'),
                'Applied with KPIs' if cell.get('score', 0) >= 4 else cell.get('reason'),
            ))

    def _build_score_report(self, mode, summary, model, disruptions, practices):
        title = 'KPI Effectiveness Evaluation Report' if mode == 'kpi' else 'PRMM Maturity Evaluation Report'
        lines = [f"# {title}\n", f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n", '## Methodology\n']
        if mode == 'kpi':
            lines.append('This score evaluates whether a resilience practice improves each KPI compared with the disrupted baseline scenario.\n')
        else:
            lines.append('This score evaluates the maturity state of each D × P × K relation using separate evidence gates for recognition, implementation, monitoring, and optimization.\n')
        lines.append('\n## Scoring Table\n')
        if mode == 'kpi':
            lines.append('0 = no valid KPI value\n1 = practice/query not implemented\n2 = practice not activated\n3 = no significant KPI improvement beyond tolerance\n4 = KPI improved beyond tolerance\n5 = not implemented yet / benchmark effectiveness is not added\n')
        else:
            lines.append('S1 = recognition coverage\nS2 = implementation/documentation coverage\nS3 = applied and monitored with KPIs\nS4 = improvement/optimization evidence beyond tolerance\nS5 = benchmark/excellence not implemented yet\n')
            lines.append('Score 5 is intentionally not assigned in this version because benchmark-based maturity is not implemented yet.\n')
        lines.append('\n## Summary\n')
        lines.append(f"- Evaluated cells: {summary['evaluated_cells']}\n")
        if mode == 'kpi':
            lines.append(f"- Final KPI effectiveness score: {summary['final_effectiveness_score']:.1f}%\n")
            for level in range(1, 6):
                value = summary['level_scores'][level]
                lines.append(f"- L{level}: {value:.1f}%{' (not implemented yet)' if level == 5 else ''}\n")
            lines.append('Level 5 / benchmark-based effectiveness is not implemented yet.\n')
        else:
            lines.append(f"- S1: {summary['diagnostic_scores'][1]:.1f}%\n")
            lines.append(f"- S2: {summary['diagnostic_scores'][2]:.1f}%\n")
            lines.append(f"- S3: {summary['diagnostic_scores'][3]:.1f}%\n")
            lines.append(f"- S4: {summary['diagnostic_scores'][4]:.1f}%\n")
            lines.append('- S5: 0.0%\n')
            lines.append(f"- S1 cascaded: {summary['cascaded_scores'][1]:.1f}%\n")
            lines.append(f"- S2 cascaded: {summary['cascaded_scores'][2]:.1f}%\n")
            lines.append(f"- S3 cascaded: {summary['cascaded_scores'][3]:.1f}%\n")
            lines.append(f"- S4 cascaded: {summary['cascaded_scores'][4]:.1f}%\n")
            lines.append('- S5 cascaded: 0.0%\n')
            lines.append(f"- Weighted PRMM final score: {summary['final_weighted_prmm']:.1f}%\n")
            lines.append(f"- PRMM maturity category: {summary['category']}\n")
            lines.append('Level-specific D/P/K scopes were not configured; all evaluated cells were used as the default scope.\n')
            lines.append('S4 is calculated from the gate: applied and monitored, improvement available, and improvement greater than tolerance.\n')
        lines.append('\n## Per-cell Results\n')
        for cell in summary['cells']:
            lines.append(f"### D={cell.get('d_name')} / P={cell.get('p_name')} / K={cell.get('k_name')}\n")
            lines.append(f"- Mapping exists: {cell.get('mapping_exists')}\n")
            lines.append(f"- Practice exists in model: {cell.get('practice_exists_in_model')}\n")
            lines.append(f"- KPI query exists: {cell.get('kpi_query_exists')}\n")
            lines.append(f"- Gate L1 recognized: {cell.get('gate_L1_recognized')}\n")
            lines.append(f"- Gate L2 implemented: {cell.get('gate_L2_implemented')}\n")
            lines.append(f"- Gate L3 applied and monitored: {cell.get('gate_L3_applied_monitored')}\n")
            lines.append(f"- Gate L4 improved or optimized: {cell.get('gate_L4_improved_or_optimized')}\n")
            lines.append(f"- Gate L5 benchmark: {cell.get('gate_L5_benchmark')}\n")
            lines.append(f"- Baseline value: {cell.get('baseline_value')}\n")
            lines.append(f"- Practice value: {cell.get('practice_value')}\n")
            lines.append(f"- Direction: {cell.get('direction')}\n")
            lines.append(f"- Tolerance: {cell.get('tolerance')}\n")
            lines.append(f"- Activation status: {cell.get('activation_status')}\n")
            lines.append(f"- Activation count: {cell.get('activation_count')}\n")
            lines.append(f"- Score: {cell.get('score')}\n")
            lines.append(f"- Reason: {cell.get('reason')}\n")
            improvement = cell.get('improvement')
            tolerance = cell.get('tolerance')
            improvement_gt_tolerance = bool(
                improvement is not None and tolerance is not None and improvement > tolerance
            )
            lines.append('- S4 calculation details:\n')
            lines.append(f"  - Direction: {cell.get('direction')}\n")
            lines.append(f"  - Baseline value: {cell.get('baseline_value')}\n")
            lines.append(f"  - Practice value: {cell.get('practice_value')}\n")
            lines.append('- Improvement formula: practice - baseline when direction is higher; baseline - practice when direction is lower\n')
            lines.append(f"  - Improvement value: {improvement}\n")
            lines.append(f"  - Tolerance: {tolerance}\n")
            lines.append(f"  - Improvement > tolerance: {improvement_gt_tolerance}\n")
            lines.append(f"- Warnings: {', '.join(cell.get('warnings') or []) or '(none)'}\n")
            lines.append(f"- Parse method: {cell.get('parse_method')}\n")
            if cell.get('parse_error'):
                lines.append(f"- Parse error: {cell.get('parse_error')}\n")
        lines.append('\n## Skipped / Unmapped Items\n')
        if not summary.get('skipped_items'):
            lines.append('- (none)\n')
        else:
            for item in summary.get('skipped_items', []):
                lines.append(f"- {item.get('item')}: {item.get('reason')} (excluded={item.get('excluded_from_denominator')})\n")
        return ''.join(lines)

    def calculate_kpi_effectiveness(self):
        model = self.model_var.get()
        if not model or not os.path.isfile(model):
            messagebox.showerror('Error', 'Please select a valid model file first.')
            return
        if uqr is None:
            messagebox.showerror('Missing dependency', 'uppaal_query_runner module is not available.')
            return
        resolved_verifyta = self._resolve_verifyta(self.verifyta_var.get())
        if not resolved_verifyta:
            messagebox.showerror('verifyta not found', 'Select a valid verifyta executable first.')
            return

        def worker():
            try:
                self.set_status('Calculating KPI effectiveness...')
                text = read_text(Path(model))
                disruptions, practices = self._extract_enable_states(text)
                evidence = self._collect_prmm_cell_evidence(text, disruptions, practices, resolved_verifyta)
                summary = self._aggregate_kpi_effectiveness_results(evidence['cells'])
                summary['skipped_items'] = evidence['skipped_items']
                summary['counts'] = evidence['counts']
                summary['scenario_details'] = evidence['scenario_details']
                self.last_kpi_effectiveness_data = {
                    'model': model,
                    'disruptions': disruptions,
                    'practices': practices,
                    'summary': summary,
                }
                report_text = self._build_score_report('kpi', summary, model, disruptions, practices)
                report_path = Path(model).with_name('KPI_Effectiveness_Report.md')
                report_path.write_text(report_text, encoding='utf-8')
                self.last_kpi_effectiveness_report_path = str(report_path)
                self.after(0, lambda: self._update_kpi_effectiveness_dashboard(summary))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror('Error', f'Failed to calculate KPI effectiveness:\n{exc}'))
            finally:
                self.after(0, lambda: self.set_status('Ready'))

        threading.Thread(target=worker, daemon=True).start()

    def calculate_prmm_maturity(self):
        model = self.model_var.get()
        if not model or not os.path.isfile(model):
            messagebox.showerror('Error', 'Please select a valid model file first.')
            return
        if uqr is None:
            messagebox.showerror('Missing dependency', 'uppaal_query_runner module is not available.')
            return
        resolved_verifyta = self._resolve_verifyta(self.verifyta_var.get())
        if not resolved_verifyta:
            messagebox.showerror('verifyta not found', 'Select a valid verifyta executable first.')
            return

        def worker():
            try:
                self.set_status('Calculating PRMM maturity...')
                text = read_text(Path(model))
                disruptions, practices = self._extract_enable_states(text)
                evidence = self._collect_prmm_cell_evidence(text, disruptions, practices, resolved_verifyta)
                summary = self._aggregate_prmm_maturity_results(evidence['cells'])
                summary['skipped_items'] = evidence['skipped_items']
                summary['counts'] = evidence['counts']
                summary['scenario_details'] = evidence['scenario_details']
                self.last_prmm_maturity_data = {
                    'model': model,
                    'disruptions': disruptions,
                    'practices': practices,
                    'summary': summary,
                }
                report_text = self._build_score_report('prmm', summary, model, disruptions, practices)
                report_path = Path(model).with_name('PRMM_Maturity_Report.md')
                report_path.write_text(report_text, encoding='utf-8')
                self.last_prmm_maturity_report_path = str(report_path)
                self.after(0, lambda: self._update_prmm_maturity_dashboard(summary))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror('Error', f'Failed to calculate PRMM maturity:\n{exc}'))
            finally:
                self.after(0, lambda: self.set_status('Ready'))

        threading.Thread(target=worker, daemon=True).start()

    def export_kpi_effectiveness_report(self):
        if not hasattr(self, 'last_kpi_effectiveness_data'):
            messagebox.showwarning('Not calculated', 'Run KPI Effectiveness Evaluation first.')
            return
        messagebox.showinfo('Report saved', f"KPI Effectiveness report saved to:\n{self.last_kpi_effectiveness_report_path}")

    def export_prmm_maturity_report(self):
        if not hasattr(self, 'last_prmm_maturity_data'):
            messagebox.showwarning('Not calculated', 'Run PRMM Maturity Evaluation first.')
            return
        messagebox.showinfo('Report saved', f"PRMM Maturity report saved to:\n{self.last_prmm_maturity_report_path}")

    def calculate_prmm(self):
        """Calculate PRMM maturity score using KPI improvement between baseline and practice scenarios."""
        model = self.model_var.get()
        if not model or not os.path.isfile(model):
            messagebox.showerror('Error', 'Please select a valid model file first.')
            return

        if uqr is None:
            messagebox.showerror('Missing dependency', 'uppaal_query_runner module is not available.')
            return

        if not self.prmm_dp_map or not any(self.prmm_dp_map.values()):
            messagebox.showwarning(
                'No D -> P mappings',
                'Define at least one D -> P mapping before calculating PRMM.',
            )
            return

        if not self.prmm_k_map or not any(v['d'] and v['p'] for v in self.prmm_k_map.values()):
            messagebox.showwarning(
                'No PRMM mappings',
                'Define at least one K -> D/P mapping (with both D and P) before calculating.',
            )
            return

        resolved_verifyta = self._resolve_verifyta(self.verifyta_var.get())
        if not resolved_verifyta:
            messagebox.showerror('verifyta not found', 'Select a valid verifyta executable first.')
            return

        self.prmm_calc_btn.configure(state='disabled')
        self.set_status('Calculating PRMM (KPI-based)...')
        self.append_log('PRMM: Starting calculation...')

        def worker():
            try:
                self.refresh_prmm_sources()
                self.append_log('PRMM: Sources refreshed. Entering scenario evaluation (scenario caching)...')

                text = read_text(Path(model))
                enable_patterns = re.findall(r'const\s+bool\s+(ENABLE_[DP]_\w+)\s*=\s*(true|false)', text)
                disruptions = {name: val.lower() == 'true' for name, val in enable_patterns if name.startswith('ENABLE_D_')}
                practices = {name: val.lower() == 'true' for name, val in enable_patterns if name.startswith('ENABLE_P_')}

                self.last_prmm_data = {
                    'model': model,
                    'disruptions': disruptions,
                    'practices': practices,
                    'dp_map': {k: sorted(v) for k, v in self.prmm_dp_map.items()},
                    'k_map': {k: {'d': sorted(v['d']), 'p': sorted(v['p'])} for k, v in self.prmm_k_map.items()},
                    'k_dir_map': dict(self.prmm_k_dir_map),
                    'p_activation_map': dict(self.prmm_p_activation_map),
                    'p_groups': dict(self.prmm_p_groups),
                }

                self._update_prmm_info(model, disruptions, practices)

                score_data = self._calculate_prmm_scores(
                    base_text=text,
                    disruptions=disruptions,
                    practices=practices,
                    verifyta_path=resolved_verifyta,
                )

                levels = {f'Level {i}': self.__dict__[f'level{i}_var'].get() for i in range(1, 6)}
                final_score = self.final_score_var.get()
                recommendations = self.prmm_recommendations_text.get('1.0', 'end').strip()
                self.last_prmm_data.update({
                    'levels': levels,
                    'final_score': final_score,
                    'recommendations': recommendations,
                    'matrix_scores': score_data.get('matrix_scores', {}),
                    'unmapped_k': score_data.get('unmapped_k', []),
                    'mapped_k': score_data.get('mapped_k', []),
                    'cell_results': score_data.get('cell_results', []),
                    'prmm_counts': score_data.get('prmm_counts', {}),
                    'prmm_completed': score_data.get('prmm_completed', False),
                    'scenario_details': score_data.get('scenario_details', []),
                    'skipped_items': score_data.get('skipped_items', []),
                    'maturity_category': self.maturity_category_var.get(),
                })
                self.after(0, lambda: self._update_prmm_dashboard(score_data))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror('Error', f'Failed to calculate PRMM:\n{e}'))
            finally:
                def _enable():
                    self.prmm_calc_btn.configure(state='normal')
                    self.set_status('Ready')
                self.after(0, _enable)

        threading.Thread(target=worker, daemon=True).start()

    def _update_prmm_info(self, model, disruptions, practices):
        """Update PRMM info display."""
        info_text = f"Model: {Path(model).name}\n\n"
        info_text += f"Enabled Disruptions ({sum(1 for v in disruptions.values() if v)}/{len(disruptions)}):\n"
        for name, enabled in sorted(disruptions.items()):
            status = "✓ ENABLED" if enabled else "✗ disabled"
            info_text += f"  {self._display_name(name)}: {status}\n"
        
        info_text += f"\nEnabled Practices ({sum(1 for v in practices.values() if v)}/{len(practices)}):\n"
        for name, enabled in sorted(practices.items()):
            status = "✓ ENABLED" if enabled else "✗ disabled"
            info_text += f"  {self._display_name(name)}: {status}\n"

        self.prmm_info_text.configure(state='normal')
        self.prmm_info_text.delete('1.0', 'end')
        self.prmm_info_text.insert('end', info_text)
        self.prmm_info_text.configure(state='disabled')

    def _build_model_variant_text(self, text, d_name, p_name, d_on, p_on):
        """Return a model text where all D/P are off except the target D/P flags."""
        pattern = re.compile(
            r'(^\s*const\s+bool\s+(ENABLE_[DP]_\w+)\s*=\s*)(true|false)(\s*;.*)$',
            re.MULTILINE,
        )

        def repl(match):
            name = match.group(2)
            if name == d_name:
                value = 'true' if d_on else 'false'
            elif name == p_name:
                value = 'true' if p_on else 'false'
            else:
                value = 'false'
            return f"{match.group(1)}{value}{match.group(4)}"

        return pattern.sub(repl, text)

    def _build_model_variant_text_multi(self, text, d_name, enabled_practices):
        """Return a model text with one D enabled and selected practices enabled."""
        pattern = re.compile(
            r'(^\s*const\s+bool\s+(ENABLE_[DP]_\w+)\s*=\s*)(true|false)(\s*;.*)$',
            re.MULTILINE,
        )
        enabled_set = set(enabled_practices or [])

        def repl(match):
            name = match.group(2)
            if name.startswith('ENABLE_D_'):
                value = 'true' if name == d_name else 'false'
            elif name.startswith('ENABLE_P_'):
                value = 'true' if name in enabled_set else 'false'
            else:
                value = 'false'
            return f"{match.group(1)}{value}{match.group(4)}"

        return pattern.sub(repl, text)

    def _extract_enable_states(self, text):
        matches = re.findall(r'const\s+bool\s+(ENABLE_[DP]_\w+)\s*=\s*(true|false)', text)
        disruptions = {}
        practices = {}
        for name, value in matches:
            enabled = value.lower() == 'true'
            if name.startswith('ENABLE_D_'):
                disruptions[name] = enabled
            elif name.startswith('ENABLE_P_'):
                practices[name] = enabled
        return disruptions, practices

    def _write_model_variant(self, tmpdir, filename, text):
        safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', filename)
        path = os.path.join(tmpdir, safe_name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def _run_single_query(self, verifyta_path, model_path, query):
        rows = uqr.run_verifyta_for_queries(model_path, [query], verifyta_path=verifyta_path, trace_dir=None, logger=None)
        return rows[0] if rows else {}

    def _clean_output_text(self, text):
        if not text:
            return ''
        cleaned = ANSI_ESCAPE_RE.sub('', text)
        return cleaned

    def _extract_numeric_value_from_text(self, raw, result_text, query_type):
        raw_clean = self._clean_output_text(raw)
        result_clean = self._clean_output_text(result_text)

        match = PROB_RE.search(raw_clean) or PROB_RE.search(result_clean)
        if match:
            try:
                success = int(match.group('success'))
                runs = int(match.group('runs'))
                value = success / runs if runs else 0.0
                return value, 'probability', 'probability'
            except Exception:
                return None, None, 'probability'

        match = EST_RE.search(raw_clean) or EST_RE.search(result_clean)
        if match:
            try:
                value = float(match.group('value'))
                return value, 'numeric', 'estimate'
            except Exception:
                return None, None, 'estimate'

        match = EST_APPROX_RE.search(raw_clean) or EST_APPROX_RE.search(result_clean)
        if match:
            try:
                value = float(match.group('value'))
                return value, 'numeric', 'estimate_approx'
            except Exception:
                return None, None, 'estimate_approx'

        mean_match = MEAN_RE.search(raw_clean)
        if mean_match:
            try:
                value = float(mean_match.group('value'))
                return value, 'numeric', 'mean_line'
            except Exception:
                return None, None, 'mean_line'

        if query_type == 'probability':
            num_match = re.search(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', result_clean)
            if num_match:
                try:
                    return float(num_match.group(0)), 'probability', 'query_type_fallback'
                except Exception:
                    return None, None, 'query_type_fallback'

        num_match = re.search(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', result_clean)
        if num_match:
            try:
                return float(num_match.group(0)), 'numeric', 'numeric_fallback'
            except Exception:
                return None, None, 'numeric_fallback'

        return None, None, 'none'

    def _extract_numeric_value(self, row):
        if not row:
            return None, None, 'none'

        raw = row.get('raw_output') or ''
        result_text = row.get('result_text') or ''
        query_type = row.get('query_type') or ''
        return self._extract_numeric_value_from_text(raw, result_text, query_type)

    def _detect_suspicious_value(self, formula, value, kind, baseline_value, practice_value):
        warnings = []
        text = (formula or '').lower()
        if value is None:
            warnings.append('missing parsed value')
            return warnings
        if value < 0:
            warnings.append('negative value detected')
        if kind == 'probability' and (value < 0 or value > 1):
            warnings.append('probability outside [0,1]')
        if 'availability' in text and value < 10:
            warnings.append('availability below 10%')
        if baseline_value is not None and practice_value is not None:
            delta = abs(practice_value - baseline_value)
            if baseline_value != 0 and delta > abs(baseline_value) * 10:
                warnings.append('very large unexpected change')
        return warnings

    def _calculate_improvement(self, baseline_value, practice_value, direction):
        if baseline_value is None or practice_value is None:
            return None
        if direction == 'lower':
            return baseline_value - practice_value
        return practice_value - baseline_value

    def _kpi_tolerance(self, kind):
        if kind == 'probability':
            return 0.005
        return 0.5

    def _score_cell(self, improvement, tolerance, activation_count, has_activation, benchmark_flag):
        if improvement is None:
            return 0, 'no KPI value'
        if has_activation and (activation_count is None or activation_count == 0):
            return 2, 'practice not activated'
        if improvement <= tolerance:
            return 3, 'no KPI improvement beyond tolerance'
        if benchmark_flag:
            return 5, 'KPI improved and benchmark/optimization flagged'
        return 4, 'KPI improved beyond tolerance'

    def _make_cell_result(self, k_name, d_name, p_name, baseline_value, practice_value, improvement, activation_count, score, reason):
        return {
            'k_name': k_name,
            'd_name': d_name,
            'p_name': p_name,
            'baseline_value': baseline_value,
            'practice_value': practice_value,
            'improvement': improvement,
            'activation_count': activation_count,
            'score': score,
            'reason': reason,
        }

    def _calculate_prmm_scores(self, base_text, disruptions, practices, verifyta_path):
        """Calculate PRMM scores using KPI improvement between baseline and practice scenarios."""
        def practice_exists(name):
            return name in practices or name in self.prmm_p_groups

        mapped_k = []
        unmapped_k = []
        matrix_scores = {}
        cell_results = []
        scenario_details = []
        skipped_items = []
        scenario_cache = {}
        activation_cache = {}
        baseline_runs = 0
        practice_runs = 0
        query_executions = 0
        kpi_query_executions = 0
        activation_query_executions = 0
        cache_hits = 0
        cache_misses = 0
        skipped_cells = 0
        dp_k_map = {}
        d_k_map = {}
        d_p_map = {}

        with tempfile.TemporaryDirectory(prefix='prmm_eval_') as tmpdir:
            for k_name, rel in self.prmm_k_map.items():
                d_related = sorted(rel.get('d', set()))
                p_related = sorted(rel.get('p', set()))
                if not d_related or not p_related:
                    unmapped_k.append(k_name)
                    skipped_items.append({
                        'item': k_name,
                        'reason': 'missing D or P mapping',
                        'excluded_from_denominator': True,
                    })
                    continue

                query = self.prmm_k_query_map.get(k_name)
                if not query:
                    unmapped_k.append(k_name)
                    skipped_cells += len(d_related) * len(p_related)
                    skipped_items.append({
                        'item': k_name,
                        'reason': 'query not found for K mapping',
                        'excluded_from_denominator': True,
                    })
                    continue

                mapped_k.append(k_name)
                matrix_scores.setdefault(k_name, {'cells': []})

                for d_name in d_related:
                    for p_name in p_related:
                        dp_k_map.setdefault((d_name, p_name), []).append(k_name)

            valid_dp_k_map = {}
            for (d_name, p_name), k_names in dp_k_map.items():
                if not practice_exists(p_name):
                    for k_name in k_names:
                        cell_score = 1
                        cell = self._make_cell_result(k_name, d_name, p_name, None, None, None, None, cell_score, 'practice not in model')
                        cell_results.append(cell)
                        matrix_scores[k_name]['cells'].append(cell)
                        skipped_cells += 1
                        skipped_items.append({
                            'item': f'{k_name} / {d_name} / {p_name}',
                            'reason': 'practice not in model',
                            'excluded_from_denominator': True,
                        })
                    continue

                valid_dp_k_map[(d_name, p_name)] = k_names
                d_p_map.setdefault(d_name, set()).add(p_name)
                d_k_map.setdefault(d_name, set()).update(k_names)

            def _run_and_cache_query(scenario_type, d_name, p_name, model_path, query):
                nonlocal cache_misses, query_executions, kpi_query_executions
                if scenario_type == 'baseline':
                    cache_key = (scenario_type, d_name)
                else:
                    cache_key = (scenario_type, d_name, p_name)
                scenario_bucket = scenario_cache.setdefault(cache_key, {})
                q_index = query.get('index')
                if q_index in scenario_bucket:
                    return scenario_bucket[q_index]

                cache_misses += 1
                row = self._run_single_query(verifyta_path, model_path, query)
                value, kind, method = self._extract_numeric_value(row)
                query_executions += 1
                kpi_query_executions += 1
                scenario_bucket[q_index] = {
                    'row': row,
                    'value': value,
                    'kind': kind,
                    'parsing_method': method,
                    'result_line': row.get('result_text'),
                }
                return scenario_bucket[q_index]

            def _get_cached_query(scenario_type, d_name, p_name, query):
                nonlocal cache_hits
                if scenario_type == 'baseline':
                    cache_key = (scenario_type, d_name)
                else:
                    cache_key = (scenario_type, d_name, p_name)
                q_index = query.get('index')
                scenario_bucket = scenario_cache.get(cache_key, {})
                if q_index in scenario_bucket:
                    cache_hits += 1
                    return scenario_bucket[q_index]
                return None

            def _run_and_cache_activation(d_name, p_name, model_path, activation_query):
                nonlocal cache_misses, query_executions, activation_query_executions
                a_index = activation_query.get('index')
                cache_key = (d_name, p_name, a_index)
                if cache_key in activation_cache:
                    return activation_cache[cache_key]

                cache_misses += 1
                row = self._run_single_query(verifyta_path, model_path, activation_query)
                value, _kind, method = self._extract_numeric_value(row)
                query_executions += 1
                activation_query_executions += 1
                activation_cache[cache_key] = {
                    'row': row,
                    'value': value,
                    'parsing_method': method,
                    'result_line': row.get('result_text'),
                }
                return activation_cache[cache_key]

            def _get_cached_activation(d_name, p_name, activation_query):
                nonlocal cache_hits
                a_index = activation_query.get('index')
                cache_key = (d_name, p_name, a_index)
                if cache_key in activation_cache:
                    cache_hits += 1
                    return activation_cache[cache_key]
                return None

            baseline_context = {}
            for d_name, p_names in d_p_map.items():
                self.append_log(f"PRMM: Evaluating disrupted baseline D={d_name} with scenario caching")
                self.append_log(f"PRMM: Baseline config: {d_name}=true, all ENABLE_P_*=false, all other D/P=false")

                baseline_text = self._build_model_variant_text_multi(base_text, d_name, [])
                baseline_path = self._write_model_variant(tmpdir, f"baseline_{d_name}.xml", baseline_text)
                baseline_runs += 1

                baseline_enable_d, baseline_enable_p = self._extract_enable_states(baseline_text)
                baseline_context[d_name] = {
                    'baseline_path': baseline_path,
                    'baseline_enable_d': baseline_enable_d,
                    'baseline_enable_p': baseline_enable_p,
                    'baseline_name': f'baseline_{d_name}',
                }

                d_k_names = []
                for k_name in sorted(d_k_map.get(d_name, set())):
                    d_k_names.append(k_name)

                for k_name in d_k_names:
                    query = self.prmm_k_query_map.get(k_name)
                    if not query:
                        continue
                    self.append_log(f"PRMM: Query formula (baseline): {query.get('formula', '')}")
                    _run_and_cache_query('baseline', d_name, None, baseline_path, query)

            for (d_name, p_name), k_names in valid_dp_k_map.items():
                enabled_practices = list(self.prmm_p_groups.get(p_name, [p_name]))
                group_name = p_name if p_name in self.prmm_p_groups else None
                enabled_practice_text = ', '.join(enabled_practices)
                self.append_log(f"PRMM: Evaluating D/P pair D={d_name} P={p_name} with scenario caching")
                self.append_log(
                    f"PRMM: Practice config: {d_name}=true, {enabled_practice_text} enabled, all other D/P=false"
                )

                baseline_info = baseline_context.get(d_name, {})
                baseline_path = baseline_info.get('baseline_path')
                baseline_enable_d = baseline_info.get('baseline_enable_d', {})
                baseline_enable_p = baseline_info.get('baseline_enable_p', {})
                baseline_name = baseline_info.get('baseline_name', f'baseline_{d_name}')

                practice_text = self._build_model_variant_text_multi(base_text, d_name, enabled_practices)
                practice_path = self._write_model_variant(tmpdir, f"practice_{d_name}_{p_name}.xml", practice_text)
                practice_runs += 1

                practice_enable_d, practice_enable_p = self._extract_enable_states(practice_text)

                scenario_details.append({
                    'd_name': d_name,
                    'p_name': p_name,
                    'p_group': group_name,
                    'practice_enabled_practices': enabled_practices,
                    'baseline_name': baseline_name,
                    'practice_name': f'practice_{d_name}_{p_name}',
                    'baseline_enable_d': baseline_enable_d,
                    'baseline_enable_p': baseline_enable_p,
                    'practice_enable_d': practice_enable_d,
                    'practice_enable_p': practice_enable_p,
                    'baseline_path': baseline_path,
                    'practice_path': practice_path,
                })

                unique_k_names = []
                seen_k = set()
                for k_name in k_names:
                    if k_name not in seen_k:
                        seen_k.add(k_name)
                        unique_k_names.append(k_name)

                for k_name in unique_k_names:
                    query = self.prmm_k_query_map.get(k_name)
                    if not query:
                        continue
                    self.append_log(f"PRMM: Query formula (practice): {query.get('formula', '')}")
                    _run_and_cache_query('practice', d_name, p_name, practice_path, query)

                for k_name in unique_k_names:
                    query = self.prmm_k_query_map.get(k_name)
                    if not query:
                        continue

                    self.append_log(f"PRMM: Evaluating cell K={k_name} D={d_name} P={p_name}")

                    baseline_entry = _get_cached_query('baseline', d_name, None, query)
                    practice_entry = _get_cached_query('practice', d_name, p_name, query)
                    if not baseline_entry or not practice_entry:
                        skipped_cells += 1
                        skipped_items.append({
                            'item': f'{k_name} / {d_name} / {p_name}',
                            'reason': 'missing cached scenario result',
                            'excluded_from_denominator': True,
                        })
                        continue

                    baseline_row = baseline_entry.get('row', {})
                    practice_row = practice_entry.get('row', {})
                    baseline_value = baseline_entry.get('value')
                    practice_value = practice_entry.get('value')
                    baseline_kind = baseline_entry.get('kind')
                    practice_kind = practice_entry.get('kind')
                    baseline_method = baseline_entry.get('parsing_method')
                    practice_method = practice_entry.get('parsing_method')

                    if baseline_row.get('command'):
                        self.append_log(f"PRMM: verifyta command (baseline): {baseline_row.get('command')}")
                    if practice_row.get('command'):
                        self.append_log(f"PRMM: verifyta command (practice): {practice_row.get('command')}")
                    if baseline_row.get('raw_output'):
                        self.append_log(f"PRMM: verifyta raw output (baseline): {baseline_row.get('raw_output')}")
                    if practice_row.get('raw_output'):
                        self.append_log(f"PRMM: verifyta raw output (practice): {practice_row.get('raw_output')}")

                    self.append_log(f"PRMM: Parsed baseline value: {baseline_value}")
                    self.append_log(f"PRMM: Parsed practice value: {practice_value}")

                    if baseline_value is None or practice_value is None:
                        cell_score = 0
                        cell = self._make_cell_result(k_name, d_name, p_name, baseline_value, practice_value, None, None, cell_score, 'no numeric KPI')
                        cell['baseline_parse_method'] = baseline_method
                        cell['practice_parse_method'] = practice_method
                        cell['baseline_query'] = {
                            'index': baseline_row.get('index'),
                            'formula': baseline_row.get('formula'),
                            'status': baseline_row.get('status'),
                            'returncode': baseline_row.get('returncode'),
                            'success': baseline_row.get('returncode') == 0,
                            'raw_output': baseline_row.get('raw_output'),
                            'result_text': baseline_row.get('result_text'),
                            'parsed_value': baseline_value,
                            'parse_method': baseline_method,
                            'parse_error': 'unable to parse numeric KPI',
                        }
                        cell['practice_query'] = {
                            'index': practice_row.get('index'),
                            'formula': practice_row.get('formula'),
                            'status': practice_row.get('status'),
                            'returncode': practice_row.get('returncode'),
                            'success': practice_row.get('returncode') == 0,
                            'raw_output': practice_row.get('raw_output'),
                            'result_text': practice_row.get('result_text'),
                            'parsed_value': practice_value,
                            'parse_method': practice_method,
                            'parse_error': 'unable to parse numeric KPI',
                        }
                        cell_results.append(cell)
                        matrix_scores[k_name]['cells'].append(cell)
                        continue

                    activation_query_labels = self.prmm_p_activation_map.get(p_name) or []
                    if isinstance(activation_query_labels, str):
                        activation_query_labels = [activation_query_labels]
                    activation_count = None
                    activation_query_info = []
                    activation_values = []
                    if activation_query_labels:
                        for activation_label in activation_query_labels:
                            activation_query = self.prmm_k_query_map.get(activation_label)
                            if not activation_query:
                                continue
                            _run_and_cache_activation(d_name, p_name, practice_path, activation_query)
                            activation_entry = _get_cached_activation(d_name, p_name, activation_query)
                            if not activation_entry:
                                continue
                            activation_row = activation_entry.get('row', {})
                            activation_value = activation_entry.get('value')
                            activation_method = activation_entry.get('parsing_method')
                            activation_values.append(activation_value)
                            if activation_row.get('command'):
                                self.append_log(f"PRMM: verifyta command (activation): {activation_row.get('command')}")
                            if activation_row.get('raw_output'):
                                self.append_log(f"PRMM: verifyta raw output (activation): {activation_row.get('raw_output')}")
                            activation_query_info.append({
                                'index': activation_row.get('index'),
                                'formula': activation_row.get('formula'),
                                'status': activation_row.get('status'),
                                'returncode': activation_row.get('returncode'),
                                'success': activation_row.get('returncode') == 0,
                                'raw_output': activation_row.get('raw_output'),
                                'result_text': activation_row.get('result_text'),
                                'parsed_value': activation_value,
                                'parse_method': activation_method,
                                'parse_error': None if activation_value is not None else 'unable to parse numeric KPI',
                            })
                        if activation_values and all(v is not None for v in activation_values):
                            activation_count = min(activation_values)

                    direction = self.prmm_k_dir_map.get(k_name, 'higher')
                    tolerance = self._kpi_tolerance(baseline_kind or practice_kind)
                    improvement = self._calculate_improvement(baseline_value, practice_value, direction)
                    self.append_log(f"PRMM: Improvement: {improvement}")
                    if activation_query_labels:
                        self.append_log(f"PRMM: Activation count: {activation_count}")

                    benchmark_flag = False
                    cell_score, reason = self._score_cell(
                        improvement=improvement,
                        tolerance=tolerance,
                        activation_count=activation_count,
                        has_activation=bool(activation_query_labels),
                        benchmark_flag=benchmark_flag,
                    )

                    self.append_log(f"PRMM: Assigned score: {cell_score} ({reason})")

                    cell = self._make_cell_result(
                        k_name,
                        d_name,
                        p_name,
                        baseline_value,
                        practice_value,
                        improvement,
                        activation_count,
                        cell_score,
                        reason,
                    )
                    cell['direction'] = direction
                    cell['tolerance'] = tolerance
                    cell['benchmark_flag'] = benchmark_flag
                    cell['baseline_parse_method'] = baseline_method
                    cell['practice_parse_method'] = practice_method
                    cell['baseline_query'] = {
                        'index': baseline_row.get('index'),
                        'formula': baseline_row.get('formula'),
                        'status': baseline_row.get('status'),
                        'returncode': baseline_row.get('returncode'),
                        'success': baseline_row.get('returncode') == 0,
                        'raw_output': baseline_row.get('raw_output'),
                        'result_text': baseline_row.get('result_text'),
                        'parsed_value': baseline_value,
                        'parse_method': baseline_method,
                        'parse_error': None if baseline_value is not None else 'unable to parse numeric KPI',
                    }
                    cell['practice_query'] = {
                        'index': practice_row.get('index'),
                        'formula': practice_row.get('formula'),
                        'status': practice_row.get('status'),
                        'returncode': practice_row.get('returncode'),
                        'success': practice_row.get('returncode') == 0,
                        'raw_output': practice_row.get('raw_output'),
                        'result_text': practice_row.get('result_text'),
                        'parsed_value': practice_value,
                        'parse_method': practice_method,
                        'parse_error': None if practice_value is not None else 'unable to parse numeric KPI',
                    }
                    cell['activation_query'] = activation_query_info
                    cell['activation_queries'] = activation_query_info
                    cell['warnings'] = self._detect_suspicious_value(
                        query.get('formula', ''),
                        practice_value,
                        practice_kind,
                        baseline_value,
                        practice_value,
                    )
                    cell_results.append(cell)
                    matrix_scores[k_name]['cells'].append(cell)

        if not cell_results:
            raise RuntimeError('No applicable D/P/K cells were found. Add K -> D/P mappings first.')

        evaluated_cells = len(cell_results)
        prmm_counts = {
            'baseline_runs': baseline_runs,
            'practice_runs': practice_runs,
            'query_executions': query_executions,
            'kpi_query_executions': kpi_query_executions,
            'activation_query_executions': activation_query_executions,
            'evaluated_cells': evaluated_cells,
            'skipped_cells': skipped_cells,
            'cache_hits': cache_hits,
            'cache_misses': cache_misses,
            'unique_dp_pairs': len(valid_dp_k_map),
            'unique_d_baselines': len(d_p_map),
            'unique_dp_practices': len(valid_dp_k_map),
        }

        scores = [cell['score'] for cell in cell_results]
        total_cells = len(cell_results)
        prmm_matrix_score = sum(scores) / (total_cells * 5.0) * 100.0

        def pct_at_or_above(threshold):
            return (sum(1 for score in scores if score >= threshold) / total_cells) * 100.0 if total_cells else 0.0

        score_l1 = pct_at_or_above(1)
        score_l2 = pct_at_or_above(2)
        score_l3 = pct_at_or_above(3)
        score_l4 = pct_at_or_above(4)
        score_l5 = pct_at_or_above(5)

        for level, score in enumerate([score_l1, score_l2, score_l3, score_l4, score_l5], start=1):
            status = "PASS" if score >= 60 else "FAIL"
            self.__dict__[f'level{level}_var'].set(f"{score:.1f}% {status}")

        self.final_score_var.set(f"{prmm_matrix_score:.1f}%")

        if prmm_matrix_score >= 90:
            category = 'Benchmark-Aligned Excellence'
        elif prmm_matrix_score >= 80:
            category = 'Continuous Optimization'
        elif prmm_matrix_score >= 70:
            category = 'Practice-Linked Resilience'
        elif prmm_matrix_score >= 60:
            category = 'Conceptual Readiness'
        else:
            category = 'Early Awareness'

        self.maturity_category_var.set(category)
        self._generate_prmm_recommendations(prmm_matrix_score, mapped_k, unmapped_k, score_l4, score_l5)
        return {
            'matrix_scores': matrix_scores,
            'mapped_k': mapped_k,
            'unmapped_k': unmapped_k,
            'cell_results': cell_results,
            'scenario_details': scenario_details,
            'skipped_items': skipped_items,
            'prmm_counts': prmm_counts,
            'prmm_completed': evaluated_cells > 0 and query_executions > 0,
        }

    def _generate_prmm_recommendations(self, final_score, mapped_k, unmapped_k, score_l4, score_l5):
        """Generate improvement recommendations based on maturity gaps."""
        recommendations = "Recommendations for Improving Resilience Maturity:\n\n"
        
        if final_score < 60:
            recommendations += "CRITICAL: Process is in Early Awareness stage.\n"
            recommendations += "  - Prioritize structured risk identification and documentation\n"
            recommendations += "  - Define and implement basic resilience practices\n"
            recommendations += "  - Establish KPI tracking mechanisms\n\n"
        elif final_score < 70:
            recommendations += "NEEDS IMPROVEMENT: Process shows Conceptual Readiness.\n"
            recommendations += "  - Move from documented to applied practices\n"
            recommendations += "  - Link practices to measurable KPIs\n"
            recommendations += "  - Establish feedback mechanisms\n\n"
        else:
            recommendations += "GOOD FOUNDATION: Process demonstrates Practice-Linked Resilience or better.\n\n"
        
        if unmapped_k:
            recommendations += f"- Unmapped K items were excluded from scoring: {len(unmapped_k)}\n"

        if len(mapped_k) < 2:
            recommendations += "- Map more queries/K items to D and P to stabilize the evaluation\n"
        
        if score_l4 < 70:
            recommendations += "- Implement continuous optimization: establish monthly resilience performance reviews\n"
            recommendations += "- Create closed-loop corrective action cycles linking disruption analysis to preventive actions\n"
        
        if score_l5 < 80:
            recommendations += "- Benchmark KPIs against industry standards (e.g., IATF 16949, automotive standards)\n"
            recommendations += "- Develop external comparison mechanisms and best practice adoption plans\n"
        
        recommendations += f"\nCurrent Status:\n"
        recommendations += f"- Mapped K items: {len(mapped_k)}\n"
        recommendations += f"- Unmapped K items excluded: {len(unmapped_k)}\n"
        recommendations += f"- Overall Score: {final_score:.1f}%\n"
        
        self.prmm_recommendations_text.configure(state='normal')
        self.prmm_recommendations_text.delete('1.0', 'end')
        self.prmm_recommendations_text.insert('end', recommendations)
        self.prmm_recommendations_text.configure(state='disabled')

    def export_prmm_report(self):
        """Export the last-calculated PRMM evaluation to a Markdown report."""
        if not hasattr(self, 'last_prmm_data'):
            if messagebox.askyesno('Not calculated', 'PRMM has not been calculated yet. Calculate now?'):
                self.calculate_prmm()
                return
            else:
                return

        data = getattr(self, 'last_prmm_data', None)
        if not data:
            messagebox.showerror('No data', 'No PRMM data available to export.')
            return

        if not data.get('prmm_completed'):
            messagebox.showerror(
                'No completed PRMM calculation',
                'No completed PRMM calculation available. Please click Calculate Maturity first.',
            )
            return

        model = Path(data.get('model'))
        default_name = f"{model.stem}_PRMM_report.md"
        path = filedialog.asksaveasfilename(title='Save PRMM report', defaultextension='.md', initialfile=default_name, filetypes=[('Markdown','*.md'), ('Text','*.txt')])
        if not path:
            return

        lines = []
        lines.append(f"# PRMM Evaluation Report — {model.name}\n")
        lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        lines.append('## Model\n')
        lines.append(f"- Path: {data.get('model')}\n")

        lines.append('## Enabled Disruptions\n')
        for name, en in sorted(data['disruptions'].items()):
            lines.append(f"- {self._display_name_with_code(name)}: {'ENABLED' if en else 'disabled'}\n")

        lines.append('\n## Enabled Practices\n')
        for name, en in sorted(data['practices'].items()):
            lines.append(f"- {self._display_name_with_code(name)}: {'ENABLED' if en else 'disabled'}\n")

        lines.append('\n## User-defined Relationships\n')
        lines.append('### Practice Groups\n')
        groups = data.get('p_groups', {})
        if not groups:
            lines.append('- (none)\n')
        else:
            for name, members in sorted(groups.items()):
                member_labels = ', '.join(self._display_name_with_code(p) for p in members)
                lines.append(f"- {self._display_name_with_code(name)}: {member_labels}\n")
        lines.append('### D -> P\n')
        for d, practices in sorted(data.get('dp_map', {}).items()):
            if practices:
                d_label = self._display_name_with_code(d)
                p_labels = ', '.join(self._display_name_with_code(p) for p in practices)
                lines.append(f"- {d_label}: {p_labels}\n")
        lines.append('### Practice Activation Queries\n')
        activation_map = data.get('p_activation_map', {})
        if not any(activation_map.values()):
            lines.append('- (none)\n')
        else:
            for p, k in sorted(activation_map.items()):
                queries = k or []
                if isinstance(queries, str):
                    queries = [queries]
                if queries:
                    lines.append(f"- {self._display_name_with_code(p)}: {', '.join(queries)}\n")
        lines.append('### K -> D/P\n')
        for k, rel in sorted(data.get('k_map', {}).items()):
            if rel.get('d') or rel.get('p'):
                direction = data.get('k_dir_map', {}).get(k, 'higher')
                d_labels = ', '.join(self._display_name_with_code(d) for d in rel.get('d', []))
                p_labels = ', '.join(self._display_name_with_code(p) for p in rel.get('p', []))
                lines.append(
                    f"- {k}: D[{d_labels}] P[{p_labels}] dir={direction}\n"
                )

        lines.append('\n## Calculation Details\n')
        # Include level scores and matrix scores
        levels = data.get('levels', {})
        for k, v in levels.items():
            lines.append(f"- {k}: {v}\n")

        lines.append('\n## Scenario Caching Details\n')
        counts = data.get('prmm_counts', {})
        lines.append(f"- Unique D baselines evaluated: {counts.get('unique_d_baselines', 0)}\n")
        lines.append(f"- Unique D-P practice scenarios evaluated: {counts.get('unique_dp_practices', 0)}\n")
        lines.append(f"- Baseline scenario runs: {counts.get('baseline_runs', 0)}\n")
        lines.append(f"- Practice scenario runs: {counts.get('practice_runs', 0)}\n")
        lines.append(f"- KPI query executions: {counts.get('kpi_query_executions', 0)}\n")
        lines.append(f"- Activation query executions: {counts.get('activation_query_executions', 0)}\n")
        lines.append(f"- Cache hits: {counts.get('cache_hits', 0)}\n")
        lines.append(f"- Cache misses: {counts.get('cache_misses', 0)}\n")
        lines.append(
            "\nBaseline caching was applied by disruption. The same disrupted baseline was executed once per D and "
            "reused across all practices mapped to that disruption.\n"
        )

        cells = data.get('cell_results', [])
        scores = [cell.get('score', 0) for cell in cells]
        evaluated_cells = len(cells)
        sum_scores = sum(score for score in scores if isinstance(score, (int, float)))
        max_score = evaluated_cells * 5

        def pct_at_or_above(threshold):
            return (sum(1 for score in scores if score >= threshold) / evaluated_cells) * 100.0 if evaluated_cells else 0.0

        l1 = pct_at_or_above(1)
        l2 = pct_at_or_above(2)
        l3 = pct_at_or_above(3)
        l4 = pct_at_or_above(4)
        l5 = pct_at_or_above(5)
        matrix_effectiveness = (sum_scores / max_score) * 100.0 if max_score else 0.0
        weighted_prmm = 0.05 * l1 + 0.10 * l2 + 0.25 * l3 + 0.30 * l4 + 0.30 * l5

        improved = sum(1 for cell in cells if cell.get('score', 0) >= 4)
        not_improved = evaluated_cells - improved

        activation_rows = {}
        for cell in cells:
            entries = cell.get('activation_queries') or cell.get('activation_query')
            if not entries:
                continue
            if isinstance(entries, dict):
                entries = [entries]
            for entry in entries:
                formula = entry.get('formula') or ''
                activation_rows[formula] = entry.get('parsed_value')

        activation_status = 'N/A'
        if activation_rows:
            activation_status = 'PASS' if all(v is not None and v > 0 for v in activation_rows.values()) else 'FAIL'

        lines.append('\n## Results Dashboard\n')
        lines.append(f"- Matrix effectiveness score: {matrix_effectiveness:.1f}%\n")
        lines.append(f"- Weighted PRMM final score: {weighted_prmm:.1f}%\n")
        lines.append(f"- Maturity category: {data.get('maturity_category', self.maturity_category_var.get())}\n")
        lines.append(f"- Improved KPIs: {improved} / {evaluated_cells}\n")
        lines.append(f"- Not improved KPIs: {not_improved} / {evaluated_cells}\n")
        lines.append(f"- Activation status: {activation_status}\n")

        if activation_rows:
            lines.append('\n### Activation Status\n')
            lines.append('| Activation query | Value | Status |\n')
            lines.append('| --- | --- | --- |\n')
            for formula, value in sorted(activation_rows.items()):
                status = 'PASS' if value is not None and value > 0 else 'FAIL'
                lines.append(f"| {formula} | {self._format_number(value)} | {status} |\n")

        lines.append('\n### KPI Results\n')
        lines.append('| KPI | Clean KPI name | Direction | Baseline | Practice | Improvement | Score | Result |\n')
        lines.append('| --- | --- | --- | --- | --- | --- | --- | --- |\n')
        for cell in cells:
            k_name = cell.get('k_name', '')
            kpi_code_match = re.match(r'^(Q\d+)', k_name)
            kpi_code = kpi_code_match.group(1) if kpi_code_match else k_name
            clean_name = self._clean_kpi_name(k_name)
            direction = cell.get('direction', '')
            baseline = self._format_number(cell.get('baseline_value'))
            practice = self._format_number(cell.get('practice_value'))
            improvement = self._format_improvement(cell.get('improvement'))
            score = cell.get('score', '')
            result = 'Improved' if isinstance(score, (int, float)) and score >= 4 else 'Not improved'
            lines.append(
                f"| {kpi_code} | {clean_name} | {direction} | {baseline} | {practice} | {improvement} | {score} | {result} |\n"
            )

        lines.append('\n## Scenario Construction Details\n')
        for item in data.get('scenario_details', []):
            d_name = item.get('d_name')
            p_name = item.get('p_name')
            lines.append(f"### D={self._display_name_with_code(d_name)} / P={self._display_name_with_code(p_name)}\n")
            if item.get('p_group'):
                lines.append(f"- Practice group: {self._display_name_with_code(item.get('p_group'))}\n")
                enabled = item.get('practice_enabled_practices', [])
                if enabled:
                    enabled_labels = ', '.join(self._display_name_with_code(p) for p in enabled)
                    lines.append(f"- Practices enabled in group: {enabled_labels}\n")
            lines.append(f"- Baseline scenario name: {item.get('baseline_name')}\n")
            lines.append(f"- Practice scenario name: {item.get('practice_name')}\n")
            lines.append(f"- Baseline XML path: {item.get('baseline_path')}\n")
            lines.append(f"- Practice XML path: {item.get('practice_path')}\n")
            lines.append('- Baseline ENABLE_D_* values:\n')
            for name, enabled in sorted(item.get('baseline_enable_d', {}).items()):
                lines.append(f"  - {self._display_name_with_code(name)}: {'ENABLED' if enabled else 'disabled'}\n")
            lines.append('- Baseline ENABLE_P_* values:\n')
            for name, enabled in sorted(item.get('baseline_enable_p', {}).items()):
                lines.append(f"  - {self._display_name_with_code(name)}: {'ENABLED' if enabled else 'disabled'}\n")
            lines.append('- Practice ENABLE_D_* values:\n')
            for name, enabled in sorted(item.get('practice_enable_d', {}).items()):
                lines.append(f"  - {self._display_name_with_code(name)}: {'ENABLED' if enabled else 'disabled'}\n")
            lines.append('- Practice ENABLE_P_* values:\n')
            for name, enabled in sorted(item.get('practice_enable_p', {}).items()):
                lines.append(f"  - {self._display_name_with_code(name)}: {'ENABLED' if enabled else 'disabled'}\n")

        lines.append('\n## Query Execution Evidence\n')
        for cell in data.get('cell_results', []):
            d_label = self._display_name_with_code(cell.get('d_name'))
            p_label = self._display_name_with_code(cell.get('p_name'))
            lines.append(f"### {cell.get('k_name')} / {d_label} / {p_label}\n")
            for label, q in [('Baseline', cell.get('baseline_query')), ('Practice', cell.get('practice_query'))]:
                if not q:
                    continue
                lines.append(f"- {label} query index: {q.get('index')}\n")
                lines.append(f"- {label} query formula: {q.get('formula')}\n")
                lines.append(f"- {label} verifyta success: {q.get('success')}\n")
                lines.append(f"- {label} status: {q.get('status')}\n")
                lines.append(f"- {label} parsed value: {q.get('parsed_value')}\n")
                lines.append(f"- {label} parsing method: {q.get('parse_method')}\n")
                if q.get('parse_error'):
                    lines.append(f"- {label} parse error: {q.get('parse_error')}\n")
                if q.get('result_text'):
                    lines.append(f"- {label} result line: {q.get('result_text')}\n")
                if q.get('raw_output'):
                    lines.append(f"- {label} raw output:\n\n```\n{q.get('raw_output')}\n```\n")
            activation_entries = cell.get('activation_queries') or cell.get('activation_query')
            if activation_entries:
                if isinstance(activation_entries, dict):
                    activation_entries = [activation_entries]
                for activation in activation_entries:
                    lines.append(f"- Activation query index: {activation.get('index')}\n")
                    lines.append(f"- Activation query formula: {activation.get('formula')}\n")
                    lines.append(f"- Activation verifyta success: {activation.get('success')}\n")
                    lines.append(f"- Activation parsed value: {activation.get('parsed_value')}\n")
                    lines.append(f"- Activation parsing method: {activation.get('parse_method')}\n")
                    if activation.get('parse_error'):
                        lines.append(f"- Activation parse error: {activation.get('parse_error')}\n")
                    if activation.get('result_text'):
                        lines.append(f"- Activation result line: {activation.get('result_text')}\n")
                    if activation.get('raw_output'):
                        lines.append(f"- Activation raw output:\n\n```\n{activation.get('raw_output')}\n```\n")

        lines.append('\n## Per-cell PRMM Explanation\n')
        for cell in data.get('cell_results', []):
            d_label = self._display_name_with_code(cell.get('d_name'))
            p_label = self._display_name_with_code(cell.get('p_name'))
            lines.append(f"### {cell.get('k_name')} / {d_label} / {p_label}\n")
            lines.append(f"- KPI direction: {cell.get('direction')}\n")
            lines.append(f"- Baseline value: {cell.get('baseline_value')}\n")
            lines.append(f"- Practice value: {cell.get('practice_value')}\n")
            lines.append("- Improvement formula used: practice - baseline (higher) or baseline - practice (lower)\n")
            lines.append(f"- Improvement value: {cell.get('improvement')}\n")
            lines.append(f"- Tolerance used: {cell.get('tolerance')}\n")
            activation_entries = cell.get('activation_queries') or cell.get('activation_query')
            has_activation = bool(activation_entries)
            lines.append(f"- Activation query used: {'yes' if has_activation else 'no'}\n")
            if activation_entries:
                if isinstance(activation_entries, dict):
                    activation_entries = [activation_entries]
                values = [entry.get('parsed_value') for entry in activation_entries]
                lines.append(f"- Activation values: {values}\n")
            else:
                lines.append("- Activation values: (none)\n")
            lines.append(f"- Final score: {cell.get('score')}\n")
            lines.append(f"- Reason: {cell.get('reason')}\n")
            warnings = cell.get('warnings') or []
            if warnings:
                lines.append(f"- Warnings: {', '.join(warnings)}\n")

        lines.append('\n## Matrix Scores\n')
        for cell in data.get('cell_results', []):
            d_label = self._display_name_with_code(cell.get('d_name'))
            p_label = self._display_name_with_code(cell.get('p_name'))
            lines.append(
                f"- {cell.get('k_name')} / {d_label} / {p_label}: "
                f"baseline={cell.get('baseline_value')} practice={cell.get('practice_value')} "
                f"improvement={cell.get('improvement')} activation={cell.get('activation_count')} "
                f"score={cell.get('score')} reason={cell.get('reason')}\n"
            )

        cells = data.get('cell_results', [])
        scores = [cell.get('score', 0) for cell in cells]
        evaluated_cells = len(cells)
        sum_scores = sum(score for score in scores if isinstance(score, (int, float)))
        max_score = evaluated_cells * 5

        def pct_at_or_above(threshold):
            return (sum(1 for score in scores if score >= threshold) / evaluated_cells) * 100.0 if evaluated_cells else 0.0

        l1 = pct_at_or_above(1)
        l2 = pct_at_or_above(2)
        l3 = pct_at_or_above(3)
        l4 = pct_at_or_above(4)
        l5 = pct_at_or_above(5)
        matrix_effectiveness = (sum_scores / max_score) * 100.0 if max_score else 0.0
        weighted_prmm = 0.05 * l1 + 0.10 * l2 + 0.25 * l3 + 0.30 * l4 + 0.30 * l5

        lines.append('\n## Score Aggregation\n')
        lines.append(f"- Evaluated cells: {evaluated_cells}\n")
        lines.append(f"- Skipped cells: {data.get('prmm_counts', {}).get('skipped_cells', 0)}\n")
        lines.append(f"- Sum of cell scores: {sum_scores}\n")
        lines.append(f"- Maximum possible score: {max_score}\n")
        lines.append(f"- Matrix effectiveness score: {matrix_effectiveness:.1f}%\n")
        lines.append(f"- Level 1: {l1:.1f}%\n")
        lines.append(f"- Level 2: {l2:.1f}%\n")
        lines.append(f"- Level 3: {l3:.1f}%\n")
        lines.append(f"- Level 4: {l4:.1f}%\n")
        lines.append(f"- Level 5: {l5:.1f}%\n")
        lines.append(f"- Weighted PRMM final score: {weighted_prmm:.1f}%\n")

        lines.append('\n## Skipped / N/A Items\n')
        skipped = data.get('skipped_items', [])
        if not skipped:
            lines.append('- (none)\n')
        else:
            for item in skipped:
                lines.append(
                    f"- {item.get('item')}: {item.get('reason')} "
                    f"(excluded from denominator={item.get('excluded_from_denominator')})\n"
                )

        lines.append('\n## Suspicious Value Warnings\n')
        any_warning = False
        for cell in cells:
            warnings = cell.get('warnings') or []
            if warnings:
                any_warning = True
                lines.append(f"- {cell.get('k_name')} / {cell.get('d_name')} / {cell.get('p_name')}: {', '.join(warnings)}\n")
        if not any_warning:
            lines.append('- (none)\n')

        lines.append(f"\n## Final Composite Score\n- {data.get('final_score')}\n")

        lines.append('\n## Final Interpretation\n')
        lines.append(f"- Matrix effectiveness score: {matrix_effectiveness:.1f}%\n")
        lines.append(f"- Weighted PRMM final score: {weighted_prmm:.1f}%\n")
        lines.append(f"- Maturity category: {data.get('maturity_category', self.maturity_category_var.get())}\n")
        reasons = {}
        improved = set()
        not_improved = set()
        for cell in cells:
            reason = cell.get('reason')
            if reason:
                reasons[reason] = reasons.get(reason, 0) + 1
            if cell.get('score', 0) >= 4:
                improved.add(cell.get('k_name'))
            else:
                not_improved.add(cell.get('k_name'))
        if reasons:
            top_reasons = sorted(reasons.items(), key=lambda x: x[1], reverse=True)[:5]
            lines.append('- Main reasons for lost points:\n')
            for reason, count in top_reasons:
                lines.append(f"  - {reason} ({count})\n")
        if improved:
            lines.append(f"- Main KPIs improved: {', '.join(sorted(improved))}\n")
        if not_improved:
            lines.append(f"- Main KPIs not improved: {', '.join(sorted(not_improved))}\n")

        lines.append('\n## Recommendations\n')
        rec = data.get('recommendations', '')
        if rec:
            lines.append(rec + '\n')
        else:
            lines.append('No recommendations available.\n')

        # Include raw counts and simple calculation notes
        num_d = sum(1 for v in data['disruptions'].values() if v)
        num_p = sum(1 for v in data['practices'].values() if v)
        counts = data.get('prmm_counts', {})
        lines.append('\n## Raw Counts and Notes\n')
        lines.append(f"- Active Disruptions: {num_d}\n")
        lines.append(f"- Active Practices: {num_p}\n")
        if counts:
            lines.append(f"- Baseline scenario runs: {counts.get('baseline_runs', 0)}\n")
            lines.append(f"- Practice scenario runs: {counts.get('practice_runs', 0)}\n")
            lines.append(f"- Query executions: {counts.get('query_executions', 0)}\n")
            lines.append(f"- KPI query executions: {counts.get('kpi_query_executions', 0)}\n")
            lines.append(f"- Activation query executions: {counts.get('activation_query_executions', 0)}\n")
            lines.append(f"- Evaluated D-P-K cells: {counts.get('evaluated_cells', 0)}\n")
            lines.append(f"- Skipped cells: {counts.get('skipped_cells', 0)}\n")
            lines.append(f"- Cache hits: {counts.get('cache_hits', 0)}\n")
            lines.append(f"- Cache misses: {counts.get('cache_misses', 0)}\n")
            lines.append(f"- Unique D baselines evaluated: {counts.get('unique_d_baselines', 0)}\n")
            lines.append(f"- Unique D-P practice scenarios evaluated: {counts.get('unique_dp_practices', 0)}\n")
        lines.append('\nCalculation method: PRMM D×P×K simplified scoring as implemented in the GUI.\n')

        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            messagebox.showinfo('Report saved', f'PRMM report saved to:\n{path}')
            self.append_log(f'PRMM report exported: {path}')
        except Exception as e:
            messagebox.showerror('Save failed', str(e))

    def append_log(self, msg):
        def _append():
            self.log.configure(state='normal')
            self.log.insert('end', msg + '\n')
            self.log.see('end')
            self.log.configure(state='disabled')
        self.after(0, _append)

    def set_status(self, msg):
        self.after(0, lambda: self.status_var.set(msg))

    def clear_tree(self):
        for i in self.tree.get_children():
            self.tree.delete(i)

    def populate_tree(self, rows):
        def _pop():
            self.clear_tree()
            for r in rows:
                self.tree.insert('', 'end', values=(
                    r.get('run_no'),
                    r.get('run_timestamp'),
                    r.get('index'),
                    r.get('query_type'),
                    r.get('formula'),
                    r.get('status'),
                    r.get('trace_file'),
                ))
        self.after(0, _pop)

    def run_selected(self):
        self._run_queries(run_all=False)

    def run_all(self):
        self._run_queries(run_all=True)

    def erase_saved_traces(self):
        model = self.model_var.get()
        if not model or not os.path.isfile(model):
            messagebox.showerror('Error', 'Please select a valid model file')
            return

        ok = messagebox.askyesno(
            'Confirm delete',
            f'Delete all saved query results (<result> blocks) from:\n{model}\n\nThis cannot be undone.',
        )
        if not ok:
            return

        try:
            path = Path(model)
            text = read_text(path)

            updated_text, n1 = RESULT_BLOCK_RE.subn("\n", text)
            updated_text, n2 = RESULT_SELF_CLOSING_RE.subn("\n", updated_text)
            removed = n1 + n2

            if removed == 0:
                messagebox.showinfo('No saved results', 'No <result> blocks were found in the selected XML file.')
                return

            path.write_text(updated_text, encoding='utf-8')
            self.append_log(f'Erased {removed} saved query result block(s) from: {model}')
            self.set_status('Saved XML query results erased')
        except Exception as e:
            messagebox.showerror('Delete failed', str(e))

    def _run_queries(self, run_all=False):
        model = self.model_var.get()
        verifyta = self.verifyta_var.get()
        if not model or not os.path.isfile(model):
            messagebox.showerror('Error','Please select a valid model file')
            return
        out = self._default_output_csv_for_model(model)

        if not self.queries:
            self.load_queries()
        if not self.queries:
            messagebox.showerror('Error','No queries were found in the model')
            return

        if run_all:
            selected_queries = list(self.queries)
        else:
            indices = list(self.query_list.curselection())
            if not indices:
                messagebox.showwarning('Select a query', 'Select one or more queries in the list, or click Run All Queries.')
                return
            selected_queries = [self.queries[i] for i in indices]

        # Get number of runs
        try:
            num_runs = int(self.runs_var.get().strip())
            if num_runs < 1:
                num_runs = 1
        except (ValueError, AttributeError):
            num_runs = 1

        self.run_btn.configure(state='disabled')
        self.set_status('Preparing to run...')
        self.append_log(f'Starting query run from {model} -> {out}')
        self.append_log(f'Using verifyta: {verifyta}')
        self.append_log(f'Selected {len(selected_queries)} query(s)')
        self.append_log(f'Number of runs: {num_runs}')
        if num_runs > 1:
            self.append_log('30 seconds delay between runs')

        resolved_verifyta = self._resolve_verifyta(verifyta)
        if not resolved_verifyta:
            self.run_btn.configure(state='normal')
            self.set_status('Ready')
            messagebox.showerror(
                'verifyta not found',
                'verifyta was not found. Select the UPPAAL verifier executable first.',
            )
            return

        self.append_log(f'Resolved verifyta: {resolved_verifyta}')
        self.append_log(f'Intermediate run output path: {out}')

        if not run_all and len(selected_queries) == 1:
            self.set_status('Running selected query...')
        elif not run_all:
            self.set_status('Running selected queries...')
        else:
            self.set_status('Running all queries...')

        def worker():
            try:
                all_rows = []
                generated_trace_files = []
                for run_idx in range(num_runs):
                    if run_idx > 0:
                        self.append_log(f'Waiting 30 seconds before run {run_idx + 1}/{num_runs}...')
                        for i in range(30):
                            if i % 5 == 0 and i > 0:
                                self.set_status(f'Waiting {30 - i}s before next run...')
                            time.sleep(1)
                        self.set_status('Running query...')

                    self.append_log(f'Running {len(selected_queries)} query(s) (run {run_idx + 1}/{num_runs})')
                    if uqr is None:
                        rows = [{
                            'run_no': '',
                            'run_timestamp': '',
                            'index': q.get('index', ''),
                            'query_type': 'unknown',
                            'formula': q.get('formula', ''),
                            'comment': q.get('comment', ''),
                            'status': 'helper unavailable',
                            'result_text': '',
                            'returncode': '',
                            'command': '',
                            'trace_file': '',
                            'query_file': '',
                        } for q in selected_queries]
                        self.append_log('verifyta helper module unavailable; showing selected query list only')
                    else:
                        rows = uqr.run_verifyta_for_queries(
                            model,
                            selected_queries,
                            verifyta_path=resolved_verifyta,
                            trace_dir=self._trace_dir_for_output(out),
                            logger=self.append_log,
                        )

                    all_rows.extend(rows)
                    for r in rows:
                        trace_file = (r.get('trace_file') or '').strip()
                        if trace_file and os.path.isfile(trace_file):
                            generated_trace_files.append(trace_file)

                # Final step: build CSV from generated trace files (no manual selection needed).
                if generated_trace_files:
                    seen = set()
                    unique_trace_files = []
                    for trace_file in generated_trace_files:
                        if trace_file not in seen:
                            seen.add(trace_file)
                            unique_trace_files.append(trace_file)

                    parsed_rows = [parse_trace(Path(p)) for p in unique_trace_files]
                    trace_dir = Path(self._trace_dir_for_output(out))
                    output_name = f"{Path(out).stem}_values.csv"
                    final_csv_path = trace_dir / output_name
                    write_trace_csv(parsed_rows, final_csv_path)
                    self.append_log(f'Wrote extracted trace CSV to {final_csv_path}')
                else:
                    self.append_log('No generated trace files found; extracted CSV was not written.')

                self.populate_tree(all_rows)
                self.append_log('All runs complete')
            except Exception as e:
                self.append_log('Error: ' + str(e))
                self.after(0, lambda: messagebox.showerror('Run failed', str(e)))
            finally:
                def _enable():
                    self.run_btn.configure(state='normal')
                    self.status_var.set('Ready')
                self.after(0, _enable)

        threading.Thread(target=worker, daemon=True).start()

    def _resolve_verifyta(self, verifyta):
        if verifyta and os.path.isfile(verifyta):
            return verifyta

        if verifyta and verifyta.lower() == 'verifyta':
            candidates = [
                r'C:\Program Files\UPPAAL-5.0.0\app\bin\verifyta.exe',
                r'C:\Program Files (x86)\UPPAAL-5.0.0\app\bin\verifyta.exe',
            ]
            for candidate in candidates:
                if os.path.isfile(candidate):
                    return candidate

        return None

    def _default_output_csv_for_model(self, model_path):
        model_name = Path(model_path).stem if model_path else 'queries'
        return str(Path(model_path).with_name(f'{model_name}_queries.csv'))


def main():
    if os.environ.get('UPPAAL_PARSER_EXAMPLES') == '1':
        _run_parser_examples()
    if os.environ.get('UPPAAL_SCORING_EXAMPLES') == '1':
        _run_scoring_examples()
    app = App()
    app.mainloop()


if __name__ == '__main__':
    main()
