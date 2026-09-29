"""
Substantiates C2's tractability claim ("tractable for SMC") with concrete
state space and computational cost evidence, extracted directly from the
deposited artifacts rather than asserted:
  1. Per template location/edge counts and total clock count from the
     UPPAAL model file (model/Supply Chain V11.4.1.xml).
  2. Per query run counts and SMC sampling throughput from the raw
     verifyta trace files (results/raw_traces/**/*.txt).

Reproduces every number cited in the new "Tractability evidence for C2"
paragraph in Paper1_IMRaD_Draft.tex.
"""
import glob
import re
import statistics
import xml.etree.ElementTree as ET


def model_structure(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    templates = root.findall("template")
    rows = []
    total_loc = total_edge = 0
    for t in templates:
        name = t.find("name").text.strip()
        n_loc = len(t.findall("location"))
        n_edge = len(t.findall("transition"))
        rows.append((name, n_loc, n_edge))
        total_loc += n_loc
        total_edge += n_edge

    clocks = set()
    decl_texts = [root.find("declaration").text]
    for t in templates:
        d = t.find("declaration")
        if d is not None and d.text:
            decl_texts.append(d.text)
    for decl in decl_texts:
        for m in re.finditer(r"clock\s+([a-zA-Z0-9_, ]+);", decl):
            for name in m.group(1).split(","):
                clocks.add(name.strip())

    return rows, total_loc, total_edge, clocks


def trace_stats(traces_glob):
    files = glob.glob(traces_glob, recursive=True)
    run_counts = []
    throughputs = []
    for f in files:
        text = open(f, errors="ignore").read()
        m = re.search(r"\((\d+)/(\d+) runs\)", text)
        if m:
            run_counts.append(int(m.group(2)))
        else:
            m2 = re.search(r"\((\d+) runs\)", text)
            if m2:
                run_counts.append(int(m2.group(1)))
        tps = re.findall(r"Throughput: (\d+) (?:runs|items)/sec", text)
        throughputs.extend(int(x) for x in tps)
    return files, run_counts, throughputs


def main():
    rows, total_loc, total_edge, clocks = model_structure("../model/Supply Chain V11.4.1.xml")
    print(f"{'Template':30s} locations edges")
    for name, n_loc, n_edge in sorted(rows):
        print(f"{name:30s} {n_loc:9d} {n_edge:5d}")
    print(f"\nTotal: {len(rows)} templates, {total_loc} locations, {total_edge} edges, "
          f"{len(clocks)} clocks {sorted(clocks)}")

    files, run_counts, throughputs = trace_stats("../results/raw_traces/**/*.txt")
    print(f"\nTrace files found: {len(files)}")
    print(f"Run counts: min={min(run_counts)}, median={statistics.median(run_counts)}, "
          f"max={max(run_counts)}")
    print(f"Throughput samples: {len(throughputs)}")
    print(f"Throughput (runs or items/sec): min={min(throughputs)}, "
          f"median={statistics.median(throughputs)}, max={max(throughputs)}")


if __name__ == "__main__":
    main()
