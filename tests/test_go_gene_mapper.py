"""
Unit tests for go_gene_mapper module.

QuickGO is mocked at ``_fetch_quickgo_page`` and the on-disk cache is bypassed,
so the tests never touch the network or the user's real cache.
"""

import pytest
from unittest.mock import patch, MagicMock

import requests

from k_sites.data_retrieval import go_gene_mapper
from k_sites.data_retrieval.go_gene_mapper import (
    get_genes_for_go_term,
    GoTermNotFoundError,
    GeneRetrievalError,
)


def annotation(symbol, product_id, evidence, reference="PMID:1"):
    """Build a QuickGO annotation record in the shape the mapper reads."""
    return {
        "symbol": symbol,
        "geneProductId": product_id,
        "goEvidence": evidence,
        "reference": reference,
        "qualifier": "involved_in",
    }


@pytest.fixture(autouse=True)
def isolated_cache():
    """Run every test with an empty in-memory cache and no disk access."""
    with patch.object(go_gene_mapper, "_load_cache"), \
         patch.object(go_gene_mapper, "_save_cache"), \
         patch.dict(go_gene_mapper._go_gene_cache, {}, clear=True):
        yield


class TestGoGeneMapper:
    """Test cases for GO term to gene mapping functionality."""

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_get_genes_for_valid_go_term(self, mock_fetch):
        mock_fetch.return_value = (2, [
            annotation("BRCA1", "UniProtKB:P38398", "IDA"),
            annotation("TP53", "UniProtKB:P04637", "IMP"),
        ])

        genes = get_genes_for_go_term("GO:0006281", "9606")

        assert [g["symbol"] for g in genes] == ["BRCA1", "TP53"]
        assert genes[0]["entrez_id"] == "UniProtKB:P38398"
        assert genes[0]["evidence_codes"] == ["IDA"]
        assert genes[0]["go_evidence_type"] == "experimental"

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_experimental_filter_excludes_iea(self, mock_fetch):
        mock_fetch.return_value = (2, [
            annotation("BRCA1", "UniProtKB:P38398", "IEA"),
            annotation("TP53", "UniProtKB:P04637", "IDA"),
        ])

        genes = get_genes_for_go_term("GO:0006281", "9606", "experimental")

        assert [g["symbol"] for g in genes] == ["TP53"]

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_computational_filter_includes_iea(self, mock_fetch):
        mock_fetch.return_value = (2, [
            annotation("BRCA1", "UniProtKB:P38398", "IEA"),
            annotation("TP53", "UniProtKB:P04637", "IDA"),
        ])

        genes = get_genes_for_go_term("GO:0006281", "9606", "computational")

        assert [g["symbol"] for g in genes] == ["BRCA1"]

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_all_filter_keeps_every_gene(self, mock_fetch):
        mock_fetch.return_value = (2, [
            annotation("BRCA1", "UniProtKB:P38398", "IEA"),
            annotation("TP53", "UniProtKB:P04637", "IDA"),
        ])

        genes = get_genes_for_go_term("GO:0006281", "9606", "all")

        assert {g["symbol"] for g in genes} == {"BRCA1", "TP53"}

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_annotations_for_same_gene_are_merged(self, mock_fetch):
        mock_fetch.return_value = (2, [
            annotation("BRCA1", "UniProtKB:P38398", "IDA"),
            annotation("BRCA1", "UniProtKB:P38398", "IMP"),
        ])

        genes = get_genes_for_go_term("GO:0006281", "9606")

        assert len(genes) == 1
        assert set(genes[0]["evidence_codes"]) == {"IDA", "IMP"}

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_get_genes_empty_result(self, mock_fetch):
        mock_fetch.return_value = (0, [])

        assert get_genes_for_go_term("GO:0000000", "9606") == []

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_results_are_cached(self, mock_fetch):
        mock_fetch.return_value = (1, [annotation("BRCA1", "UniProtKB:P38398", "IDA")])

        first = get_genes_for_go_term("GO:0006281", "9606")
        second = get_genes_for_go_term("GO:0006281", "9606")

        assert first == second
        assert mock_fetch.call_count == 1

    @patch("k_sites.data_retrieval.go_gene_mapper.http_get")
    def test_request_failure_raises_error(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("Network error")

        with pytest.raises(GeneRetrievalError):
            get_genes_for_go_term("GO:0006281", "9606")

    @patch("k_sites.data_retrieval.go_gene_mapper.http_get")
    def test_server_error_raises_error(self, mock_get):
        mock_get.return_value = MagicMock(status_code=503, text="unavailable")

        with pytest.raises(GeneRetrievalError):
            get_genes_for_go_term("GO:0006281", "9606")

    @patch("k_sites.data_retrieval.go_gene_mapper.http_get")
    def test_go_term_not_found_raises_error(self, mock_get):
        mock_get.return_value = MagicMock(status_code=400, text="invalid goId")

        with pytest.raises(GoTermNotFoundError):
            get_genes_for_go_term("GO:0000000", "9606")

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_failed_extra_page_fails_the_lookup(self, mock_fetch):
        first = [annotation("BRCA1", "UniProtKB:P38398", "IDA")]
        mock_fetch.side_effect = [(450, first), (450, first), GeneRetrievalError("page 3 failed")]

        with pytest.raises(GeneRetrievalError):
            get_genes_for_go_term("GO:0006281", "9606")

    def test_invalid_go_term_format(self):
        with pytest.raises(ValueError):
            get_genes_for_go_term("INVALID_FORMAT", "9606")

        with pytest.raises(ValueError):
            get_genes_for_go_term("GO:123", "9606")  # Wrong length
