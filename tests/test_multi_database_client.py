"""
Unit tests for the multi-database client. HTTP is mocked at ``http_get``.
"""

import pytest
import requests
from unittest.mock import patch, MagicMock

from k_sites.data_retrieval import multi_database_client as mdc
from k_sites.data_retrieval.multi_database_client import LookupFailure, MultiDatabaseClient

HTTP_GET = "k_sites.data_retrieval.multi_database_client.http_get"


@pytest.fixture(autouse=True)
def no_sleep():
    with patch.object(mdc.time, "sleep"):
        yield


def response(status=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


def qg(go_id, evidence, qualifier="involved_in", name="process"):
    return {"goId": go_id, "goEvidence": evidence, "goName": name,
            "goAspect": "biological_process", "qualifier": qualifier}


@pytest.fixture
def client():
    return MultiDatabaseClient()


class TestEvidenceClassification:
    @pytest.mark.parametrize("codes,expected", [
        (["IDA"], "experimental"),
        (["IMP"], "experimental"),
        (["IDA:UniProtKB"], "experimental"),     # UniProt format
        (["ida"], "experimental"),
        (["ISS"], "computational"),
        (["TAS:ProtInc"], "curatorial"),
        (["IEA"], "IEA"),
        (["IEA", "IDA"], "experimental"),         # strongest wins
        (["ECO:0000314"], "unknown"),             # an ECO id is not a GO evidence code
        ([], "unknown"),
        ([""], "unknown"),
    ])
    def test_classify(self, client, codes, expected):
        assert client._classify_evidence(codes) == expected

    def test_accepts_plain_string(self, client):
        assert client._classify_evidence("IDA") == "experimental"


class TestQuickGO:
    def test_request_uses_valid_parameters(self, client):
        """QuickGO answers HTTP 400 to pages above 200 and to unknown includeFields."""
        with patch(HTTP_GET) as mock_get:
            mock_get.side_effect = [
                response(200, {"results": [{"primaryAccession": "P28340"}]}),   # UniProt resolve
                response(200, {"numberOfHits": 1, "results": [qg("GO:0006260", "IDA")]}),
            ]
            data = client._query_quickgo("POLD1", "9606")

        quickgo_params = mock_get.call_args_list[1].kwargs["params"]
        assert quickgo_params["limit"] <= 200
        assert quickgo_params["aspect"] == "biological_process"
        assert quickgo_params["includeFields"] == "goName"
        assert data["bp_term_count"] == 1
        assert data["bp_terms"][0]["evidence_type"] == "experimental"

    def test_paginates_until_all_hits_are_read(self, client):
        page1 = [qg(f"GO:{i:07d}", "IDA") for i in range(1, 201)]
        page2 = [qg(f"GO:{i:07d}", "IEA") for i in range(201, 251)]
        with patch(HTTP_GET) as mock_get:
            mock_get.side_effect = [
                response(200, {"results": [{"primaryAccession": "P1"}]}),
                response(200, {"numberOfHits": 250, "results": page1}),
                response(200, {"numberOfHits": 250, "results": page2}),
            ]
            data = client._query_quickgo("BIG", "9606")

        assert data["bp_term_count"] == 250
        assert mock_get.call_count == 3

    def test_not_annotations_are_ignored(self, client):
        with patch(HTTP_GET) as mock_get:
            mock_get.side_effect = [
                response(200, {"results": [{"primaryAccession": "P1"}]}),
                response(200, {"numberOfHits": 2, "results": [
                    qg("GO:0000001", "IDA"),
                    qg("GO:0000002", "IDA", qualifier="NOT|involved_in"),
                ]}),
            ]
            data = client._query_quickgo("G", "9606")

        assert [t["go_id"] for t in data["bp_terms"]] == ["GO:0000001"]

    def test_unknown_gene_is_not_a_failure(self, client):
        with patch(HTTP_GET) as mock_get:
            mock_get.return_value = response(200, {"results": []})
            data = client._query_quickgo("NOSUCHGENE", "9606")

        assert data["found"] is False
        assert data["bp_terms"] == []

    def test_http_error_raises_lookup_failure(self, client):
        with patch(HTTP_GET) as mock_get:
            mock_get.side_effect = [
                response(200, {"results": [{"primaryAccession": "P1"}]}),
                response(400, text="bad request"),
            ]
            with pytest.raises(LookupFailure):
                client._query_quickgo("G", "9606")

    def test_network_error_raises_lookup_failure(self, client):
        with patch(HTTP_GET, side_effect=requests.ConnectionError("down")):
            with pytest.raises(LookupFailure):
                client._query_quickgo("G", "9606")


class TestUniProt:
    def test_bp_terms_are_extracted_with_normalised_evidence(self, client):
        entry = {"primaryAccession": "P28340", "uniProtKBCrossReferences": [
            {"database": "GO", "id": "GO:0006260", "properties": [
                {"key": "GoTerm", "value": "P:DNA replication"},
                {"key": "GoEvidenceType", "value": "IMP:UniProtKB"}]},
            {"database": "GO", "id": "GO:0005634", "properties": [
                {"key": "GoTerm", "value": "C:nucleus"},
                {"key": "GoEvidenceType", "value": "IDA:HPA"}]},
        ]}
        with patch(HTTP_GET, return_value=response(200, {"results": [entry]})):
            data = client._query_uniprot("POLD1", "9606")

        assert data["found"] is True
        assert len(data["bp_terms"]) == 1
        assert data["bp_terms"][0]["evidence_type"] == "experimental"

    def test_http_error_raises_lookup_failure(self, client):
        with patch(HTTP_GET, return_value=response(500, text="oops")):
            with pytest.raises(LookupFailure):
                client._query_uniprot("G", "9606")


class TestKegg:
    def test_only_exact_gene_symbol_match_is_used(self, client):
        find_text = "hsa:111\tPOLD1P, pseudogene; something\nhsa:5424\tPOLD1, CDC2; DNA polymerase delta 1\n"
        link_text = "hsa:5424\tpath:hsa03030\nhsa:5424\tpath:hsa03410\n"
        with patch(HTTP_GET, side_effect=[response(200, text=find_text), response(200, text=link_text)]):
            data = client._query_kegg("POLD1", "9606")

        assert data["kegg_gene_id"] == "hsa:5424"
        assert data["pathway_count"] == 2

    def test_no_exact_match_means_not_found(self, client):
        find_text = "hsa:111\tPOLD1P, pseudogene; something\n"
        with patch(HTTP_GET, return_value=response(200, text=find_text)):
            data = client._query_kegg("POLD1", "9606")

        assert data["found"] is False
        assert data["pathway_count"] == 0

    def test_unsupported_organism_is_not_a_failure(self, client):
        data = client._query_kegg("G", "99999")
        assert data["found"] is False


class TestCombine:
    def test_strongest_evidence_wins_across_sources(self, client):
        results = {
            "go_data": {"bp_terms": [{"go_id": "GO:1", "evidence_type": "IEA", "go_name": ""}]},
            "uniprot_data": {"bp_terms": [
                {"go_id": "GO:1", "evidence_type": "experimental", "go_name": "x"},
                {"go_id": "GO:2", "evidence_type": "computational", "go_name": "y"},
            ]},
        }
        terms = client._combine_bp_terms(results)
        by_id = {t["go_id"]: t for t in terms}

        assert len(terms) == 2
        assert by_id["GO:1"]["evidence_type"] == "experimental"

        results["combined_bp_terms"] = terms
        counts = client._combine_evidence(results)
        assert counts["experimental"] == 1
        assert counts["computational"] == 1


class TestQueryAll:
    def test_failed_source_is_reported_not_hidden(self, client):
        with patch.object(client, "_query_quickgo", side_effect=LookupFailure("HTTP 400")), \
             patch.object(client, "_query_uniprot", return_value={"bp_terms": [
                 {"go_id": "GO:1", "evidence_type": "experimental", "go_name": ""}]}), \
             patch.object(client, "_query_kegg", return_value={"pathway_count": 3}):
            result = client.query_all_databases_simultaneously("G", "9606")

        assert result["query_status"]["go"].startswith("failed")
        assert result["query_status"]["uniprot"] == "success"
        assert any("go lookup failed" in issue for issue in result["data_issues"])
        assert len(result["combined_bp_terms"]) == 1
        assert result["combined_evidence"]["experimental"] == 1
