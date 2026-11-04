#!/usr/bin/env python3
"""Validate and package a reproducible Arabidopsis detailed-evidence release."""

import argparse
import collections
import csv
import gzip
import hashlib
import json
import subprocess
import zipfile
from datetime import date
from pathlib import Path

import requests

from build_evidence_data import THALEMINE_LIST_CALLS, fetch_thalemine_list
from build_evidence_details import sentences, validate_details


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_tair(path):
    raw = {}
    with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            gene = row["LOCUS_NAME"].strip().upper()
            germplasm = row["GERMPLASM_NAME"].strip()
            references = {value for value in row["PUBMED_ID"].split() if value.isdigit()}
            for text in sentences(row["PHENOTYPE"]):
                raw[(gene, germplasm, text)] = references
    return raw


def audit_tair(data, raw):
    findings = 0
    genes = set()
    calls = collections.Counter()
    pmids = set()
    owners = collections.defaultdict(set)
    for gene, record in data["genes"].items():
        tair_records = [record for record in record["records"] if record["source"] == "tair"]
        if not tair_records:
            continue
        genes.add(gene)
        calls[record["call"]] += 1
        for finding in tair_records:
            key = (gene, finding["source_record_id"], finding["phenotype"])
            if key not in raw:
                raise ValueError(f"TAIR output does not match a raw row: {key}")
            if not set(finding["references"]) <= raw[key]:
                raise ValueError(f"TAIR references do not match the raw row: {key}")
            owners[(finding["source_record_id"], finding["phenotype"])].add(gene)
            pmids.update(finding["references"])
            findings += 1
    ambiguous = {key: loci for key, loci in owners.items() if len(loci) > 1}
    if ambiguous:
        raise ValueError(f"Cross-locus TAIR evidence: {next(iter(ambiguous))}")
    return {"genes": len(genes), "findings": findings, "calls": dict(calls), "pubmed_ids": len(pmids)}, pmids


def audit_thalemine(data, http):
    expected = collections.defaultdict(set)
    raw_lists = []
    for index, (name, call) in enumerate(THALEMINE_LIST_CALLS.items(), 1):
        text = fetch_thalemine_list(name, http)
        raw_lists.append({"name": name, "file": f"sources/thalemine/list_{index:02d}.txt", "text": text})
        for line in text.strip().splitlines():
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                gene = parts[1].strip() or parts[0].strip().upper()
                expected[gene].add((name, "LETHAL" if call == "L" else "VIABLE"))
    actual = collections.defaultdict(set)
    for gene, record in data["genes"].items():
        for finding in record["records"]:
            if finding["source"] == "thalemine":
                actual[gene].add((finding["source_record_id"], finding["call"]))
    if actual != expected:
        raise ValueError(f"ThaleMine mismatch: {len(actual)} output genes, {len(expected)} source genes")
    return {"genes": len(actual), "records": sum(map(len, actual.values()))}, raw_lists


def audit_pubmed(pmids, http):
    ordered = sorted(pmids, key=int)
    for start in range(0, len(ordered), 75):
        batch = ordered[start:start + 75]
        response = http.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                            params={"db": "pubmed", "id": ",".join(batch), "retmode": "json"}, timeout=60)
        response.raise_for_status()
        result = response.json()["result"]
        if set(result["uids"]) != set(batch):
            raise ValueError(f"Missing PubMed records: {set(batch) - set(result['uids'])}")
    return len(ordered)


def create_release(details_path, tair_path, manifest_path, package_path, http=None, validate_external=True):
    details_path, tair_path = Path(details_path), Path(tair_path)
    data = json.loads(details_path.read_text(encoding="utf-8"))
    validate_details(data)
    tair_stats, pmids = audit_tair(data, read_tair(tair_path))
    http = http or requests.Session()
    validation = {"tair": tair_stats}
    raw_lists = []
    if validate_external:
        thalemine_stats, raw_lists = audit_thalemine(data, http)
        validation["thalemine"] = thalemine_stats
        validation["pubmed_ids_valid"] = audit_pubmed(pmids, http)
    builder = Path(__file__)
    scripts = [builder, builder.parent / "build_evidence_details.py", builder.parent / "build_evidence_data.py"]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    manifest = {
        "format": 1,
        "created": date.today().isoformat(),
        "organism": data["organism"],
        "coverage": data["pilot"],
        "details": {"file": details_path.name, "genes": len(data["genes"]), "sha256": sha256(details_path)},
        "builder": {"commit": commit, "dirty": dirty,
                    "scripts": [{"file": f"builder/{script.name}", "sha256": sha256(script)} for script in scripts]},
        "validation": validation,
        "sources": {
            "tair": {"file": f"sources/{tair_path.name}", "sha256": sha256(tair_path)},
            "thalemine": {"lists": [{"file": item["file"], "name": item["name"], "sha256": hashlib.sha256(item["text"].encode()).hexdigest()}
                                      for item in raw_lists]},
        },
    }
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    package_path = Path(package_path)
    package_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in ((details_path, details_path.name), (manifest_path, "manifest.json"), (tair_path, f"sources/{tair_path.name}")):
            archive.write(path, name)
        for script in scripts:
            archive.write(script, f"builder/{script.name}")
        for item in raw_lists:
            archive.writestr(item["file"], item["text"])
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--details", default="webapp/results/evidence-details/3702.json")
    parser.add_argument("--tair", default=".cache/evidence-sources/tair_phenotype.txt.gz")
    parser.add_argument("--manifest", default="webapp/results/evidence-details/manifest.json")
    parser.add_argument("--package", default="webapp/results/evidence-details-release.zip")
    parser.add_argument("--skip-external-validation", action="store_true")
    args = parser.parse_args()
    http = requests.Session()
    http.headers["User-Agent"] = "K-Sites evidence release validator"
    manifest = create_release(args.details, args.tair, args.manifest, args.package, http, not args.skip_external_validation)
    print(f"Validated {manifest['details']['genes']} genes; wrote {args.manifest} and {args.package}")


if __name__ == "__main__":
    main()
