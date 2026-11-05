import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_pneumonia_details as details


def test_pneumonia_aggregates_strains_and_preserves_conflicts(tmp_path):
    path = tmp_path / "pneumonia.xlsx"
    rows = [
        {"Subcluster": "1000_0", "Strain": "D39-AC1770", "locus_tag": "EQH42_00001", "Binomial Call": "Essential", "Binomial z value": 0.99},
        {"Subcluster": "1000_0", "Strain": "PG01", "locus_tag": "EQH15_00001", "Binomial Call": "Non-Essential", "Binomial z value": 0.01},
        {"Subcluster": "1001_0", "Strain": "PG01", "locus_tag": "EQH15_00002", "Binomial Call": "Essential", "Binomial z value": 0.99},
        {"Subcluster": "1001_0", "Strain": "PG01", "locus_tag": "EQH15_00003", "Binomial Call": "Non-Essential", "Binomial z value": 0.01},
        {"Subcluster": "1002_0", "Strain": "TIGR4-AC316", "locus_tag": "EQH41_00004", "Binomial Call": "Uncertain", "Binomial z value": 0.5},
        {"Subcluster": "1002_0", "Strain": "PG02", "locus_tag": "EQH16_00004", "Binomial Call": "Essential", "Binomial z value": 0.99},
        {"Subcluster": "1002_0", "Strain": "PG02", "locus_tag": "EQH16_00004", "Binomial Call": "Essential", "Binomial z value": 0.99},
    ]
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Supplementary_data_6", index=False)

    scoring, detail = details.pneumonia_details(path)

    assert scoring["EQH42_00001"]["n"] == [1, 0, 1] and scoring["EQH42_00001"]["x"] == 1
    assert scoring["EQH15_00002"]["n"] == [1, 0, 0]
    assert scoring["EQH16_00004"]["n"] == [1, 0, 0]
    assert len(detail["EQH16_00004"]) == 1
    assert all(record["background"] != "TIGR4-AC316" for record in detail["EQH16_00004"])
