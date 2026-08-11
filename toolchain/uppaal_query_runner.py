#!/usr/bin/env python3
"""Run UPPAAL queries with `verifyta` and save fresh results to CSV.

Usage:
    python uppaal_query_runner.py --model "Supply Chain V9.5 - Copy.xml" --verifyta "C:\\Path\\to\\verifyta.exe" --output queries.csv

The script extracts the queries from the XML, writes temporary .q files, runs
`verifyta` for each query, then exports the live results to CSV.
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from xml.etree import ElementTree as ET


def extract_queries(model_path):
    tree = ET.parse(model_path)
    root = tree.getroot()
    queries = []
    for i, q in enumerate(root.findall('.//queries/query')):
        formula_el = q.find('formula')
        comment_el = q.find('comment')
        formula = formula_el.text.strip() if formula_el is not None and formula_el.text else ''
        comment = comment_el.text.strip() if comment_el is not None and comment_el.text else ''

        result_el = q.find('result')
        outcome = rtype = rvalue = timestamp = details = ''
        options = {}
        if result_el is not None:
            outcome = result_el.get('outcome','')
            rtype = result_el.get('type','')
            rvalue = result_el.get('value','')
            timestamp = result_el.get('timestamp','')
            det_el = result_el.find('details')
            details = det_el.text.strip() if det_el is not None and det_el.text else ''
            for opt in result_el.findall('option'):
                k = opt.get('key')
                v = opt.get('value')
                if k:
                    options[k] = v

        queries.append({
            'index': i+1,
            'formula': formula,
            'comment': comment,
            'outcome': outcome,
            'result_type': rtype,
            'result_value': rvalue,
            'timestamp': timestamp,
            'details': details,
            'options': options,
        })
    return queries


def write_query_file(queries, query_path):
    with open(query_path, 'w', encoding='utf-8', newline='') as f:
        for q in queries:
            comment = (q.get('comment') or '').strip()
            if comment:
                f.write(f'// {comment}\n')
            formula = q.get('formula') or ''
            formula = re.sub(r'\s+', ' ', formula).strip()
            f.write(formula + '\n')


def classify_query(formula):
    text = (formula or '').lstrip().lower()
    if text.startswith('simulate'):
        return 'simulate'
    if text.startswith('pr['):
        return 'probability'
    if text.startswith('e['):
        return 'estimate'
    if text.startswith('e<>') or text.startswith('a<>') or text.startswith('[]'):
        return 'symbolic'
    return 'other'


def safe_filename(text, max_length=80):
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', text or '')
    cleaned = cleaned.strip('._-')
    return (cleaned[:max_length] or 'query')


def next_trace_number(trace_dir, trace_base):
    if not trace_dir:
        return 1

    pattern = re.compile(rf"^{re.escape(trace_base)}_(\d+)\.txt$")
    highest = 0
    if os.path.isdir(trace_dir):
        for name in os.listdir(trace_dir):
            match = pattern.match(name)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def parse_verifyta_output(output_text):
    text = output_text.strip()
    lower = text.lower()

    if 'not satisfied' in lower:
        status = 'not satisfied'
    elif 'satisfied' in lower:
        status = 'satisfied'
    elif 'error' in lower or 'failed' in lower:
        status = 'error'
    else:
        status = 'unknown'

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result_text = lines[-1] if lines else ''

    # For simulation queries, keep the complete trace so all recorded points are
    # preserved in the CSV rather than only the final sample.
    if 'verifying formula' in lower and ('simulate ' in lower or 'simulate[' in lower):
        result_text = text

    # Try to capture a useful numeric or symbolic result line when present.
    for line in reversed(lines):
        if re.search(r'(\d+\.\d+|\btrue\b|\bfalse\b|satisfied|not satisfied|error|failed)', line, re.IGNORECASE):
            result_text = line
            break

    if 'verifying formula' in lower and ('simulate ' in lower or 'simulate[' in lower):
        result_text = text

    if status == 'error':
        result_text = 'Run Fail'
    elif not result_text:
        # Preserve a numeric zero for successful runs that do not expose a
        # parseable final line in the verifyta output.
        result_text = '0'

    return {
        'status': status,
        'result_text': result_text,
        'raw_output': text,
    }


def run_verifyta_for_queries(model_path, queries, verifyta_path='verifyta', trace_dir=None, logger=None):
    results = []

    def log(msg):
        if logger:
            logger(msg)

    if not verifyta_path:
        raise FileNotFoundError('No verifyta executable path was provided')

    if trace_dir:
        os.makedirs(trace_dir, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='uppaal_queries_') as tmpdir:
        for i, query in enumerate(queries, start=1):
            # Wait 20 seconds before each query (except the first one)
            if i > 1:
                log(f'Waiting 20 seconds before query {i}/{len(queries)}...')
                for s in range(20):
                    if s % 5 == 0 and s > 0:
                        log(f'  {20 - s}s remaining...')
                    time.sleep(1)
            
            query_path = os.path.join(tmpdir, f'query_{i}.q')
            write_query_file([query], query_path)

            cmd = [verifyta_path, model_path, query_path]
            log(f'Running query {i}/{len(queries)}')
            log(f'  formula: {query.get("formula", "")}')

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
            )

            stdout = proc.stdout or ''
            stderr = proc.stderr or ''
            combined = '\n'.join(part for part in [stdout, stderr] if part).strip()
            parsed = parse_verifyta_output(combined)

            if proc.returncode != 0 and parsed['status'] == 'unknown':
                parsed['status'] = 'error'

            trace_file = ''
            run_no = ''
            run_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if trace_dir:
                query_kind = classify_query(query.get('formula', ''))
                slug = safe_filename(query.get('formula', ''))
                trace_base = f"{i:03d}_{query_kind}_{slug}"
                run_no = next_trace_number(trace_dir, trace_base)
                trace_name = f"{trace_base}_{run_no}.txt"
                trace_file = os.path.join(trace_dir, trace_name)
                with open(trace_file, 'w', encoding='utf-8', newline='') as tf:
                    tf.write(parsed['raw_output'])

            results.append({
                'run_no': run_no,
                'run_timestamp': run_timestamp,
                'index': query.get('index', i),
                'query_type': classify_query(query.get('formula', '')),
                'formula': query.get('formula', ''),
                'comment': query.get('comment', ''),
                'status': parsed['status'],
                'result_text': parsed['result_text'],
                'returncode': proc.returncode,
                'command': ' '.join(cmd),
                'stdout': stdout,
                'stderr': stderr,
                'raw_output': parsed['raw_output'],
                'trace_file': trace_file,
                'query_file': query_path,
            })

            log(f'  status: {parsed["status"]}')
            if parsed['result_text']:
                log(f'  result: {parsed["result_text"]}')
            if proc.returncode != 0:
                log(f'  verifyta exit code: {proc.returncode}')
                if parsed['raw_output']:
                    log('  verifyta output:')
                    for line in parsed['raw_output'].splitlines():
                        log('    ' + line)
            
            # Log completion
            log(f'Query {i}/{len(queries)} completed')

    return results


def write_csv(rows, out_path):
    fieldnames = ['run_no', 'run_timestamp', 'index', 'query_type', 'formula', 'comment', 'status', 'result_text', 'returncode', 'command', 'trace_file', 'query_file']
    csv_dir = os.path.dirname(os.path.abspath(out_path))
    existing_rows = []
    if os.path.isfile(out_path):
        with open(out_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_rows.append(row)

    combined_rows = existing_rows + rows

    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in combined_rows:
            r2 = r.copy()
            trace_file = r2.get('trace_file', '')
            if trace_file:
                try:
                    trace_file = os.path.relpath(trace_file, csv_dir)
                except ValueError:
                    pass
            writer.writerow({
                'run_no': r2.get('run_no', ''),
                'run_timestamp': r2.get('run_timestamp', ''),
                'index': r2.get('index', ''),
                'query_type': r2.get('query_type', ''),
                'formula': r2.get('formula', ''),
                'comment': r2.get('comment', ''),
                'status': r2.get('status', ''),
                'result_text': r2.get('result_text', ''),
                'returncode': r2.get('returncode', ''),
                'command': r2.get('command', ''),
                'trace_file': trace_file,
                'query_file': r2.get('query_file', ''),
            })


def main():
    p = argparse.ArgumentParser(description='Run UPPAAL queries with verifyta and export results to CSV')
    p.add_argument('--model', '-m', required=True, help='Path to UPPAAL XML model file')
    p.add_argument('--verifyta', help='Path to verifyta executable (or let it be found on PATH)', default='verifyta')
    p.add_argument('--output', '-o', default='queries.csv', help='CSV output path')
    p.add_argument('--dry-run', action='store_true', help='Only extract queries; do not run verifyta')
    args = p.parse_args()

    try:
        queries = extract_queries(args.model)
    except ET.ParseError as e:
        print('Failed to parse XML:', e, file=sys.stderr)
        sys.exit(2)

    if not queries:
        print('No <queries> found in the model; CSV will be empty (header only).')
        write_csv([], args.output)
        return

    if args.dry_run:
        write_csv([
            {
                'index': q.get('index', ''),
                'formula': q.get('formula', ''),
                'comment': q.get('comment', ''),
                'status': 'not run',
                'result_text': '',
                'returncode': '',
                'command': '',
                'raw_output': '',
                'query_file': '',
            }
            for q in queries
        ], args.output)
        print(f'Wrote {len(queries)} extracted queries to {args.output} (dry run)')
        return

    out_abs = os.path.abspath(args.output)
    trace_dir = os.path.join(os.path.dirname(out_abs), f"{os.path.splitext(os.path.basename(out_abs))[0]}_traces")
    rows = run_verifyta_for_queries(args.model, queries, verifyta_path=args.verifyta, trace_dir=trace_dir)
    write_csv(rows, args.output)
    print(f'Wrote {len(rows)} query results to {args.output}')


if __name__ == '__main__':
    main()
