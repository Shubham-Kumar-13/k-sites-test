"""
The measured evidence and the verdicts against published knockout results.

tests/fixtures/benchmark/paper_truth.json lists genes (mostly mouse; also zebrafish, fly, worm) whose knockout outcome was read from the abstract of the original
paper (through PubMed). The small evidence fixture (a copy of the real data files) must give the same outcome, and the verdict
must flag every lethal gene and none of the viable ones as AVOID.
"""

import json
from pathlib import Path

import pytest

from k_sites.knockout_evidence import EvidenceProvider, assess_gene
from k_sites.workflow.safety_recommender import get_safety_recommendation

HERE = Path(__file__).resolve().parent
TRUTH = json.loads((HERE / "fixtures" / "benchmark" / "paper_truth.json").read_text(encoding="utf-8"))["genes"]
PROVIDER = EvidenceProvider.from_directory(HERE / "fixtures" / "evidence")
FLAGGED = ("AVOID", "HIGH_CONCERN")


def taxid_of(entry):
    return entry.get("taxid", "10090")


def verdict_for(gene, taxid="10090", pleiotropy=3.0):
    evidence = assess_gene(PROVIDER, taxid, gene)
    return evidence, get_safety_recommendation(gene, pleiotropy, knockout_evidence=evidence)


def test_the_truth_set_is_balanced_and_cited():
    lethal = [g for g in TRUTH if g["expected"] == "lethal"]
    viable = [g for g in TRUTH if g["expected"] == "viable"]

    assert len(lethal) >= 8 and len(viable) >= 6
    assert {"7955", "7227", "6239"} <= {taxid_of(g) for g in TRUTH}
    assert all(any(taxid_of(g) == taxid and g["expected"] == "lethal" for g in TRUTH) for taxid in ("7955", "7227", "6239"))
    assert all(any(taxid_of(g) == taxid and g["expected"] == "viable" for g in TRUTH) for taxid in ("7955", "7227", "6239"))
    assert all(g["pmids"] and g["doi"] and g["citation"] for g in TRUTH)


@pytest.mark.parametrize("entry", TRUTH, ids=[f"{taxid_of(g)}-{g['gene']}" for g in TRUTH])
def test_the_data_agrees_with_the_paper(entry):
    evidence, recommendation = verdict_for(entry["gene"], taxid_of(entry))
    organism = evidence["organism"]

    assert evidence["found"], f"{entry['gene']} is missing from the evidence files"
    if entry["expected"] == "lethal":
        # lethal in the paper: the data says lethal or subviable, or (when other knockout lines of the gene are viable)
        # lists at least one lethal line, and the verdict flags the gene either way
        assert organism["call"] in ("LETHAL", "SUBVIABLE") or organism["counts"]["lethal"] >= 1, organism["text"]
        assert recommendation.safety_level.value in FLAGGED, recommendation.safety_level
        if entry.get("stage") in ("E", "P", "L") and organism["call"] == "LETHAL":
            assert organism["stage"] == entry["stage"]
    else:
        assert organism["call"] == "VIABLE", organism["text"]
        assert recommendation.safety_level.value != "AVOID"


def test_every_paper_gene_reaches_a_verdict_that_separates_lethal_from_viable():
    flagged = {(taxid_of(g), g["gene"]): verdict_for(g["gene"], taxid_of(g))[1].safety_level.value in FLAGGED for g in TRUTH}

    assert all(flagged[(taxid_of(g), g["gene"])] for g in TRUTH if g["expected"] == "lethal")
    assert not any(flagged[(taxid_of(g), g["gene"])] for g in TRUTH if g["expected"] == "viable"
                   and verdict_for(g["gene"], taxid_of(g))[0]["organism"]["counts"]["lethal"] == 0)


@pytest.mark.parametrize("taxid", ["7955", "7227", "6239"])
def test_zebrafish_fly_and_worm_are_measured_not_hints(taxid):
    entries = [g for g in TRUTH if taxid_of(g) == taxid]
    for entry in entries:
        evidence, _ = verdict_for(entry["gene"], taxid)

        assert evidence["organism"]["basis"] == "direct" and not evidence["organism"]["distant"]
        assert evidence["has_measured"]


def test_in_human_cells_the_known_mouse_lethals_are_not_all_treated_alike():
    # TDG and POLB kill the mouse embryo but human cells tolerate their loss; PCNA is needed by almost every cell line
    tdg, _ = verdict_for("TDG", "9606")
    pcna, pcna_verdict = verdict_for("PCNA", "9606", 10.0)

    assert tdg["cells"]["call"] == "NON_ESSENTIAL" and tdg["organism"]["call"] == "LETHAL"
    assert pcna["cells"]["call"] == "ESSENTIAL" and pcna_verdict.safety_level.value == "AVOID"
