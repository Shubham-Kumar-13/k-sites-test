#!/usr/bin/env python3
"""Audit and package detailed releases for PomBase, SGD, ZFIN, FlyBase, WormBase and E. coli."""

import argparse
import csv
import gzip
import json
import subprocess
import zipfile
from datetime import date
from pathlib import Path

import requests

from build_evidence_data import (MPOntology, SurvivalTerms, open_text, parse_fly_alleles, parse_fly_references,
                                 parse_worm_papers, parse_zfin_features, parse_zfin_fish, parse_zfin_stages)
from build_fungi_details import pombase_details, sgd_details
from build_zfin_details import fish_metadata, zfin_details
from build_fly_details import fly_details
from build_worm_details import worm_details
from build_ecoli_details import ecoli_details
from build_mouse_details import merge_mouse_records
from package_evidence_details import sha256
from package_mouse_details import audit_pubmed_sample

TAXIDS = ("4896", "559292", "7955", "7227", "6239", "83333")


def expected(taxid, cache):
    if taxid == "4896":
        with open(cache / "pombase_gene_names.tsv", encoding="utf-8") as names, open(cache / "pombase_viability.tsv", encoding="utf-8") as viability:
            records = pombase_details(viability, names)
        sources = ["pombase_gene_names.tsv", "pombase_viability.tsv"]
        scripts = ["build_fungi_details.py"]
    elif taxid == "559292":
        with open(cache / "sgd_phenotype.tab", encoding="utf-8") as handle:
            records = sgd_details(handle)
        sources = ["sgd_phenotype.tab"]
        scripts = ["build_fungi_details.py"]
    elif taxid == "7955":
        with open_text(cache / "zfin_stages.txt") as handle:
            stages = parse_zfin_stages(handle)
        with open_text(cache / "zfin_features.txt") as handle:
            features = parse_zfin_features(handle)
        with open_text(cache / "zfin_fish_components.txt") as handle:
            fish = parse_zfin_fish(handle, features)
        with open_text(cache / "zfin_fish_components.txt") as handle:
            metadata = fish_metadata(handle, fish)
        with open_text(cache / "zfin_pubmed.txt") as handle:
            pubmed = {f[0]: f[1] for f in (line.rstrip("\r\n").split("\t") for line in handle) if len(f) >= 2 and f[1].isdigit()}
        with open_text(cache / "zfin_phenotype.txt") as handle:
            records = zfin_details(handle, fish, metadata, stages, pubmed)
        sources = ["zfin_stages.txt", "zfin_features.txt", "zfin_fish_components.txt", "zfin_pubmed.txt", "zfin_phenotype.txt"]
        scripts = ["build_zfin_details.py"]
    elif taxid == "7227":
        with open_text(cache / "flybase_alleles.tsv.gz") as handle:
            alleles = parse_fly_alleles(handle)
        with open_text(cache / "flybase_references.tsv.gz") as handle:
            pubmed = parse_fly_references(handle)
        with open_text(cache / "flybase_genotype_phenotype.tsv.gz") as handle:
            records = fly_details(handle, alleles, pubmed)
        sources = ["flybase_alleles.tsv.gz", "flybase_references.tsv.gz", "flybase_genotype_phenotype.tsv.gz"]
        scripts = ["build_fly_details.py"]
    elif taxid == "6239":
        with open_text(cache / "wormbase_phenotype_ontology.obo.gz") as handle:
            ontology = MPOntology(handle)
        with gzip.open(cache / "alliance_phenotype_wb.json.gz", "rt", encoding="utf-8") as handle:
            papers = parse_worm_papers(json.load(handle))
        with open_text(cache / "wormbase_phenotype_association.wb.gz") as handle:
            records, _ = worm_details(handle, ontology, papers)
        sources = ["wormbase_phenotype_ontology.obo.gz", "alliance_phenotype_wb.json.gz", "wormbase_phenotype_association.wb.gz"]
        scripts = ["build_worm_details.py"]
    else:
        records = {gene: [record] for gene, record in ecoli_details(cache / "ecoli_core_essential.xlsx").items()}
        sources = ["ecoli_core_essential.xlsx"]
        scripts = ["build_ecoli_details.py"]
    return merge_mouse_records([records]), sources, scripts


def create_release(taxid, cache, directory):
    details_path = directory / f"{taxid}.json"
    sqlite_path = directory / f"{taxid}.sqlite"
    data = json.loads(details_path.read_text(encoding="utf-8"))
    genes, source_names, script_names = expected(taxid, cache)
    if data["genes"] != genes:
        raise ValueError(f"{taxid} detailed data does not exactly match raw sources")
    records = [finding for gene in genes.values() for finding in gene["records"]]
    pmids = {pmid for finding in records for pmid in finding["references"]}
    http = requests.Session()
    http.headers["User-Agent"] = "K-Sites model-organism release validator"
    checked = audit_pubmed_sample(pmids, http, maximum=50) if pmids else 0
    scripts = [Path(__file__)] + [Path(__file__).parent / name for name in script_names + ["build_mouse_details.py", "build_evidence_data.py"]]
    manifest = {
        "format": 1,
        "created": date.today().isoformat(),
        "organism": data["organism"],
        "coverage": data["coverage"],
        "details": {"json": details_path.name, "sqlite": sqlite_path.name,
                    "json_sha256": sha256(details_path), "sqlite_sha256": sha256(sqlite_path)},
        "builder": {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                    "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()),
                    "scripts": [{"file": f"builder/{script.name}", "sha256": sha256(script)} for script in scripts]},
        "validation": {"exact_raw_match": True, "genes": len(genes), "records": len(records), "pubmed_sample_valid": checked},
        "sources": {name: {"file": f"sources/{name}", "sha256": sha256(cache / name)} for name in source_names},
    }
    manifest_path = directory / f"{taxid}-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    package_path = directory / f"evidence-details-{taxid}-release.zip"
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in ((details_path, details_path.name), (sqlite_path, sqlite_path.name), (manifest_path, "manifest.json")):
            archive.write(path, name)
        for script in scripts:
            archive.write(script, f"builder/{script.name}")
        for name in source_names:
            archive.write(cache / name, f"sources/{name}")
    return manifest, package_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", default=".cache/evidence-sources")
    parser.add_argument("--directory", default="webapp/results/evidence-details")
    parser.add_argument("--organisms", nargs="*", default=TAXIDS, choices=TAXIDS)
    args = parser.parse_args()
    for taxid in args.organisms:
        manifest, package = create_release(taxid, Path(args.cache), Path(args.directory))
        print(f"{taxid}: {manifest['validation']['genes']} genes, {manifest['validation']['records']} records -> {package}")


if __name__ == "__main__":
    main()
