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
    get_genes_for_go_term_with_coverage,
    GoTermNotFoundError,
    GeneRetrievalError,
)


class TestUnnamedProteinRecords:
    """QuickGO uses the accession as the symbol of an unreviewed protein record that has no gene name; it is not a gene."""

    RESULTS = [
        {"symbol": "A8K1L8", "geneProductId": "UniProtKB:A8K1L8", "goEvidence": "IEA", "qualifier": "involved_in"},
        {"symbol": "A8K1L8", "geneProductId": "UniProtKB:A8K1L8", "goEvidence": "IBA", "qualifier": "involved_in"},
        {"symbol": "B3GAT1", "geneProductId": "UniProtKB:O43505", "goEvidence": "IDA", "qualifier": "involved_in"},   # looks like an accession, is a gene
        {"symbol": "TRA2A", "geneProductId": "UniProtKB:Q13595-2", "goEvidence": "IDA", "qualifier": "involved_in"},
        {"symbol": "Q9Y2X3", "geneProductId": "UniProtKB:Q9Y2X3-2", "goEvidence": "IEA", "qualifier": "involved_in"},   # an isoform of an unnamed record
    ]

    def test_unnamed_records_are_left_out_and_counted(self):
        genes = go_gene_mapper._process_annotations(self.RESULTS, "all")

        assert sorted(g["symbol"] for g in genes) == ["B3GAT1", "TRA2A"]
        assert go_gene_mapper.count_unnamed_records(self.RESULTS) == 2

    def test_the_read_limit_covers_a_large_term(self):
        assert go_gene_mapper.DEFAULT_MAX_ANNOTATIONS >= 6000


