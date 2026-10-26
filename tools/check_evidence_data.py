"""
Release gate for the built knockout evidence (run after tools/build_evidence_data.py; the website deploy stops when it fails).

It asks, for every organism file, whether the verdicts follow the rules, and for human and mouse whether they agree with
independent gold standards:

  1. rules (all organisms, a sample of genes): a lethal result is never rated SAFE, a gene without a measurement is never
     rated SAFE, an estimate is never rated AVOID, and every AVOID rests on a measurement;
  2. human, cultured cells: at least 90% of the 684 core-essential genes (CEGv2) are rated AVOID and at least 95% of the 927
     non-essential genes (NEGv1) are not;
  3. mouse, whole animal: at least 85% of the core-essential genes are rated AVOID or HIGH_CONCERN;
  4. yeast: the duplicated ribosomal genes (RPL1A/B, RPL2A/B, ...) carry a paralog warning.

  5. yeast, fly, worm, zebrafish: the share of the genes in the Database of Essential Genes (DEG, independent of the sources
     K-Sites reads) that the organism's own knockout data call lethal, next to the share of ALL genes with a result that are
     called lethal. A source that calls nearly everything lethal is not informative, and the site says so before a run
     (--write-reliability stores the numbers in index.json). The DEG download is optional: without it this check is skipped.

Usage: python tools/check_evidence_data.py --data site/evidence-data [--report report.md] [--write-reliability]
Exit status 1 when a check fails.
"""
import argparse
import collections
import csv
import io
import json
import sys
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from k_sites.knockout_evidence import EvidenceProvider, assess_gene          # noqa: E402
from k_sites.knockout_evidence.provider import DirectorySource              # noqa: E402
from k_sites.workflow.safety_recommender import get_safety_recommendation   # noqa: E402

GOLD = ROOT / "tools" / "data" / "gold"
SAMPLE = 2500                       # genes checked per organism for the rules
PLEIOTROPY = 2.0                    # a typical specific gene, so the verdict rests on the evidence
CORE_AVOID_HUMAN, NON_ESSENTIAL_KEPT_HUMAN, CORE_FLAGGED_MOUSE = 0.90, 0.95, 0.85


def gold(name):
    with open(GOLD / name, encoding="utf-8") as handle:
        return [line.split("\t")[0] for index, line in enumerate(handle) if index and line.strip()]


def verdict(provider, taxid, symbol, context):
    evidence = assess_gene(provider, taxid, symbol, context)
    return evidence, get_safety_recommendation(symbol, PLEIOTROPY, knockout_evidence=evidence)


def rule_violations(provider, taxid, genes, context):
    problems = collections.Counter()
    examples = {}
    for symbol in genes:
        evidence, recommendation = verdict(provider, taxid, symbol, context)
        level, basis = recommendation.safety_level.value, recommendation.evidence_basis
        broken = []
        if level == "SAFE" and evidence["organism"]["call"] == "LETHAL" and context == "organism":
            broken.append("a lethal gene rated SAFE")
        if level == "SAFE" and basis not in ("measured", "ortholog"):
            broken.append("SAFE without a measurement")
        if level == "AVOID" and basis not in ("measured", "ortholog"):
            broken.append("AVOID without a measurement")
        for text in broken:
            problems[text] += 1
            examples.setdefault(text, symbol)
    return problems, examples


DEG_URL = "http://tubic.org/deg/public/download/deg_annotation_e.csv.zip"
# DEG data set -> (taxon id, name): the whole-genome deletion / RNAi / mutant screens of each organism
DEG_SETS = {"DEG2001": ("559292", "yeast"), "DEG2002": ("6239", "worm"), "DEG2004": ("7955", "zebrafish"), "DEG2007": ("7227", "fly")}
MIN_YEAST_RECALL = 0.85           # of the yeast genes essential in the deletion screen, this share must be called lethal


