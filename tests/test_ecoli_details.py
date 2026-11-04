import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ecoli_details as details


def test_ecoli_keeps_strain_locus_and_core_essentiality(tmp_path):
    path = tmp_path / "ecoli.xlsx"
    pd.DataFrame([
        {"Keio gene name": "dnaA", "EcoGene Essentiality: Escherichia coli BW25113": 1,
         "Core Essentiality": 1, "Locus: Escherichia coli BW25113 (Keio)": "b0001"},
        {"Keio gene name": "lacZ", "EcoGene Essentiality: Escherichia coli BW25113": 0,
         "Core Essentiality": 0, "Locus: Escherichia coli BW25113 (Keio)": "b0344"},
    ]).to_excel(path, index=False)

    records = details.ecoli_details(path)

    assert records["DNAA"]["call"] == "L"
    assert records["DNAA"]["qualifiers"] == ["core_essential"]
    assert records["DNAA"]["background"] == "E. coli BW25113"
    assert records["DNAA"]["source_record_id"] == "b0001"
    assert records["LACZ"]["call"] == "V"


def test_ecoli_rejects_missing_essentiality_column(tmp_path):
    path = tmp_path / "ecoli.xlsx"
    pd.DataFrame([{"Keio gene name": "dnaA", "Core Essentiality": 1}]).to_excel(path, index=False)

    with pytest.raises(ValueError, match="missing columns"):
        details.ecoli_details(path)
