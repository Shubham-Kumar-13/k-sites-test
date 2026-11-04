#!/usr/bin/env python3
"""Build experiment-level zebrafish evidence from clean homozygous ZFIN mutant lines."""

import argparse
import collections
import json
from datetime import date
from pathlib import Path

from build_evidence_data import (ZFIN_DEAD, ZFIN_JUVENILE_HOURS, ZFIN_REDUCED, ZFIN_WHOLE_ORGANISM, earliest_stage, open_text,
                                 parse_zfin_features, parse_zfin_fish, parse_zfin_stages, zfin_stage_letter)
from build_mouse_details import merge_mouse_records, write_sqlite


def fish_metadata(lines, accepted):
    metadata = collections.defaultdict(lambda: {"name": "", "alleles": set()})
    for line in lines:
        fields = line.rstrip("\r\n").split("\t")
        if len(fields) >= 6 and fields[0] in accepted:
            metadata[fields[0]]["name"] = fields[1]
            if fields[4]:
                metadata[fields[0]]["alleles"].add(fields[4])
    return {fish: {"name": item["name"], "alleles": sorted(item["alleles"])} for fish, item in metadata.items()}


def zfin_details(phenotype_lines, fish, metadata, stages, pubmed):
    symbols = {}
    observations = collections.defaultdict(list)
    for line in phenotype_lines:
        fields = line.rstrip("\r\n").split("\t")
        if len(fields) < 24 or fields[18] not in fish or fish[fields[18]][0] != fields[2]:
            continue
        symbols[fields[2]] = fields[1]
        stage = zfin_stage_letter(fields[20], stages)
        observations[fields[18]].append({
            "pato": fields[9],
            "term": fields[10],
            "structure": fields[7],
            "tag": fields[11],
            "stage": stage,
            "begin_hours": stages[fields[20]][0] if fields[20] in stages else None,
            "reference": fields[23],
        })
    records = collections.defaultdict(list)
    for fish_id, items in observations.items():
        gene, kind = fish[fish_id]
        lethal = [item for item in items if item["structure"] == ZFIN_WHOLE_ORGANISM and item["tag"] == "abnormal" and item["pato"] in ZFIN_DEAD]
        reduced = [item for item in items if item["structure"] == ZFIN_WHOLE_ORGANISM and item["tag"] == "abnormal" and item["pato"] in ZFIN_REDUCED]
        late = [item for item in items if item["begin_hours"] is not None and item["begin_hours"] >= ZFIN_JUVENILE_HOURS]
        if lethal:
            call = "L"
        elif reduced:
            call = "S"
        elif late and kind == "null":
            call = "V"
        else:
            continue
        stage = earliest_stage({item["stage"] for item in lethal + reduced}) if call in ("L", "S") else None
        references = sorted({pubmed[item["reference"]] for item in lethal + reduced + late if item["reference"] in pubmed}, key=int)
        records[symbols[gene].upper()].append({
            "source": "zfin",
            "source_record_id": fish_id,
            "call": call,
            "experiment_type": "homozygous_mutant_line",
            "zygosity": "homozygous",
            "evidence_level": "direct" if kind == "null" else "qualified",
            "genotype": metadata[fish_id]["name"],
            "background": "",
            "alleles": [{"id": allele, "symbol": allele, "class": kind} for allele in metadata[fish_id]["alleles"]],
            "phenotype": "; ".join(sorted({item["term"] for item in items})),
            "phenotype_terms": items,
            "stage": stage,
            "systems": [],
            "qualifiers": ["living_juvenile_or_adult"] if call == "V" else [],
            "references": references,
        })
    return records


def validate(data, scoring):
    for gene, record in data["genes"].items():
        expected = scoring[gene]
        counts = record["counts"]
        assert expected["n"] == [counts["lethal"], counts["subviable"], counts["viable"]], gene
        assert expected["src"] == "Z", gene
    return True


def build(out, cache):
    with open_text(cache / "zfin_stages.txt") as handle:
        stages = parse_zfin_stages(handle)
    with open_text(cache / "zfin_features.txt") as handle:
        features = parse_zfin_features(handle)
    with open_text(cache / "zfin_fish_components.txt") as handle:
        fish = parse_zfin_fish(handle, features)
    with open_text(cache / "zfin_fish_components.txt") as handle:
        metadata = fish_metadata(handle, fish)
    with open_text(cache / "zfin_pubmed.txt") as handle:
        pubmed = {fields[0]: fields[1] for fields in (line.rstrip("\r\n").split("\t") for line in handle)
                  if len(fields) >= 2 and fields[1].isdigit()}
    with open_text(cache / "zfin_phenotype.txt") as handle:
        records = zfin_details(handle, fish, metadata, stages, pubmed)
    genes = merge_mouse_records([records])
    data = {
        "format": 1,
        "built": date.today().isoformat(),
        "organism": {"taxid": "7955", "name": "Danio rerio"},
        "coverage": {"scope": "All clean homozygous ZFIN mutant lines passing the existing viability rules",
                     "genes": len(genes), "records": sum(len(record["records"]) for record in genes.values())},
        "genes": genes,
    }
    scoring = json.loads(Path("webapp/results/evidence-data/7955.json").read_text(encoding="utf-8"))["genes"]
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
    parser.add_argument("--out", default="webapp/results/evidence-details/7955.json")
    parser.add_argument("--cache", default=".cache/evidence-sources")
    args = parser.parse_args()
    data = build(args.out, Path(args.cache))
    print(f"Wrote {args.out}: {len(data['genes'])} genes, {data['coverage']['records']} mutant-line records")


if __name__ == "__main__":
    main()
