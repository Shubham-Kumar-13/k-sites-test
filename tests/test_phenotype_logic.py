"""
The phenotype prediction must judge only what the papers say about losing THIS gene.
(The same cases are tested for the browser version in tests/js/rag.test.mjs.)
"""

import numpy as np
import pytest

from k_sites.rag_system.literature_context import (
    DEFAULT_RELEVANCE_THRESHOLD,
    DiversityAwareVectorStore,
    LiteratureRecord,
    PhenotypeExtractor,
    PhenotypeSeverity,
)

extractor = PhenotypeExtractor()


class TestEvidenceSentences:
    def test_only_sentences_naming_the_gene_and_its_loss_count(self):
        text = ("Xrcc1-deficient mice die early in embryogenesis. Brca1 loss is embryonic lethal. "
                "XRCC1 is expressed in the nucleus. PARP inhibitors are lethal to cells lacking XRCC1 under treatment.")

        sentences = extractor.gene_evidence_sentences(text, "XRCC1")

        assert sentences == ["Xrcc1-deficient mice die early in embryogenesis."]

    def test_protein_name_works_as_an_alias(self):
        text = "Mice deficient in DNA polymerase beta die neonatally."

        assert extractor.gene_evidence_sentences(text, "POLB") == []
        assert len(extractor.gene_evidence_sentences(text, "POLB", aliases=["DNA polymerase beta"])) == 1
        assert extractor.gene_evidence_sentences(text, "POLB", aliases=["Pol beta"]) == []   # too short to be safe

    def test_symbol_is_not_matched_inside_another_word(self):
        assert extractor.gene_evidence_sentences("The knockout of POLBX is lethal.", "POLB") == []
        assert len(extractor.gene_evidence_sentences("The POLB-/- knockout is lethal.", "POLB")) == 1

    def test_gene_sentences_without_the_loss_requirement(self):
        text = "A paralog may compensate for XRCC1."

        assert extractor.gene_evidence_sentences(text, "XRCC1") == []
        assert len(extractor.gene_evidence_sentences(text, "XRCC1", require_loss=False)) == 1


class TestSeverity:
    def classify(self, text):
        phenotypes = extractor.extract_phenotypes_from_text(text)
        return extractor.classify_severity(phenotypes, text)[0]

    def test_synthetic_lethality_is_not_lethality(self):
        text = "Parp1 loss is synthetic lethal with Brca1 deficiency; the non-lethal mutant is sublethal."

        assert not any("lethal" in p["term"] for p in extractor.extract_phenotypes_from_text(text))
        assert self.classify(text) == PhenotypeSeverity.UNKNOWN

    @pytest.mark.parametrize("text,expected", [
        ("embryonic lethal at E8.5", PhenotypeSeverity.LETHAL),
        ("mice die shortly after birth", PhenotypeSeverity.LETHAL),
        ("non-viable embryos", PhenotypeSeverity.LETHAL),
        ("a severe defect in growth", PhenotypeSeverity.SEVERE),
        ("a moderate reduction", PhenotypeSeverity.MODERATE),
        ("the knockout mice are viable and fertile", PhenotypeSeverity.MILD),
        ("embryos were not viable", PhenotypeSeverity.UNKNOWN),
        ("nothing to see here", PhenotypeSeverity.UNKNOWN),
    ])
    def test_highest_severity_with_evidence_wins(self, text, expected):
        assert self.classify(text) == expected

    def test_drug_inhibition_sentences_are_not_gene_loss(self):
        text = "PARP1 inhibition is lethal to BRCA-deficient knockout cells. PARP1 trapping causes cell lethality."

        assert extractor.gene_evidence_sentences(text, "PARP1") == []


def unit(*values):
    v = np.array(values, dtype="float32")
    return v / np.linalg.norm(v)


class FakeModel:
    """Embeddings from a small table; texts are looked up by their first word."""

    def __init__(self, table):
        self.table = table

    def encode(self, texts, show_progress_bar=False):
        return np.array([self.table[t.split(".")[0].split(" ")[0]] for t in texts], dtype="float32")


def store_with(table, docs):
    import k_sites.rag_system.literature_context as module
    module.RAG_AVAILABLE = True
    store = DiversityAwareVectorStore.__new__(DiversityAwareVectorStore)
    store.model = FakeModel(table)
    store.index = None
    store.documents = []
    store.embeddings = None
    import faiss
    store.add_documents([LiteratureRecord(p, None, t, "", None, [], "", "", None, []) for p, t in docs])
    return store


class TestRelevance:
    def test_relevance_is_cosine_similarity(self):
        table = {"lethal": unit(1, 0, 0), "viable": unit(0, 1, 0), "paralog": unit(0, 0, 1), "q": unit(1, 0.2, 0)}
        store = store_with(table, [("a", "lethal"), ("b", "viable"), ("c", "paralog")])

        hits = store.search("q", k=5, relevance_threshold=0.5, diversity_weight=0, context_aware=False)

        assert [doc.pmid for doc, _ in hits] == ["a"]
        assert hits[0][1] == pytest.approx(float(np.dot(unit(1, 0, 0), unit(1, 0.2, 0))), abs=1e-5)

    def test_default_cutoff_is_realistic_for_short_queries(self):
        # a cosine of 0.35 (typical for a good abstract) must pass; the old cut-off kept nothing
        assert DEFAULT_RELEVANCE_THRESHOLD == 0.30
        table = {"doc": unit(1, 0), "q": unit(0.35, np.sqrt(1 - 0.35 ** 2))}
        store = store_with(table, [("a", "doc")])

        hits = store.search("q", k=5, diversity_weight=0, context_aware=False)

        assert len(hits) == 1
        assert hits[0][1] == pytest.approx(0.35, abs=1e-4)
