#!/usr/bin/env python3
"""UPPAAL Query Runner GUI — PRMM V6

This file extends PRMM V5 with:
- Proportional Level 4 (improvement strength) scoring instead of binary pass/fail
- S4_final = 0.5 * S4_coverage + 0.5 * S4_strength
- Strength score mapping: 0-5 scale based on improvement percentage thresholds
- Improved S4 calculation consistency with direct cell modification

Inherits from PRMM V5 which includes:
- Query comment parsing for keys like [DK:...], [PK:...], [GK:...], [DIR:...]
- Automated D → KPI and P → activation mappings based on keys
- Formula-level caching to avoid repeated statistical UPPAAL queries
- General resilience dashboard tracking
- Enhanced PRMM reports with auto-mapping summaries
- Validation warnings for missing or conflicting keys

Do not modify the V5 or V4 files. All V6-specific changes are isolated here.
"""
import csv
import glob
import html
import json
import os
import re
import threading
import time
import tempfile
import textwrap
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from dataclasses import dataclass
from typing import Iterable, List, Optional, Dict, Set

from PIL import Image, ImageDraw, ImageFont

try:
    import uppaal_query_runner as uqr
except Exception:
    uqr = None


from uppaal_query_runner_gui_v3_PRMM_dual_scoring import App as AppV3, read_text


# ============================================================
# GLOBAL KEY MAPS (DISRUPTION AND PRACTICE)
# ============================================================

DISRUPTION_KEY_MAP = {
    "ENABLE_D_DEMAND_SHOCK": "DS",
    "ENABLE_D_RAW_SHORTAGE": "RS",
    "ENABLE_D_QUALITY_SHOCK": "QS",
    "ENABLE_D_FINISHED_TRANSPORT_DELAY": "FTD",
}

PRACTICE_KEY_MAP = {
    "ENABLE_P_EMERGENCY_RAW_REPLENISHMENT": "ERR",
    "ENABLE_P_ADAPTIVE_RAW_SAFETY_STOCK": "ARSS",
    "ENABLE_P_DEMAND_SURGE_CAPACITY": "DSC",
    "ENABLE_P_BACKUP_FINISHED_GOODS_TRUCK": "BFGT",
}

PRMM_HEATMAP_TARGET_QUERIES = [
    {
        'label': 'Active prod. blocked time',
        'aliases': ['active production blocked time', 'active prod blocked time', 'active prod. blocked time'],
        'formula_aliases': ['active_prod_blocked_time', 'blocked_time_active', 'activeprodblockedtime'],
    },
    {
        'label': 'Latent prod. blocked time',
        'aliases': ['latent production blocked time', 'latent prod blocked time', 'latent prod. blocked time'],
        'formula_aliases': ['latent_prod_blocked_time', 'blocked_time_latent', 'latentprodblockedtime'],
    },
    {
        'label': 'Safe-stock recovery time',
        'aliases': ['safe-stock recovery time', 'safe stock recovery time'],
        'formula_aliases': ['safe_stock_recovery_time', 'max_safe_stock_recovery_time', 'avg_batch_recovery_time', 'recovery_time'],
    },
    {
        'label': 'Stockout duration',
        'aliases': ['stockout duration'],
        'formula_aliases': ['stockout_duration_live', 'stockout_duration', 'max_stockout_duration_live_all', 'stockout_duration_live_all'],
    },
    {
        'label': 'Avg lead time',
        'aliases': ['avg lead time', 'average lead time'],
        'formula_aliases': ['avg_lead_time', 'average_lead_time', 'lead_time_avg', 'avg_batch_recovery_time'],
    },
    {
        'label': 'Min. availability',
        'aliases': ['min availability', 'minimum availability', 'min. availability'],
        'formula_aliases': ['availability_pct', 'min_availability_pct_all', 'store_availability', 'availability'],
    },
]


# ============================================================
# COMMENT PARSING HELPERS
# ============================================================

def extract_disruption_keys(text: str) -> List[str]:
    """Extract all [DK:...] keys from a comment."""
    if not text:
        return []
    pattern = r'\[DK:([^\]]+)\]'
    return re.findall(pattern, text)


def extract_practice_keys(text: str) -> List[str]:
    """Extract all [PK:...] keys from a comment."""
    if not text:
        return []
    pattern = r'\[PK:([^\]]+)\]'
    return re.findall(pattern, text)


def extract_general_keys(text: str) -> List[str]:
    """Extract [GK:...] keys from a comment."""
    if not text:
        return []
    pattern = r'\[GK:([^\]]+)\]'
    return re.findall(pattern, text)


def extract_direction(text: str) -> Optional[str]:
    """Extract [DIR:higher] or [DIR:lower] from a comment."""
    if not text:
        return None
    match = re.search(r'\[DIR:(higher|lower)\]', text)
    return match.group(1) if match else None


def is_kpi_comment(text: str) -> bool:
    """True if [KPI] is in the comment."""
    return '[KPI]' in (text or '')


def is_activation_comment(text: str) -> bool:
    """True if [ACT] is in the comment."""
    return '[ACT]' in (text or '')


def normalize_query_formula(formula: str) -> str:
    """Remove repeated whitespace and strip for deduplication."""
    if not formula:
        return ''
    return re.sub(r'\s+', ' ', formula).strip()


# ============================================================
# LEVEL 4 IMPROVEMENT STRENGTH SCORING (V6)
# ============================================================

def calculate_improvement_percentage(baseline_value, practice_value, direction):
    """Calculate normalized improvement percentage.
    
    For direction='lower': improvement_pct = ((baseline - practice) / |baseline|) * 100
    For direction='higher': improvement_pct = ((practice - baseline) / |baseline|) * 100
    
    Returns None if baseline is 0 or missing (avoid division by zero).
    """
    if baseline_value is None or practice_value is None:
        return None
    
    try:
        # Convert to float in case values come as strings
        baseline = float(baseline_value)
        practice = float(practice_value)
        
        if baseline == 0:
            return None  # Avoid division by zero
        
        if direction == 'lower':
            # For lower-is-better: improvement = (baseline - practice) / |baseline|
            improvement_pct = ((baseline - practice) / abs(baseline)) * 100
        else:  # direction == 'higher' or default
            # For higher-is-better: improvement = (practice - baseline) / |baseline|
            improvement_pct = ((practice - baseline) / abs(baseline)) * 100
        return improvement_pct
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def calculate_strength_score(improvement_pct):
    """Convert improvement percentage to 0-5 strength score.
    
    improvement_pct <= 0       -> 0 (no improvement or worse)
    0 < improvement_pct < 5    -> 1 (minimal)
    5 <= improvement_pct < 10  -> 2 (slight)
    10 <= improvement_pct < 15 -> 3 (moderate)
    15 <= improvement_pct < 20 -> 4 (good)
    improvement_pct >= 20      -> 5 (excellent)
    """
    if improvement_pct is None:
        return 0
    if improvement_pct <= 0:
        return 0
    elif improvement_pct < 5:
        return 1
    elif improvement_pct < 10:
        return 2
    elif improvement_pct < 15:
        return 3
    elif improvement_pct < 20:
        return 4
    else:  # improvement_pct >= 20
        return 5


# ============================================================
# PRMM V6 APP CLASS (V5 + IMPROVED LEVEL 4 SCORING)
# ============================================================

