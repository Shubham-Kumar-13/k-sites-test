"""
Unit tests for pleiotropy_scorer module.

Database lookups are mocked at ``query_gene_from_all_databases`` so no network is used.
"""

import math
import pytest
from unittest.mock import patch

from k_sites.gene_analysis.pleiotropy_scorer import (
    DATA_INSUFFICIENT,
    DATA_OK,
    calculate_pleiotropy_score,
    calculate_specificity_score,
    rank_genes_by_specificity,
    score_gene_pleiotropy,
    score_pleiotropy,
    validate_across_species,
)

QUERY = "k_sites.data_retrieval.multi_database_client.query_gene_from_all_databases"


def term(index, evidence_type):
    return {"go_id": f"GO:{index:07d}", "go_name": f"process {index}", "evidence_type": evidence_type}


def db_result(experimental=0, computational=0, iea=0, kegg_pathways=0, status=None, issues=None):
    """Build a multi-database client result with the given number of BP terms per evidence type."""
    terms = []
    for evidence_type, count in (("experimental", experimental), ("computational", computational), ("IEA", iea)):
        for _ in range(count):
            terms.append(term(len(terms) + 1, evidence_type))
    return {
        "combined_bp_terms": terms,
        "combined_evidence": {"experimental": experimental, "computational": computational, "IEA": iea},
        "kegg_data": {"pathway_count": kegg_pathways},
        "query_status": status or {"go": "success", "uniprot": "success", "kegg": "success"},
        "data_issues": issues or [],
    }


class TestPleiotropyFormula:
    def test_no_or_single_term_is_zero(self):
        assert calculate_pleiotropy_score(0) == 0.0
        assert calculate_pleiotropy_score(1) == 0.0

    def test_exponential_decay_on_other_terms(self):
        # 4 BP terms -> 3 "other" terms
        expected = 10.0 * (1 - math.exp(-0.3 * 3))
        assert calculate_pleiotropy_score(4) == pytest.approx(expected)

    def test_score_increases_with_terms(self):
        scores = [calculate_pleiotropy_score(n) for n in range(1, 11)]
        assert scores == sorted(scores)

    def test_capped_at_ten(self):
        assert calculate_pleiotropy_score(11) == 10.0
        assert calculate_pleiotropy_score(500) == 10.0


class TestSpecificity:
    def test_inverse_on_zero_to_one_scale(self):
        assert calculate_specificity_score(0.0) == 1.0
        assert calculate_specificity_score(10.0) == 0.0
        assert calculate_specificity_score(2.5) == pytest.approx(0.75)

    def test_clamped(self):
        assert calculate_specificity_score(-5) == 1.0
        assert calculate_specificity_score(25) == 0.0


class TestScoreGenePleiotropy:
    @patch(QUERY)
    def test_specific_gene(self, mock_query):
        mock_query.return_value = db_result(experimental=1)

        result = score_gene_pleiotropy("GENE1", "9606", "GO:0006281")

        assert result["data_status"] == DATA_OK
        assert result["pleiotropy_score"] == 0.0
        assert result["specificity_score"] == 1.0
        assert result["bp_term_count"] == 1

    @patch(QUERY)
    def test_pleiotropic_gene_scores_higher(self, mock_query):
        mock_query.return_value = db_result(experimental=8)
        broad = score_gene_pleiotropy("BROAD", "9606", "GO:0006281")

        mock_query.return_value = db_result(experimental=2)
        narrow = score_gene_pleiotropy("NARROW", "9606", "GO:0006281")

        assert broad["pleiotropy_score"] > narrow["pleiotropy_score"]
        assert broad["specificity_score"] < narrow["specificity_score"]

    @patch(QUERY)
    def test_kegg_pathway_count_is_reported(self, mock_query):
        mock_query.return_value = db_result(experimental=3, kegg_pathways=7)

        assert score_gene_pleiotropy("GENE1", "9606")["kegg_pathway_count"] == 7

    @patch(QUERY)
    def test_experimental_filter_counts_only_experimental_terms(self, mock_query):
        mock_query.return_value = db_result(experimental=2, computational=2, iea=2)

        experimental = score_gene_pleiotropy("G", "9606", evidence_filter="experimental")
        computational = score_gene_pleiotropy("G", "9606", evidence_filter="computational")
        everything = score_gene_pleiotropy("G", "9606", evidence_filter="all")

        assert experimental["pleiotropy_score"] == pytest.approx(calculate_pleiotropy_score(2))
        assert computational["pleiotropy_score"] == pytest.approx(calculate_pleiotropy_score(4))
        assert everything["pleiotropy_score"] == pytest.approx(calculate_pleiotropy_score(6))

    @patch(QUERY)
    def test_evidence_quality_weights(self, mock_query):
        mock_query.return_value = db_result(experimental=2)
        assert score_gene_pleiotropy("G", "9606")["evidence_quality"] == pytest.approx(1.0)

        mock_query.return_value = db_result(iea=2)
        assert score_gene_pleiotropy("G", "9606", evidence_filter="all")["evidence_quality"] == pytest.approx(0.3)


