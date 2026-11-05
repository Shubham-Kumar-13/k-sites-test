import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_tradis_details as details


def source(tmp_path, rows):
    path = tmp_path / "tradis.xlsx"
    pd.DataFrame(rows).to_excel(path, index=False)
    return path


def test_tradis_cutoff_and_missing_values(tmp_path):
    path = source(tmp_path, [
        {"Keio gene name": "zero", "TraDIS Essentiality: Klebsiella pneumoniae Ecl8": -6.5, "Locus: Klebsiella pneumoniae Ecl8": "KP1"},
        {"Keio gene name": "boundary", "TraDIS Essentiality: Klebsiella pneumoniae Ecl8": 0, "Locus: Klebsiella pneumoniae Ecl8": "KP2"},
        {"Keio gene name": "nonessential", "TraDIS Essentiality: Klebsiella pneumoniae Ecl8": 0.25, "Locus: Klebsiella pneumoniae Ecl8": "KP3"},
        {"Keio gene name": "missing", "TraDIS Essentiality: Klebsiella pneumoniae Ecl8": float("nan"), "Locus: Klebsiella pneumoniae Ecl8": "KP4"},
    ])

    scoring, detail = details.build_tradis(path, ("573",))

    assert set(scoring["573"]) == {"ZERO", "BOUNDARY", "NONESSENTIAL"}
    assert scoring["573"]["ZERO"]["v"] == "L"
    assert scoring["573"]["BOUNDARY"]["v"] == "L"
    assert scoring["573"]["NONESSENTIAL"]["v"] == "V"
    assert detail["573"]["ZERO"]["records"][0]["essentiality_score"] == -6.5
    assert detail["573"]["ZERO"]["records"][0]["experiment_type"] == "transposon_insertion_essentiality"


def test_tradis_rejects_conflicting_duplicates_and_missing_columns(tmp_path):
    path = source(tmp_path, [
        {"Keio gene name": "gene", "TraDIS Essentiality: Klebsiella pneumoniae Ecl8": -1, "Locus: Klebsiella pneumoniae Ecl8": "KP1"},
        {"Keio gene name": "gene", "TraDIS Essentiality: Klebsiella pneumoniae Ecl8": 1, "Locus: Klebsiella pneumoniae Ecl8": "KP1"},
    ])
    with pytest.raises(ValueError, match="Conflicting TraDIS rows"):
        details.build_tradis(path, ("573",))

    with pytest.raises(ValueError, match="missing columns"):
        details.build_tradis(path, ("637910",))


def test_tradis_preserves_distinct_loci_with_the_same_symbol(tmp_path):
    path = source(tmp_path, [
        {"Keio gene name": "insF1", "TraDIS Essentiality: Klebsiella pneumoniae Ecl8": 3.3, "Locus: Klebsiella pneumoniae Ecl8": "KP1"},
        {"Keio gene name": "insF1", "TraDIS Essentiality: Klebsiella pneumoniae Ecl8": 3.35, "Locus: Klebsiella pneumoniae Ecl8": "KP2"},
    ])

    scoring, _ = details.build_tradis(path, ("573",))

    assert set(scoring["573"]) == {"INSF1", "KP2"}
    assert scoring["573"]["INSF1"]["id"] == "KP1"
    assert scoring["573"]["KP2"]["id"] == "KP2"
