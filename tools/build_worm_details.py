#!/usr/bin/env python3
"""Build experiment-level C. elegans evidence from WormBase alleles and RNAi."""

import argparse
import collections
import gzip
import json
from datetime import date
from pathlib import Path

from build_evidence_data import (MPOntology, WORM_EMBRYONIC, WORM_LARVAL, WORM_ADULT, WORM_LETHAL, WORM_STERILE,
                                 WORM_MIN_VIABLE_ALLELES, earliest_stage, open_text, parse_worm_papers)
from build_mouse_details import merge_mouse_records, write_sqlite


def worm_details(lines, ontology, papers):
    lethal = ontology.descendants(WORM_LETHAL)
    stage_of = {term: ("E" if term in ontology.descendants(WORM_EMBRYONIC) else
                       "L" if term in ontology.descendants(WORM_LARVAL) else
                       "A" if term in ontology.descendants(WORM_ADULT) else "U") for term in lethal}
    sterile = ontology.descendants(WORM_STERILE)
    genes = {}
    sequence_names = {}
    for line in lines:
        if line.startswith("!") or not line.strip():
            continue
        fields = line.rstrip("\r\n").split("\t")
        if len(fields) < 11 or fields[0] != "WB":
            continue
        term, negated = fields[4], fields[3].strip().upper() == "NOT"
        if term not in lethal and term not in sterile:
            continue
        gene = genes.setdefault(fields[1], {"symbol": fields[2], "experiments": {}})
        if fields[10]:
            sequence_names[fields[10].upper()] = fields[2]
        for experiment in (value for value in fields[7].split("|") if value.startswith(("WB:WBVar", "WB:WBRNAi"))):
            item = gene["experiments"].setdefault(experiment, {"lethal": set(), "notlethal": False, "sterile": False, "refs": []})
            if term in lethal and not negated:
                item["lethal"].add(stage_of[term])
                item["refs"].append(fields[5].replace("WB_REF:", ""))
            elif term == WORM_LETHAL and negated:
                item["notlethal"] = True
                item["refs"].append(fields[5].replace("WB_REF:", ""))
            elif term in sterile and not negated:
                item["sterile"] = True
    records = collections.defaultdict(list)
    for gene in genes.values():
        viable_alleles = []
        for experiment, item in gene["experiments"].items():
            if item["lethal"]:
                call = "L"
            elif item["notlethal"] and experiment.startswith("WB:WBVar"):
                viable_alleles.append(experiment)
                continue
            else:
                continue
            records[gene["symbol"].upper()].append({
                "source": "wormbase",
                "source_record_id": experiment,
                "call": call,
                "experiment_type": "RNAi" if experiment.startswith("WB:WBRNAi") else "allele",
                "zygosity": "not_reported",
                "evidence_level": "qualified" if experiment.startswith("WB:WBRNAi") else "direct",
                "genotype": gene["symbol"],
                "background": "",
                "alleles": [{"id": experiment, "symbol": experiment, "class": "RNAi" if experiment.startswith("WB:WBRNAi") else "allele"}],
                "phenotype": "lethal",
                "phenotype_terms": [],
                "stage": earliest_stage(item["lethal"]),
                "systems": [],
                "qualifiers": (["infertile"] if item["sterile"] else []) + (["rnai_only"] if experiment.startswith("WB:WBRNAi") else []),
                "references": sorted({papers[ref] for ref in item["refs"] if ref in papers}, key=int),
            })
        for experiment in viable_alleles if len(viable_alleles) >= WORM_MIN_VIABLE_ALLELES else []:
            item = gene["experiments"][experiment]
            records[gene["symbol"].upper()].append({
                "source": "wormbase",
                "source_record_id": experiment,
                "call": "V",
                "experiment_type": "allele",
                "zygosity": "not_reported",
                "evidence_level": "qualified",
                "genotype": gene["symbol"],
                "background": "",
                "alleles": [{"id": experiment, "symbol": experiment, "class": "allele"}],
                "phenotype": "not lethal",
                "phenotype_terms": [],
                "stage": None,
                "systems": [],
                "qualifiers": ["viability_requires_two_alleles"] if len(viable_alleles) >= WORM_MIN_VIABLE_ALLELES else ["insufficient_viability_evidence"],
                "references": sorted({papers[ref] for ref in item["refs"] if ref in papers}, key=int),
            })
    return records, sequence_names


def validate(data, scoring):
    for gene, record in data["genes"].items():
        expected = scoring[gene]
        counts = record["counts"]
        assert expected["n"] == [counts["lethal"], counts["subviable"], counts["viable"]], gene
        assert expected["src"] == "W", gene
        lethal = [finding for finding in record["records"] if finding["call"] == "L"]
        assert bool(expected.get("k")) == bool(lethal and all(finding["experiment_type"] == "RNAi" for finding in lethal)), gene
    return True


def build(out, cache):
    with open_text(cache / "wormbase_phenotype_ontology.obo.gz") as handle:
        ontology = MPOntology(handle)
    with gzip.open(cache / "alliance_phenotype_wb.json.gz", "rt", encoding="utf-8") as handle:
        papers = parse_worm_papers(json.load(handle))
    with open_text(cache / "wormbase_phenotype_association.wb.gz") as handle:
        records, _ = worm_details(handle, ontology, papers)
    genes = merge_mouse_records([records])
    data = {
        "format": 1,
        "built": date.today().isoformat(),
        "organism": {"taxid": "6239", "name": "Caenorhabditis elegans"},
        "coverage": {"scope": "All WormBase allele and RNAi experiments passing the existing viability rules",
                     "genes": len(genes), "records": sum(len(record["records"]) for record in genes.values())},
        "genes": genes,
    }
    scoring = json.loads(Path("webapp/results/evidence-data/6239.json").read_text(encoding="utf-8"))["genes"]
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
    parser.add_argument("--out", default="webapp/results/evidence-details/6239.json")
    parser.add_argument("--cache", default=".cache/evidence-sources")
    args = parser.parse_args()
    data = build(args.out, Path(args.cache))
    print(f"Wrote {args.out}: {len(data['genes'])} genes, {data['coverage']['records']} experiment records")


if __name__ == "__main__":
    main()
