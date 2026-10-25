"""
Pipeline tests with the data sources mocked.
"""

from unittest.mock import patch

from k_sites.workflow.pipeline import run_k_sites_pipeline


def scored(symbol, pleiotropy, specificity):
    return {
        "symbol": symbol, "description": symbol, "entrez_id": "", "data_status": "ok", "data_issues": [],
        "pleiotropy_score": pleiotropy, "specificity_score": specificity, "evidence_quality": 1.0,
        "literature_score": 0.8, "conservation_score": 0.5, "composite_score": 0.7,
        "bp_term_count": 2, "kegg_pathway_count": 4,
    }


def unscorable(symbol):
    return {
        "symbol": symbol, "description": symbol, "data_status": "insufficient_data",
        "data_issues": ["go lookup failed: HTTP 503"], "lookup_failed": True,
        "pleiotropy_score": None, "specificity_score": None, "composite_score": 0.0,
    }


def run(ranked, **kwargs):
    with patch("k_sites.data_retrieval.organism_resolver.resolve_organism",
               return_value={"taxid": "9606", "scientific_name": "Homo sapiens"}), \
         patch("k_sites.data_retrieval.go_gene_mapper.get_genes_for_go_term",
               return_value=[{"symbol": g["symbol"]} for g in ranked]), \
         patch("k_sites.gene_analysis.pleiotropy_scorer.rank_genes_by_specificity", return_value=ranked), \
         patch("k_sites.gene_analysis.pleiotropy_scorer.validate_gene_specificity_across_species",
               return_value={"conservation_score": 0.5}):
        return run_k_sites_pipeline(go_term="GO:0006281", organism="9606", **kwargs)


class TestPipeline:
    def test_unscorable_genes_are_reported_separately_not_as_safe(self):
        results = run([scored("GOOD", 1.0, 0.9), unscorable("BAD")], max_pleiotropy=5)

        assert [g["symbol"] for g in results["genes"]] == ["GOOD"]
        assert [g["symbol"] for g in results["insufficient_data_genes"]] == ["BAD"]
        assert results["insufficient_data_genes"][0]["lookup_failed"] is True
        assert results["statistics"]["genes_insufficient_data"] == 1
        assert results["statistics"]["total_genes_screened"] == 2
        assert results["statistics"]["genes_passed_filter"] == 1

    def test_genes_above_the_pleiotropy_cutoff_are_dropped(self):
        results = run([scored("SPECIFIC", 1.0, 0.9), scored("BROAD", 8.0, 0.2)], max_pleiotropy=5)

        assert [g["symbol"] for g in results["genes"]] == ["SPECIFIC"]

    def test_gene_result_carries_scores_and_safety_recommendation(self):
        gene = run([scored("GOOD", 1.0, 0.9)], max_pleiotropy=5)["genes"][0]

        assert gene["pleiotropy_score"] == 1.0
        assert gene["specificity_score"] == 0.9
        assert gene["kegg_pathway_count"] == 4
        assert gene["literature_support"] == 0.8
        assert gene["safety_recommendation"]["safety_level"] == "SAFE"

    def test_average_pleiotropy_ignores_unscorable_genes(self):
        results = run([scored("A", 2.0, 0.8), scored("B", 4.0, 0.6), unscorable("C")], max_pleiotropy=10)

        assert results["statistics"]["avg_pleiotropy"] == 3.0
