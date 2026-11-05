#!/usr/bin/env python3
"""Package validated TraDIS scoring and experiment-level releases without external publication."""

import argparse
import json
import sqlite3
import subprocess
import zipfile
from datetime import date
from pathlib import Path

from build_tradis_details import ORGANISMS, build_tradis
from package_evidence_details import sha256


def create_release(taxid, source, data_dir, details_dir):
    scoring, details = build_tradis(source, (taxid,))
    scoring_file = data_dir / f"{taxid}.json"
    details_file = details_dir / f"{taxid}.json"
    sqlite_file = details_dir / f"{taxid}.sqlite"
    deployed_scoring = json.loads(scoring_file.read_text(encoding="utf-8"))["genes"]
    deployed_details = json.loads(details_file.read_text(encoding="utf-8"))["genes"]
    if deployed_scoring != scoring[taxid] or deployed_details != details[taxid]:
        raise ValueError(f"Deployed TraDIS data does not match raw source for {taxid}")
    with sqlite3.connect(sqlite_file) as connection:
        if connection.execute("SELECT COUNT(*) FROM genes").fetchone()[0] != len(scoring[taxid]):
            raise ValueError(f"SQLite count mismatch for {taxid}")
    scripts = [Path(__file__), Path(__file__).parent / "build_tradis_details.py",
               Path(__file__).parent / "build_mouse_details.py", Path(__file__).parent / "build_evidence_data.py"]
    manifest = {
        "format": 1,
        "created": date.today().isoformat(),
        "organism": {"taxid": taxid, "name": ORGANISMS[taxid]["name"]},
        "details": {"scoring": scoring_file.name, "json": details_file.name, "sqlite": sqlite_file.name,
                    "genes": len(scoring[taxid]), "json_sha256": sha256(details_file), "sqlite_sha256": sha256(sqlite_file),
                    "scoring_sha256": sha256(scoring_file)},
        "builder": {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                    "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()),
                    "scripts": [{"file": f"builder/{script.name}", "sha256": sha256(script)} for script in scripts]},
        "validation": {"exact_raw_match": True, "genes": len(scoring[taxid]), "essentiality_rule": "score <= 0 is essential"},
        "sources": {source.name: {"file": f"sources/{source.name}", "sha256": sha256(source)}},
    }
    manifest_file = details_dir / f"{taxid}-manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    package = details_dir / f"evidence-details-{taxid}-release.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(scoring_file, f"evidence-data/{scoring_file.name}")
        archive.write(details_file, details_file.name)
        archive.write(sqlite_file, sqlite_file.name)
        archive.write(manifest_file, "manifest.json")
        archive.write(source, f"sources/{source.name}")
        for script in scripts:
            archive.write(script, f"builder/{script.name}")
    return package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=".cache/evidence-sources/ecoli_core_essential.xlsx")
    parser.add_argument("--data-dir", default="webapp/results/evidence-data")
    parser.add_argument("--details-dir", default="webapp/results/evidence-details")
    parser.add_argument("--organisms", nargs="*", default=list(ORGANISMS), choices=list(ORGANISMS))
    args = parser.parse_args()
    for taxid in args.organisms:
        print(create_release(taxid, Path(args.source), Path(args.data_dir), Path(args.details_dir)))


if __name__ == "__main__":
    main()
