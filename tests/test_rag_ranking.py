from k_sites.knockout_evidence import assess_gene
from k_sites.workflow.pipeline import gene_ranking_key
from k_sites.workflow.safety_recommender import get_safety_recommendation


def recommendation(severity, risk):
    return get_safety_recommendation(
        "G", 1.0,
        phenotype_prediction={"severity": severity, "risk_level": risk, "confidence_score": 0.1,
                              "predicted_phenotypes": [], "supporting_evidence": []},
        knockout_evidence=assess_gene(None, "9606", "G"),
    )


def test_unknown_rag_result_remains_unverified():
    result = recommendation("UNKNOWN", "UNKNOWN")

    assert result.evidence_basis == "none"
    assert result.safety_level.value == "CAUTION"


def test_meaningful_prediction_gets_no_ranking_advantage_over_none():
    unknown = recommendation("UNKNOWN", "UNKNOWN")
    predicted = recommendation("MILD", "LOW")
    assert predicted.evidence_basis == "predicted"

    def entry(result):
        return {"composite_score": 0.8,
                "safety_recommendation": {"safety_level": result.safety_level.value, "evidence_basis": result.evidence_basis}}

    assert gene_ranking_key(entry(unknown)) == gene_ranking_key(entry(predicted))


def test_a_meaningful_severity_is_usable_even_when_risk_is_unknown():
    assert recommendation("MILD", "UNKNOWN").evidence_basis == "predicted"


def test_actual_no_literature_result_remains_unverified():
    from unittest.mock import patch
    from k_sites.rag_system.literature_context import RAGPhenotypePredictor, RiskLevel

    predictor = RAGPhenotypePredictor()
    with patch.object(predictor.literature_miner, "search_pubmed", return_value=[]):
        prediction = predictor.predict_phenotype("G")

    assert prediction.risk_level == RiskLevel.UNKNOWN
    result = get_safety_recommendation(
        "G", 1.0, phenotype_prediction=prediction.__dict__, knockout_evidence=assess_gene(None, "9606", "G"))
    assert result.evidence_basis == "none"
