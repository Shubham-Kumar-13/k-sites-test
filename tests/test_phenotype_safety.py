"""
Phenotype prediction must actually reach the safety recommendation, and the literature
parser must keep text that sits behind inline markup.
"""

import xml.etree.ElementTree as ET

import numpy as np
import pytest

from k_sites.rag_system.literature_context import (
    DiversityAwareVectorStore,
    LiteratureMiner,
    LiteratureRecord,
    PhenotypePrediction,
    PhenotypeSeverity,
    RiskLevel,
)
from k_sites.workflow.safety_recommender import _enum_text, get_safety_recommendation


def prediction(severity, risk, confidence, stage=None):
    return PhenotypePrediction(
        severity=severity, risk_level=risk, confidence_score=confidence,
        predicted_phenotypes=[], supporting_evidence=[], lethality_stage=stage,
    )


class TestPhenotypeReachesTheVerdict:
    """pipeline.py hands the recommender the dataclass __dict__, whose values are Enum members."""

    def test_lethal_high_confidence_gene_is_not_called_safe(self):
        p = prediction(PhenotypeSeverity.LETHAL, RiskLevel.CRITICAL, 0.9, "Embryonic")

        result = get_safety_recommendation("ESSENTIAL", 1.0, p.__dict__, {"conservation_score": 0.9}, 0.9)

        assert result.safety_level.value == "HIGH_CONCERN"
        assert result.primary_recommendation.value == "Conditional Knockout (Cre-Lox)"
        assert any("critical risk phenotype" in c for c in result.concerns)

    def test_lethal_and_very_pleiotropic_gene_is_avoided(self):
        p = prediction(PhenotypeSeverity.LETHAL, RiskLevel.CRITICAL, 0.9)

        result = get_safety_recommendation("ESSENTIAL", 9.0, p.__dict__, {"conservation_score": 0.9}, 0.9)

        assert result.safety_level.value == "AVOID"

    def test_justification_names_the_risk_cleanly(self):
        p = prediction(PhenotypeSeverity.LETHAL, RiskLevel.CRITICAL, 0.9)

        result = get_safety_recommendation("ESSENTIAL", 1.0, p.__dict__, None, 0.5)

        assert any("Predicted CRITICAL risk phenotype" in line for line in result.justification)
        assert not any("RiskLevel." in line for line in result.justification)

    def test_moderate_risk_is_not_a_concern(self):
        p = prediction(PhenotypeSeverity.MILD, RiskLevel.LOW, 0.9)

        result = get_safety_recommendation("TOLERANT", 1.0, p.__dict__, {"conservation_score": 0.4}, 0.5)

        assert result.safety_level.value == "SAFE"

    @pytest.mark.parametrize("value", [RiskLevel.CRITICAL, "CRITICAL", "RiskLevel.CRITICAL", {"value": "CRITICAL"}])
    def test_every_way_of_writing_the_risk_gives_the_same_answer(self, value):
        assert _enum_text(value) == "CRITICAL"

    def test_missing_prediction_is_empty(self):
        assert _enum_text(None) == ""


class TestPubMedParsing:
    def parse(self, xml):
        return LiteratureMiner()._parse_pubmed_article(ET.fromstring(xml))

    def test_title_and_abstract_keep_text_after_inline_markup(self):
        record = self.parse(
            "<PubmedArticle><MedlineCitation><PMID>1</PMID><Article>"
            "<ArticleTitle>Loss of <i>Pold1</i> causes embryonic lethality</ArticleTitle>"
            "<Abstract><AbstractText>Mice lacking <i>Pold1</i> die at E8.5; "
            "heterozygotes are viable.</AbstractText></Abstract>"
            "</Article></MedlineCitation></PubmedArticle>"
        )

        assert record.title == "Loss of Pold1 causes embryonic lethality"
        assert record.abstract == "Mice lacking Pold1 die at E8.5; heterozygotes are viable."

    def test_structured_abstract_sections_are_joined(self):
        record = self.parse(
            "<PubmedArticle><MedlineCitation><PMID>2</PMID><Article><ArticleTitle>T</ArticleTitle>"
            "<Abstract><AbstractText Label='A'>First.</AbstractText>"
            "<AbstractText Label='B'>Second <sub>x</sub> part.</AbstractText></Abstract>"
            "</Article></MedlineCitation></PubmedArticle>"
        )

        assert record.abstract == "First. Second x part."


class TestDiversitySelection:
    def test_mmr_uses_each_candidates_own_embedding(self):
        """Three documents: 0 and 1 are near-duplicates, 2 is different. After picking 0 the
        diverse choice must be document 2. (The old code compared against a misaligned row.)"""
        store = DiversityAwareVectorStore.__new__(DiversityAwareVectorStore)
        store.embeddings = np.array([[1.0, 0.0], [0.99, 0.141], [0.0, 1.0]], dtype="float32")
        store.embeddings /= np.linalg.norm(store.embeddings, axis=1, keepdims=True)
        docs = [LiteratureRecord(str(i), None, f"t{i}", "a", None, [], "", "", None, []) for i in range(3)]
        candidates = [(docs[0], 0.95, 0), (docs[1], 0.94, 1), (docs[2], 0.90, 2)]

        import k_sites.rag_system.literature_context as module
        original = module.RAG_AVAILABLE
        module.RAG_AVAILABLE = True
        try:
            picked = store._maximal_marginal_relevance(candidates, 2, 0.3)
        finally:
            module.RAG_AVAILABLE = original

        assert [doc.pmid for doc, _, _ in picked] == ["0", "2"]
