import csv
import gzip
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import package_evidence_details as release


def fixture_data():
    finding = {
        "source": "tair", "source_record_id": "SALK_1", "call": "LETHAL",
        "evidence_level": "qualified", "experiment_type": "mutant_not_otherwise_specified",
        "zygosity": "homozygous", "qualifiers": [], "phenotype": "Homozygotes are embryo lethal.",
        "references": ["26555280"],
    }
    return {
        "format": 1, "built": "2026-11-04",
        "organism": {"taxid": "3702", "name": "Arabidopsis thaliana"},
        "pilot": {"tair_gene_limit": None, "tair_genes": 1, "scope": "test"},
        "genes": {"AT1G01010": {
            "call": "LETHAL", "conflicting": False, "counts": {"lethal": 1, "viable": 0},
            "sources": ["tair"], "records": [finding],
        }},
    }


def write_tair(path):
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["LOCUS_NAME", "GERMPLASM_NAME", "PHENOTYPE", "PUBMED_ID"], delimiter="\t")
        writer.writeheader()
        writer.writerow({"LOCUS_NAME": "AT1G01010", "GERMPLASM_NAME": "SALK_1",
                         "PHENOTYPE": "Homozygotes are embryo lethal.", "PUBMED_ID": "26555280"})


def test_raw_audit_matches_every_output_record(tmp_path):
    path = tmp_path / "tair.gz"
    write_tair(path)

    stats, pmids = release.audit_tair(fixture_data(), release.read_tair(path))

    assert stats["genes"] == 1 and stats["findings"] == 1
    assert pmids == {"26555280"}


def test_raw_audit_rejects_a_changed_phenotype(tmp_path):
    path = tmp_path / "tair.gz"
    write_tair(path)
    data = fixture_data()
    data["genes"]["AT1G01010"]["records"][0]["phenotype"] = "Not embryo lethal."

    with pytest.raises(ValueError, match="does not match"):
        release.audit_tair(data, release.read_tair(path))


def test_release_contains_data_sources_builder_and_checksums(tmp_path):
    tair = tmp_path / "tair.gz"
    write_tair(tair)
    details = tmp_path / "3702.json"
    details.write_text(json.dumps(fixture_data()), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    package = tmp_path / "release.zip"

    manifest = release.create_release(details, tair, manifest_path, package, validate_external=False)

    assert manifest["details"]["sha256"] == release.sha256(details)
    assert manifest["sources"]["tair"]["sha256"] == release.sha256(tair)
    assert json.loads(manifest_path.read_text())["validation"]["tair"]["findings"] == 1
    with zipfile.ZipFile(package) as archive:
        assert set(archive.namelist()) == {
            "3702.json", "manifest.json", "sources/tair.gz", "builder/package_evidence_details.py",
            "builder/build_evidence_details.py", "builder/build_evidence_data.py",
        }
        assert json.loads(archive.read("3702.json"))["genes"]["AT1G01010"]["call"] == "LETHAL"
        assert len(manifest["builder"]["scripts"]) == 3
