#!/usr/bin/env python3
"""Build experiment-level Drosophila evidence from FlyBase single-allele phenotypes."""

import argparse
import collections
import json
from datetime import date
from pathlib import Path

from build_evidence_data import (FLY_EXCLUDED_QUALIFIERS, FLY_PARTIAL_LETHAL_PREFIX, FLY_COMPLETE_LETHAL_PREFIX,
                                 FLY_VIABLE, FLY_STERILE, earliest_stage, fly_stage_letter, open_text,
                                 parse_fly_alleles, parse_fly_references)
from build_mouse_details import merge_mouse_records, write_sqlite


def fly_details(phenotype_lines, alleles, pubmed):
    state = {}
    for line in phenotype_lines:
        if line.startswith("#") or not line.strip():
            continue
        fields = line.rstrip("\r\n").split("\t")
        if len(fields) < 7 or fields[1] not in alleles or any(word in fields[4].lower() for word in FLY_EXCLUDED_QUALIFIERS):
            continue
        name, term = fields[2], fields[3]
        item = state.setdefault(fields[1], {"L": [], "S": [], "V": [], "sterile": False, "observations": []})
        if name.startswith(FLY_PARTIAL_LETHAL_PREFIX) or name == "semi-lethal":
            item["S"].append(fly_stage_letter(name))
        elif name.startswith(FLY_COMPLETE_LETHAL_PREFIX) and term.startswith("FBcv:"):
            item["L"].append(fly_stage_letter(name))
        elif term == FLY_VIABLE:
            item["V"].append("V")
        elif term in FLY_STERILE:
            item["sterile"] = True
        else:
            continue
        item["observations"].append({"name": name, "term": term, "reference": fields[6]})
    records = collections.defaultdict(list)
    for allele_id, item in state.items():
        gene, symbol, kind = alleles[allele_id]
        if item["L"]:
            call = "L"
        elif item["S"]:
            call = "S"
        elif item["V"] and kind == "null":
            call = "V"
        else:
            continue
        stage = earliest_stage(set(item[call])) if call in ("L", "S") else None
        references = sorted({pubmed[observation["reference"]] for observation in item["observations"]
                             if observation["reference"] in pubmed}, key=int)
        records[symbol.upper()].append({
            "source": "flybase",
            "source_record_id": allele_id,
            "call": call,
            "experiment_type": "single_allele_genotype",
            "zygosity": "not_reported",
            "evidence_level": "direct" if kind == "null" else "qualified",
            "genotype": allele_id,
            "background": "",
            "alleles": [{"id": allele_id, "symbol": allele_id, "class": kind}],
            "phenotype": "; ".join(sorted({observation["name"] for observation in item["observations"]})),
            "phenotype_terms": item["observations"],
            "stage": stage,
            "systems": [],
            "qualifiers": ["infertile"] if item["sterile"] else [],
            "references": references,
        })
    return records


def validate(data, scoring):
    for gene, record in data["genes"].items():
        expected = scoring[gene]
        counts = record["counts"]
        assert expected["n"] == [counts["lethal"], counts["subviable"], counts["viable"]], gene
        assert expected["src"] == "F", gene
    return True


def build(out, cache):
    with open_text(cache / "flybase_alleles.tsv.gz") as handle:
        alleles = parse_fly_alleles(handle)
    with open_text(cache / "flybase_references.tsv.gz") as handle:
        pubmed = parse_fly_references(handle)
    with open_text(cache / "flybase_genotype_phenotype.tsv.gz") as handle:
        records = fly_details(handle, alleles, pubmed)
    genes = merge_mouse_records([records])
    data = {
        "format": 1,
        "built": date.today().isoformat(),
        "organism": {"taxid": "7227", "name": "Drosophila melanogaster"},
        "coverage": {"scope": "All FlyBase single-allele genotypes passing the existing viability rules",
                     "genes": len(genes), "records": sum(len(record["records"]) for record in genes.values())},
        "genes": genes,
    }
    scoring = json.loads(Path("webapp/results/evidence-data/7227.json").read_text(encoding="utf-8"))["genes"]
    direct = {gene: record for gene, record in scoring.items() if "v" in record}
    assert len(genes) == len(direct)
    validate(data, direct)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    write_sqlite(out.with_suffix(".sqlite"), data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="webapp/results/evidence-details/7227.json")
    parser.add_argument("--cache", default=".cache/evidence-sources")
    args = parser.parse_args()
    data = build(args.out, Path(args.cache))
    print(f"Wrote {args.out}: {len(data['genes'])} genes, {data['coverage']['records']} allele records")


if __name__ == "__main__":
    main()
