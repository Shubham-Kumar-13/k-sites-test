"""
KEGG gene names: a gene's main symbol must win over another gene that merely lists it as a synonym.
(LRIG1 lists "LIG1"; POLK lists "POLQ".)
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


builder = load_tool("build_kegg_data")

FIND_LIG1 = (
    "hsa:26018\tLRIG1, LIG-1, LIG1; leucine-rich repeats and immunoglobulin-like domains protein 1\n"
    "hsa:91298\tRLIG1, C12orf29; RNA ligase 1\n"
    "hsa:3978\tLIG1, IMD96, LIGI; DNA ligase 1\n"
)
LINK_LIG1 = "hsa:3978\tpath:hsa03410\nhsa:3978\tpath:hsa03420\nhsa:3978\tpath:hsa03430\n"

FIND_POLQ = (
    "hsa:10721\tPOLQ, PRO0327; DNA polymerase theta\n"
    "hsa:51426\tPOLK, DINB1, POLQ; DNA polymerase kappa\n"
)


def response(status, text):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


class TestLiveLookup:
    def lookup(self, symbol, find_text, link_text):
        from k_sites.data_retrieval.multi_database_client import MultiDatabaseClient
        client = MultiDatabaseClient()
        with patch("k_sites.data_retrieval.multi_database_client.http_get",
                   side_effect=[response(200, find_text), response(200, link_text)]), \
             patch("k_sites.data_retrieval.multi_database_client.time.sleep"):
            return client._query_kegg(symbol, "9606")

    def test_main_symbol_beats_a_gene_that_lists_it_as_a_synonym(self):
        data = self.lookup("LIG1", FIND_LIG1, LINK_LIG1)

        assert data["kegg_gene_id"] == "hsa:3978"
        assert data["pathway_count"] == 3

    def test_a_gene_without_pathways_is_not_given_a_synonym_owners_pathways(self):
        data = self.lookup("POLQ", FIND_POLQ, "")

        assert data["kegg_gene_id"] == "hsa:10721"
        assert data["pathway_count"] == 0

    def test_a_synonym_is_used_only_when_no_gene_has_it_as_main_symbol(self):
        data = self.lookup("CDC2", "hsa:5424\tPOLD1, CDC2; DNA polymerase delta\n", "hsa:5424\tpath:hsa03030\n")

        assert data["kegg_gene_id"] == "hsa:5424"


class TestDataBuilder:
    def build(self, listing, links):
        responses = [response(200, listing), response(200, links)]
        for r in responses:
            r.raise_for_status = lambda: None
        http = MagicMock()
        http.get.side_effect = responses
        return builder.build_organism(http, "hsa")

    LIST = (
        "hsa:26018\tCDS\t1:1..2\tLRIG1, LIG-1, LIG1; leucine-rich repeats protein\n"
        "hsa:3978\tCDS\t1:1..2\tLIG1, IMD96; DNA ligase 1\n"
        "hsa:10721\tCDS\t1:1..2\tPOLQ, PRO0327; DNA polymerase theta\n"
        "hsa:51426\tCDS\t1:1..2\tPOLK, DINB1, POLQ; DNA polymerase kappa\n"
        "hsa:1\tCDS\t1:1..2\tNOPATH; no pathways\n"
    )
    LINKS = "hsa:3978\tpath:hsa03410\nhsa:3978\tpath:hsa03420\nhsa:51426\tpath:hsa03460\n"

    def test_the_main_symbol_wins_and_genes_without_pathways_are_left_out(self):
        genes = self.build(self.LIST, self.LINKS)

        assert genes["LIG1"] == [2, "hsa:3978"]
        assert genes["POLK"] == [1, "hsa:51426"]
        assert "POLQ" not in genes          # POLQ itself has no pathways; POLK's synonym must not give it POLK's
        assert "NOPATH" not in genes
        assert "LRIG1" not in genes         # no pathways

    def test_names_are_the_part_before_the_semicolon(self):
        assert builder.gene_names("POLD1, CDC2, POLD; DNA polymerase delta") == ["POLD1", "CDC2", "POLD"]
        assert builder.gene_names("just a description") == ["JUST A DESCRIPTION"]


HTEXT = """+E\tKEGG Organism
#<h2>KEGG Organisms</h2>
!
AEukaryotes (3)
B
B  Animals (2)
C    Mammals (2)
D      Primates (1)
E        hsa  Homo sapiens (human)
D      Rodents (1)
E        mmu  Mus musculus (mouse)
B  Plants (1)
C    Eudicots (1)
D      Brassicales (1)
E        ath  Arabidopsis thaliana (thale cress)
AProkaryotes (1)
B
B  Bacteria (1)
C    Enterobacteria (1)
D      Enterobacteriaceae (1)
E        eco  Escherichia coli K-12 MG1655
"""


class TestOrganismList:
    def test_kingdoms_and_names(self):
        organisms = {o["kegg_code"]: o for o in builder.parse_organisms(HTEXT)}

        assert set(organisms) == {"hsa", "mmu", "ath", "eco"}
        assert organisms["hsa"]["name"] == "Homo sapiens" and organisms["hsa"]["common_name"] == "human"
        assert organisms["hsa"]["kingdom"] == "Animals" and organisms["hsa"]["taxid"] == "9606"
        assert organisms["ath"]["kingdom"] == "Plants"
        assert organisms["eco"]["kingdom"] == "Microbes" and organisms["eco"]["common_name"] == ""
        assert organisms["mmu"]["taxonomy"] == "Eukaryotes;Animals;Mammals;Rodents"

    def test_kingdom_rules_match_the_picker(self):
        assert builder.classify_organism("Prokaryotes;Archaea;Euryarchaeota") == "Microbes"
        assert builder.classify_organism("Eukaryotes;Fungi;Ascomycetes") == "Fungi"
        assert builder.classify_organism("Eukaryotes;Protists;Alveolates") == "Other Eukaryotes"