class App(AppV3):
    def __init__(self):
        self.detected_disruption_vars = {}
        self._new_run_button_created = False
        self._auto_map_button_created = False
        
        # Formula cache: (scenario_type, d_name, [p_name], normalized_formula) -> result
        self.prmm_formula_cache = {}
        
        # Auto-mapping metadata collected during auto_map_prmm_by_query_keys()
        self.prmm_auto_mapping_summary = {
            'disruption_keys_found': set(),
            'practice_keys_found': set(),
            'kpi_queries_by_disruption': {},
            'activation_queries_by_practice': {},
            'general_resilience_queries': [],
            'warnings': [],
        }
        
        super().__init__()
        self.title('UPPAAL Query Runner v5 (PRMM V5)')
        self._ensure_v4_prmm_sections()
        self.after(0, self._rename_prmm_controls)

    def _build_prmm_maturity_tab(self):
        """Build the inherited PRMM maturity tab and append the comparison heat map."""
        super()._build_prmm_maturity_tab()

        parent = self.prmm_maturity_tab
        children = parent.winfo_children()
        container = children[0] if children else parent

        heatmap_box = ttk.LabelFrame(container, text='Comparison Heat Map')
        heatmap_box.pack(fill='both', expand=True, pady=6)

        top = ttk.Frame(heatmap_box)
        top.pack(fill='x', padx=4, pady=(4, 2))
        self.prmm_heatmap_status_var = tk.StringVar(
            value='Heat map will show baseline/practice improvement values after PRMM evaluation.'
        )
        ttk.Label(top, textvariable=self.prmm_heatmap_status_var).pack(side='left', anchor='w')
        ttk.Button(top, text='Export heat map PNG', command=self.export_prmm_heatmap_png).pack(side='right')

        legend = ttk.Frame(top)
        legend.pack(side='right')
        ttk.Label(legend, text='Red = negative').pack(side='left', padx=(0, 8))
        ttk.Label(legend, text='White = near 0').pack(side='left', padx=(0, 8))
        ttk.Label(legend, text='Green = positive').pack(side='left')

        heatmap_frame = ttk.Frame(heatmap_box)
        heatmap_frame.pack(fill='both', expand=True, padx=4, pady=(0, 4))
        heatmap_frame.rowconfigure(0, weight=1)
        heatmap_frame.columnconfigure(0, weight=1)

        self.prmm_heatmap_canvas = tk.Canvas(heatmap_frame, height=280, borderwidth=0, highlightthickness=0, bg='white')
        self.prmm_heatmap_canvas.grid(row=0, column=0, sticky='nsew')
        heatmap_vscroll = ttk.Scrollbar(heatmap_frame, orient='vertical', command=self.prmm_heatmap_canvas.yview)
        heatmap_vscroll.grid(row=0, column=1, sticky='ns')
        heatmap_hscroll = ttk.Scrollbar(heatmap_frame, orient='horizontal', command=self.prmm_heatmap_canvas.xview)
        heatmap_hscroll.grid(row=1, column=0, sticky='ew')
        self.prmm_heatmap_canvas.configure(yscrollcommand=heatmap_vscroll.set, xscrollcommand=heatmap_hscroll.set)

        self._clear_prmm_heatmap()

    def _clear_prmm_heatmap(self):
        """Clear the PRMM heat map canvas."""
        if hasattr(self, 'prmm_heatmap_canvas'):
            self.prmm_heatmap_canvas.delete('all')
            self.prmm_heatmap_canvas.create_text(
                20,
                20,
                anchor='nw',
                text='Run PRMM evaluation to display the baseline/practice comparison heat map.',
                fill='#666666',
                font=('Arial', 10),
            )
            self.prmm_heatmap_canvas.configure(scrollregion=(0, 0, 600, 120))
            self.prmm_heatmap_export_bbox = (0, 0, 600, 120)
        if hasattr(self, 'prmm_heatmap_status_var'):
            self.prmm_heatmap_status_var.set('Heat map is empty until a PRMM evaluation is run.')

    def _format_heatmap_label(self, text, width=14):
        """Wrap a label into multiple lines for the heat map canvas."""
        if not text:
            return ''
        return '\n'.join(textwrap.wrap(str(text), width=width, break_long_words=False, break_on_hyphens=False))

    def _blend_heatmap_color(self, start_hex, end_hex, ratio):
        """Blend two hex colors by ratio in [0, 1]."""
        ratio = max(0.0, min(1.0, ratio))
        start_hex = start_hex.lstrip('#')
        end_hex = end_hex.lstrip('#')
        start_rgb = tuple(int(start_hex[i:i + 2], 16) for i in (0, 2, 4))
        end_rgb = tuple(int(end_hex[i:i + 2], 16) for i in (0, 2, 4))
        blended = tuple(int(start + (end - start) * ratio) for start, end in zip(start_rgb, end_rgb))
        return '#{:02x}{:02x}{:02x}'.format(*blended)

    def _heatmap_fill_color(self, value, vmin=-20.0, vmax=100.0):
        """Return a heat map fill color for a percentage value."""
        if value is None:
            return '#f1f1f1'
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return '#f1f1f1'

        if numeric <= 0:
            ratio = 0.0 if vmin == 0 else max(0.0, min(1.0, (numeric - vmin) / (0.0 - vmin)))
            return self._blend_heatmap_color('#d66a74', '#f4eded', ratio)
        ratio = 1.0 if vmax == 0 else max(0.0, min(1.0, numeric / vmax))
        return self._blend_heatmap_color('#f4eded', '#1f7a4d', ratio)

    def _heatmap_text_color(self, value):
        """Choose a readable text color for the heat map cell."""
        if value is None:
            return '#444444'
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return '#444444'
        return '#ffffff' if numeric >= 15 or numeric <= -10 else '#222222'

    def _prmm_heatmap_data(self, summary):
        """Build row/column axes and cell values from the PRMM summary."""
        row_order = []
        row_labels = {}
        col_order = []
        col_labels = {}
        cell_values = {}
        target_specs = PRMM_HEATMAP_TARGET_QUERIES
        target_hits = {spec['label']: [] for spec in target_specs}

        def normalize_metric_text(text):
            return (text or '').lower().replace('.', '').replace('-', ' ').replace('_', ' ')

        def candidate_matches(spec, candidate_text):
            normalized_candidate = normalize_metric_text(candidate_text)
            aliases = [spec['label']] + list(spec.get('aliases', [])) + list(spec.get('formula_aliases', []))
            for alias in aliases:
                normalized_alias = normalize_metric_text(alias)
                if normalized_alias and (normalized_alias in normalized_candidate or normalized_candidate in normalized_alias):
                    return True
            return False

        for row in summary.get('dp_rows', []) or []:
            d_name = row.get('d_name')
            p_name = row.get('p_name')
            if d_name is None or p_name is None:
                continue
            row_key = (d_name, p_name)
            if row_key not in row_labels:
                row_labels[row_key] = f"{self._display_name(d_name)} → {self._display_name(d_name)}+{self._display_name(p_name)}"
                row_order.append(row_key)

        for cell in summary.get('dpk_rows', []) or []:
            d_name = cell.get('d_name')
            p_name = cell.get('p_name')
            k_name = cell.get('k_name')
            if d_name is None or p_name is None or k_name is None:
                continue
            row_key = (d_name, p_name)
            if row_key not in row_labels:
                row_labels[row_key] = f"{self._display_name(d_name)} → {self._display_name(d_name)}+{self._display_name(p_name)}"
                row_order.append(row_key)
            query_meta = (self.prmm_k_query_map.get(k_name) or {})
            query_formula = query_meta.get('formula', '') or cell.get('formula', '') or ''
            query_comment = query_meta.get('comment', '') or cell.get('query_comment', '') or ''
            clean_name = self._clean_kpi_name(k_name)
            for spec in target_specs:
                if candidate_matches(spec, clean_name) or candidate_matches(spec, query_formula) or candidate_matches(spec, query_comment):
                    target_hits[spec['label']].append({
                        'k_name': k_name,
                        'value': cell.get('v6_improvement_pct') if cell.get('v6_improvement_pct') is not None else cell.get('improvement'),
                    })
                    break

        # Resolve each screenshot metric to the best available value for each row.
        for spec in target_specs:
            col_order.append(spec['label'])
            col_labels[spec['label']] = spec['label']

        for row_key in row_order:
            for spec in target_specs:
                label = spec['label']
                candidates = target_hits.get(label) or []
                selected_value = None
                for candidate in candidates:
                    candidate_k_name = candidate.get('k_name')
                    if candidate_k_name is None:
                        continue
                    # Prefer exact row-level evidence if present, otherwise any matched cell for the same metric.
                    matched_cell = None
                    for cell in summary.get('dpk_rows', []) or []:
                        if cell.get('k_name') == candidate_k_name and (cell.get('d_name'), cell.get('p_name')) == row_key:
                            matched_cell = cell
                            break
                    if matched_cell is not None:
                        selected_value = matched_cell.get('v6_improvement_pct')
                        if selected_value is None:
                            selected_value = matched_cell.get('improvement')
                        break
                    if selected_value is None:
                        selected_value = candidate.get('value')
                cell_values[(row_key, label)] = selected_value

        return row_order, row_labels, col_order, col_labels, cell_values

    def _render_prmm_heatmap(self, summary):
        """Render the PRMM baseline/practice comparison heat map."""
        canvas = getattr(self, 'prmm_heatmap_canvas', None)
        if canvas is None:
            return

        canvas.delete('all')
        if not summary or not summary.get('dpk_rows'):
            self._clear_prmm_heatmap()
            return

        row_order, row_labels, col_order, col_labels, cell_values = self._prmm_heatmap_data(summary)
        if not row_order:
            canvas.create_rectangle(0, 0, 900, 120, fill='white', outline='')
            canvas.create_text(
                20,
                20,
                anchor='nw',
                text='No comparison rows were found in this run. The heat map only shows: active prod. blocked time, latent prod. blocked time, safe-stock recovery time, stockout duration, avg lead time, and min. availability.',
                fill='#666666',
                font=('Arial', 10),
                width=840,
            )
            if hasattr(self, 'prmm_heatmap_status_var'):
                self.prmm_heatmap_status_var.set('No comparison rows were found in the current PRMM run.')
            return

        cell_width = 126
        cell_height = 58
        row_label_width = 260
        col_label_height = 78
        left_margin = 16
        top_margin = 12
        legend_height = 24
        width = left_margin + row_label_width + (len(col_order) * cell_width) + 30
        height = top_margin + col_label_height + (len(row_order) * cell_height) + legend_height + 34

        canvas.configure(scrollregion=(0, 0, width, height))
        self.prmm_heatmap_export_bbox = canvas.bbox('all') or (0, 0, width, height)
        canvas.create_rectangle(0, 0, width, height, fill='white', outline='')
        canvas.create_text(
            left_margin,
            6,
            anchor='nw',
            text='Rows = disruption/practice scenarios, columns = KPI/query results, color = improvement percentage',
            fill='#444444',
            font=('Arial', 9, 'italic'),
        )

        # Column labels.
        for col_index, k_name in enumerate(col_order):
            x0 = left_margin + row_label_width + (col_index * cell_width)
            x1 = x0 + cell_width
            y0 = top_margin + 18
            y1 = top_margin + col_label_height
            canvas.create_rectangle(x0, y0, x1, y1, fill='#f5f5f5', outline='white', width=2)
            canvas.create_text(
                (x0 + x1) / 2,
                y0 + 10,
                text=self._format_heatmap_label(col_labels.get(k_name, k_name), width=16),
                fill='#222222',
                font=('Arial', 9, 'bold'),
                anchor='n',
                justify='center',
            )

        # Row labels and cells.
        for row_index, row_key in enumerate(row_order):
            y0 = top_margin + col_label_height + (row_index * cell_height)
            y1 = y0 + cell_height
            canvas.create_rectangle(left_margin, y0, left_margin + row_label_width, y1, fill='#fafafa', outline='white', width=2)
            canvas.create_text(
                left_margin + 8,
                y0 + cell_height / 2,
                text=self._format_heatmap_label(row_labels.get(row_key, str(row_key)), width=28),
                fill='#222222',
                font=('Arial', 10, 'bold'),
                anchor='w',
                justify='left',
            )

            for col_index, k_name in enumerate(col_order):
                x0 = left_margin + row_label_width + (col_index * cell_width)
                x1 = x0 + cell_width
                value = cell_values.get((row_key, k_name))
                if value is None:
                    direct_value = (summary.get('heatmap_metric_values') or {}).get((row_key[0], row_key[1], k_name))
                    if isinstance(direct_value, dict):
                        value = direct_value.get('improvement')
                fill = self._heatmap_fill_color(value)
                text_color = self._heatmap_text_color(value)
                canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline='white', width=2)
                if value is None:
                    display = 'N/A'
                else:
                    try:
                        numeric = float(value)
                        display = f'{numeric:+.0f}%'
                    except (TypeError, ValueError):
                        display = str(value)
                canvas.create_text(
                    (x0 + x1) / 2,
                    y0 + cell_height / 2,
                    text=display,
                    fill=text_color,
                    font=('Arial', 12, 'bold'),
                )

        # Legend bar.
        legend_y = top_margin + col_label_height + (len(row_order) * cell_height) + 8
        legend_x = left_margin + row_label_width
        legend_steps = [(-20, '#d66a74'), (0, '#f4eded'), (100, '#1f7a4d')]
        canvas.create_text(legend_x, legend_y, anchor='nw', text='Legend:', fill='#444444', font=('Arial', 9, 'bold'))
        for idx, (label, color) in enumerate(legend_steps):
            x0 = legend_x + 58 + idx * 115
            canvas.create_rectangle(x0, legend_y - 1, x0 + 28, legend_y + 18, fill=color, outline='#999999')
            canvas.create_text(x0 + 34, legend_y, anchor='nw', text=f'{label:+d}%', fill='#444444', font=('Arial', 9))

        self.prmm_heatmap_status_var.set(
            f'Heat map populated with {len(row_order)} row(s) and {len(col_order)} screenshot metric column(s).'
        )

    def export_prmm_heatmap_png(self):
        """Export the current PRMM heat map as a PNG image."""
        data = getattr(self, 'last_prmm_maturity_data', None)
        if not data:
            messagebox.showwarning('Export heat map', 'Run PRMM evaluation before exporting the heat map.')
            return

        summary = data.get('summary', {}) or {}
        row_order, row_labels, col_order, col_labels, cell_values = self._prmm_heatmap_data(summary)
        if not row_order:
            messagebox.showwarning('Export heat map', 'There is no heat map data to export yet.')
            return

        output_path = filedialog.asksaveasfilename(
            title='Save heat map as PNG',
            defaultextension='.png',
            filetypes=[('PNG image', '*.png')],
            initialfile=f'PRMM Heat Map {datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.png',
        )
        if not output_path:
            return

        cell_width = 126
        cell_height = 58
        row_label_width = 260
        col_label_height = 78
        left_margin = 16
        top_margin = 12
        legend_height = 24
        width = left_margin + row_label_width + (len(col_order) * cell_width) + 30
        height = top_margin + col_label_height + (len(row_order) * cell_height) + legend_height + 34

        image = Image.new('RGBA', (width, height), 'white')
        draw = ImageDraw.Draw(image)
        font_small = ImageFont.load_default()
        font_bold = ImageFont.load_default()

        def draw_centered_multiline(box, text, font, fill, spacing=2):
            x0, y0, x1, y1 = box
            bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align='center')
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            x = x0 + max(0, (x1 - x0 - text_width) / 2)
            y = y0 + max(0, (y1 - y0 - text_height) / 2)
            draw.multiline_text((x, y), text, font=font, fill=fill, spacing=spacing, align='center')

        draw.text(
            (left_margin, 6),
            'Rows = disruption/practice scenarios, columns = KPI/query results, color = improvement percentage',
            fill='#444444',
            font=font_small,
        )

        for col_index, k_name in enumerate(col_order):
            x0 = left_margin + row_label_width + (col_index * cell_width)
            x1 = x0 + cell_width
            y0 = top_margin + 18
            y1 = top_margin + col_label_height
            draw.rectangle((x0, y0, x1, y1), fill='#f5f5f5', outline='white', width=2)
            draw_centered_multiline(
                (x0, y0 + 10, x1, y1),
                self._format_heatmap_label(col_labels.get(k_name, k_name), width=16),
                font_bold,
                '#222222',
            )

        for row_index, row_key in enumerate(row_order):
            y0 = top_margin + col_label_height + (row_index * cell_height)
            y1 = y0 + cell_height
            draw.rectangle((left_margin, y0, left_margin + row_label_width, y1), fill='#fafafa', outline='white', width=2)
            draw_centered_multiline(
                (left_margin + 8, y0, left_margin + row_label_width - 8, y1),
                self._format_heatmap_label(row_labels.get(row_key, str(row_key)), width=28),
                font_bold,
                '#222222',
            )

            for col_index, k_name in enumerate(col_order):
                x0 = left_margin + row_label_width + (col_index * cell_width)
                x1 = x0 + cell_width
                value = cell_values.get((row_key, k_name))
                if value is None:
                    direct_value = (summary.get('heatmap_metric_values') or {}).get((row_key[0], row_key[1], k_name))
                    if isinstance(direct_value, dict):
                        value = direct_value.get('improvement')
                fill = self._heatmap_fill_color(value)
                text_color = self._heatmap_text_color(value)
                draw.rectangle((x0, y0, x1, y1), fill=fill, outline='white', width=2)
                if value is None:
                    display = 'N/A'
                else:
                    try:
                        display = f'{float(value):+.0f}%'
                    except (TypeError, ValueError):
                        display = str(value)
                draw_centered_multiline((x0, y0, x1, y1), display, font_bold, text_color, spacing=1)

        legend_y = top_margin + col_label_height + (len(row_order) * cell_height) + 8
        legend_x = left_margin + row_label_width
        legend_steps = [(-20, '#d66a74'), (0, '#f4eded'), (100, '#1f7a4d')]
        draw.text((legend_x, legend_y), 'Legend:', fill='#444444', font=font_small)
        for idx, (label, color) in enumerate(legend_steps):
            x0 = legend_x + 58 + idx * 115
            draw.rectangle((x0, legend_y - 1, x0 + 28, legend_y + 18), fill=color, outline='#999999')
            draw.text((x0 + 34, legend_y), f'{label:+d}%', fill='#444444', font=font_small)

        image.save(output_path, format='PNG')
        self.prmm_heatmap_status_var.set(f'Heat map exported to {output_path}.')
        messagebox.showinfo('Export heat map', f'Heat map saved to:\n{output_path}')

    def _ensure_v4_prmm_sections(self):
        """Inherited from V4."""
        parent = getattr(self, 'prmm_maturity_tab', None)
        if parent is None:
            return

        self.enabled_disruptions_frame = ttk.LabelFrame(parent, text='Enabled disruptions')
        self.enabled_disruptions_frame.pack(fill='x', pady=6, padx=8)
        self.enabled_disruptions_text = tk.Text(self.enabled_disruptions_frame, height=5, state='disabled', wrap='word')
        self.enabled_disruptions_text.pack(fill='x', padx=4, pady=4)

        self.detected_disruptions_frame = ttk.LabelFrame(parent, text='Detected disruptions')
        self.detected_disruptions_frame.pack(fill='x', pady=6, padx=8)
        top = ttk.Frame(self.detected_disruptions_frame)
        top.pack(fill='x', padx=4, pady=(4, 2))
        ttk.Label(top, text='Level 1 recognition is based on whether an enabled disruption is marked as detected.').pack(side='left')
        ttk.Button(top, text='Refresh detected disruptions', command=self.refresh_prmm_sources).pack(side='right')

        container = ttk.Frame(self.detected_disruptions_frame)
        container.pack(fill='both', expand=True, padx=4, pady=(0, 4))
        self.detected_canvas = tk.Canvas(container, borderwidth=0, highlightthickness=0, height=140)
        self.detected_canvas.pack(side='left', fill='both', expand=True)
        self.detected_scrollbar = ttk.Scrollbar(container, orient='vertical', command=self.detected_canvas.yview)
        self.detected_scrollbar.pack(side='right', fill='y')
        self.detected_canvas.configure(yscrollcommand=self.detected_scrollbar.set)
        self.detected_inner = ttk.Frame(self.detected_canvas)
        self.detected_window = self.detected_canvas.create_window((0, 0), window=self.detected_inner, anchor='nw')
        self.detected_inner.bind('<Configure>', lambda _e: self.detected_canvas.configure(scrollregion=self.detected_canvas.bbox('all')))
        self.detected_canvas.bind('<Configure>', lambda e: self.detected_canvas.itemconfigure(self.detected_window, width=e.width))

    def _rename_prmm_controls(self):
        """Inherited from V4, extended with Auto-map button."""
        def walk(widget):
            for child in widget.winfo_children():
                try:
                    text = child.cget('text')
                except Exception:
                    text = None
                if text == 'Run PRMM Maturity Evaluation':
                    child.configure(text='Run PRMM Maturity Evaluation V5')
                    parent = child.master
                    if parent is not None and not self._new_run_button_created:
                        ttk.Button(parent, text='New Run / Clear Scenario', command=self.new_prmm_v4_run).pack(side='right', padx=4)
                        ttk.Button(parent, text='Auto-map by query keys', command=self.auto_map_prmm_by_query_keys).pack(side='right', padx=2)
                        self._new_run_button_created = True
                        self._auto_map_button_created = True
                elif text == 'Export PRMM Maturity Report':
                    child.configure(text='Export PRMM Maturity Report V5')
                walk(child)

        parent = getattr(self, 'prmm_maturity_tab', None)
        if parent is not None:
            walk(parent)

    def _enabled_disruptions_from_model(self, model_path):
        """Inherited from V4."""
        if not model_path or not os.path.isfile(model_path):
            return []
        text = read_text(Path(model_path))
        matches = re.findall(r'const\s+bool\s+(ENABLE_[DP]_\w+)\s*=\s*(true|false)', text)
        return [name for name, value in matches if name.startswith('ENABLE_D_') and value.lower() == 'true']

    def _refresh_enabled_and_detected_disruptions(self):
        """Inherited from V4."""
        model_path = self.model_var.get()
        enabled = self._enabled_disruptions_from_model(model_path)
        previous = {name: bool(var.get()) for name, var in self.detected_disruption_vars.items()}

        if hasattr(self, 'enabled_disruptions_text'):
            text = ['Enabled disruptions:\n']
            if enabled:
                for name in enabled:
                    text.append(f'- {name}\n')
            else:
                text.append('- (none)\n')
            self.enabled_disruptions_text.configure(state='normal')
            self.enabled_disruptions_text.delete('1.0', 'end')
            self.enabled_disruptions_text.insert('end', ''.join(text))
            self.enabled_disruptions_text.configure(state='disabled')

        if not hasattr(self, 'detected_inner'):
            return

        for child in self.detected_inner.winfo_children():
            child.destroy()
        self.detected_disruption_vars = {}

        if not enabled:
            ttk.Label(self.detected_inner, text='No enabled disruptions were found in the current model.').pack(anchor='w', padx=4, pady=4)
            return

        for name in enabled:
            var = tk.BooleanVar(value=previous.get(name, True))
            self.detected_disruption_vars[name] = var
            row = ttk.Frame(self.detected_inner)
            row.pack(fill='x', pady=2, padx=4)
            ttk.Checkbutton(row, text=self._display_name_with_code(name), variable=var).pack(side='left', anchor='w')

    def refresh_prmm_sources(self):
        """Inherited from V4."""
        try:
            super().refresh_prmm_sources()
        finally:
            self._refresh_enabled_and_detected_disruptions()
            self._rename_prmm_controls()

    def _prmm_reports_dir(self, model_path):
        """Resolve where PRMM evaluation reports/comparison records should be
        written: <repo>/results/prmm_reports/ when the model sits inside the
        expected repo layout (model_dir/../results), falling back to the
        model's own folder otherwise."""
        model_dir = Path(model_path).parent
        project_root = model_dir.parent
        prmm_dir = project_root / 'results' / 'prmm_reports'
        if (project_root / 'results').is_dir() or model_dir.name.lower() == 'model':
            prmm_dir.mkdir(parents=True, exist_ok=True)
            return prmm_dir
        return model_dir

    def make_prmm_report_filename(self, output_dir):
        """Build a timestamped V5 PRMM report filename with seconds and avoid overwrites."""
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        base_name = f'PRMM Evaluation ({timestamp})'
        candidate = Path(output_dir) / f'{base_name}.md'
        counter = 1
        while candidate.exists():
            candidate = Path(output_dir) / f'{base_name}_{counter}.md'
            counter += 1
        return candidate

    def make_prmm_comparison_filename(self, output_dir):
        """Build a timestamped PRMM comparison export filename and avoid overwrites."""
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        base_name = f'PRMM Comparison Records ({timestamp})'
        candidate = Path(output_dir) / f'{base_name}.json'
        counter = 1
        while candidate.exists():
            candidate = Path(output_dir) / f'{base_name}_{counter}.json'
            counter += 1
        return candidate

    def _build_prmm_comparison_records(self, data):
        """Build a machine-readable record of baseline vs practice comparisons."""
        summary = data.get('summary', {}) or {}
        records = []
        for cell in summary.get('dpk_rows', []) or []:
            if cell.get('baseline_value') is None and cell.get('practice_value') is None:
                continue
            records.append({
                'd_name': cell.get('d_name'),
                'p_name': cell.get('p_name'),
                'k_name': cell.get('k_name'),
                'formula': cell.get('formula', ''),
                'direction': cell.get('direction', 'higher'),
                'baseline_value': cell.get('baseline_value'),
                'practice_value': cell.get('practice_value'),
                'improvement': cell.get('improvement'),
                'tolerance': cell.get('tolerance'),
                'gate_L3_passed': bool(cell.get('gate_L3_passed')),
                'gate_L4_passed': bool(cell.get('gate_L4_passed')),
                'v6_improvement_pct': cell.get('v6_improvement_pct'),
                'v6_strength_score': cell.get('v6_strength_score'),
                'formula_cache_reused': bool(cell.get('formula_cache_reused')),
                'formula_cache_source': cell.get('formula_cache_source'),
                'activation_status': cell.get('activation_status'),
                'activation_count': cell.get('activation_count'),
                'query_index': cell.get('query_index'),
                'query_comment': cell.get('query_comment', ''),
                'query_disruption_keys': list(cell.get('query_disruption_keys') or []),
                'current_disruption_key': cell.get('current_disruption_key'),
                'matches_current_disruption': bool(cell.get('matches_current_disruption')),
                'included_in_denominator': bool(cell.get('included_in_denominator', False)),
                'gate_L3_reason': cell.get('gate_L3_reason'),
                'gate_L4_reason': cell.get('gate_L4_reason'),
            })
        return {
            'generated_at': datetime.now().isoformat(timespec='seconds'),
            'model': data.get('model'),
            'enabled_disruptions': list(summary.get('enabled_disruptions', [])),
            'record_count': len(records),
            'records': records,
        }

    def _write_prmm_comparison_records(self, output_path, data):
        """Write PRMM comparison records to disk as JSON."""
        payload = self._build_prmm_comparison_records(data)
        output_path = Path(output_path)
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
        return output_path

    def _build_model_variant_text_multi(self, text, d_name, enabled_practices):
        """Return a model text with one disruption enabled and selected practices enabled."""
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

    def _write_model_variant(self, tmpdir, filename, text):
        """Write a temporary model variant and return its path."""
        safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', filename)
        path = os.path.join(tmpdir, safe_name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return path

    def _run_heatmap_metric_family(self, verifyta_path, baseline_path, practice_path, query_formulas, direction='higher', aggregator='single'):
        """Execute one heatmap metric family and return baseline/practice/improvement data."""
        baseline_values = []
        practice_values = []
        result_lines = []

        for formula in query_formulas:
            query = {'formula': formula}
            baseline_row = self._run_single_query(verifyta_path, baseline_path, query)
            practice_row = self._run_single_query(verifyta_path, practice_path, query)
            baseline_value, _baseline_kind, _baseline_method = self._extract_numeric_value(baseline_row)
            practice_value, _practice_kind, _practice_method = self._extract_numeric_value(practice_row)
            if baseline_value is not None:
                baseline_values.append(baseline_value)
            if practice_value is not None:
                practice_values.append(practice_value)
            result_lines.append({
                'formula': formula,
                'baseline_value': baseline_value,
                'practice_value': practice_value,
                'baseline_result_text': baseline_row.get('result_text', ''),
                'practice_result_text': practice_row.get('result_text', ''),
            })

        if not baseline_values or not practice_values:
            return None

        if aggregator == 'min':
            baseline_agg = min(baseline_values)
            practice_agg = min(practice_values)
        elif aggregator == 'max':
            baseline_agg = max(baseline_values)
            practice_agg = max(practice_values)
        else:
            baseline_agg = baseline_values[0]
            practice_agg = practice_values[0]

        improvement = calculate_improvement_percentage(baseline_agg, practice_agg, direction)
        return {
            'baseline_value': baseline_agg,
            'practice_value': practice_agg,
            'improvement': improvement,
            'direction': direction,
            'detail_rows': result_lines,
        }

    def _reset_prmm_maturity_results_view(self):
        """Inherited from V4."""
        if hasattr(self, 'prmm_summary_matrix_var'):
            self.prmm_summary_matrix_var.set('S1 recognition score: —')
        if hasattr(self, 'prmm_summary_weighted_var'):
            self.prmm_summary_weighted_var.set('Weighted PRMM final score: —')
        if hasattr(self, 'prmm_summary_category_var'):
            self.prmm_summary_category_var.set('Maturity category: —')
        if hasattr(self, 'prmm_summary_activation_var'):
            self.prmm_summary_activation_var.set('Detected disruptions: —')
        if hasattr(self, 'prmm_summary_counts_var'):
            self.prmm_summary_counts_var.set('Evaluated cells: —')
        if hasattr(self, 'prmm_summary_report_var'):
            self.prmm_summary_report_var.set('Report path: —')

        if hasattr(self, 'prmm_level_vars'):
            for level in range(1, 6):
                if level == 5:
                    self.prmm_level_vars[level].set('S5: benchmark not implemented | 0.0%')
                else:
                    self.prmm_level_vars[level].set('—')

        if hasattr(self, 'prmm_activation_table'):
            for item in self.prmm_activation_table.get_children():
                self.prmm_activation_table.delete(item)
        if hasattr(self, 'prmm_results_table'):
            for item in self.prmm_results_table.get_children():
                self.prmm_results_table.delete(item)
        if hasattr(self, 'prmm_recommendations_text'):
            self.prmm_recommendations_text.configure(state='normal')
            self.prmm_recommendations_text.delete('1.0', 'end')
            self.prmm_recommendations_text.configure(state='disabled')
        if hasattr(self, 'prmm_heatmap_canvas'):
            self._clear_prmm_heatmap()

    def _update_prmm_maturity_dashboard(self, summary):
        """Refresh the inherited PRMM dashboard and render the comparison heat map."""
        super()._update_prmm_maturity_dashboard(summary)
        self._render_prmm_heatmap(summary)

    def clear_prmm_v4_run_data(self):
        """Inherited from V4."""
        # 1) Detected disruptions: uncheck all but keep enabled list visible.
        for var in self.detected_disruption_vars.values():
            try:
                var.set(False)
            except Exception:
                pass

        # 2) Scenario mappings: clear run-specific D->P, DxP->K, activation, and directions.
        if hasattr(self, 'prmm_d_items'):
            self.prmm_dp_map = {name: set() for name in self.prmm_d_items}
        if hasattr(self, 'prmm_k_items'):
            self.prmm_k_map = {label: {'d': set(), 'p': set()} for label in self.prmm_k_items}
            self.prmm_k_dir_map = {label: 'higher' for label in self.prmm_k_items}
        if hasattr(self, 'prmm_p_items'):
            self.prmm_p_activation_map = {name: [] for name in self.prmm_p_items}

        for listbox_name in (
            'prmm_d_listbox',
            'prmm_p_listbox',
            'prmm_k_listbox',
            'prmm_k_d_listbox',
            'prmm_k_p_listbox',
            'prmm_group_practices_listbox',
            'prmm_groups_listbox',
        ):
            listbox = getattr(self, listbox_name, None)
            if listbox is not None:
                try:
                    listbox.selection_clear(0, 'end')
                except Exception:
                    pass

        if hasattr(self, 'prmm_group_name_var'):
            self.prmm_group_name_var.set('')

        if hasattr(self, '_update_prmm_mapping_summary'):
            try:
                self._update_prmm_mapping_summary()
            except Exception:
                pass

        # 3/4/5) Clear previous PRMM run outputs and run-specific metadata.
        self._reset_prmm_maturity_results_view()
        
        # Clear formula cache on new run
        self.prmm_formula_cache = {}
        
        for attr in (
            'last_prmm_maturity_data',
            'last_prmm_maturity_report_path',
        ):
            if hasattr(self, attr):
                delattr(self, attr)

        self.set_status('New PRMM run initialized. Previous scenario selections and results were cleared.')
        self.append_log('New PRMM run initialized. Previous scenario selections and results were cleared.')

    def new_prmm_v4_run(self):
        """Inherited from V4."""
        self.clear_prmm_v4_run_data()

    def _practice_exists(self, practice_name):
        """Inherited from V4."""
        return practice_name in getattr(self, 'prmm_base_practices', []) or practice_name in self.prmm_p_groups

    def _lookup_evidence_cell(self, cells, d_name, p_name, k_name):
        """Inherited from V4."""
        for cell in cells:
            if cell.get('d_name') == d_name and cell.get('p_name') == p_name and cell.get('k_name') == k_name:
                return cell
        return None

    def _is_disruption_detected(self, disruption_name):
        """Inherited from V4."""
        variable = self.detected_disruption_vars.get(disruption_name)
        return bool(variable.get()) if variable is not None else False

    def _cell_passes_l3(self, cell):
        """Inherited from V4."""
        activation_status = cell.get('activation_status', 'not_required')
        return bool(
            cell.get('mapping_exists')
            and cell.get('practice_exists_in_model')
            and cell.get('kpi_query_exists')
            and activation_status in ('confirmed_active', 'not_required')
            and cell.get('baseline_value') is not None
            and cell.get('practice_value') is not None
        )

    def _cell_passes_l4(self, cell):
        """Inherited from V4."""
        improvement = cell.get('improvement')
        tolerance = cell.get('tolerance')
        return bool(self._cell_passes_l3(cell) and improvement is not None and tolerance is not None and improvement > tolerance)

    def _summarize_activation(self, cells_for_dp, p_name):
        """Inherited from V4."""
        activation_labels = []
        for cell in cells_for_dp:
            for activation in cell.get('activation_queries') or []:
                activation_labels.append(activation)
        if not activation_labels and self.prmm_p_activation_map.get(p_name):
            activation_labels = list(self.prmm_p_activation_map.get(p_name) or [])
        values = [item.get('parsed_value') for item in activation_labels if isinstance(item, dict)]
        if not activation_labels:
            return 'not_required', None
        if any(value is None for value in values):
            return 'unknown', None
        activation_count = max(values) if values else 0
        if activation_count > 0:
            return 'confirmed_active', activation_count
        return 'confirmed_inactive', 0

    def _find_k_labels_for_query_info(self, query_info):
        """Resolve one or more existing K labels for a parsed query record."""
        if not query_info:
            return []
        normalized_formula = normalize_query_formula(query_info.get('formula', ''))
        comment = (query_info.get('comment') or '').strip()
        labels = []
        for label, metadata in self.prmm_k_query_map.items():
            label_formula = normalize_query_formula(metadata.get('formula', ''))
            label_comment = (metadata.get('comment') or '').strip()
            if normalized_formula and label_formula == normalized_formula and comment == label_comment:
                labels.append(label)

        return labels

    def _register_auto_query_label(self, label_prefix, query_info, auto_kind, direction=None):
        """Create and register a stable internal label for a query if no existing label is found."""
        query_index = query_info.get('index')
        if query_index is None:
            return None

        base_label = f'{label_prefix}_Q{query_index + 1}'
        label = base_label
        suffix = 2
        while label in self.prmm_k_query_map:
            existing = self.prmm_k_query_map.get(label) or {}
            if existing.get('index') == query_index:
                return label
            label = f'{base_label}_{suffix}'
            suffix += 1

        query_formula = query_info.get('formula', '')
        normalized_formula = query_info.get('normalized_formula') or normalize_query_formula(query_formula)
        comment = (query_info.get('comment') or '').strip()
        disruption_keys = list(query_info.get('disruption_keys') or extract_disruption_keys(comment))
        practice_keys = list(query_info.get('practice_keys') or extract_practice_keys(comment))
        general_keys = list(query_info.get('general_keys') or extract_general_keys(comment))
        resolved_direction = direction or query_info.get('direction') or extract_direction(comment)

        metadata = {
            'index': query_index,
            'formula': query_formula,
            'normalized_formula': normalized_formula,
            'comment': comment,
            'disruption_keys': disruption_keys,
            'practice_keys': practice_keys,
            'general_keys': general_keys,
            'direction': resolved_direction,
            'is_kpi': bool(query_info.get('is_kpi')),
            'is_activation': bool(query_info.get('is_activation')),
            'auto_label': True,
            'auto_label_kind': auto_kind,
        }

        self.prmm_k_query_map[label] = metadata
        self.prmm_k_map.setdefault(label, {'d': set(), 'p': set()})
        self.prmm_k_dir_map[label] = resolved_direction or self.prmm_k_dir_map.get(label, 'higher')
        if label_prefix == 'K_AUTO' and label not in self.prmm_k_items:
            self.prmm_k_items.append(label)
            listbox = getattr(self, 'prmm_k_listbox', None)
            if listbox is not None:
                try:
                    listbox.insert('end', label)
                except Exception:
                    pass

        return label

    def _build_prmm_effective_k_map(self):
        """Build a run-scoped K map that propagates disruption-level KPI mappings to manual D × P pairs."""
        effective_k_map = {}
        propagation_map = {}

        kpi_queries_by_disruption = (self.prmm_auto_mapping_summary or {}).get('kpi_queries_by_disruption', {})

        # Keep only explicit manual D × P × K relations from the current UI state.
        for k_name, rel in self.prmm_k_map.items():
            d_related = set(rel.get('d', set()))
            p_related = set(rel.get('p', set()))
            if d_related and p_related:
                effective_k_map[k_name] = {'d': set(d_related), 'p': set(p_related)}

        for d_name, query_infos in kpi_queries_by_disruption.items():
            current_disruption_key = DISRUPTION_KEY_MAP.get(d_name)
            manual_practices = sorted(self.prmm_dp_map.get(d_name, set()))
            if not current_disruption_key or not manual_practices:
                continue
            for query_info in query_infos:
                query_comment = query_info.get('comment', '') or ''
                query_disruption_keys = extract_disruption_keys(query_comment)
                if current_disruption_key not in query_disruption_keys:
                    self.prmm_auto_mapping_summary.setdefault('warnings', []).append(
                        f'Warning: Propagation skipped for {d_name} because query does not contain [DK:{current_disruption_key}]'
                    )
                    continue
                k_labels = self._find_k_labels_for_query_info(query_info)
                if not k_labels:
                    continue
                for p_name in manual_practices:
                    for k_label in k_labels:
                        effective_k_map.setdefault(k_label, {'d': set(), 'p': set()})
                        effective_k_map[k_label]['d'].add(d_name)
                        effective_k_map[k_label]['p'].add(p_name)
                        propagation_map.setdefault((d_name, p_name), set()).add(k_label)

        return effective_k_map, propagation_map

    def _collect_prmm_cell_evidence(self, base_text, disruptions, practices, verifyta_path):
        """Override V4 evidence collection to add formula-level caching.
        
        Extends parent's scenario caching with normalized formula deduplication.
        If two queries have the same normalized formula, the result is reused.
        """
        # Call parent implementation first
        evidence = super()._collect_prmm_cell_evidence(base_text, disruptions, practices, verifyta_path)
        
        # Post-process evidence to track and mark formula-level cache hits
        formula_execution_map = {}  # normalized_formula -> first execution result
        reused_count = 0
        
        for cell in evidence.get('cells', []):
            # Try to get formula from multiple possible locations
            formula = cell.get('formula')
            if not formula:
                formula = cell.get('baseline_query_label')
            if not formula:
                formula = cell.get('practice_query_label')
            if not formula:
                continue
            
            normalized = normalize_query_formula(formula)
            
            # Track formula execution
            if normalized in formula_execution_map:
                # This formula was already executed, mark as reused
                cell['formula_cache_reused'] = True
                cell['formula_cache_source'] = formula_execution_map[normalized]['k_name']
                reused_count += 1
            else:
                # First time this normalized formula appears, mark it
                cell['formula_cache_reused'] = False
                formula_execution_map[normalized] = {
                    'k_name': cell.get('k_name'),
                    'result': cell.get('practice_value'),
                }
        
        # Store cache info for reporting
        if not hasattr(self, 'prmm_formula_execution_report'):
            self.prmm_formula_execution_report = {
                'formula_deduplication_count': reused_count,
                'unique_formulas': len(formula_execution_map),
            }
        
        return evidence

    def _compute_prmm_auto_mapping_summary(self, text):
        """Synchronous helper to compute PRMM auto-mapping from model text.
        
        This is the core auto-mapping logic extracted to be callable from both:
        - auto_map_prmm_by_query_keys() in a worker thread (manual button)
        - calculate_prmm_maturity() synchronously before evaluation
        
        Populates:
        - self.prmm_auto_mapping_summary
        - self.prmm_k_map (with auto-labels for new queries)
        - self.prmm_k_query_map (query metadata)
        - self.prmm_k_dir_map (direction hints)
        - self.prmm_p_activation_map (activation query labels per practice)
        
        Returns the summary dict for logging/display purposes.
        """
        # Extract all queries from model
        queries = self._extract_prmm_queries_with_comments(text)
        
        # Reset auto-mapping summary
        self.prmm_auto_mapping_summary = {
            'disruption_keys_found': set(),
            'practice_keys_found': set(),
            'kpi_queries_by_disruption': {},
            'activation_queries_by_practice': {},
            'general_resilience_queries': [],
            'warnings': [],
        }
        
        # 1. Auto-map disruption KPI queries
        disruptions_map, practices_map = self._extract_enable_states(text)
        enabled_disruptions = [name for name, enabled in disruptions_map.items() if enabled]
        
        for d_name in enabled_disruptions:
            d_key = DISRUPTION_KEY_MAP.get(d_name)
            if not d_key:
                self.prmm_auto_mapping_summary['warnings'].append(
                    f'Warning: Disruption {d_name} has no key in DISRUPTION_KEY_MAP'
                )
                continue
            
            self.prmm_auto_mapping_summary['disruption_keys_found'].add(d_key)
            
            # Find queries with matching [DK:d_key][KPI]
            matching_queries = []
            for query_info in queries:
                comment = query_info.get('comment', '')
                d_keys = extract_disruption_keys(comment)
                if d_key in d_keys and is_kpi_comment(comment):
                    matching_queries.append(query_info)
                    labels = self._find_k_labels_for_query_info(query_info)
                    if not labels:
                        auto_label = self._register_auto_query_label('K_AUTO', query_info, 'kpi', query_info.get('direction'))
                        if auto_label:
                            labels = [auto_label]
                    for label in labels:
                        self.prmm_k_map.setdefault(label, {'d': set(), 'p': set()})
                        self.prmm_k_map[label]['d'].add(d_name)
                        direction = query_info.get('direction')
                        if direction and self.prmm_k_dir_map.get(label, 'higher') in (None, '', 'higher'):
                            self.prmm_k_dir_map[label] = direction
                        elif not direction:
                            self.prmm_auto_mapping_summary['warnings'].append(
                                f'Warning: Query with [DK:{d_key}][KPI] has no [DIR:higher/lower]'
                            )
            
            if matching_queries:
                self.prmm_auto_mapping_summary['kpi_queries_by_disruption'][d_name] = matching_queries
            else:
                self.prmm_auto_mapping_summary['warnings'].append(
                    f'Warning: Disruption {d_name} (key={d_key}) has no auto-mapped KPI query'
                )
        
        # 2. Auto-map practice activation queries
        enabled_practices = [name for name, enabled in practices_map.items() if enabled]
        for p_name in enabled_practices:
            p_key = PRACTICE_KEY_MAP.get(p_name)
            if not p_key:
                self.prmm_auto_mapping_summary['warnings'].append(
                    f'Warning: Practice {p_name} has no key in PRACTICE_KEY_MAP'
                )
                continue
            
            self.prmm_auto_mapping_summary['practice_keys_found'].add(p_key)
            
            # Find queries with matching [PK:p_key][ACT]
            matching_activation = []
            for query_info in queries:
                comment = query_info.get('comment', '')
                p_keys = extract_practice_keys(comment)
                if p_key in p_keys and is_activation_comment(comment):
                    matching_activation.append(query_info)
                    matching_labels = self._find_k_labels_for_query_info(query_info)
                    if not matching_labels:
                        auto_label = self._register_auto_query_label('ACT_AUTO', query_info, 'activation')
                        if auto_label:
                            matching_labels = [auto_label]
                    if matching_labels:
                        current_labels = list(self.prmm_p_activation_map.get(p_name) or [])
                        for label in matching_labels:
                            if label not in current_labels:
                                current_labels.append(label)
                        self.prmm_p_activation_map[p_name] = current_labels
            
            if matching_activation:
                self.prmm_auto_mapping_summary['activation_queries_by_practice'][p_name] = matching_activation
            else:
                self.prmm_auto_mapping_summary['warnings'].append(
                    f'Warning: Practice {p_name} (key={p_key}) has no [PK:{p_key}][ACT] activation query'
                )
        
        # 3. Collect general resilience queries
        for query_info in queries:
            comment = query_info.get('comment', '')
            g_keys = extract_general_keys(comment)
            if 'RES' in g_keys:
                self.prmm_auto_mapping_summary['general_resilience_queries'].append(query_info)
        
        # 4. Auto-fill KPI directions
        for query_info in queries:
            comment = query_info.get('comment', '')
            if is_kpi_comment(comment):
                direction = extract_direction(comment)
                if direction:
                    # Find corresponding K labels and update direction
                    # This will be done during evidence collection
                    pass
                else:
                    d_keys = extract_disruption_keys(comment)
                    if d_keys:
                        self.prmm_auto_mapping_summary['warnings'].append(
                            f'Warning: Query with [DK:{d_keys[0]}][KPI] has no [DIR:higher/lower]'
                        )
        
        return self.prmm_auto_mapping_summary

    def auto_map_prmm_by_query_keys(self):
        """Auto-map KPI and activation queries based on query comment keys.
        
        Does not execute verifyta. Only parses keys and updates internal mappings.
        """
        model_path = self.model_var.get()
        if not model_path or not os.path.isfile(model_path):
            messagebox.showerror('Error', 'Please select a valid model file first.')
            return

        def worker():
            try:
                self.set_status('Auto-mapping queries by keys...')
                text = read_text(Path(model_path))
                
                # Call the synchronous helper to compute auto-mapping
                summary = self._compute_prmm_auto_mapping_summary(text)
                
                # Show summary
                summary_lines = []
                summary_lines.append(f'Disruption keys found: {len(summary.get("disruption_keys_found", set()))}')
                summary_lines.append(f'Practice keys found: {len(summary.get("practice_keys_found", set()))}')
                summary_lines.append(f'KPI queries auto-mapped: {len(summary.get("kpi_queries_by_disruption", {}))}')
                summary_lines.append(f'Activation queries auto-mapped: {len(summary.get("activation_queries_by_practice", {}))}')
                summary_lines.append(f'General resilience queries: {len(summary.get("general_resilience_queries", []))}')
                summary_lines.append(f'Warnings: {len(summary.get("warnings", []))}')
                
                summary_text = '\n'.join(summary_lines)
                if summary.get('warnings'):
                    summary_text += '\n\nWarnings:\n' + '\n'.join(summary['warnings'])
                
                self.after(0, lambda: messagebox.showinfo('Auto-mapping Summary', summary_text))
                self.after(0, lambda: self._update_prmm_mapping_summary())
                self.append_log(f'Auto-mapping complete: {summary_lines[0]}, {summary_lines[1]}, {summary_lines[2]}, {summary_lines[3]}, {summary_lines[4]}')
                
            except Exception as exc:
                error_text = f'Failed to auto-map by query keys:\n{exc}'
                self.after(0, lambda text=error_text: messagebox.showerror('Error', text))
            finally:
                self.after(0, lambda: self.set_status('Ready'))

        threading.Thread(target=worker, daemon=True).start()

    def _update_prmm_mapping_summary(self):
        """Override V4 to show both manual and auto-mapping information."""
        lines = []
        
        # ===== MANUAL MAPPING SECTION =====
        lines.append('MANUAL MAPPINGS:\n')
        lines.append('================\n\n')
        
        lines.append('Practice groups:\n')
        if not self.prmm_p_groups:
            lines.append('  (none)\n')
        else:
            for group_name in sorted(self.prmm_p_groups):
                members = ', '.join(self._display_name(p) for p in self.prmm_p_groups.get(group_name, []))
                lines.append(f'  {self._display_name(group_name)}: {members}\n')

        lines.append('\nD -> P mappings (manual):\n')
        if not any(self.prmm_dp_map.values()):
            lines.append('  (none)\n')
        else:
            for d in sorted(self.prmm_dp_map):
                practices = sorted(self.prmm_dp_map.get(d, set()))
                if practices:
                    label = self._display_name(d)
                    practice_labels = ', '.join(self._display_name(p) for p in practices)
                    lines.append(f'  {label}: {practice_labels}\n')

        lines.append('\nPractice activation queries (manual):\n')
        any_activation = any(self.prmm_p_activation_map.get(p) for p in self.prmm_p_items)
        if not any_activation:
            lines.append('  (none)\n')
        else:
            for p in sorted(self.prmm_p_items):
                activation = self.prmm_p_activation_map.get(p) or []
                if activation:
                    lines.append(f'  {self._display_name(p)}: {", ".join(activation)}\n')

        lines.append('\nK -> D/P mappings (manual):\n')
        manual_k_items = [k for k in sorted(self.prmm_k_map) 
                         if (self.prmm_k_map.get(k, {}).get('d') or self.prmm_k_map.get(k, {}).get('p'))]
        if not manual_k_items:
            lines.append('  (none)\n')
        else:
            for k in manual_k_items:
                rel = self.prmm_k_map.get(k, {'d': set(), 'p': set()})
                if rel['d'] or rel['p']:
                    direction = self.prmm_k_dir_map.get(k, 'higher')
                    d_labels = ', '.join(self._display_name(d) for d in sorted(rel['d']))
                    p_labels = ', '.join(self._display_name(p) for p in sorted(rel['p']))
                    lines.append(f"  {k}: D[{d_labels}]  P[{p_labels}] dir={direction}\n")
        
        # ===== AUTO-MAPPING SECTION =====
        auto_map = self.prmm_auto_mapping_summary
        lines.append('\n\nAUTO-MAPPING SUMMARY (QUERY KEYS):\n')
        lines.append('===================================\n\n')
        
        d_keys = auto_map.get('disruption_keys_found', set())
        p_keys = auto_map.get('practice_keys_found', set())
        lines.append(f'Disruption keys found: {len(d_keys)}\n')
        if d_keys:
            lines.append(f'  {", ".join(sorted(d_keys))}\n')
        
        lines.append(f'\nPractice keys found: {len(p_keys)}\n')
        if p_keys:
            lines.append(f'  {", ".join(sorted(p_keys))}\n')
        
        lines.append('\nAuto-mapped KPI queries by disruption:\n')
        kpi_by_d = auto_map.get('kpi_queries_by_disruption', {})
        if not kpi_by_d:
            lines.append('  (none)\n')
        else:
            for d in sorted(kpi_by_d):
                count = len(kpi_by_d[d])
                lines.append(f'  {d}: {count} query/queries\n')
        
        lines.append('\nAuto-mapped activation queries by practice:\n')
        act_by_p = auto_map.get('activation_queries_by_practice', {})
        if not act_by_p:
            lines.append('  (none)\n')
        else:
            for p in sorted(act_by_p):
                count = len(act_by_p[p])
                lines.append(f'  {p}: {count} query/queries\n')
        
        gen_resilience = auto_map.get('general_resilience_queries', [])
        lines.append(f'\nGeneral resilience queries: {len(gen_resilience)}\n')
        
        prop_count = auto_map.get('propagated_dpk_count', 0)
        lines.append(f'\nPropagated D×P×K mappings: {prop_count}\n')
        
        lines.append('\nWarnings:\n')
        warnings = auto_map.get('warnings', [])
        if not warnings:
            lines.append('  (none)\n')
        else:
            for warning in warnings:
                lines.append(f'  ⚠ {warning}\n')

        self.prmm_mapping_text.configure(state='normal')
        self.prmm_mapping_text.delete('1.0', 'end')
        self.prmm_mapping_text.insert('end', ''.join(lines))
        self.prmm_mapping_text.configure(state='disabled')

    def _apply_v6_s4_strength(self, summary):
        """Apply V6 Level 4 strength scoring to cells in summary['dpk_rows'].
        
        This helper runs AFTER parent aggregation and modifies the actual cells
        in summary['dpk_rows'] to add v6_improvement_pct and v6_strength_score.
        
        Then recomputes S4 metrics:
        - S4_coverage = % of L3 cells where improvement > tolerance (binary pass/fail)
        - S4_strength = average(strength_score) / 5 * 100 (only for cells with valid calculations)
        - S4_final = 0.5 * S4_coverage + 0.5 * S4_strength
        """
        # Get all L3 cells from the actual dpk_rows in summary
        dpk_rows = summary.get('dpk_rows', [])
        l3_cells = [cell for cell in dpk_rows if cell.get('gate_L3_passed')]
        
        if not l3_cells:
            # No L3 cells: all metrics are 0
            summary['s4_coverage'] = 0.0
            summary['s4_strength'] = 0.0
            summary['s4_final'] = 0.0
            summary['diagnostic_scores'][4] = 0.0
            cascaded_s3 = summary.get('cascaded_scores', {}).get(3, 0)
            summary['cascaded_scores'][4] = 0.0 if cascaded_s3 < 60 else 0.0
            return
        
        # Calculate improvement strength for each L3 cell directly in dpk_rows
        strength_scores = []  # Only includes strength scores from cells with valid calculations
        for cell in l3_cells:
            # Use the actual cell fields required by V6 reporting
            try:
                baseline_value = cell['baseline_value']
                practice_value = cell['practice_value']
                direction_value = cell['direction']
            except KeyError:
                baseline_value = None
                practice_value = None
                direction_value = None
            
            # Calculate improvement percentage - mark as None only if truly invalid
            improvement_pct = None
            strength_reason = None
            
            # Check for missing values or zero baseline
            if baseline_value is None or practice_value is None:
                strength_reason = 'missing baseline or practice value'
            else:
                try:
                    baseline = float(baseline_value)
                    practice = float(practice_value)
                    direction = str(direction_value).strip().lower() if direction_value is not None else ''
                    
                    if baseline == 0:
                        strength_reason = 'baseline is 0 (division by zero protection)'
                    else:
                        # Calculate improvement - zero and negative are valid results
                        if direction == 'lower':
                            improvement_pct = ((baseline - practice) / abs(baseline)) * 100
                        elif direction == 'higher':
                            improvement_pct = ((practice - baseline) / abs(baseline)) * 100
                        else:
                            strength_reason = f'invalid direction: {direction_value}'
                except (TypeError, ValueError) as e:
                    strength_reason = f'conversion error: {type(e).__name__}'
            
            # Calculate strength score from improvement percentage
            # 0-5 scale: <= 0 = 0, 0-5 = 1, 5-10 = 2, 10-15 = 3, 15-20 = 4, >= 20 = 5
            if improvement_pct is not None:
                if improvement_pct <= 0:
                    strength = 0
                elif improvement_pct < 5:
                    strength = 1
                elif improvement_pct < 10:
                    strength = 2
                elif improvement_pct < 15:
                    strength = 3
                elif improvement_pct < 20:
                    strength = 4
                else:  # improvement_pct >= 20
                    strength = 5
                # Only include valid strength scores in average
                strength_scores.append(strength)
            else:
                strength = 0
            
            # Store on the actual cell in dpk_rows (always, even if improvement_pct is None)
            cell['v6_improvement_pct'] = improvement_pct
            cell['v6_strength_score'] = strength
            cell['v6_strength_reason'] = strength_reason
        
        # S4_coverage = binary pass/fail percentage (old V5 logic)
        s4_coverage = (sum(1 for cell in l3_cells if cell.get('gate_L4_passed')) / len(l3_cells)) * 100.0
        
        # S4_strength = average strength score normalized to 0-100%
        # Only include cells with valid improvement_pct calculations
        if strength_scores:
            avg_strength = (sum(strength_scores) / len(strength_scores)) / 5.0 * 100.0
        else:
            avg_strength = 0.0
        
        # S4_final = blend of coverage and strength (0.5 each)
        s4_final = 0.5 * s4_coverage + 0.5 * avg_strength
        
        # Store scores in summary
        summary['s4_coverage'] = s4_coverage
        summary['s4_strength'] = avg_strength
        summary['s4_final'] = s4_final
        
        # Update diagnostic scores to use S4_final
        summary['diagnostic_scores'][4] = s4_final
        
        # Update cascaded scores with proper gate logic (cascade if S3 >= 60)
        cascaded_s3 = summary.get('cascaded_scores', {}).get(3, 0)
        if cascaded_s3 >= 60:
            summary['cascaded_scores'][4] = s4_final
        else:
            summary['cascaded_scores'][4] = 0.0
        
        # Recalculate weighted PRMM with updated cascaded S4
        cascaded = summary.get('cascaded_scores', {})
        weighted_prmm = (0.05 * cascaded.get(1, 0) + 0.10 * cascaded.get(2, 0) + 
                        0.25 * cascaded.get(3, 0) + 0.30 * cascaded.get(4, 0) + 0.30 * cascaded.get(5, 0))
        
        # Update category based on new weighted_prmm
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
        
        summary['weighted_prmm'] = weighted_prmm
        summary['category'] = category

    def _aggregate_prmm_maturity_results_v4(self, enabled_disruptions, practices_map, evidence):
        """Override V5 to add Level 4 improvement strength scoring (V6).
        
        V6 enhancement: S4 is now calculated as a blend of coverage and strength using
        a dedicated helper that modifies cells in summary['dpk_rows'] directly.
        
        S4_coverage = percentage of L3 KPI cells where improvement > tolerance
        S4_strength = average(strength_score) / 5 * 100
        S4_final = 0.5 * S4_coverage + 0.5 * S4_strength
        """
        # Clear formula execution report to ensure fresh statistics for this evaluation
        if hasattr(self, 'prmm_formula_execution_report'):
            delattr(self, 'prmm_formula_execution_report')
        
        # Get base summary from parent
        summary = super()._aggregate_prmm_maturity_results_v4(enabled_disruptions, practices_map, evidence)
        
        # Apply V6 Level 4 strength scoring - modifies cells in summary['dpk_rows'] directly
        self._apply_v6_s4_strength(summary)
        
        return summary

    def _extract_prmm_queries_with_comments(self, text):
        """Extract UPPAAL queries with their comments.
        
        Returns a list of dicts with:
        - index
        - formula
        - normalized_formula
        - comment
        - disruption_keys
        - practice_keys
        - general_keys
        - is_kpi
        - is_activation
        - direction
        """
        queries = []
        
        # Parse <query> blocks
        query_pattern = r'<query>(.*?)</query>'
        matches = re.finditer(query_pattern, text, re.DOTALL)
        
        for idx, match in enumerate(matches):
            query_block = match.group(1)
            
            # Extract formula
            formula_match = re.search(r'<formula>(.*?)</formula>', query_block, re.DOTALL)
            formula = formula_match.group(1) if formula_match else ''
            # Decode XML/HTML entities (e.g., &lt; -> <, &gt; -> >, &amp; -> &)
            formula = html.unescape(formula)
            
            # Extract comment
            comment_match = re.search(r'<comment>(.*?)</comment>', query_block, re.DOTALL)
            comment = comment_match.group(1) if comment_match else ''
            # Decode XML/HTML entities in comment
            comment = html.unescape(comment)
            
            normalized = normalize_query_formula(formula)
            d_keys = extract_disruption_keys(comment)
            p_keys = extract_practice_keys(comment)
            g_keys = extract_general_keys(comment)
            is_kpi = is_kpi_comment(comment)
            is_act = is_activation_comment(comment)
            direction = extract_direction(comment)
            
            queries.append({
                'index': idx,
                'formula': formula,
                'normalized_formula': normalized,
                'comment': comment,
                'disruption_keys': d_keys,
                'practice_keys': p_keys,
                'general_keys': g_keys,
                'is_kpi': is_kpi,
                'is_activation': is_act,
                'direction': direction,
            })
        
        return queries

    def _aggregate_prmm_maturity_results_v4(self, enabled_disruptions, practices_map, evidence):
        """Inherited from V4, with formula cache usage."""
        cells = list(evidence.get('cells', []))
        cell_lookup = {(c.get('d_name'), c.get('p_name'), c.get('k_name')): c for c in cells}
        detected_map = {name: self._is_disruption_detected(name) for name in enabled_disruptions}
        detection_count = sum(1 for value in detected_map.values() if value)

        disruption_rows = []
        dp_rows = []
        dpk_rows = []
        skipped_items = list(evidence.get('skipped_items', []))

        def scope_reason(enabled, detected):
            if not enabled:
                return 'outside selected scope'
            if enabled and not detected:
                return 'outside selected scope because disruption was not detected'
            return ''

        enabled_detected = [d for d in enabled_disruptions if detected_map.get(d)]

        for d_name in enabled_disruptions:
            linked_practices = sorted(self.prmm_dp_map.get(d_name, set()))
            existing_practices = [p for p in linked_practices if self._practice_exists(p)]
            detected = detected_map.get(d_name, False)
            level1_pass = detected
            level2_pass = bool(level1_pass and existing_practices)
            explanation = 'disruption was enabled and detected' if detected else 'disruption was enabled but not marked as detected'
            if detected and not existing_practices:
                explanation = 'disruption was detected but has no linked practice'
            disruption_rows.append({
                'd_name': d_name,
                'enabled': True,
                'detected': detected,
                'linked_practices': linked_practices,
                'existing_practices': existing_practices,
                'gate_L1_passed': level1_pass,
                'gate_L2_passed': level2_pass,
                'reason': explanation,
                'included_in_denominator': True,
            })
            if not detected:
                skipped_items.append({'item': d_name, 'reason': scope_reason(True, False), 'excluded_from_denominator': True, 'category': 'outside selected scope'})
            elif not linked_practices:
                skipped_items.append({'item': d_name, 'reason': 'missing practice mapping', 'excluded_from_denominator': True, 'category': 'missing practice mapping'})
            elif not existing_practices:
                skipped_items.append({'item': d_name, 'reason': 'linked practices do not exist in model', 'excluded_from_denominator': True, 'category': 'missing practice mapping'})

        dp_expected = []
        for d_name in enabled_detected:
            for p_name in sorted(self.prmm_dp_map.get(d_name, set())):
                if not self._practice_exists(p_name):
                    continue
                dp_expected.append((d_name, p_name))

        dp_expected_unique = []
        seen_dp = set()
        for item in dp_expected:
            if item not in seen_dp:
                seen_dp.add(item)
                dp_expected_unique.append(item)

        dpk_expected_count = 0
        s3_pass_count = 0
        s4_pass_count = 0
        dpfail_map = {}

        k_relations_by_dp = {}
        for k_name, rel in self.prmm_k_map.items():
            for d_name in rel.get('d', set()):
                for p_name in rel.get('p', set()):
                    k_relations_by_dp.setdefault((d_name, p_name), []).append(k_name)

        for d_name, p_name in dp_expected_unique:
            cells_for_dp = []
            linked_ks = sorted(k_relations_by_dp.get((d_name, p_name), []))
            activation_status, activation_count = self._summarize_activation(
                [cell_lookup.get((d_name, p_name, k_name)) for k_name in linked_ks if cell_lookup.get((d_name, p_name, k_name))],
                p_name,
            )
            dp_pass_l2 = True
            dp_pass_l3 = False
            if not linked_ks:
                skipped_items.append({'item': f'{d_name} / {p_name}', 'reason': 'missing KPI mapping', 'excluded_from_denominator': True, 'category': 'missing KPI mapping'})

            for k_name in linked_ks:
                query_meta = self.prmm_k_query_map.get(k_name) or {}
                expected_formula = query_meta.get('formula', '')
                query_comment = query_meta.get('comment', '')
                query_index = query_meta.get('index')
                query_disruption_keys = extract_disruption_keys(query_comment)
                current_disruption_key = DISRUPTION_KEY_MAP.get(d_name)
                matches_current_disruption = bool(current_disruption_key and current_disruption_key in query_disruption_keys)
                direction_from_comment = extract_direction(query_comment)
                cell = cell_lookup.get((d_name, p_name, k_name))
                if cell is None:
                    query_exists = bool(self.prmm_k_query_map.get(k_name))
                    reason = 'missing query' if not query_exists else 'parse failure or missing evidence'
                    cell = {
                        'd_name': d_name,
                        'p_name': p_name,
                        'k_name': k_name,
                        'mapping_exists': True,
                        'practice_exists_in_model': self._practice_exists(p_name),
                        'kpi_query_exists': query_exists,
                        'baseline_value': None,
                        'practice_value': None,
                        'baseline_kind': None,
                        'practice_kind': None,
                        'improvement': None,
                        'direction': self.prmm_k_dir_map.get(k_name, 'higher'),
                        'tolerance': self._kpi_tolerance('numeric'),
                        'activation_status': 'not_required',
                        'activation_count': None,
                        'activation_required': False,
                        'activation_queries': [],
                        'parse_error': reason,
                        'reason': reason,
                        'formula': expected_formula,
                        'query_index': query_index,
                        'query_comment': query_comment,
                        'query_disruption_keys': query_disruption_keys,
                        'current_disruption_key': current_disruption_key,
                        'matches_current_disruption': matches_current_disruption,
                        'direction_source': 'comment' if direction_from_comment else 'manual/default',
                        'included_in_denominator': False,
                        'gate_L3_passed': False,
                        'gate_L4_passed': False,
                        'included_in_denom_l3': False,
                        'included_in_denom_l4': False,
                    }
                else:
                    cell = dict(cell)
                    cell['formula'] = expected_formula
                    cell['query_index'] = query_index
                    cell['query_comment'] = query_comment
                    cell['query_disruption_keys'] = query_disruption_keys
                    cell['current_disruption_key'] = current_disruption_key
                    cell['matches_current_disruption'] = matches_current_disruption
                    cell['direction_source'] = 'comment' if direction_from_comment else 'manual/default'
                    cell['gate_L3_passed'] = self._cell_passes_l3(cell)
                    cell['gate_L4_passed'] = self._cell_passes_l4(cell)
                    cell['included_in_denominator'] = cell['gate_L3_passed']
                    cell['included_in_denom_l3'] = cell['gate_L3_passed']
                    cell['included_in_denom_l4'] = cell['gate_L3_passed']

                cell['gate_L2_passed'] = dp_pass_l2
                cell['gate_L3_passed'] = self._cell_passes_l3(cell)
                cell['gate_L4_passed'] = self._cell_passes_l4(cell)
                cell['formula'] = cell.get('formula') or expected_formula
                cell.setdefault('query_index', query_index)
                cell.setdefault('query_comment', query_comment)
                cell.setdefault('query_disruption_keys', query_disruption_keys)
                cell.setdefault('current_disruption_key', current_disruption_key)
                cell.setdefault('matches_current_disruption', matches_current_disruption)
                cell.setdefault('direction_source', 'comment' if direction_from_comment else 'manual/default')
                if not cell.get('gate_L3_reason'):
                    if not cell.get('mapping_exists'):
                        cell['gate_L3_reason'] = 'missing D mapping'
                    elif not cell.get('practice_exists_in_model'):
                        cell['gate_L3_reason'] = 'practice missing from model'
                    elif not cell.get('kpi_query_exists'):
                        cell['gate_L3_reason'] = 'missing KPI query'
                    elif cell.get('activation_status') not in ('confirmed_active', 'not_required'):
                        cell['gate_L3_reason'] = f"activation status is {cell.get('activation_status')}"
                    elif cell.get('baseline_value') is None or cell.get('practice_value') is None:
                        cell['gate_L3_reason'] = 'baseline or practice value could not be parsed'
                    else:
                        cell['gate_L3_reason'] = 'all L3 conditions satisfied'
                if not cell.get('gate_L4_reason'):
                    if not cell.get('gate_L3_passed'):
                        cell['gate_L4_reason'] = 'Gate L3 did not pass'
                    elif cell.get('improvement') is None or cell.get('tolerance') is None:
                        cell['gate_L4_reason'] = 'missing improvement or tolerance'
                    elif cell.get('improvement') > cell.get('tolerance'):
                        cell['gate_L4_reason'] = 'improvement > tolerance'
                    else:
                        cell['gate_L4_reason'] = 'improvement <= tolerance'
                cells_for_dp.append(cell)
                dpk_expected_count += 1
                if cell['gate_L3_passed']:
                    s3_pass_count += 1 if not dpfail_map.get((d_name, p_name)) else 0
                    dpfail_map[(d_name, p_name)] = True
                if cell['gate_L4_passed']:
                    s4_pass_count += 1

            dp_rows.append({
                'd_name': d_name,
                'p_name': p_name,
                'practice_exists': True,
                'activation_status': activation_status,
                'activation_count': activation_count,
                'linked_kpis': linked_ks,
                'passed_level_2': dp_pass_l2,
                'passed_level_3': any(cell['gate_L3_passed'] for cell in cells_for_dp),
                'cells': cells_for_dp,
                'reason': 'has linked practice' if linked_ks else 'missing KPI mapping',
                'included_in_denominator': True,
            })

            for cell in cells_for_dp:
                dpk_rows.append(cell)

        s1_denom = len(enabled_disruptions)
        s1_num = detection_count
        s1 = (s1_num / s1_denom * 100.0) if s1_denom else 0.0

        s2_denom = detection_count
        s2_num = sum(1 for d in enabled_detected if any(self._practice_exists(p) for p in self.prmm_dp_map.get(d, set())))
        s2 = (s2_num / s2_denom * 100.0) if s2_denom else 0.0

        s3_denom = len(dp_expected_unique)
        s3_num = sum(1 for row in dp_rows if row.get('passed_level_3'))
        s3 = (s3_num / s3_denom * 100.0) if s3_denom else 0.0

        l3_cells = [cell for cell in dpk_rows if cell.get('gate_L3_passed')]
        s4_denom = len(l3_cells)
        s4_num = sum(1 for cell in l3_cells if cell.get('gate_L4_passed'))
        s4 = (s4_num / s4_denom * 100.0) if s4_denom else 0.0

        s5 = 0.0
        cascaded = {1: s1, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
        if cascaded[1] >= 60:
            cascaded[2] = s2
        if cascaded[2] >= 60:
            cascaded[3] = s3
        if cascaded[3] >= 60:
            cascaded[4] = s4

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

        summary = {
            'enabled_disruptions': enabled_disruptions,
            'detected_map': detected_map,
            'disruption_rows': disruption_rows,
            'dp_rows': dp_rows,
            'dpk_rows': dpk_rows,
            'cells': dpk_rows,
            'evaluated_cells': len(dpk_rows),
            'skipped_items': skipped_items,
            'diagnostic_scores': {1: s1, 2: s2, 3: s3, 4: s4, 5: s5},
            'cascaded_scores': cascaded,
            'final_weighted_prmm': weighted_prmm,
            'category': category,
            'counts': {
                'enabled_disruptions': len(enabled_disruptions),
                'detected_disruptions': detection_count,
                'expected_dp_pairs': len(dp_expected_unique),
                'expected_dpk_cells': len(dpk_rows),
                'l3_cells': len(l3_cells),
                'l4_cells': s4_num,
                'evaluated_cells': len(dpk_rows),
                **(evidence.get('counts', {}) or {}),
            },
            'note_level5': 'Level 5 requires benchmark-based or continuous optimization evidence. This is not implemented in V5, therefore S5 = 0.0 and no cell receives benchmark maturity.',
        }

        # Ensure V6 improvement percentage and strength are computed on the actual
        # cells used by reporting (summary['dpk_rows']).
        self._apply_v6_s4_strength(summary)

        return summary

    def calculate_prmm_maturity(self):
        """Inherited from V4, extended to auto-refresh auto-mapping before evaluation."""
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
                self.set_status('Calculating PRMM maturity V5...')
                text = read_text(Path(model))
                disruptions_map, practices_map = self._extract_enable_states(text)
                enabled_disruptions = [name for name, enabled in disruptions_map.items() if enabled]
                self._refresh_enabled_and_detected_disruptions()
                # Automatically refresh auto-mapping before building effective K map
                self._compute_prmm_auto_mapping_summary(text)
                effective_k_map, propagation_map = self._build_prmm_effective_k_map()
                # Count total propagated D×P×K mappings
                propagated_count = sum(len(k_set) for k_set in propagation_map.values())
                self.prmm_auto_mapping_summary['propagated_dpk_count'] = propagated_count
                original_k_map = self.prmm_k_map
                self.prmm_k_map = effective_k_map
                try:
                    evidence = self._collect_prmm_cell_evidence(text, enabled_disruptions, practices_map, resolved_verifyta)
                    summary = self._aggregate_prmm_maturity_results_v4(enabled_disruptions, practices_map, evidence)
                finally:
                    self.prmm_k_map = original_k_map

                heatmap_metric_values = {}
                direct_heatmap_metrics = {
                    'Stockout duration': {
                        'query_formulas': [
                            'E[<=800;50] (max: stockout_duration_live(0))',
                            'E[<=800;50] (max: stockout_duration_live(1))',
                            'E[<=800;50] (max: stockout_duration_live(2))',
                        ],
                        'direction': 'lower',
                        'aggregator': 'max',
                    },
                    'Avg lead time': {
                        'query_formulas': ['E[<=800;50] (max: avg_lead_time())'],
                        'direction': 'lower',
                        'aggregator': 'single',
                    },
                    'Min. availability': {
                        'query_formulas': [
                            'E[<=800;50] (min: availability_pct(0))',
                            'E[<=800;50] (min: availability_pct(1))',
                            'E[<=800;50] (min: availability_pct(2))',
                        ],
                        'direction': 'higher',
                        'aggregator': 'min',
                    },
                }

                with tempfile.TemporaryDirectory(prefix='prmm_heatmap_') as heatmap_tmpdir:
                    for row in summary.get('dp_rows', []) or []:
                        d_name = row.get('d_name')
                        p_name = row.get('p_name')
                        if not d_name or not p_name:
                            continue
                        practice_list = list(self.prmm_p_groups.get(p_name, [p_name]))
                        baseline_text = self._build_model_variant_text_multi(text, d_name, [])
                        practice_text = self._build_model_variant_text_multi(text, d_name, practice_list)
                        baseline_path = self._write_model_variant(heatmap_tmpdir, f'heatmap_baseline_{d_name}_{p_name}.xml', baseline_text)
                        practice_path = self._write_model_variant(heatmap_tmpdir, f'heatmap_practice_{d_name}_{p_name}.xml', practice_text)

                        for metric_label, spec in direct_heatmap_metrics.items():
                            family_result = self._run_heatmap_metric_family(
                                resolved_verifyta,
                                baseline_path,
                                practice_path,
                                spec['query_formulas'],
                                direction=spec['direction'],
                                aggregator=spec['aggregator'],
                            )
                            if family_result is not None:
                                heatmap_metric_values[(d_name, p_name, metric_label)] = family_result

                summary['heatmap_metric_values'] = heatmap_metric_values
                self.last_prmm_maturity_data = {
                    'model': model,
                    'disruptions': disruptions_map,
                    'enabled_disruptions': enabled_disruptions,
                    'detected_map': summary.get('detected_map', {}),
                    'practices': practices_map,
                    'summary': summary,
                    'prmm_p_groups': dict(self.prmm_p_groups),
                    'prmm_dp_map': {k: sorted(v) for k, v in self.prmm_dp_map.items()},
                    'prmm_k_map': {k: {'d': sorted(v.get('d', set())), 'p': sorted(v.get('p', set()))} for k, v in self.prmm_k_map.items()},
                    'prmm_k_query_map': dict(self.prmm_k_query_map),
                    'prmm_p_activation_map': {k: list(v) for k, v in self.prmm_p_activation_map.items()},
                    'kpi_propagation_map': {f'{d} / {p}': sorted(k_labels) for (d, p), k_labels in propagation_map.items()},
                    'evidence': evidence,
                    'auto_mapping_summary': self.prmm_auto_mapping_summary,
                }
                report_text = self._build_prmm_v4_report(self.last_prmm_maturity_data)
                prmm_output_dir = self._prmm_reports_dir(model)
                report_path = self.make_prmm_report_filename(prmm_output_dir)
                report_path.write_text(report_text, encoding='utf-8')
                self.last_prmm_maturity_report_path = str(report_path)

                comparison_path = self.make_prmm_comparison_filename(prmm_output_dir)
                self._write_prmm_comparison_records(comparison_path, self.last_prmm_maturity_data)
                self.last_prmm_comparison_path = str(comparison_path)

                self.last_prmm_maturity_data['comparison_records_path'] = str(comparison_path)
                self.last_prmm_maturity_data['comparison_records'] = self._build_prmm_comparison_records(self.last_prmm_maturity_data)

                self.after(0, lambda: self._update_prmm_maturity_dashboard(summary))
            except Exception as exc:
                error_text = f'Failed to calculate PRMM maturity V5:\n{exc}'
                self.after(0, lambda text=error_text: messagebox.showerror('Error', text))
            finally:
                self.after(0, lambda: self.set_status('Ready'))

        threading.Thread(target=worker, daemon=True).start()

    def _build_prmm_v4_report(self, data):
        """Extended from V4 with key-based mapping summary, general resilience dashboard, and formula cache metrics."""
        summary = data.get('summary', {})
        auto_mapping = data.get('auto_mapping_summary', {})
        manual_k_map = data.get('prmm_k_map', {})
        propagation_map = data.get('kpi_propagation_map', {})

        def _manual_k_labels_for_dp(d_name, p_name):
            labels = set()
            for k_name, rel in manual_k_map.items():
                if d_name in set(rel.get('d', [])) and p_name in set(rel.get('p', [])):
                    labels.add(k_name)
            return labels

        def _propagated_k_labels_for_dp(d_name, p_name):
            return set(propagation_map.get(f'{d_name} / {p_name}', []))
        
        lines = []
        lines.append('# PRMM Maturity Evaluation Report V6\n\n')
        lines.append(f'Generated: {time.strftime("%Y-%m-%d %H:%M:%S")}\n\n')
        
        # Formula cache statistics (if available)
        if hasattr(self, 'prmm_formula_execution_report'):
            cache_report = self.prmm_formula_execution_report
            lines.append('## Formula-level cache statistics\n')
            lines.append(f'- Unique formula patterns executed: {cache_report.get("unique_formulas", 0)}\n')
            lines.append(f'- Formula results reused (deduplicated): {cache_report.get("formula_deduplication_count", 0)}\n')
            lines.append('- (Identical formulas executed only once per scenario type to maintain statistical consistency)\n\n')
        lines.append('## Methodology\n')
        lines.append('V6 refines PRMM Level 4 scoring with an improvement strength component. It builds on V5 query-comment-based auto-mapping and formula-level caching. Enabled disruptions are the starting scope, detected disruptions determine Level 1 recognition, linked practices build Level 2 coverage, and KPI monitoring builds Level 3. Level 4 now combines (1) coverage: the percentage of L3 KPIs with improvement > tolerance, and (2) strength: the average normalized improvement magnitude (0-100%). The final S4 score blends these: S4_final = 0.5 × S4_coverage + 0.5 × S4_strength, providing a more proportional assessment that considers both how many KPIs improved and how much they improved. Level 5 is not implemented.\n\n')
        lines.append('## Article-based interpretation\n')
        lines.append('- Level 1 = disruption recognition / awareness.\n')
        lines.append('- Level 2 = detected disruptions linked to risk-reducing practices.\n')
        lines.append('- Level 3 = practices monitored by KPIs.\n')
        lines.append('- Level 4 = V6 combines improvement coverage (KPIs exceeding tolerance) with improvement strength (normalized magnitude), providing proportional credit for continuous optimization.\n')
        lines.append('- Level 5 = benchmark / excellence not implemented yet.\n\n')

        # Key-based auto-mapping summary
        lines.append('## Key-based auto-mapping summary\n')
        if auto_mapping:
            lines.append(f'- Disruption keys found: {", ".join(sorted(auto_mapping.get("disruption_keys_found", set()))) or "(none)"}\n')
            lines.append(f'- Practice keys found: {", ".join(sorted(auto_mapping.get("practice_keys_found", set()))) or "(none)"}\n')
            kpi_queries_by_disruption = auto_mapping.get('kpi_queries_by_disruption', {})
            disruptions_with_kpi = len(kpi_queries_by_disruption)
            total_kpi_mappings = sum(len(queries) for queries in kpi_queries_by_disruption.values())
            unique_kpi_formulas = set()
            for queries in kpi_queries_by_disruption.values():
                for query_info in queries:
                    normalized_formula = query_info.get('normalized_formula')
                    if not normalized_formula:
                        normalized_formula = normalize_query_formula(query_info.get('formula', ''))
                    if normalized_formula:
                        unique_kpi_formulas.add(normalized_formula)

            lines.append(f'- Disruptions with auto-mapped KPI queries: {disruptions_with_kpi}\n')
            lines.append(f'- Total disruption-to-KPI query mappings: {total_kpi_mappings}\n')
            lines.append(f'- Unique KPI query formulas used: {len(unique_kpi_formulas)}\n')
            lines.append(f'- Activation queries auto-mapped per practice: {len(auto_mapping.get("activation_queries_by_practice", {}))}\n')
            lines.append(f'- General resilience queries: {len(auto_mapping.get("general_resilience_queries", []))}\n')
            lines.append('Disruption-level KPI mappings are propagated to manually linked D × P pairs.\n')
            lines.append('Note: one query formula may be mapped to multiple disruptions when its comment contains multiple [DK:...] keys.\n')
            
            if kpi_queries_by_disruption:
                lines.append('\nAuto-mapped KPI queries by disruption:\n')
                for d_name, queries in kpi_queries_by_disruption.items():
                    lines.append(f'  - {d_name}: {len(queries)} query/queries\n')
            
            if auto_mapping.get('activation_queries_by_practice'):
                lines.append('\nAuto-mapped activation queries by practice:\n')
                for p_name, queries in auto_mapping['activation_queries_by_practice'].items():
                    lines.append(f'  - {p_name}: {len(queries)} query/queries\n')
            
            if auto_mapping.get('warnings'):
                lines.append(f'\nValidation warnings ({len(auto_mapping["warnings"])}): \n')
                for warning in auto_mapping['warnings'][:10]:  # Show first 10
                    lines.append(f'  - {warning}\n')
                if len(auto_mapping['warnings']) > 10:
                    lines.append(f'  ... and {len(auto_mapping["warnings"]) - 10} more warnings\n')
        lines.append('\n')

        enabled_disruptions = summary.get('enabled_disruptions', [])
        detected_map = summary.get('detected_map', {})
        lines.append('## Summary\n')
        lines.append(f'- Enabled disruptions: {len(enabled_disruptions)}\n')
        lines.append(f'- Detected disruptions: {sum(1 for value in detected_map.values() if value)}\n')
        lines.append(f'- S1 recognition score: {summary.get("diagnostic_scores", {}).get(1, 0.0):.1f}%\n')
        lines.append(f'- S2 practice identification score: {summary.get("diagnostic_scores", {}).get(2, 0.0):.1f}%\n')
        lines.append(f'- S3 KPI monitoring score: {summary.get("diagnostic_scores", {}).get(3, 0.0):.1f}%\n')
        # V6: Show S4 with coverage, strength, and final components
        lines.append(f'- S4 coverage score (% of L3 KPIs with improvement > tolerance): {summary.get("s4_coverage", summary.get("diagnostic_scores", {}).get(4, 0.0)):.1f}%\n')
        lines.append(f'- S4 strength score (average improvement magnitude 0-100%): {summary.get("s4_strength", 0.0):.1f}%\n')
        lines.append(f'- S4 final improvement score (0.5×coverage + 0.5×strength): {summary.get("diagnostic_scores", {}).get(4, 0.0):.1f}%\n')
        lines.append(f'- S5 benchmark score: {summary.get("diagnostic_scores", {}).get(5, 0.0):.1f}%\n')
        lines.append(f'- S1 cascaded: {summary.get("cascaded_scores", {}).get(1, 0.0):.1f}%\n')
        lines.append(f'- S2 cascaded: {summary.get("cascaded_scores", {}).get(2, 0.0):.1f}%\n')
        lines.append(f'- S3 cascaded: {summary.get("cascaded_scores", {}).get(3, 0.0):.1f}%\n')
        lines.append(f'- S4 cascaded: {summary.get("cascaded_scores", {}).get(4, 0.0):.1f}%\n')
        lines.append(f'- S5 cascaded: {summary.get("cascaded_scores", {}).get(5, 0.0):.1f}%\n')
        lines.append(f'- Weighted PRMM final score: {summary.get("final_weighted_prmm", 0.0):.1f}%\n')
        lines.append(f'- Category: {summary.get("category", "Early Awareness")}\n\n')
        lines.append('## Disruption-level section\n')
        for row in summary.get('disruption_rows', []):
            lines.append(f'### D = {row.get("d_name")}\n')
            lines.append(f'- Enabled: yes\n')
            lines.append(f'- Detected: {"yes" if row.get("detected") else "no"}\n')
            lines.append(f'- L1: {"pass" if row.get("gate_L1_passed") else "fail"}\n')
            lines.append(f'- Linked practices: {", ".join(row.get("linked_practices", [])) or "(none)"}\n')
            lines.append(f'- Level 2 result: {"pass" if row.get("gate_L2_passed") else "fail"}\n')
            lines.append(f'- Explanation: {row.get("reason")}\n')
            lines.append(f'- Included in denominator: {row.get("included_in_denominator", True)}\n\n')

        lines.append('## D × P section\n')
        for row in summary.get('dp_rows', []):
            d_name = row.get('d_name')
            p_name = row.get('p_name')
            manual_k_labels = _manual_k_labels_for_dp(d_name, p_name)
            propagated_k_labels = _propagated_k_labels_for_dp(d_name, p_name)
            propagated_only = propagated_k_labels - manual_k_labels
            linked_kpis = sorted(set(row.get('linked_kpis', [])))
            lines.append(f'### D = {row.get("d_name")} / P = {row.get("p_name")}\n')
            lines.append(f'- Practice exists: {"yes" if row.get("practice_exists") else "no"}\n')
            lines.append(f'- Activation status: {row.get("activation_status")}\n')
            lines.append(f'- Activation count: {row.get("activation_count")}\n')
            lines.append('- Activation aggregation rule: maximum parsed activation value across activation queries; active only if the maximum is greater than 0.\n')
            lines.append(f'- Passed Level 2: {"yes" if row.get("passed_level_2") else "no"}\n')
            lines.append(f'- Passed Level 3 at D×P level: {"yes" if row.get("passed_level_3") else "no"}\n')
            lines.append(f'- Linked KPI count: {len(linked_kpis)}\n')
            lines.append(f'- KPIs from manual D×P mapping: {len(manual_k_labels)}\n')
            lines.append(f'- KPIs propagated from disruption-level auto-mapping: {len(propagated_only)}\n')
            lines.append(f'- Included in denominator: {row.get("included_in_denominator", True)}\n\n')

        lines.append('## D × P × K section\n')
        for cell in summary.get('dpk_rows', []):
            d_name = cell.get('d_name')
            p_name = cell.get('p_name')
            k_name = cell.get('k_name')
            manual_k_labels = _manual_k_labels_for_dp(d_name, p_name)
            propagated_k_labels = _propagated_k_labels_for_dp(d_name, p_name)
            if k_name in manual_k_labels and k_name in propagated_k_labels:
                mapping_source = 'manual D×P mapping + propagated from disruption-level auto-mapping'
            elif k_name in manual_k_labels:
                mapping_source = 'manual D×P mapping'
            elif k_name in propagated_k_labels:
                mapping_source = 'propagated from disruption-level auto-mapping'
            else:
                mapping_source = 'manual or propagated mapping not identified'
            lines.append(f'### D = {cell.get("d_name")} / P = {cell.get("p_name")} / K = {cell.get("k_name")}\n')
            lines.append(f'- KPI query exists: {"yes" if cell.get("kpi_query_exists") else "no"}\n')
            lines.append(f'- Mapping source: {mapping_source}\n')
            lines.append(f'- Propagated query index: {cell.get("query_index") if cell.get("query_index") is not None else "(none)"}\n')
            lines.append(f'- Query comment: {cell.get("query_comment") or "(none)"}\n')
            lines.append(f'- Detected disruption keys: {", ".join(cell.get("query_disruption_keys") or []) or "(none)"}\n')
            lines.append(f'- Current disruption key: {cell.get("current_disruption_key") or "(none)"}\n')
            lines.append(f'- Matches current disruption: {"yes" if cell.get("matches_current_disruption") else "no"}\n')
            lines.append(f'- Direction source: {cell.get("direction_source", "manual/default")}\n')
            lines.append(f'- Baseline value: {cell.get("baseline_value")}\n')
            lines.append(f'- Practice value: {cell.get("practice_value")}\n')
            lines.append(f'- Direction: {cell.get("direction")}\n')
            lines.append(f'- Formula: {cell.get("formula", "")}\n')
            
            # Show if formula was reused from cache
            if cell.get('formula_cache_reused'):
                lines.append(f'- **Formula result reused from cache** (first executed for K={cell.get("formula_cache_source")})\n')
            
            lines.append(f'- Improvement: {cell.get("improvement")}\n')
            lines.append(f'- Tolerance: {cell.get("tolerance")}\n')
            improvement_gt_tolerance = bool(
                cell.get('improvement') is not None
                and cell.get('tolerance') is not None
                and cell.get('improvement') > cell.get('tolerance')
            )
            lines.append(f'- Improvement > tolerance: {"yes" if improvement_gt_tolerance else "no"}\n')
            lines.append(f'- Activation status used for L3: {cell.get("activation_status") or "not_required"}\n')
            lines.append(f'- Gate L3 passed: {"yes" if cell.get("gate_L3_passed") else "no"}\n')
            lines.append(f'- Gate L3 reason: {cell.get("gate_L3_reason") or cell.get("reason") or cell.get("parse_error") or "(none)"}\n')
            
            # V6: Show Level 4 improvement strength details for L3 cells
            if cell.get('gate_L3_passed'):
                baseline_val = cell.get('baseline_value')
                practice_val = cell.get('practice_value')
                direction_val = cell.get('direction', 'higher')
                improvement_pct = cell.get('v6_improvement_pct')
                strength_score = cell.get('v6_strength_score', 0)
                
                if improvement_pct is not None:
                    lines.append(f'- V6: Baseline: {baseline_val}, Practice: {practice_val}, Direction: {direction_val}\n')
                    lines.append(f'- V6: Improvement percentage: {improvement_pct:.2f}%\n')
                    lines.append(f'- V6: Strength score (0-5): {strength_score}/5\n')
                else:
                    lines.append(f'- V6: Improvement percentage: (cannot calculate - baseline is 0, missing, or invalid type)\n')
                    lines.append(f'  Baseline: {baseline_val}, Practice: {practice_val}, Direction: {direction_val}\n')
                    lines.append(f'- V6: Strength score (0-5): 0/5\n')
                
                lines.append(f'- V6: Old Gate L4 (improvement > tolerance): {"pass" if improvement_gt_tolerance else "fail"}\n')
            
            lines.append(f'- Gate L4 passed (V6 final): {"yes" if cell.get("gate_L4_passed") else "no"}\n')
            lines.append(f'- Gate L4 reason: {cell.get("gate_L4_reason") or cell.get("reason") or cell.get("parse_error") or "(none)"}\n')
            lines.append(f'- Included in denominator: {cell.get("gate_L3_passed", False)}\n')
            
            # Execution audit trail for auto-created labels
            if k_name and k_name.startswith(('K_AUTO', 'ACT_AUTO')):
                lines.append('\n  **Execution audit for auto-created label:**\n')
                k_metadata = data.get('prmm_k_query_map', {}).get(k_name, {})
                lines.append(f'  - K label: {k_name}\n')
                lines.append(f'  - Query index: {k_metadata.get("index") or cell.get("query_index") or "(unknown)"}\n')
                lines.append(f'  - Query comment: {k_metadata.get("comment") or "(unknown)"}\n')
                lines.append(f'  - Formula from prmm_k_query_map: {k_metadata.get("formula") or "(unknown)"}\n')
                lines.append(f'  - Baseline query label: {cell.get("baseline_query_label") or "(unknown)"}\n')
                lines.append(f'  - Practice query label: {cell.get("practice_query_label") or "(unknown)"}\n')
                lines.append(f'  - Baseline raw output: {cell.get("baseline_result_text") or "(none)"}\n')
                lines.append(f'  - Practice raw output: {cell.get("practice_result_text") or "(none)"}\n')
                lines.append(f'  - Activation query labels: {cell.get("activation_query_labels") or "(none)"}\n')
                if cell.get('activation_queries'):
                    for act_entry in cell['activation_queries']:
                        lines.append(f'    - {act_entry.get("label", "unknown")}: parsed_value={act_entry.get("parsed_value", "unknown")}\n')
                else:
                    lines.append(f'  - Activation parsed values: (none)\n')
            
            lines.append('\n')

        # Execution evidence summary
        lines.append('## Execution evidence summary\n')
        evidence = data.get('evidence', {})
        kpi_executions = evidence.get('counts', {}).get('kpi_query_executions', 0)
        activation_executions = evidence.get('counts', {}).get('activation_query_executions', 0)
        cache_hits = evidence.get('counts', {}).get('cache_hits', 0)
        cache_misses = evidence.get('counts', {}).get('cache_misses', 0)
        lines.append(f'- KPI query executions: {kpi_executions}\n')
        lines.append(f'- Activation query executions: {activation_executions}\n')
        lines.append(f'- Scenario cache hits: {cache_hits}\n')
        lines.append(f'- Scenario cache misses: {cache_misses}\n')
        lines.append(f'- Formula-level cache deduplication: {self.prmm_formula_execution_report.get("formula_deduplication_count", 0) if hasattr(self, "prmm_formula_execution_report") else 0}\n')
        lines.append(f'- Unique KPI formulas executed: {self.prmm_formula_execution_report.get("unique_formulas", 0) if hasattr(self, "prmm_formula_execution_report") else 0}\n')
        lines.append('\n')

        comparison_path = data.get('comparison_records_path') or getattr(self, 'last_prmm_comparison_path', None)
        if comparison_path:
            lines.append('## Comparison records\n')
            lines.append(f'- Saved comparison file: {comparison_path}\n')
            lines.append('- Each record stores baseline_value, practice_value, improvement, tolerance, direction, and scoring metadata per D×P×K cell.\n\n')
        
        lines.append('## General resilience dashboard\n')
        if auto_mapping.get('general_resilience_queries'):
            for query_info in auto_mapping['general_resilience_queries']:
                lines.append(f'- Query: {query_info.get("comment", query_info.get("formula", ""))}\n')
                lines.append(f'  Direction: {query_info.get("direction", "unspecified")}\n')
        else:
            lines.append('- (no general resilience queries found)\n')
        lines.append('\n')

        lines.append('## Skipped / unmapped section\n')
        if not summary.get('skipped_items'):
            lines.append('- (none)\n')
        else:
            for item in summary.get('skipped_items', []):
                lines.append(f'- {item.get("item")}: {item.get("reason")} (excluded={item.get("excluded_from_denominator")})\n')

        lines.append('\n## Level 5 note\n')
        lines.append('Level 5 is not implemented in V6. It requires benchmark or external reference values. Therefore S5 = 0.0.\n')
        return ''.join(lines)


if __name__ == '__main__':
    app = App()
    app.mainloop()
