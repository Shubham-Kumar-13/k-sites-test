import io
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import test_evidence_builder as fixtures
from test_evidence_builder import OBO, ALLELES, genotype
from build_evidence_data import MPOntology, SurvivalTerms
import build_mouse_details as details


def survival():
    return SurvivalTerms(MPOntology(io.StringIO(OBO)))


def test_mgi_genotype_retains_alleles_zygosity_stage_and_references():
    genotypes = {"G1": genotype("Gene<tm1>/Gene<tm1>", ["A:ko"], ["MP:0011092"], {"MP:0011092": ["10", "11"]}, gid="G1")}

    records = details.mgi_details(genotypes, ALLELES, survival())["MGI:1"]

    assert len(records) == 1
    finding = records[0]
    assert finding["call"] == "L" and finding["stage"] == "E"
    assert finding["zygosity"] == "homozygous" and finding["evidence_level"] == "direct"
    assert finding["genotype"] == "Gene<tm1>/Gene<tm1>"
    assert finding["alleles"][0]["class"] == "ko"
    assert finding["references"] == ["10", "11"]
    assert finding["phenotype_terms"][0]["id"] == "MP:0011092"


def test_mgi_adult_viability_is_direct_but_hypomorph_viability_is_not_a_null_measurement():
    null = {"G1": genotype("Gene<tm1>/Gene<tm1>", ["A:ko"], ["MP:0001262"], gid="G1")}
    hypo = {"G2": genotype("Gene<tm3>/Gene<tm3>", ["A:hypo"], ["MP:0001262"], gid="G2")}

    assert details.mgi_details(null, ALLELES, survival())["MGI:1"][0]["call"] == "V"
    assert details.mgi_details(hypo, ALLELES, survival()) == {}


def test_impc_colonies_are_deduplicated_and_keep_screen_metadata():
    records = details.impc_details(fixtures.TestImpc.VIABILITY, [], ALLELES, survival())

    assert len(records["MGI:1"]) == 2
    assert {r["call"] for r in records["MGI:1"]} == {"L", "S"}
    assert all(r["stage"] == "W" for r in records["MGI:1"])
    assert all(r["qualifiers"] == ["survival_to_weaning"] for r in records["MGI:1"])
    assert records["MGI:2"][0]["call"] == "V"


def test_impc_phenotype_assertion_adds_source_without_changing_viability_counts():
    row = {"zygosity": "homozygote", "marker_accession_id": "MGI:1", "marker_symbol": "Gene",
           "allele_accession_id": "A:ko", "mp_term_id": "MP:0001262", "mp_term_name": "decreased body weight",
           "colony_id": "C1", "parameter_stable_id": "IMPC_GEO_047_002", "strain_name": "C57BL/6N"}
    records = details.impc_details([], iter([row]), ALLELES, survival())
    summary = details.merge_mouse_records([records])["MGI:1"]

    assert summary["call"] == "UNKNOWN"
    assert summary["counts"] == {"lethal": 0, "subviable": 0, "viable": 0}
    assert summary["sources"] == ["impc"]
    assert summary["records"][0]["call"] == "OBSERVATION"
    assert summary["records"][0]["phenotype"] == "decreased body weight"


def test_gene_summary_preserves_conflicting_measurements_and_counts():
    mgi = {"MGI:1": [{
        "source": "mgi", "source_record_id": "G1", "call": "L", "experiment_type": "genetic_mutant",
        "zygosity": "homozygous", "evidence_level": "direct", "genotype": "Gene<tm1>/Gene<tm1>",
        "background": "", "alleles": [], "phenotype": "lethal", "phenotype_terms": [], "stage": "E",
        "systems": [], "qualifiers": [], "references": [],
    }]}
    impc = {"MGI:1": [{
        "source": "impc", "source_record_id": "C1", "call": "V", "experiment_type": "impc_viability_screen",
        "zygosity": "homozygote", "evidence_level": "direct", "genotype": "", "background": "",
        "alleles": [], "phenotype": "viable", "phenotype_terms": [], "stage": "W",
        "systems": [], "qualifiers": [], "references": [],
    }]}

    record = details.merge_mouse_records([mgi, impc])["MGI:1"]

    assert record["call"] == "CONFLICTING"
    assert record["counts"] == {"lethal": 1, "subviable": 0, "viable": 1}
    assert record["sources"] == ["impc", "mgi"]
    data = {"genes": {"GENE": record}}
    assert details.validate_mouse_details(data, {"GENE": {"n": [1, 0, 1], "src": "MI"}})


def test_sqlite_returns_one_gene_without_reading_the_json(tmp_path):
    record = {"call": "LETHAL", "records": [{"source": "mgi", "source_record_id": "G1"}]}
    data = {"built": "2026-11-04", "coverage": {"genes": 1}, "genes": {"TDG": record}}
    path = details.write_sqlite(tmp_path / "10090.sqlite", data)

    with sqlite3.connect(path) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
        payload = connection.execute("SELECT payload FROM genes WHERE symbol = 'TDG'").fetchone()[0]

    assert metadata["built"] == "2026-11-04"
    assert json.loads(payload) == record
