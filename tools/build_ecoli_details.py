#!/usr/bin/env python3
"""Build curated E. coli BW25113 essentiality provenance."""

import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

from build_mouse_details import merge_mouse_records, write_sqlite


def ecoli_details(source):
    frame = pd.read_excel(source)
    gene_column = "Keio gene name"
    essential_column = "EcoGene Essentiality: Escherichia coli BW25113"
    missing = {gene_column, essential_column, "Core Essentiality"} - set(frame.columns)
    if missing:
        raise ValueError(f"E. coli source is missing columns: {', '.join(sorted(missing))}")
    records = {}
    for _, row in frame.iterrows():
        symbol = row[gene_column]
        if not symbol or pd.isna(symbol):
            continue
        essential = row[essential_column]
        core = row["Core Essentiality"]
        if essential not in (0, 1) or core not in (0, 1):
            raise ValueError(f"Unexpected E. coli essentiality flags for {symbol}")
        symbol = str(symbol).strip().upper()
        locus = row.get("Locus: Escherichia coli BW25113 (Keio)", "")
        if pd.isna(locus):
            locus = ""
        records[symbol] = {
            "call": "L" if essential == 1 else "V",
            "experiment_type": "curated_essentiality",
            "zygosity": "not_reported",
            "evidence_level": "direct",
            "genotype": "Keio collection / curated essentiality",
            "background": "E. coli BW25113",
            "alleles": [{"id": str(locus), "symbol": symbol, "class": "essentiality"}],
            "phenotype": "essential" if essential == 1 else "non-essential",
            "phenotype_terms": [],
            "stage": None,
            "systems": [],
            "qualifiers": ["core_essential"] if core == 1 else [],
            "references": [],
            "source": "ecoli_core",
            "source_record_id": str(locus) or symbol,
        }
    return records


def validate(data, scoring):
    for gene, record in data["genes"].items():
        expected = scoring[gene]
        counts = record["counts"]
        assert expected["n"] == [counts["lethal"], counts["subviable"], counts["viable"]], gene
        assert expected["src"] == "EC", gene
    return True


def build(out, source):
    records = ecoli_details(source)
    genes = merge_mouse_records([{gene: [record] for gene, record in records.items()}])
    data = {
        "format": 1,
        "built": date.today().isoformat(),
        "organism": {"taxid": "83333", "name": "Escherichia coli"},
        "coverage": {"scope": "All curated EcoGene essentiality records for E. coli BW25113",
                     "genes": len(genes), "records": sum(len(record["records"]) for record in genes.values())},
        "genes": genes,
    }
    scoring = json.loads(Path("webapp/results/evidence-data/83333.json").read_text(encoding="utf-8"))["genes"]
    assert len(genes) == len(scoring)
    validate(data, scoring)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    write_sqlite(out.with_suffix(".sqlite"), data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="webapp/results/evidence-details/83333.json")
    parser.add_argument("--source", default=".cache/evidence-sources/ecoli_core_essential.xlsx")
    args = parser.parse_args()
    data = build(args.out, args.source)
    print(f"Wrote {args.out}: {len(data['genes'])} genes, {data['coverage']['records']} essentiality records")


if __name__ == "__main__":
    main()