class TestInsufficientData:
    """A gene that cannot be assessed must never look perfectly specific."""

    @patch(QUERY)
    def test_no_annotations_is_insufficient(self, mock_query):
        mock_query.return_value = db_result()

        result = score_gene_pleiotropy("GENE1", "9606", "GO:0006281")

        assert result["data_status"] == DATA_INSUFFICIENT
        assert result["pleiotropy_score"] is None
        assert result["specificity_score"] is None
        assert result["lookup_failed"] is False
        assert result["data_issues"]

    @patch(QUERY)
    def test_failed_go_lookup_is_flagged_as_lookup_failure(self, mock_query):
        mock_query.return_value = db_result(
            status={"go": "failed: HTTP 400", "uniprot": "failed: timeout", "kegg": "success"},
            issues=["go lookup failed: HTTP 400", "uniprot lookup failed: timeout"],
        )

        result = score_gene_pleiotropy("GENE1", "9606", "GO:0006281")

        assert result["data_status"] == DATA_INSUFFICIENT
        assert result["lookup_failed"] is True
        assert result["specificity_score"] is None

    @patch(QUERY)
    def test_partial_failure_still_scores_with_issue_recorded(self, mock_query):
        mock_query.return_value = db_result(
            experimental=3,
            status={"go": "failed: timeout", "uniprot": "success", "kegg": "success"},
            issues=["go lookup failed: timeout"],
        )

        result = score_gene_pleiotropy("GENE1", "9606")

        assert result["data_status"] == DATA_OK
        assert "go lookup failed: timeout" in result["data_issues"]

    @patch(QUERY)
    def test_no_term_with_requested_evidence_is_insufficient(self, mock_query):
        mock_query.return_value = db_result(computational=3)

        result = score_gene_pleiotropy("GENE1", "9606", evidence_filter="experimental")

        assert result["data_status"] == DATA_INSUFFICIENT
        assert result["pleiotropy_score"] is None
        assert "experimental" in result["data_issues"][0]

    @patch(QUERY)
    def test_exception_is_insufficient_not_specific(self, mock_query):
        mock_query.side_effect = RuntimeError("boom")

        result = score_gene_pleiotropy("GENE1", "9606", "GO:0006281")

        assert result["data_status"] == DATA_INSUFFICIENT
        assert result["lookup_failed"] is True
        assert result["pleiotropy_score"] is None
        assert "error" in result

    @patch(QUERY)
    def test_ranking_puts_unscorable_genes_last_without_scores(self, mock_query):
        def fake_query(symbol, taxid):
            return db_result(experimental=2) if symbol == "GOOD" else db_result()

        mock_query.side_effect = fake_query

        ranked = rank_genes_by_specificity(
            [{"symbol": "BAD"}, {"symbol": "GOOD"}],
            "9606", target_go_term="GO:0006281",
            include_literature=False, include_cross_species=False,
        )

        assert [g["symbol"] for g in ranked] == ["GOOD", "BAD"]
        assert ranked[0]["data_status"] == DATA_OK
        assert ranked[1]["data_status"] == DATA_INSUFFICIENT
        assert ranked[1]["pleiotropy_score"] is None
        assert ranked[1]["passes_threshold"] is False


class TestLegacyScorePleiotropy:
    @patch(QUERY)
    def test_returns_pleiotropy_number(self, mock_query):
        mock_query.return_value = db_result(experimental=4)

        assert score_pleiotropy("GENE1", "9606", "GO:0006281") == pytest.approx(calculate_pleiotropy_score(4))

    @patch(QUERY)
    def test_returns_none_when_not_scorable(self, mock_query):
        mock_query.return_value = db_result()

        assert score_pleiotropy("GENE1", "9606", "GO:0006281") is None


class TestCrossSpecies:
    @patch("k_sites.gene_analysis.pleiotropy_scorer._validate_in_species")
    def test_failed_lookups_do_not_count_as_absent(self, mock_validate):
        def fake(symbol, go_term, taxid):
            if taxid == "9606":
                return {"found": True, "specificity_score": 0.9}
            if taxid == "10090":
                return {"found": False}
            return {"found": False, "error": "UniProt down"}

        mock_validate.side_effect = fake

        result = validate_across_species("G", "GO:0006281", ["9606", "10090", "7227", "6239"])

        # found in 1 of the 2 species that could be queried
        assert result["conservation_score"] == pytest.approx(0.5)
        assert result["species_queried"] == 2
        assert result["lookup_errors"] == 2

    @patch("k_sites.gene_analysis.pleiotropy_scorer._validate_in_species")
    def test_all_lookups_failed_gives_zero_not_a_crash(self, mock_validate):
        mock_validate.return_value = {"found": False, "error": "down"}

        result = validate_across_species("G", "GO:0006281", ["9606", "10090"])

        assert result["conservation_score"] == 0.0
        assert result["species_queried"] == 0