def annotation(symbol, product_id, evidence, reference="PMID:1", qualifier="involved_in"):
    """Build a QuickGO annotation record in the shape the mapper reads."""
    return {
        "symbol": symbol,
        "geneProductId": product_id,
        "goEvidence": evidence,
        "reference": reference,
        "qualifier": qualifier,
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


def page_of(count):
    return [annotation(f"G{i}", f"UniProtKB:P{i:05d}", "IDA") for i in range(count)]


class TestCoverage:
    """The safety limit may stop the read early; the caller must be told how much was read."""

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_complete_read_has_no_message(self, mock_fetch):
        mock_fetch.return_value = (2, [
            annotation("BRCA1", "UniProtKB:P38398", "IDA"),
            annotation("TP53", "UniProtKB:P04637", "IDA"),
        ])

        _, coverage = get_genes_for_go_term_with_coverage("GO:0006281", "9606")

        assert coverage["complete"] is True
        assert coverage["coverage"] == 1.0
        assert coverage["message"] == ""

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_limit_stops_the_read_and_says_how_much_was_read(self, mock_fetch):
        # 1000 annotations exist; the limit allows 400 (2 pages of 200)
        mock_fetch.return_value = (1000, page_of(200))

        genes, coverage = get_genes_for_go_term_with_coverage("GO:0006281", "9606", max_annotations=400)

        assert mock_fetch.call_count == 2
        assert coverage["complete"] is False
        assert coverage["annotations_total"] == 1000
        assert coverage["annotations_read"] == 400
        assert coverage["coverage"] == pytest.approx(0.4)
        assert "Only 40% of annotations were read (400 of 1,000)" in coverage["message"]

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_incomplete_read_never_shows_one_hundred_percent(self, mock_fetch):
        mock_fetch.return_value = (201, page_of(200))

        _, coverage = get_genes_for_go_term_with_coverage("GO:0006281", "9606", max_annotations=200)

        assert "Only 99% of annotations" in coverage["message"]

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_warning_is_logged(self, mock_fetch, caplog):
        mock_fetch.return_value = (1000, page_of(200))

        with caplog.at_level("WARNING"):
            get_genes_for_go_term_with_coverage("GO:0006281", "9606", max_annotations=200)

        assert "Only 20% of annotations were read" in caplog.text

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_progress_is_reported_per_page(self, mock_fetch):
        mock_fetch.return_value = (600, page_of(200))
        events = []

        get_genes_for_go_term_with_coverage(
            "GO:0006281", "9606",
            progress_callback=lambda stage, done, total: events.append((stage, done, total)),
        )

        assert events[0] == ("Reading GO annotations", 1, 3)
        assert events[-1] == ("Reading GO annotations", 3, 3)

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_different_limits_are_cached_separately(self, mock_fetch):
        mock_fetch.return_value = (400, page_of(200))

        _, small = get_genes_for_go_term_with_coverage("GO:0006281", "9606", max_annotations=200)
        _, large = get_genes_for_go_term_with_coverage("GO:0006281", "9606", max_annotations=400)

        assert small["complete"] is False
        assert large["complete"] is True


class TestOneEntryPerGene:
    """QuickGO lists each protein variant of a gene separately; the gene list must not."""

    def variants(self):
        return [
            {**annotation("MUTYH", "UniProtKB:Q9UIF7", "IDA"), "name": "Adenine DNA glycosylase"},
            {**annotation("MUTYH", "UniProtKB:Q9UIF7-2", "IEA"), "name": "Adenine DNA glycosylase isoform 2"},
            {**annotation("MUTYH", "UniProtKB:A0A0S2Z3J8", "IEA"), "name": "Adenine DNA glycosylase, isoform CRA_a"},
            annotation("UNG", "UniProtKB:P13051", "IDA"),
        ]

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_variants_of_one_gene_are_merged(self, mock_fetch):
        mock_fetch.return_value = (4, self.variants())

        genes = get_genes_for_go_term("GO:0006284", "9606", "all")

        assert sorted(g["symbol"] for g in genes) == ["MUTYH", "UNG"]

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_merged_gene_keeps_the_canonical_accession_and_a_real_name(self, mock_fetch):
        mock_fetch.return_value = (4, self.variants())

        mutyh = next(g for g in get_genes_for_go_term("GO:0006284", "9606", "all") if g["symbol"] == "MUTYH")

        assert mutyh["entrez_id"] == "UniProtKB:Q9UIF7"           # not the isoform or TrEMBL entry
        assert mutyh["description"] == "Adenine DNA glycosylase"   # a name, not a PubMed id
        assert mutyh["go_evidence_type"] == "experimental"         # strongest evidence across variants
        assert set(mutyh["evidence_codes"]) == {"IDA", "IEA"}
        assert len(mutyh["uniprot_accessions"]) == 3

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_not_annotations_do_not_make_a_gene_a_candidate(self, mock_fetch):
        mock_fetch.return_value = (2, [
            annotation("GOOD", "UniProtKB:P00001", "IDA"),
            annotation("EXCLUDED", "UniProtKB:P00002", "IDA", qualifier="NOT|involved_in"),
        ])

        genes = get_genes_for_go_term("GO:0006284", "9606", "all")

        assert [g["symbol"] for g in genes] == ["GOOD"]

    @patch.object(go_gene_mapper, "_fetch_quickgo_page")
    def test_exp_evidence_counts_as_experimental(self, mock_fetch):
        mock_fetch.return_value = (1, [annotation("GENE", "UniProtKB:P00003", "EXP")])

        assert len(get_genes_for_go_term("GO:0006284", "9606", "experimental")) == 1


class TestNamePicking:
    def test_prefers_a_specific_name_over_isoform_and_generic_ones(self):
        names = ["Uracil-DNA glycosylase-like domain-containing protein",
                 "Single-strand-selective monofunctional uracil-DNA glycosylase 1 isoform 1",
                 "Single-strand-selective monofunctional uracil-DNA glycosylase 1"]

        assert go_gene_mapper._pick_name(names) == "Single-strand-selective monofunctional uracil-DNA glycosylase 1"

    def test_falls_back_when_every_name_is_generic(self):
        assert go_gene_mapper._pick_name(["Isoform 2"], fallback="PMID:1") == "Isoform 2"
        assert go_gene_mapper._pick_name([], fallback="PMID:1") == "PMID:1"
