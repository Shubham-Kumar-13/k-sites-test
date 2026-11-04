#!/usr/bin/env python3
"""Build experiment-level evidence for PomBase fission yeast and SGD budding yeast."""

import argparse
import collections
import json
from datetime import date
from pathlib import Path

from build_evidence_data import YEAST_EXPERIMENTS
from build_mouse_details import merge_mouse_records, write_sqlite

ORGANISMS = {
    "pombe": ("4896", "Schizosaccharomyces pombe", "pombase", "P"),
    "yeast": ("559292", "Saccharomyces cerevisiae S288C", "sgd", "S"),
}


def pombase_details(viability_lines, name_lines):
    names = {}
    for line in name_lines:
        if line.startswith("#") or line.startswith("gene_systematic_id"):
            continue
        parts = line.rstrip("\r\n").split("\t")
        if len(parts) >= 2:
            names[parts[0]] = parts[1] or parts[0]
    records = collections.defaultdict(list)
    for line in viability_lines:
        parts = line.rstrip("\r\n").split("\t")
        if len(parts) < 2 or parts[1] not in ("viable", "inviable", "condition-dependent"):
            continue
        systematic, viability = parts[:2]
        call = {"viable": "V", "inviable": "L", "condition-dependent": "S"}[viability]
        records[names.get(systematic, systematic).upper()].append({
            "source": "pombase",
            "source_record_id": systematic,
            "call": call,
            "experiment_type": "deletion_viability",
            "zygosity": "not_reported",
            "evidence_level": "direct",
            "genotype": "gene deletion",
            "background": "",
            "alleles": [],
            "phenotype": viability,
            "phenotype_terms": [],
            "stage": None,
            "systems": [],
            "qualifiers": ["condition_dependent"] if call == "S" else [],
            "references": [],
        })
    return records


def sgd_details(lines):
    records = collections.defaultdict(list)
    for line_number, line in enumerate(lines, 1):
        fields = line.rstrip("\r\n").split("\t")
        if len(fields) < 12 or fields[6] != "null" or fields[5] not in YEAST_EXPERIMENTS or fields[10].strip() or fields[11].strip():
            continue
        phenotype = fields[9].strip()
        if phenotype not in ("inviable", "viable"):
            continue
        systematic, standard = fields[0], fields[2]
        references = [ref[5:] for ref in fields[4].split("|") if ref.startswith("PMID:") and ref[5:].isdigit()]
        for symbol in {systematic.upper(), (standard or systematic).upper()}:
            records[symbol].append({
                "source": "sgd",
                "source_record_id": f"SGD:{systematic}:{line_number}",
                "call": "L" if phenotype == "inviable" else "V",
                "experiment_type": fields[5],
                "zygosity": "not_reported",
                "evidence_level": "direct",
                "genotype": "null mutation",
                "background": fields[8],
                "alleles": [{"id": fields[7], "symbol": fields[7], "class": "null"}],
                "phenotype": phenotype,
                "phenotype_terms": [],
                "stage": "U" if phenotype == "inviable" else None,
                "systems": [],
                "qualifiers": [],
                "references": references,
            })
    return records


def validate(data, scoring, source_code):
    for gene, record in data["genes"].items():
        counts = record["counts"]
        assert scoring[gene]["n"] == [counts["lethal"], counts["subviable"], counts["viable"]], gene
        assert scoring[gene]["src"] == source_code, gene
    return True


def build(organism, out, cache):
    taxid, name, source, source_code = ORGANISMS[organism]
    if organism == "pombe":
        with open(cache / "pombase_gene_names.tsv", encoding="utf-8") as names, open(cache / "pombase_viability.tsv", encoding="utf-8") as viability:
            records = pombase_details(viability, names)
    else:
        with open(cache / "sgd_phenotype.tab", encoding="utf-8") as handle:
            records = sgd_details(handle)
    genes = merge_mouse_records([records])
    data = {
        "format": 1,
        "built": date.today().isoformat(),
        "organism": {"taxid": taxid, "name": name},
        "coverage": {"scope": f"All {source} rows passing the existing direct-evidence rules",
                     "genes": len(genes), "records": sum(len(record["records"]) for record in genes.values())},
        "genes": genes,
    }
    scoring_path = Path("webapp/results/evidence-data") / f"{taxid}.json"
    scoring = json.loads(scoring_path.read_text(encoding="utf-8"))["genes"]
    assert len(genes) == len(scoring)
    validate(data, scoring, source_code)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    write_sqlite(out.with_suffix(".sqlite"), data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("organism", choices=ORGANISMS)
    parser.add_argument("--out")
    parser.add_argument("--cache", default=".cache/evidence-sources")
    args = parser.parse_args()
    taxid = ORGANISMS[args.organism][0]
    data = build(args.organism, args.out or f"webapp/results/evidence-details/{taxid}.json", Path(args.cache))
    print(f"Wrote {args.out or f'webapp/results/evidence-details/{taxid}.json'}: {len(data['genes'])} genes, {data['coverage']['records']} records")


if __name__ == "__main__":
    main()
