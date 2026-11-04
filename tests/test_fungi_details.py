import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_fungi_details as details


def test_pombase_retains_systematic_id_and_deletion_viability():
    records = details.pombase_details(
        ["SPAC1\tviable\n", "SPAC2\tinviable\n", "SPAC3\tcondition-dependent\n"],
        ["gene_systematic_id\tgene_name\tsynonyms\n", "SPAC1\tabc1\t\n", "SPAC2\tdef2\t\n", "SPAC3\tghi3\t\n"])

    assert records["ABC1"][0]["call"] == "V"
    assert records["DEF2"][0]["call"] == "L"
    assert records["GHI3"][0]["call"] == "S"
    assert records["DEF2"][0]["source_record_id"] == "SPAC2"
    assert records["DEF2"][0]["experiment_type"] == "deletion_viability"
    assert records["GHI3"][0]["qualifiers"] == ["condition_dependent"]


def sgd_row(phenotype="viable", mutation="null", experiment="systematic mutation set", condition="", chemical="", pmid="PMID:123"):
    return ["YAL001C", "strain", "GENE1", "desc", pmid, experiment, mutation, "allele", "note", phenotype, condition, chemical, "extra"]


def test_sgd_retains_null_experiment_and_references_but_excludes_special_conditions():
    lines = ["\t".join(sgd_row("inviable")), "\t".join(sgd_row("viable")),
             "\t".join(sgd_row("inviable", condition="37C")),
             "\t".join(sgd_row("viable", mutation="point mutation"))]

    records = details.sgd_details(lines)
    summary = details.merge_mouse_records([records])["YAL001C"]

    assert summary["call"] == "CONFLICTING"
    assert summary["counts"] == {"lethal": 1, "subviable": 0, "viable": 1}
    assert summary["records"][0]["references"] == ["123"]
    assert summary["records"][0]["experiment_type"] == "systematic mutation set"
    assert len(summary["records"]) == 2
