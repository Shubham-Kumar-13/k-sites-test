#!/usr/bin/env python3
"""Build scoring and experiment-level evidence from the published TraDIS essentiality table."""

import argparse
import collections
import json
from datetime import date
from pathlib import Path

import pandas as pd

from build_mouse_details import merge_mouse_records, write_sqlite

ORGANISMS = {
    "573": {
        "name": "Klebsiella pneumoniae Ecl8",
        "essentiality": "TraDIS Essentiality: Klebsiella pneumoniae Ecl8",
        "locus": "Locus: Klebsiella pneumoniae Ecl8",
        "background": "Klebsiella pneumoniae Ecl8",
    },
    "637910": {
        "name": "Citrobacter rodentium ICC168",
        "essentiality": "TraDIS Essentiality: Citrobacter rodentium ICC168",
        "locus": "Locus: Citrobacter rodentium ICC168",
        "background": "Citrobacter rodentium ICC168",
    },
    "90370": {
        "name": "Salmonella enterica subsp. enterica serovar Typhi Ty2",
        "essentiality": "TraDIS Essentiality: Salmonella Typhi Ty2",
        "locus": "Locus: Salmonella Typhi Ty2",
        "background": "Salmonella Typhi Ty2",
    },
    "216597": {
        "name": "Salmonella enterica subsp. enterica serovar Typhimurium str. SL1344",
        "essentiality": "TraDIS Essentiality: Salmonella Typhimurium SL1344",
        "locus": "Locus: Salmonella Typhimurium SL1344",
        "background": "Salmonella Typhimurium SL1344",
    },
    "149539": {
        "name": "Salmonella enterica subsp. enterica serovar Enteritidis P125109",
        "essentiality": "TraDIS Essentiality: Salmonella Enteritidis P125109",
        "locus": "Locus: Salmonella Enteritidis P125109",
        "background": "Salmonella Enteritidis P125109",
    },
}


def build_tradis(source, taxids=tuple(ORGANISMS)):
    frame = pd.read_excel(source)
    scoring, details = {}, {}
    for taxid in taxids:
        info = ORGANISMS[taxid]
        essentiality, locus_column = info["essentiality"], info["locus"]
        if essentiality not in frame.columns or locus_column not in frame.columns:
            raise ValueError(f"TraDIS source is missing columns for {info['name']}")
        genes = {}
        detail_records = {}
        for _, row in frame.iterrows():
            symbol = row.get("Keio gene name")
            score = row[essentiality]
            if not symbol or pd.isna(symbol) or pd.isna(score):
                continue
            symbol = str(symbol).strip().upper()
            score = float(score)
            call = "L" if score <= 0 else "V"
            locus = row[locus_column]
            if pd.isna(locus) or not locus:
                locus = symbol
            record = {"v": call, "n": [1 if call == "L" else 0, 0, 1 if call == "V" else 0],
                      "src": "TD", "id": str(locus)}
            key = symbol if symbol not in genes or genes[symbol]["id"] == str(locus) else str(locus)
            if key in genes and genes[key]["id"] == str(locus) and genes[key]["v"] != call:
                raise ValueError(f"Conflicting TraDIS rows for {symbol} in {info['name']}")
            genes[key] = record
            detail_records[key] = [{
                "source": "tradis",
                "source_record_id": str(locus),
                "call": call,
                "experiment_type": "transposon_insertion_essentiality",
                "zygosity": "haploid",
                "evidence_level": "direct",
                "genotype": "Tn5 transposon insertion library",
                "background": info["background"],
                "alleles": [{"id": str(locus), "symbol": symbol, "class": "transposon_insertion"}],
                "phenotype": "essential" if call == "L" else "non-essential",
                "phenotype_terms": [],
                "stage": None,
                "systems": [],
                "qualifiers": [],
                "references": [],
                "essentiality_score": score,
            }]
        scoring[taxid] = genes
        details[taxid] = merge_mouse_records([detail_records])
    return scoring, details


def build(out, details_dir, source, taxids=tuple(ORGANISMS)):
    scoring, details = build_tradis(source, taxids)
    out, details_dir = Path(out), Path(details_dir)
    out.mkdir(parents=True, exist_ok=True)
    details_dir.mkdir(parents=True, exist_ok=True)
    built = date.today().isoformat()
    for taxid, genes in scoring.items():
        (out / f"{taxid}.json").write_text(json.dumps({"genes": genes, "aliases": {}}, separators=(",", ":"), sort_keys=True), encoding="utf-8")
        data = {
            "format": 1,
            "built": built,
            "organism": {"taxid": taxid, "name": ORGANISMS[taxid]["name"]},
            "coverage": {"scope": "All TraDIS essentiality scores from the published Enterobacteriaceae study",
                         "genes": len(genes), "records": len(genes)},
            "genes": details[taxid],
        }
        (details_dir / f"{taxid}.json").write_text(json.dumps(data, separators=(",", ":"), sort_keys=True), encoding="utf-8")
        write_sqlite(details_dir / f"{taxid}.sqlite", data)
    return scoring, details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=".cache/evidence-sources/ecoli_core_essential.xlsx")
    parser.add_argument("--out", default="webapp/results/evidence-data")
    parser.add_argument("--details-dir", default="webapp/results/evidence-details")
    parser.add_argument("--organisms", nargs="*", default=list(ORGANISMS), choices=list(ORGANISMS))
    args = parser.parse_args()
    scoring, _ = build(args.out, args.details_dir, args.source, tuple(args.organisms))
    for taxid, genes in scoring.items():
        print(taxid, ORGANISMS[taxid]["name"], len(genes), collections.Counter(record["v"] for record in genes.values()))


if __name__ == "__main__":
    main()
