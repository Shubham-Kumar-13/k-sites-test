import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import test_evidence_builder as fixtures
from build_evidence_data import parse_zfin_features, parse_zfin_fish, parse_zfin_stages
import build_zfin_details as details


def test_zfin_mutant_lines_keep_genotype_alleles_stage_and_pubmed():
    stages = parse_zfin_stages(fixtures.TestZebrafish.STAGES)
    features = parse_zfin_features(fixtures.TestZebrafish.FEATURES)
    fish = parse_zfin_fish(fixtures.TestZebrafish().fish_lines(), features)
    metadata = details.fish_metadata(fixtures.TestZebrafish().fish_lines(), fish)
    helper = fixtures.TestZebrafish()
    lines = [
        helper.phenotype("F1", "ZDB-GENE-1", "gene1", "PATO:0001422", "dead", stage="ZDB-STAGE-2"),
        helper.phenotype("F2", "ZDB-GENE-1", "gene1", "PATO:0000718", "lethal (sensu genetics)", stage="ZDB-STAGE-1"),
        helper.phenotype("F3", "ZDB-GENE-2", "gene2", "PATO:0000001", "quality", structure="ZFA:0000114", stage="ZDB-STAGE-3"),
    ]

    records = details.zfin_details(lines, fish, metadata, stages, {"ZDB-PUB-1": "123"})

    lethal = records["GENE1"][0]
    assert lethal["call"] == "L" and lethal["stage"] == "L"
    assert records["GENE1"][1]["stage"] == "E"
    assert lethal["zygosity"] == "homozygous" and lethal["evidence_level"] == "direct"
    assert lethal["source_record_id"] == "F1"
    assert lethal["genotype"] == "gene1<sup>a1/a1</sup>"
    assert lethal["alleles"][0]["id"] == "ZDB-ALT-1"
    assert lethal["references"] == ["123"]
    assert records["GENE2"][0]["call"] == "V"
    assert records["GENE2"][0]["qualifiers"] == ["living_juvenile_or_adult"]


def test_unclear_alleles_and_larval_phenotypes_do_not_prove_viability():
    stages = parse_zfin_stages(fixtures.TestZebrafish.STAGES)
    fish = {"F1": ("ZDB-GENE-1", "null"), "F2": ("ZDB-GENE-2", "other")}
    metadata = {"F1": {"name": "gene1<sup>a1/a1</sup>", "alleles": ["ZDB-ALT-1"]},
                "F2": {"name": "gene2<sup>a2/a2</sup>", "alleles": ["ZDB-ALT-2"]}}
    helper = fixtures.TestZebrafish()
    lines = [helper.phenotype("F1", "ZDB-GENE-1", "gene1", "PATO:1", "q", structure="ZFA:5", stage="ZDB-STAGE-2"),
             helper.phenotype("F2", "ZDB-GENE-2", "gene2", "PATO:1", "q", structure="ZFA:5", stage="ZDB-STAGE-3")]

    records = details.zfin_details(lines, fish, metadata, stages, {})

    assert records == {}
