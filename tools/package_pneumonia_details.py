#!/usr/bin/env python3
"""Package the validated Streptococcus pneumoniae evidence release without external publication."""

import argparse
import json
import sqlite3
import subprocess
import zipfile
from datetime import date
from pathlib import Path

from build_pneumonia_details import TAXID, NAME, pneumonia_details
from build_mouse_details import merge_mouse_records
from package_evidence_details import sha256


def create_release(source, data_dir, details_dir):
    scoring, details = pneumonia_details(source)
    scoring_file = data_dir / f"{TAXID}.json"
    details_file = details_dir / f"{TAXID}.json"
    sqlite_file = details_dir / f"{TAXID}.sqlite"
    if json.loads(scoring_file.read_text(encoding="utf-8"))["genes"] != scoring:
        raise ValueError("Pneumococcal scoring data does not match raw source")
    if json.loads(details_file.read_text(encoding="utf-8"))["genes"] != merge_mouse_records([details]):
        raise ValueError("Pneumococcal detail data does not match raw source")
    with sqlite3.connect(sqlite_file) as connection:
        if connection.execute("SELECT COUNT(*) FROM genes").fetchone()[0] != len(scoring):
            raise ValueError("Pneumococcal SQLite count mismatch")
    scripts = [Path(__file__), Path(__file__).parent / "build_pneumonia_details.py",
               Path(__file__).parent / "build_mouse_details.py", Path(__file__).parent / "build_evidence_data.py"]
    manifest = {
        "format": 1,
        "created": date.today().isoformat(),
        "organism": {"taxid": TAXID, "name": NAME},
        "details": {"scoring": scoring_file.name, "json": details_file.name, "sqlite": sqlite_file.name,
                    "genes": len(scoring), "json_sha256": sha256(details_file), "sqlite_sha256": sha256(sqlite_file),
                    "scoring_sha256": sha256(scoring_file)},
        "builder": {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                    "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()),
                    "scripts": [{"file": f"builder/{script.name}", "sha256": sha256(script)} for script in scripts]},
        "validation": {"exact_raw_match": True, "genes": len(scoring), "essentiality_rule": "strain/subcluster calls aggregated with conflicts preserved"},
        "sources": {source.name: {"file": f"sources/{source.name}", "sha256": sha256(source)}},
    }
    manifest_file = details_dir / f"{TAXID}-manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    package = details_dir / f"evidence-details-{TAXID}-release.zip"
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
    parser.add_argument("--source", default=".cache/evidence-sources/pneumonia_pan_genome.xlsx")
    parser.add_argument("--data-dir", default="webapp/results/evidence-data")
    parser.add_argument("--details-dir", default="webapp/results/evidence-details")
    args = parser.parse_args()
    print(create_release(Path(args.source), Path(args.data_dir), Path(args.details_dir)))


if __name__ == "__main__":
    main()