def read_deg(cache):
    """{taxid: {SYMBOL}} of the essential genes of DEG, or None when it cannot be downloaded."""
    path = Path(cache) / "deg_annotation_e.csv"
    try:
        if not path.exists():
            Path(cache).mkdir(parents=True, exist_ok=True)
            response = requests.get(DEG_URL, timeout=120)
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                path.write_bytes(archive.read("deg_annotation_e.csv"))
    except (requests.RequestException, zipfile.BadZipFile, KeyError):
        return None
    essential = collections.defaultdict(set)
    with open(path, encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.reader(handle, delimiter=";"):
            if len(row) > 3 and row[0] in DEG_SETS and row[2] not in ("-", ""):
                essential[DEG_SETS[row[0]][0]].add(row[2].upper())
    return essential


def independent_check(data, index, essential):
    """Per organism: of the DEG essential genes with a result, how many are called lethal, against all genes with a result."""
    found = {}
    for taxid, genes_ess in essential.items():
        if taxid not in index["organisms"]:
            continue
        genes = json.loads((data / index["organisms"][taxid]["file"]).read_text(encoding="utf-8"))["genes"]
        own = [genes[s] for s in genes_ess if s in genes and "v" in genes[s]]
        everything = [r for r in genes.values() if "v" in r]
        if not own or not everything:
            continue
        found[taxid] = {
            "source": "DEG", "essential_genes": len(own),
            "essential_called_lethal": round(100 * sum(1 for r in own if r["v"] == "L") / len(own)),
            "all_called_lethal": round(100 * sum(1 for r in everything if r["v"] == "L") / len(everything)),
        }
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", required=True, help="Folder with the built evidence files")
    parser.add_argument("--report", help="Write the report to this file as well")
    parser.add_argument("--cache", default=str(ROOT / ".cache" / "deg"), help="Where the DEG download is kept")
    parser.add_argument("--write-reliability", action="store_true", help="Store the independent-check numbers in index.json")
    args = parser.parse_args()

    data = Path(args.data)
    index = json.loads((data / "index.json").read_text(encoding="utf-8"))
    provider = EvidenceProvider(DirectorySource(str(data)))
    lines, failures = ["# K-Sites evidence check", ""], []

    lines += ["## Coverage", "", "| Organism | Genes | With a knockout result or ortholog result |", "|---|---|---|"]
    for taxid, info in sorted(index["organisms"].items()):
        lines.append(f"| {info['name']} ({taxid}) | {info['genes']:,} | {info.get('measured', info['genes']):,} |")

    lines += ["", "## Rules", "", "| Organism | Genes checked | Violations |", "|---|---|---|"]
    for taxid, info in sorted(index["organisms"].items()):
        records = json.loads((data / info["file"]).read_text(encoding="utf-8"))["genes"]
        symbols = sorted(records)
        step = max(1, len(symbols) // SAMPLE)
        sample = symbols[::step]
        context = "cells" if taxid == "9606" else "organism"
        problems, examples = rule_violations(provider, taxid, sample, context)
        text = "; ".join(f"{n} x {what} (e.g. {examples[what]})" for what, n in problems.items()) or "none"
        lines.append(f"| {info['name']} | {len(sample):,} | {text} |")
        if problems:
            failures.append(f"{info['name']}: rule violations: {text}")

    def summarise(title, symbols, taxid, context, good, minimum, label):
        counts = collections.Counter()
        misses = []
        for symbol in symbols:
            evidence, recommendation = verdict(provider, taxid, symbol, context)
            if taxid == "9606" and evidence["cells"]["call"] == "UNKNOWN":
                counts["no cell-line result"] += 1
                continue
            level = recommendation.safety_level.value
            counts[level] += 1
            if level not in good:
                misses.append(symbol)
        scored = sum(n for key, n in counts.items() if key != "no cell-line result")
        hit = sum(n for key, n in counts.items() if key in good)
        share = hit / scored if scored else 0
        lines.append(f"- {title}: {hit}/{scored} {label} = {100 * share:.1f}% (required {100 * minimum:.0f}%); levels {dict(counts)}")
        if share < minimum:
            failures.append(f"{title}: {100 * share:.1f}% is below {100 * minimum:.0f}%")

    lines += ["", "## Gold standards", ""]
    core, non_essential = gold("core_essential_CEGv2.tsv"), gold("non_essential_NEGv1.tsv")
    summarise("Human, cells, core-essential genes", core, "9606", "cells", {"AVOID"}, CORE_AVOID_HUMAN, "rated AVOID")
    summarise("Human, cells, non-essential genes", non_essential, "9606", "cells",
              {"SAFE", "CAUTION", "MODERATE_CONCERN", "HIGH_CONCERN"}, NON_ESSENTIAL_KEPT_HUMAN, "not rated AVOID")
    if "10090" in index["organisms"]:
        mouse = json.loads((data / "10090.json").read_text(encoding="utf-8"))["genes"]
        present = [s for s in core if s.upper() in mouse]
        summarise("Mouse, whole animal, core-essential genes", present, "10090", "organism",
                  {"AVOID", "HIGH_CONCERN"}, CORE_FLAGGED_MOUSE, "rated AVOID or HIGH_CONCERN")

    if "559292" in index["organisms"]:
        # duplicated yeast genes: deleting one copy is survivable, so the verdict must say that the other copy covers for it
        pairs = ["RPL1A", "RPL1B", "RPL2A", "RPL2B", "RPS4A", "RPS4B", "RPS18A", "RPS18B"]      # RPL9A/B is missing from the Alliance file, which is a known gap of the source
        missing = [name for name in pairs if not (assess_gene(provider, "559292", name, "organism").get("paralogs") or {}).get("close")]
        lines.append(f"- Yeast, duplicated ribosomal genes with a paralog warning: {len(pairs) - len(missing)}/{len(pairs)}"
                     + (f" (missing: {', '.join(missing)})" if missing else ""))
        if missing:
            failures.append(f"yeast duplicated genes without a paralog warning: {', '.join(missing)}")

    essential = read_deg(args.cache)
    lines += ["", "## Independent check (DEG essential genes)", ""]
    if essential is None:
        lines.append("- The DEG download failed, so this check was skipped.")
    else:
        found = independent_check(data, index, essential)
        for taxid, numbers in found.items():
            lines.append(f"- {index['organisms'][taxid]['name']}: {numbers['essential_called_lethal']}% of {numbers['essential_genes']} "
                         f"known essential genes are called lethal, against {numbers['all_called_lethal']}% of all genes with a result")
        yeast = found.get("559292")
        if yeast and yeast["essential_called_lethal"] < 100 * MIN_YEAST_RECALL:
            failures.append(f"yeast: only {yeast['essential_called_lethal']}% of the deletion-essential genes are called lethal")
        if args.write_reliability and found:
            for taxid, numbers in found.items():
                index["organisms"][taxid]["reliability"] = numbers
            (data / "index.json").write_text(json.dumps(index, separators=(",", ":"), sort_keys=True), encoding="utf-8")
            lines.append("- The numbers were stored in index.json (shown on the website before a run).")

    lines += ["", "## Result", "", "FAILED: " + "; ".join(failures) if failures else "All checks passed."]
    report = "\n".join(lines)
    print(report)
    if args.report:
        Path(args.report).write_text(report + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
