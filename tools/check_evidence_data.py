"""
Release gate for the built knockout evidence (run after tools/build_evidence_data.py; the website deploy stops when it fails).

It asks, for every organism file, whether the verdicts follow the rules, and for human and mouse whether they agree with
independent gold standards:

  1. rules (all organisms, a sample of genes): a lethal result is never rated SAFE, a gene without a measurement is never
     rated SAFE, an estimate is never rated AVOID, and every AVOID rests on a measurement;
  2. human, cultured cells: at least 90% of the 684 core-essential genes (CEGv2) are rated AVOID and at least 95% of the 927
     non-essential genes (NEGv1) are not;
  3. mouse, whole animal: at least 85% of the core-essential genes are rated AVOID or HIGH_CONCERN.

Usage: python tools/check_evidence_data.py --data site/evidence-data [--report report.md]
Exit status 1 when a check fails.
"""
import argparse
import collections
import json
import sys
from pathlib import Path

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


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", required=True, help="Folder with the built evidence files")
    parser.add_argument("--report", help="Write the report to this file as well")
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

    lines += ["", "## Result", "", "FAILED: " + "; ".join(failures) if failures else "All checks passed."]
    report = "\n".join(lines)
    print(report)
    if args.report:
        Path(args.report).write_text(report + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
