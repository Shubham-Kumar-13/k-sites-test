import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_evidence_details as details


def row(gene, germplasm, phenotype, pmid=""):
    return {"LOCUS_NAME": gene, "GERMPLASM_NAME": germplasm, "PHENOTYPE": phenotype, "PUBMED_ID": pmid}


def test_single_mutant_viability_is_kept_but_double_mutant_lethality_is_not_attributed_to_the_gene():
    records = details.parse_tair([row(
        "AT1G02880", "AtTPK1-KO",
        "The AtTPK1-KO single mutant does not have any obvious aberrant phenotypes. "
        "The AtTPK1-KO /AtTPK2-KO double mutant demonstrates lethality.",
        "17611796",
    )])

    assert len(records["AT1G02880"]) == 1
    finding = records["AT1G02880"][0]
    assert finding["call"] == "VIABLE"
    assert finding["source_record_id"] == "AtTPK1-KO"
    assert finding["references"] == ["17611796"]
    assert "double mutant" not in finding["phenotype"]


def test_an_inseparable_single_and_double_mutant_sentence_is_left_out():
    records = details.parse_tair([row(
        "AT1G02880", "AtTPK1-KO",
        "The AtTPK1-KO single mutant does not have any obvious aberrant phenotypes, but, "
        "the AtTPK1-KO /AtTPK2-KO double mutant demonstrates lethality.",
    )])

    assert records == {}


@pytest.mark.parametrize("phenotype", [
    "double mutants are both male and female gametophyte lethal",
    "Quadruple mutant has an early embryo lethal phenotype (100%).",
    "Double homozygous pol-6 pll1-1 plant has a seedling lethal phenotype if not grafted.",
])
def test_plural_and_higher_order_mutants_are_excluded(phenotype):
    assert details.parse_tair([row("AT1G09100", "combined-line", phenotype)]) == {}


@pytest.mark.parametrize("germplasm", ["adg1 be2-1 be3-2", "bon1-1/bon2-2/bon3-3", "geneA+geneB"])
def test_multi_gene_germplasm_is_excluded_even_with_single_gene_phenotype_text(germplasm):
    assert details.parse_tair([row("AT1G03310", germplasm, "No visible phenotype.")]) == {}


@pytest.mark.parametrize("phenotype", [
    "Not embryo lethal and no obvious developmental defects.",
    "Does not segregate for embryo lethal phenotype.",
    "The reported embryo lethal phenotype was caused by loss of another locus.",
])
def test_negated_or_other_locus_lethality_is_not_accepted(phenotype):
    assert details.parse_tair([row("AT1G55040", "CS1", phenotype)]) == {}


def test_identical_germplasm_evidence_assigned_to_multiple_loci_is_left_out():
    records = details.parse_tair([
        row("AT1G01010", "CS1", "No visible phenotype."),
        row("AT1G01020", "CS1", "No visible phenotype."),
        row("AT1G01030", "CS1", "No visible phenotype."),
    ])

    assert records == {}


def test_explicit_homozygous_lethality_is_preserved_with_qualified_experiment_type():
    records = details.parse_tair([row(
        "AT1G02660", "SALK_052897",
        "Homozygotes are embryo lethal. Somewhat reduced transmission through the pollen.",
        "26555280",
    )])

    finding = records["AT1G02660"][0]
    assert finding["call"] == "LETHAL"
    assert finding["zygosity"] == "homozygous"
    assert finding["experiment_type"] == "mutant_not_otherwise_specified"
    assert finding["evidence_level"] == "qualified"


def test_condition_specific_lethality_is_marked_conditional():
    finding = details.classify_tair_sentence("Seedling lethal when exposed to fluctuating light.")

    assert finding["call"] == "LETHAL"
    assert finding["qualifiers"] == ["conditional"]


def test_uninformative_phenotypes_do_not_become_viability_evidence():
    assert details.parse_tair([
        row("AT1G01010", "CS1", "Phenotype not described."),
        row("AT1G01011", "CS2", "narrow leaves and short petioles."),
        row("AT1G01012", "CS3", "developmental arrest of mutant embryos."),
    ]) == {}


def test_conflicting_alleles_are_retained_and_marked():
    genes = details.parse_tair([
        row("AT1G01010", "lethal-1", "Homozygotes are embryo lethal."),
        row("AT1G01010", "viable-1", "Homozygous viable."),
    ])
    merged = details.merge_gene_records(genes)

    record = merged["AT1G01010"]
    assert record["call"] == "CONFLICTING"
    assert record["conflicting"] is True
    assert record["counts"] == {"lethal": 1, "viable": 1}
    assert len(record["records"]) == 2


def test_duplicate_rows_are_merged_and_references_are_retained():
    genes = details.parse_tair([
        row("AT1G01010", "CS1", "Homozygotes are embryo lethal.", "111"),
        row("AT1G01010", "CS1", "Homozygotes are embryo lethal.", "222"),
    ])

    assert len(genes["AT1G01010"]) == 1
    assert genes["AT1G01010"][0]["references"] == ["111", "222"]


def test_thalemine_records_name_the_curated_source_list(monkeypatch):
    list_name = "List Analysis for Genes with a Loss-of-Function Mutant Phenotype: Essential - Lethal"
    monkeypatch.setattr(details, "fetch_thalemine_list",
                        lambda name, http: "DCL1\tAT1G01040\nCHLOROPLAST\tATCG01060\nMITOCHONDRIA\tATMG01320\n" if name == list_name else "")

    genes = details.build_thalemine_details(object())

    assert genes["ATCG01060"][0]["call"] == "LETHAL"
    assert genes["ATMG01320"][0]["call"] == "LETHAL"
    finding = genes["AT1G01040"][0]
    assert finding["call"] == "LETHAL"
    assert finding["source"] == "thalemine"
    assert finding["source_record_id"] == list_name
    assert finding["evidence_level"] == "curated"


def test_tair_pilot_is_deterministic_and_limited():
    rows = [row(f"AT1G{i:05d}", f"CS{i}", "Homozygous viable.") for i in range(1, 106)]

    first = details.parse_tair(rows, gene_limit=100)
    second = details.parse_tair(rows, gene_limit=100)

    assert len(first) == 100
    assert first == second


def test_tair_pilot_contains_balanced_call_groups():
    genes = {}
    for index in range(3):
        genes[f"AT1G0101{index}"] = [{"call": "LETHAL"}]
        genes[f"AT1G0102{index}"] = [{"call": "VIABLE"}]
        genes[f"AT1G0103{index}"] = [{"call": "LETHAL"}, {"call": "VIABLE"}]

    selected = details.select_tair_genes(genes, 6)
    profiles = [{record["call"] for record in genes[gene]} for gene in selected]

    assert profiles.count({"LETHAL"}) == 2
    assert profiles.count({"VIABLE"}) == 2
    assert profiles.count({"LETHAL", "VIABLE"}) == 2


def test_validation_rejects_a_multi_gene_record():
    data = {
        "genes": {
            "AT1G01010": {
                "call": "LETHAL", "conflicting": False,
                "records": [{
                    "source": "tair", "source_record_id": "x", "call": "LETHAL",
                    "evidence_level": "qualified", "phenotype": "double mutant is lethal",
                }],
            },
        },
    }

    with pytest.raises(ValueError, match="Multi-gene"):
        details.validate_details(data)
