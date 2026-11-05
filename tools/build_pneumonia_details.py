#!/usr/bin/env python3
"""Build strain-resolved Streptococcus pneumoniae Tn-seq essentiality evidence."""

import argparse
import collections
import json
from datetime import date
from pathlib import Path

import pandas as pd

from build_mouse_details import merge_mouse_records, write_sqlite

TAXID = "1313"
NAME = "Streptococcus pneumoniae"
SOURCE_CODE = "PN"


def pneumonia_details(source):
    frame = pd.read_excel(source, sheet_name="Supplementary_data_6")
    frame = frame[frame["Binomial Call"].isin(["Essential", "Non-Essential"])].copy()
    frame = frame.drop_duplicates(["Strain", "locus_tag", "Binomial Call"])
    grouped = collections.defaultdict(list)
    for (subcluster, strain), rows in frame.groupby(["Subcluster", "Strain"], sort=True):
        calls = set(rows["Binomial Call"])
        call = "Essential" if "Essential" in calls else "Non-Essential"
        grouped[subcluster].append({
            "strain": strain,
            "call": call,
            "locus_tags": sorted(rows["locus_tag"].unique()),
            "z_values": sorted(set(rows["Binomial z value"].dropna())),
        })
    scoring, details = {}, {}
    for subcluster, rows in grouped.items():
        d39 = sorted({tag for row in rows for tag in row["locus_tags"] if str(tag).startswith("EQH42_")})
        tigr4 = sorted({tag for row in rows for tag in row["locus_tags"] if str(tag).startswith("EQH41_")})
        key = d39[0] if d39 else tigr4[0] if tigr4 else sorted({tag for row in rows for tag in row["locus_tags"]})[0]
        essential = sum(row["call"] == "Essential" for row in rows)
        nonessential = len(rows) - essential
        call = "L" if essential >= nonessential else "V"
        scoring[key] = {"v": call, "n": [essential, 0, nonessential], "src": SOURCE_CODE, "id": key}
        if essential and nonessential:
            scoring[key]["x"] = 1
        details[key] = []
        for row in rows:
            details[key].append({
                "source": "pneumonia_pan_genome",
                "source_record_id": f"{subcluster}:{row['strain']}",
                "call": "L" if row["call"] == "Essential" else "V",
                "experiment_type": "Tn-seq essentiality",
                "zygosity": "haploid",
                "evidence_level": "direct",
                "genotype": "Tn5 transposon insertion library",
                "background": row["strain"],
                "alleles": [{"id": tag, "symbol": tag, "class": "transposon_insertion"} for tag in row["locus_tags"]],
                "phenotype": row["call"],
                "phenotype_terms": [],
                "stage": None,
                "systems": [],
                "qualifiers": [],
                "references": [],
                "subcluster": str(subcluster),
                "binomial_z_values": row["z_values"],
            })
    return scoring, details


def build(out, details_dir, source):
    scoring, details = pneumonia_details(source)
    out, details_dir = Path(out), Path(details_dir)
    out.mkdir(parents=True, exist_ok=True)
    details_dir.mkdir(parents=True, exist_ok=True)
    (out / f"{TAXID}.json").write_text(json.dumps({"genes": scoring, "aliases": {}}, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    data = {
        "format": 1,
        "built": date.today().isoformat(),
        "organism": {"taxid": TAXID, "name": NAME},
        "coverage": {"scope": "All usable pneumococcal Tn-seq essentiality calls across study strains",
                     "genes": len(scoring), "records": sum(len(record) for record in details.values())},
        "genes": merge_mouse_records([details]),
    }
    (details_dir / f"{TAXID}.json").write_text(json.dumps(data, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    write_sqlite(details_dir / f"{TAXID}.sqlite", data)
    return scoring, data["genes"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=".cache/evidence-sources/pneumonia_pan_genome.xlsx")
    parser.add_argument("--out", default="webapp/results/evidence-data")
    parser.add_argument("--details-dir", default="webapp/results/evidence-details")
    args = parser.parse_args()
    scoring, _ = build(args.out, args.details_dir, args.source)
    print(NAME, len(scoring), collections.Counter(record["v"] for record in scoring.values()))


if __name__ == "__main__":
    main()
