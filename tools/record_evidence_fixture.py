#!/usr/bin/env python3
"""
Record a small copy of the measured-evidence data, and the verdicts the Python code gives for it.

tests/fixtures/evidence/ holds
  - index.json and one file per organism with a few dozen genes taken from the real files (so the tests read the
    real record formats), and
  - golden.json: for a list of cases, the evidence assessment and the safety recommendation computed by the Python
    code. The browser engine (tests/js/evidence.test.mjs) must reproduce every one of them exactly.

    python tools/build_evidence_data.py --out .cache/evidence-out
    python tools/record_evidence_fixture.py                       # reads .cache/evidence-out
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "tests" / "fixtures" / "evidence"

GENES = ["TDG", "POLB", "OGG1", "UNG", "NEIL1", "XPA", "PARP1", "PARP2", "POLQ", "CUL4A", "SIRT6", "PCNA", "APEX1",
         "POLE", "XRCC1", "LIG4", "FEN1", "LIG3", "SMUG1", "NEIL2", "FAM168A", "APEX2", "MPG", "NTHL1", "MUTYH",
         "RPA1", "DDB1", "HMGA1", "HMGA2", "AARS1"]
YEAST = ["ACT1", "RAD52", "POL2", "YML032C", "NTG1"]
# genes of the published knockouts used to validate zebrafish, fly and worm (tests/fixtures/benchmark/paper_truth.json)
PAPER_GENES = {"7955": ["SMN1", "AR", "LHB"], "7227": ["EGFR", "WNT2", "NOS"], "6239": ["SKN-1", "FEM-1"]}
ALIASES = ["AARS"]

# (taxid, symbol, pleiotropy score, context)
CASES = [(taxid, gene, pleiotropy, context)
         for gene, pleiotropy in [("TDG", 7.0), ("POLB", 10.0), ("OGG1", 10.0), ("UNG", 8.3), ("NEIL1", 4.5),
                                  ("XPA", 10.0), ("PARP1", 10.0), ("PARP2", 10.0), ("POLQ", 10.0), ("CUL4A", 10.0),
                                  ("SIRT6", 10.0), ("PCNA", 10.0), ("APEX1", 10.0), ("POLE", 10.0), ("XRCC1", 9.3),
                                  ("LIG4", 10.0), ("FEN1", 8.3), ("LIG3", 10.0), ("SMUG1", 2.6), ("NEIL2", 0.0),
                                  ("FAM168A", 0.0), ("APEX2", 2.6), ("MPG", 4.5), ("HMGA1", 10.0), ("HMGA2", 10.0),
                                  ("AARS", 6.0), ("NOSUCHGENE", 1.0)]
         for taxid, context in [("9606", "auto"), ("9606", "organism"), ("10090", "auto"), ("10090", "cells"),
                                ("10116", "auto")]] + [("7955", gene, 6.0, "auto") for gene in ("TDG", "OGG1")] + [
    ("559292", gene, pleiotropy, "auto") for gene, pleiotropy in [("ACT1", 6.0), ("RAD52", 2.0), ("POL2", 9.0), ("YML032C", 2.0), ("NTG1", 1.0)]]


def sample_result(provider):
    """A pipeline-shaped result for a few genes (and two that are not shown), to compare the Python and browser reports."""
    from k_sites.knockout_evidence import assess_gene
    from k_sites.workflow.pipeline import SAFETY_TIER
    from k_sites.workflow.safety_recommender import get_safety_recommendation

    def gene_entry(symbol, pleiotropy, composite):
        evidence = assess_gene(provider, "9606", symbol)
        verdict = get_safety_recommendation(symbol, pleiotropy, knockout_evidence=evidence,
                                            cross_species_validation={"conservation_score": 0.5}, literature_support=0.5)
        return {
            "symbol": symbol, "description": f"{symbol} protein", "entrez_id": "", "pleiotropy_score": pleiotropy,
            "specificity_score": round(1 - pleiotropy / 10, 4), "evidence_quality": 0.65, "literature_support": 0.5,
            "literature_score": 0.5, "pubmed_count": 41, "conservation_score": 0.5, "composite_score": composite,
            "bp_term_count": 3, "data_issues": [], "kegg_pathway_count": 2, "experimental_evidence_count": 1,
            "computational_evidence_count": 2, "iea_evidence_count": 0, "cross_species_validation": {},
            "phenotype_prediction": None, "knockout_evidence": evidence,
            "safety_recommendation": {
                "evidence_basis": verdict.evidence_basis, "safety_level": verdict.safety_level.value,
                "primary_recommendation": verdict.primary_recommendation.value,
                "alternative_recommendations": [a.value for a in verdict.alternative_recommendations],
                "justification": verdict.justification, "concerns": verdict.concerns,
                "mitigation_strategies": verdict.mitigation_strategies,
                "experimental_considerations": verdict.experimental_considerations, "confidence_score": verdict.confidence_score},
        }

    genes = [gene_entry(*row) for row in [("SMUG1", 2.61, 0.667), ("NEIL2", 0.05, 0.659), ("TDG", 6.99, 0.614),
                                          ("XRCC1", 9.33, 0.501), ("PCNA", 9.87, 0.45), ("RPA3", 9.09, 0.389), ("NOSUCHGENE", 1.05, 0.4)]]
    genes.sort(key=lambda g: (SAFETY_TIER[g["safety_recommendation"]["safety_level"]], -g["composite_score"]))
    excluded = [
        {"symbol": "PARP1", "description": "PARP1 protein", "reason": "pleiotropy",
         "detail": "Pleiotropy score 9.9 is above the cutoff of 7", "pleiotropy_score": 9.93, "composite_score": 0.49,
         "knockout_evidence": assess_gene(provider, "9606", "PARP1")},
        {"symbol": "FEN1", "description": "FEN1 protein", "reason": "ranked",
         "detail": "Ranked below the 6 genes shown (AVOID)", "pleiotropy_score": 5.5, "composite_score": 0.48,
         "knockout_evidence": assess_gene(provider, "9606", "FEN1")},
    ]
    index = provider.index
    return {
        "metadata": {"go_term": "GO:0006284", "organism": "Homo sapiens", "resolved_organism": {"taxid": "9606", "scientific_name": "Homo sapiens"},
                     "timestamp": "2026-10-25T12:00:00.000Z", "execution_duration": 12.5, "max_pleiotropy": 7, "evidence_filter": "all",
                     "knockout_context": "cells",
                     "knockout_evidence_data": {"available": True, "organism_covered": True, "version": index["built"], "sources": index["sources"]}},
        "genes": genes, "excluded_genes": excluded, "insufficient_data_genes": [],
        "warnings": ["Example warning, with a comma"],
        "statistics": {"total_genes_screened": 8, "genes_passed_filter": 6, "genes_insufficient_data": 0, "avg_pleiotropy": 5.0},
    }


def record_report_sample(provider):
    """The reports the Python code writes for sample_result(); tests/js/report.test.mjs must reproduce the CSVs."""
    import shutil
    import tempfile
    from k_sites.reporting.report_generator import generate_html_report
    result = sample_result(provider)
    (FIXTURES / "report_sample.json").write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    with tempfile.TemporaryDirectory() as folder:
        generate_html_report(json.loads(json.dumps(result)), str(Path(folder) / "report_sample.html"))
        for name in ("report_sample.html", "report_sample_comprehensive.csv", "report_sample_gene_summary.csv"):
            shutil.copy(Path(folder) / name, FIXTURES / name)


def pick(genes, keys):
    return {k: genes[k] for k in keys if k in genes}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=str(ROOT / ".cache" / "evidence-out"))
    args = parser.parse_args()
    source = Path(args.data)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for stale in FIXTURES.glob("[0-9]*.json"):                       # an organism that is no longer in the data
        stale.unlink()

    index = json.loads((source / "index.json").read_text(encoding="utf-8"))
    # genes without a knockout result that have an estimate: four known essential ones, and two of each band
    mouse_all = json.loads((source / index["organisms"]["10090"]["file"]).read_text(encoding="utf-8"))["genes"]
    human_all = json.loads((source / index["organisms"]["9606"]["file"]).read_text(encoding="utf-8"))["genes"]
    estimate_keys = ["POLE", "RPA2", "RPA3", "RPS3"]
    band_examples = []
    for low, high in ((0.5, 1.01), (0.3, 0.5), (-1.0, 0.3)):
        band_examples += [k for k in sorted(mouse_all) if "pl" in mouse_all[k] and low <= mouse_all[k]["pl"][0] < high
                          and "pl" in human_all.get(k, {}) and k not in estimate_keys][:2]
    estimate_keys += band_examples
    for taxid, info in index["organisms"].items():
        data = json.loads((source / info["file"]).read_text(encoding="utf-8"))
        own = "knockout" in info["layers"] and info.get("distant")      # zebrafish, fly, worm: measurements of their own
        if info.get("distant"):
            # a distant relative: the genes whose mouse ortholog is one of the genes used here (hints) ...
            wanted = {g.upper() for g in GENES} | {"POLB", "TDG"}
            records = data["genes"]
            keys = sorted(k for k, v in records.items() if "v" not in v and v["o"][0].upper() in wanted)[:6]
            # ... and, where there are measurements, two genes of each kind: lethal with a stage, subviable, viable,
            # reports that disagree, RNAi-only lethality, infertility, and one that has both a measurement and a mouse ortholog
            kinds = [lambda r: r.get("v") == "L" and not r.get("x") and r.get("s") not in (None, "U"),
                     lambda r: r.get("v") == "S", lambda r: r.get("v") == "V" and not r.get("x"), lambda r: r.get("x"),
                     lambda r: r.get("k"), lambda r: r.get("f"), lambda r: "v" in r and "o" in r]
            for kind in kinds:
                keys += [k for k in sorted(records) if "v" in records[k] and kind(records[k]) and k not in keys][:2]
            keys = sorted(set(keys) | {g for g in PAPER_GENES.get(taxid, []) if g in records})
        else:
            keys = YEAST if taxid == "559292" else GENES + ["Polb".upper(), "Tdg".upper()] + estimate_keys
        genes = pick(data["genes"], keys)
        if info.get("distant"):
            aliases = dict(sorted((a, t) for a, t in data["aliases"].items() if t.upper() in genes)[:3])
        else:
            aliases = {a: data["aliases"][a] for a in ALIASES if a in data["aliases"]}
        info["genes"] = len(genes)
        info["measured"] = sum(1 for record in genes.values() if any(key in record for key in (("v", "c") if own else ("v", "m", "c"))))
        (FIXTURES / info["file"]).write_text(json.dumps({"genes": genes, "aliases": aliases}, indent=1, sort_keys=True),
                                             encoding="utf-8")
    (FIXTURES / "index.json").write_text(json.dumps(index, indent=1, sort_keys=True), encoding="utf-8")

    from k_sites.knockout_evidence import EvidenceProvider, assess_gene
    from k_sites.workflow.safety_recommender import get_safety_recommendation
    provider = EvidenceProvider.from_directory(FIXTURES)
    golden = []
    cases = list(CASES)
    for taxid, info in index["organisms"].items():
        if info.get("distant"):
            fixture_genes = json.loads((FIXTURES / info["file"]).read_text(encoding="utf-8"))["genes"]
            fixture_aliases = json.loads((FIXTURES / info["file"]).read_text(encoding="utf-8"))["aliases"]
            cases += [(taxid, symbol, 5.0, "auto") for symbol in sorted(fixture_genes) + sorted(fixture_aliases)]
    for symbol in estimate_keys:
        for taxid, context in (("10090", "auto"), ("10090", "cells"), ("9606", "organism"), ("9606", "auto")):
            cases.append((taxid, symbol, 6.0, context))
        if symbol in band_examples or symbol == "RPA3":
            cases += [("10090", symbol, 2.0, "auto"), ("9606", symbol, 2.0, "organism")]
    for taxid, symbol, pleiotropy, context in cases:
        evidence = assess_gene(provider, taxid, symbol, context)
        recommendation = get_safety_recommendation(symbol, pleiotropy, knockout_evidence=evidence,
                                                   cross_species_validation={"conservation_score": 0.5},
                                                   literature_support=0.5)
        golden.append({
            "taxid": taxid, "symbol": symbol, "pleiotropy": pleiotropy, "context": context, "evidence": evidence,
            "recommendation": {
                "safety_level": recommendation.safety_level.value,
                "primary_recommendation": recommendation.primary_recommendation.value,
                "alternative_recommendations": [a.value for a in recommendation.alternative_recommendations],
                "justification": recommendation.justification, "concerns": recommendation.concerns,
                "mitigation_strategies": recommendation.mitigation_strategies,
                "experimental_considerations": recommendation.experimental_considerations,
                "confidence_score": recommendation.confidence_score, "evidence_basis": recommendation.evidence_basis,
            },
        })
    body = ",\n".join(json.dumps(case, sort_keys=True, separators=(",", ":")) for case in golden)
    (FIXTURES / "golden.json").write_text("[\n" + body + "\n]\n", encoding="utf-8")
    record_report_sample(provider)
    print(f"Recorded {len(golden)} cases and {sum(i['genes'] for i in index['organisms'].values())} genes in {FIXTURES}")


if __name__ == "__main__":
    main()
