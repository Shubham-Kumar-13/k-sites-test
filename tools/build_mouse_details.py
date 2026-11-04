#!/usr/bin/env python3
"""Build experiment-level mouse provenance from MGI genotypes and IMPC colonies."""

import argparse
import collections
import csv
import json
import sqlite3
from datetime import date
from pathlib import Path

from build_evidence_data import (MPOntology, SurvivalTerms, allele_class, build_mouse, open_text, parse_alleles,
                                 read_genotypes, evaluate_genotype, zygosity, IMPC_CALLS)

ZYGOSITY = {"hom": "homozygous", "hemi": "hemizygous", "compound": "compound_heterozygous"}


def allele_details(ids, alleles):
    return [{"id": allele_id, "symbol": alleles[allele_id]["symbol"], "class": allele_class(alleles.get(allele_id))}
            for allele_id in ids if allele_id in alleles]


def mgi_details(genotypes, alleles, survival):
    records = collections.defaultdict(list)
    for genotype in genotypes.values():
        result = evaluate_genotype(genotype, alleles, survival)
        if result is None or not genotype.marker:
            continue
        call, stage, pmids, systems, premature, infertile = result
        detailed_alleles = allele_details(genotype.alleles, alleles)
        qualifiers = []
        if premature:
            qualifiers.append("reduced_lifespan")
        if infertile:
            qualifiers.append("infertile")
        records[genotype.marker].append({
            "source": "mgi",
            "source_record_id": genotype.gid,
            "call": call,
            "experiment_type": "genetic_mutant",
            "zygosity": ZYGOSITY[zygosity(genotype.composition)],
            "evidence_level": "direct" if all(a["class"] == "ko" for a in detailed_alleles) else "qualified",
            "genotype": genotype.composition,
            "background": genotype.background,
            "alleles": detailed_alleles,
            "phenotype": "; ".join(sorted(survival.mp.names.get(term, term) for term in genotype.mps)),
            "phenotype_terms": [{"id": term, "name": survival.mp.names.get(term, term)} for term in sorted(genotype.mps)],
            "stage": stage,
            "systems": sorted(survival.system_names[term] for term in systems),
            "qualifiers": qualifiers,
            "references": sorted(pmids, key=int),
        })
    return records


def impc_details(viability_rows, g2p_rows, alleles, survival):
    g2p_rows = list(g2p_rows)
    lethal_stage = collections.defaultdict(set)
    for row in g2p_rows:
        if row.get("zygosity") not in ("homozygote", "hemizygote"):
            continue
        term = row.get("mp_term_id", "")
        allele = alleles.get(row.get("allele_accession_id", ""))
        if allele is not None and allele_class(allele) is None:
            continue
        if term in survival.lethal:
            lethal_stage[row.get("marker_accession_id", "")].add(survival.lethal[term][0])
    records = collections.defaultdict(list)
    colonies = set()
    for row in viability_rows:
        call = IMPC_CALLS.get(row.get("Viability Phenotype HOMs/HEMIs", "").strip().lower())
        if call is None or row.get("Zygosity") not in ("homozygote", "hemizygote"):
            continue
        marker = row["Gene Accession Id"]
        allele_id = row.get("Allele Accession Id", "")
        allele = alleles.get(allele_id)
        if allele is not None and allele_class(allele) is None:
            continue
        key = (marker, row.get("Colony Id"), allele_id)
        if key in colonies:
            continue
        colonies.add(key)
        detailed_alleles = allele_details([allele_id], alleles)
        definite = lethal_stage.get(marker, set()) & set("EPJ")
        records[marker].append({
            "source": "impc",
            "source_record_id": row.get("Colony Id", ""),
            "call": call,
            "experiment_type": "impc_viability_screen",
            "zygosity": row["Zygosity"],
            "evidence_level": "direct" if detailed_alleles and all(a["class"] == "ko" for a in detailed_alleles) else "qualified",
            "genotype": "",
            "background": "",
            "alleles": detailed_alleles,
            "phenotype": f"{call} in the IMPC viability screen",
            "phenotype_terms": [],
            "stage": min(definite, key="EPJ".index) if definite else "W",
            "systems": [],
            "qualifiers": ["survival_to_weaning"],
            "references": [],
        })
    for row in g2p_rows:
        if row.get("zygosity") not in ("homozygote", "hemizygote"):
            continue
        marker = row.get("marker_accession_id", "")
        term = row.get("mp_term_id", "")
        allele_id = row.get("allele_accession_id", "")
        allele = alleles.get(allele_id)
        if allele is not None and allele_class(allele) is None:
            continue
        detailed_alleles = allele_details([allele_id], alleles)
        qualifiers = []
        if term in survival.premature_death:
            qualifiers.append("reduced_lifespan")
        if term in survival.infertility:
            qualifiers.append("infertile")
        records[marker].append({
            "source": "impc",
            "source_record_id": f"{row.get('colony_id', '')}:{row.get('parameter_stable_id', '')}",
            "call": "OBSERVATION",
            "experiment_type": "impc_phenotype_assertion",
            "zygosity": row["zygosity"],
            "evidence_level": "direct" if detailed_alleles and all(a["class"] == "ko" for a in detailed_alleles) else "qualified",
            "genotype": "",
            "background": row.get("strain_name", ""),
            "alleles": detailed_alleles,
            "phenotype": row.get("mp_term_name", term),
            "phenotype_terms": [{"id": term, "name": row.get("mp_term_name", term)}],
            "stage": survival.lethal[term][0] if term in survival.lethal else None,
            "systems": sorted(survival.system_names[t] for t in survival.systems_of(term)),
            "qualifiers": qualifiers,
            "references": [],
            "phenotyping_center": row.get("phenotyping_center", ""),
            "parameter_stable_id": row.get("parameter_stable_id", ""),
            "p_value": row.get("p_value", ""),
        })
    return records


