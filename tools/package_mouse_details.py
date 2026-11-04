#!/usr/bin/env python3
"""Audit and package the reproducible MGI/IMPC experiment-level release."""

import argparse
import collections
import csv
import json
import sqlite3
import subprocess
import zipfile
from datetime import date
from pathlib import Path

import requests

from build_evidence_data import MPOntology, SurvivalTerms, build_mouse, open_text, parse_alleles, read_genotypes
from build_mouse_details import impc_details, merge_mouse_records, mgi_details, validate_mouse_details
from package_evidence_details import sha256

SOURCE_NAMES = ("MPheno_OBO.ontology", "MGI_PhenotypicAllele.rpt", "MGI_GenePheno.rpt", "impc_viability.csv.gz", "impc_g2p.csv.gz")


def audit(data, files):
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
    expected = {by_id[marker].upper(): record for marker, record in merged.items() if marker in by_id}
    if data["genes"] != expected:
        raise ValueError("Mouse detailed evidence does not exactly match the raw MGI/IMPC records")
    validate_mouse_details(data, scoring)
    records = [finding for gene in data["genes"].values() for finding in gene["records"]]
    return {
        "genes": len(data["genes"]),
        "records": len(records),
        "calls": dict(collections.Counter(gene["call"] for gene in data["genes"].values())),
        "mgi_records": sum(finding["source"] == "mgi" for finding in records),
        "impc_records": sum(finding["source"] == "impc" for finding in records),
        "observations": sum(finding["call"] == "OBSERVATION" for finding in records),
    }, {pmid for finding in records for pmid in finding["references"]}


def audit_pubmed_sample(pmids, http, maximum=100):
    ordered = sorted(pmids, key=int)
    step = max(1, len(ordered) // maximum)
    sample = ordered[::step][:maximum]
    for start in range(0, len(sample), 50):
        batch = sample[start:start + 50]
        response = http.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                            params={"db": "pubmed", "id": ",".join(batch), "retmode": "json"}, timeout=60)
        response.raise_for_status()
        result = response.json()["result"]
        if set(result["uids"]) != set(batch):
            raise ValueError(f"Missing PubMed records: {set(batch) - set(result['uids'])}")
    return len(sample)


def create_release(details_path, sqlite_path, files, manifest_path, package_path):
    data = json.loads(Path(details_path).read_text(encoding="utf-8"))
    validation, pmids = audit(data, files)
    with sqlite3.connect(sqlite_path) as connection:
        sqlite_genes = connection.execute("SELECT COUNT(*) FROM genes").fetchone()[0]
    if sqlite_genes != len(data["genes"]):
        raise ValueError("SQLite gene count does not match JSON")
    http = requests.Session()
    http.headers["User-Agent"] = "K-Sites mouse evidence release validator"
    validation["pubmed_sample_valid"] = audit_pubmed_sample(pmids, http)
    scripts = [Path(__file__), Path(__file__).parent / "build_mouse_details.py", Path(__file__).parent / "build_evidence_data.py"]
    manifest = {
        "format": 1,
        "created": date.today().isoformat(),
        "organism": data["organism"],
        "coverage": data["coverage"],
        "details": {"json": Path(details_path).name, "sqlite": Path(sqlite_path).name,
                    "json_sha256": sha256(details_path), "sqlite_sha256": sha256(sqlite_path)},
        "builder": {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                    "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()),
                    "scripts": [{"file": f"builder/{script.name}", "sha256": sha256(script)} for script in scripts]},
        "validation": validation,
        "sources": {name: {"file": f"sources/{name}", "sha256": sha256(files[name])} for name in SOURCE_NAMES},
    }
    manifest_path = Path(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in ((details_path, Path(details_path).name), (sqlite_path, Path(sqlite_path).name),
                           (manifest_path, "manifest.json")):
            archive.write(path, name)
        for script in scripts:
            archive.write(script, f"builder/{script.name}")
        for name, path in files.items():
            archive.write(path, f"sources/{name}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--details", default="webapp/results/evidence-details/10090.json")
    parser.add_argument("--sqlite", default="webapp/results/evidence-details/10090.sqlite")
    parser.add_argument("--manifest", default="webapp/results/evidence-details/10090-manifest.json")
    parser.add_argument("--package", default="webapp/results/evidence-details-mouse-release.zip")
    parser.add_argument("--cache", default=".cache/evidence-sources")
    args = parser.parse_args()
    files = {name: Path(args.cache) / name for name in SOURCE_NAMES}
    manifest = create_release(args.details, args.sqlite, files, args.manifest, args.package)
    print(f"Validated {manifest['details']['json']} and {manifest['details']['sqlite']}; wrote {args.package}")


if __name__ == "__main__":
    main()
