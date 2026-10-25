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


COMPLETE = {"annotations_total": 10, "annotations_read": 10, "coverage": 1.0, "complete": True,
            "limit": 2000, "message": ""}
PARTIAL = {"annotations_total": 5120, "annotations_read": 2000, "coverage": 0.39, "complete": False,
           "limit": 2000, "message": "Only 39% of annotations were read (2,000 of 5,120)."}


def run(ranked, coverage=COMPLETE, **kwargs):
    genes = [{"symbol": g["symbol"]} for g in ranked]
    with patch("k_sites.data_retrieval.organism_resolver.resolve_organism",
               return_value={"taxid": "9606", "scientific_name": "Homo sapiens"}), \
         patch("k_sites.data_retrieval.go_gene_mapper.get_genes_for_go_term_with_coverage",
               return_value=(genes, coverage)), \
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


class TestCoverageAndProgress:
    def test_complete_read_has_no_warning(self):
        results = run([scored("A", 1.0, 0.9)], max_pleiotropy=5)

        assert results["warnings"] == []
        assert results["metadata"]["annotation_coverage"]["complete"] is True

    def test_partial_read_is_reported_as_a_warning(self):
        results = run([scored("A", 1.0, 0.9)], coverage=PARTIAL, max_pleiotropy=5)

        assert results["warnings"] == ["Only 39% of annotations were read (2,000 of 5,120)."]
        assert results["metadata"]["annotation_coverage"]["coverage"] == 0.39

    def test_progress_callback_reports_gene_assessment(self):
        events = []
        run([scored("A", 1.0, 0.9), scored("B", 2.0, 0.8)], max_pleiotropy=5,
            progress_callback=lambda stage, done, total: events.append((stage, done, total)))

        assessing = [e for e in events if e[0] == "Assessing genes"]
        assert assessing[0] == ("Assessing genes", 0, 2)
        assert assessing[-1] == ("Assessing genes", 2, 2)
