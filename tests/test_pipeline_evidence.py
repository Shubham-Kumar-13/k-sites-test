"""
The pipeline with measured knockout evidence: ordering, the genes left out, the phenotype predictor, and the warnings.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from k_sites.knockout_evidence import EvidenceProvider
from k_sites.workflow.pipeline import run_k_sites_pipeline

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "evidence"
COMPLETE = {"annotations_total": 10, "annotations_read": 10, "coverage": 1.0, "complete": True, "limit": 2000, "message": ""}


def scored(symbol, pleiotropy, composite):
    return {
        "symbol": symbol, "description": f"{symbol} protein", "entrez_id": "", "data_status": "ok", "data_issues": [],
        "pleiotropy_score": pleiotropy, "specificity_score": 1 - pleiotropy / 10, "evidence_quality": 1.0,
        "literature_score": 0.8, "conservation_score": 0.5, "composite_score": composite,
        "bp_term_count": 2, "kegg_pathway_count": 4,
    }


@pytest.fixture(scope="module")
def provider():
    return EvidenceProvider.from_directory(FIXTURES)


def run(ranked, taxid="9606", name="Homo sapiens", **kwargs):
    genes = [{"symbol": g["symbol"]} for g in ranked]
    with patch("k_sites.data_retrieval.organism_resolver.resolve_organism",
               return_value={"taxid": taxid, "scientific_name": name}), \
         patch("k_sites.data_retrieval.go_gene_mapper.get_genes_for_go_term_with_coverage", return_value=(genes, COMPLETE)), \
         patch("k_sites.gene_analysis.pleiotropy_scorer.rank_genes_by_specificity", return_value=ranked), \
         patch("k_sites.gene_analysis.pleiotropy_scorer.validate_gene_specificity_across_species",
               return_value={"conservation_score": 0.5}):
        return run_k_sites_pipeline(go_term="GO:0006281", organism=taxid, **kwargs)


class TestOrdering:
    def test_genes_are_listed_safest_first_then_by_composite_score(self, provider):
        ranked = [scored("PCNA", 1.0, 0.95),        # essential in cells: AVOID, although it has the best composite
                  scored("OGG1", 6.0, 0.90),        # viable but multi-functional: CAUTION
                  scored("SMUG1", 1.0, 0.60),       # SAFE
                  scored("NEIL2", 0.0, 0.70)]       # SAFE, better composite
        results = run(ranked, max_pleiotropy=10, evidence_provider=provider)

        assert [g["symbol"] for g in results["genes"]] == ["NEIL2", "SMUG1", "OGG1", "PCNA"]
        assert results["statistics"]["by_safety_level"] == {"SAFE": 2, "CAUTION": 1, "AVOID": 1}

    def test_every_gene_carries_its_measured_evidence_and_the_basis_of_the_verdict(self, provider):
        gene = run([scored("PCNA", 1.0, 0.9)], max_pleiotropy=10, evidence_provider=provider)["genes"][0]

        assert gene["knockout_evidence"]["cells"]["call"] == "ESSENTIAL"
        assert gene["knockout_evidence"]["organism"]["call"] == "LETHAL"
        assert gene["safety_recommendation"]["evidence_basis"] == "measured"
        assert gene["safety_recommendation"]["safety_level"] == "AVOID"

    def test_the_knockout_context_is_chosen_or_follows_the_organism(self, provider):
        human = run([scored("TDG", 1.0, 0.9)], max_pleiotropy=10, evidence_provider=provider)
        organism = run([scored("TDG", 1.0, 0.9)], max_pleiotropy=10, evidence_provider=provider, knockout_context="organism")

        assert human["metadata"]["knockout_context"] == "cells"
        assert human["genes"][0]["safety_recommendation"]["safety_level"] == "SAFE"      # TDG is rarely essential in cell lines
        assert organism["metadata"]["knockout_context"] == "organism"
        assert organism["genes"][0]["safety_recommendation"]["safety_level"] == "AVOID"  # but the mouse knockout is lethal


class TestGenesLeftOut:
    def test_genes_above_the_pleiotropy_cutoff_are_listed_with_their_measured_result(self, provider):
        ranked = [scored("SMUG1", 1.0, 0.6), scored("POLB", 9.0, 0.3)]
        results = run(ranked, max_pleiotropy=5, evidence_provider=provider)

        assert [g["symbol"] for g in results["genes"]] == ["SMUG1"]
        left_out = results["excluded_genes"]
        assert [g["symbol"] for g in left_out] == ["POLB"]
        assert left_out[0]["reason"] == "pleiotropy" and "above the cutoff of 5" in left_out[0]["detail"]
        assert left_out[0]["knockout_evidence"]["organism"]["call"] == "LETHAL"          # visible although left out
        assert results["statistics"]["genes_above_pleiotropy_cutoff"] == 1


class TestPhenotypePrediction:
    def test_the_predictor_only_runs_for_genes_without_a_measurement(self, provider):
        predictor = MagicMock()
        predictor.predict_phenotype.return_value = None
        with patch("k_sites.rag_system.literature_context.RAGPhenotypePredictor", return_value=predictor):
            results = run([scored("SMUG1", 1.0, 0.6), scored("NOSUCHGENE", 1.0, 0.5)], max_pleiotropy=10,
                          evidence_provider=provider, predict_phenotypes=True)

        assert [c.args[0] for c in predictor.predict_phenotype.call_args_list] == ["NOSUCHGENE"]
        assert results["statistics"]["phenotype_predictions_skipped"] == 1

    def test_the_model_is_not_loaded_when_every_gene_is_measured(self, provider):
        with patch("k_sites.rag_system.literature_context.RAGPhenotypePredictor") as predictor_class:
            run([scored("SMUG1", 1.0, 0.6)], max_pleiotropy=10, evidence_provider=provider, predict_phenotypes=True)

        predictor_class.assert_not_called()


class TestWarnings:
    def test_a_missing_evidence_download_is_reported_not_hidden(self):
        with patch("k_sites.knockout_evidence.default_provider", return_value=None), \
             patch("k_sites.knockout_evidence.evidence_disabled", return_value=False):
            results = run([scored("SMUG1", 1.0, 0.6)], max_pleiotropy=10)

        assert any("Measured knockout data could not be loaded" in w for w in results["warnings"])
        gene = results["genes"][0]
        assert gene["safety_recommendation"]["safety_level"] == "CAUTION"      # as announced: nothing is rated better than CAUTION
        assert gene["safety_recommendation"]["evidence_basis"] == "none" and not gene["knockout_evidence"]["has_measured"]
        assert results["metadata"]["knockout_evidence_data"]["available"] is False

    def test_an_organism_without_data_is_reported(self, provider):
        results = run([scored("tdg", 1.0, 0.6)], taxid="3702", name="Arabidopsis thaliana", max_pleiotropy=10, evidence_provider=provider)

        assert any("no measured knockout data for Arabidopsis thaliana" in w for w in results["warnings"])
        assert results["genes"][0]["safety_recommendation"]["safety_level"] == "CAUTION"
        assert results["metadata"]["knockout_evidence_data"]["organism_covered"] is False

    def test_evidence_can_be_switched_off(self, provider):
        results = run([scored("PCNA", 1.0, 0.9)], max_pleiotropy=10, evidence_provider=provider, use_measured_evidence=False)

        assert results["genes"][0]["knockout_evidence"] is None
        assert results["genes"][0]["safety_recommendation"]["safety_level"] == "SAFE"
        assert results["warnings"] == []

    def test_the_evidence_version_and_sources_are_recorded(self, provider):
        data = run([scored("PCNA", 1.0, 0.9)], max_pleiotropy=10, evidence_provider=provider)["metadata"]["knockout_evidence_data"]

        assert data["available"] and data["organism_covered"] and data["version"]
        assert {s["id"] for s in data["sources"]} >= {"mgi", "impc", "depmap"}


class TestUnreadableFiles:
    def test_an_organism_file_that_cannot_be_read_is_reported_and_no_gene_is_rated_safe(self):
        from k_sites.knockout_evidence import EvidenceUnavailable

        class Source:
            def read(self, name):
                if name == "index.json":
                    return {"format": 1, "built": "2026-01-01", "sources": [],
                            "organisms": {"9606": {"file": "9606.json", "name": "Homo sapiens", "layers": []}}}
                raise EvidenceUnavailable("HTTP 404")

        results = run([scored("SMUG1", 1.0, 0.6)], max_pleiotropy=10, evidence_provider=EvidenceProvider(Source()))

        assert any("Measured knockout data could not be loaded" in w for w in results["warnings"])
        assert results["genes"][0]["safety_recommendation"]["safety_level"] == "CAUTION"
        assert results["metadata"]["knockout_evidence_data"]["available"] is False