def merge_mouse_records(sources):
    merged = collections.defaultdict(list)
    for source in sources:
        for marker, records in source.items():
            merged[marker].extend(records)
    result = {}
    for marker, records in merged.items():
        records.sort(key=lambda record: (record["source"], record["source_record_id"]))
        counts = collections.Counter(record["call"] for record in records if record["call"] in ("L", "S", "V"))
        calls = sorted(counts)
        call = (calls[0] if len(calls) == 1 else "CONFLICTING") if calls else "UNKNOWN"
        result[marker] = {
            "call": call,
            "conflicting": len(calls) > 1,
            "counts": {"lethal": counts["L"], "subviable": counts["S"], "viable": counts["V"]},
            "sources": sorted({record["source"] for record in records}),
            "records": records,
        }
    return result


def validate_mouse_details(data, scoring):
    for gene, record in data["genes"].items():
        expected = scoring[gene]
        counts = record["counts"]
        assert expected["n"] == [counts["lethal"], counts["subviable"], counts["viable"]], gene
        expected_sources = {"mgi": "M", "impc": "I"}
        assert expected["src"] == "".join(expected_sources[source] for source in ("mgi", "impc") if source in record["sources"]), gene
        for finding in record["records"]:
            assert finding["source_record_id"], gene
            assert finding["call"] in ("L", "S", "V", "OBSERVATION"), gene
            assert finding["evidence_level"] in ("direct", "qualified"), gene
            assert finding["experiment_type"] in ("genetic_mutant", "impc_viability_screen", "impc_phenotype_assertion"), gene
    return True


def write_sqlite(path, data):
    path = Path(path)
    if path.exists():
        path.unlink()
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("CREATE TABLE genes (symbol TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        connection.executemany("INSERT INTO metadata VALUES (?, ?)", [
            ("built", data["built"]),
            ("pilot", json.dumps(data.get("pilot", data.get("coverage", {})), separators=(",", ":"))),
        ])
        connection.executemany("INSERT INTO genes VALUES (?, ?)",
                               [(symbol, json.dumps(record, separators=(",", ":"), sort_keys=True))
                                for symbol, record in data["genes"].items()])
        connection.execute("CREATE INDEX genes_symbol_index ON genes(symbol)")
    return path


def build(out, files):
    scoring, by_id, _ = build_mouse(files)
    with open_text(files["MPheno_OBO.ontology"]) as handle:
        survival = SurvivalTerms(MPOntology(handle))
    with open_text(files["MGI_PhenotypicAllele.rpt"]) as handle:
        alleles = parse_alleles(handle)
    with open_text(files["MGI_GenePheno.rpt"]) as handle:
        genotypes = read_genotypes(handle, survival.mp)
    mgi = mgi_details(genotypes, alleles, survival)
    with open_text(files["impc_viability.csv.gz"]) as via, open_text(files["impc_g2p.csv.gz"]) as g2p:
        impc = impc_details(csv.DictReader(via), csv.DictReader(g2p), alleles, survival)
    merged = merge_mouse_records([mgi, impc])
    genes = {by_id[marker].upper(): record for marker, record in merged.items() if marker in by_id}
    data = {
        "format": 1,
        "built": date.today().isoformat(),
        "organism": {"taxid": "10090", "name": "Mus musculus"},
        "coverage": {"scope": "All MGI genotypes and IMPC colonies passing the existing viability rules",
                     "genes": len(genes), "records": sum(len(record["records"]) for record in genes.values())},
        "genes": genes,
    }
    assert len(genes) == len(scoring)
    validate_mouse_details(data, scoring)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    write_sqlite(out.with_suffix(".sqlite"), data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="webapp/results/evidence-details/10090.json")
    parser.add_argument("--cache", default=".cache/evidence-sources")
    args = parser.parse_args()
    names = ("MPheno_OBO.ontology", "MGI_PhenotypicAllele.rpt", "MGI_GenePheno.rpt", "impc_viability.csv.gz", "impc_g2p.csv.gz")
    files = {name: Path(args.cache) / name for name in names}
    data = build(args.out, files)
    print(f"Wrote {args.out}: {len(data['genes'])} genes, {data['coverage']['records']} experiment records")


if __name__ == "__main__":
    main()
