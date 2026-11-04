import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import test_evidence_builder as fixtures
from build_evidence_data import parse_fly_alleles
import build_fly_details as details


def test_fly_alleles_preserve_viability_stage_references_and_sterility():
    helper = fixtures.TestFly()
    alleles = parse_fly_alleles(helper.ALLELES)
    lines = [
        helper.row("FBal1", "lethal - all die during embryonic stage", "FBcv:0002033"),
        helper.row("FBal2", "lethal - all die before end of larval stage", "FBcv:0002002", ref="FBrf2"),
        helper.row("FBal3", "viable", "FBcv:0000349"),
        helper.row("FBal6", "partially lethal - majority die", "FBcv:0000352"),
        helper.row("FBal4", "lethal", "FBcv:0000351"),
    ]

    records = details.fly_details(lines, alleles, {"FBrf1": "11", "FBrf2": "12"})

    assert records["G1"][0]["call"] == "L"
    assert records["G1"][0]["stage"] == "E"
    assert {ref for record in records["G1"] for ref in record["references"]} == {"11", "12"}
    assert records["G2"][0]["call"] == "V"
    assert records["G5"][0]["call"] == "S"
    assert "G3" not in records


def test_hypomorph_viability_and_conditional_phenotypes_are_not_null_evidence():
    helper = fixtures.TestFly()
    alleles = parse_fly_alleles(helper.ALLELES)
    lines = [helper.row("FBal2", "viable", "FBcv:0000349"),
             helper.row("FBal3", "viable", "FBcv:0000349"),
             helper.row("FBal3", "female sterile", "FBcv:0000366"),
             helper.row("FBal1", "lethal", "FBcv:0000351", "heat sensitive")]

    records = details.fly_details(lines, alleles, {})

    assert records["G2"][0]["call"] == "V"
    assert records["G2"][0]["qualifiers"] == ["infertile"]
    assert "G1" not in records
