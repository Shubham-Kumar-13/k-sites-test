import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import test_evidence_builder as fixtures
from build_evidence_data import MPOntology
import build_worm_details as details


def ontology():
    return MPOntology(fixtures.TestWorm.OBO)


def test_worm_requires_two_not_lethal_alleles_for_viability():
    helper = fixtures.TestWorm()
    one = [helper.row("WBGene1", "aaa-1", "WBPhenotype:0000062", "WBVar1", negated="NOT")]
    two = one + [helper.row("WBGene1", "aaa-1", "WBPhenotype:0000062", "WBVar2", negated="NOT")]

    one_records, _ = details.worm_details(one, ontology(), {})
    two_records, _ = details.worm_details(two, ontology(), {})

    assert one_records == {}
    assert two_records["AAA-1"][0]["call"] == "V"
    assert two_records["AAA-1"][0]["evidence_level"] == "qualified"


def test_worm_rnai_is_marked_and_conflicting_alleles_are_preserved():
    helper = fixtures.TestWorm()
    lines = [helper.row("WBGene1", "aaa-1", "WBPhenotype:0000050", "WBRNAi1"),
             helper.row("WBGene1", "aaa-1", "WBPhenotype:0000062", "WBVar1", negated="NOT"),
             helper.row("WBGene1", "aaa-1", "WBPhenotype:0000062", "WBVar2", negated="NOT")]

    records, _ = details.worm_details(lines, ontology(), {"WBPaper1": "11"})
    summary = details.merge_mouse_records([records])["AAA-1"]

    assert summary["call"] == "CONFLICTING"
    assert summary["counts"] == {"lethal": 1, "subviable": 0, "viable": 2}
    assert any(record["experiment_type"] == "RNAi" and record["qualifiers"] == ["rnai_only"]
               for record in summary["records"])
