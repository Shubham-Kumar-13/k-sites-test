import copy

from webapp.utils.potential_candidates import select_potential_candidates


def gene(symbol, basis, level, composite, **extra):
    return {
        "symbol": symbol,
        "composite_score": composite,
        "safety_recommendation": {"safety_level": level, "evidence_basis": basis},
        **extra,
    }


def test_top_five_unverified_candidates_must_beat_the_best_supported_candidate():
    genes = [
        gene("SUPPORTED", "measured", "CAUTION", 0.70),
        gene("A", "none", "CAUTION", 0.95),
        gene("B", "predicted", "CAUTION", 0.90),
        gene("C", "estimate", "CAUTION", 0.85),
        gene("D", "none", "CAUTION", 0.80),
        gene("E", "none", "CAUTION", 0.75),
        gene("F", "none", "CAUTION", 0.70),
        gene("DISTANT", "distant", "CAUTION", 0.99),
        gene("ORTHOLOG", "ortholog", "CAUTION", 0.99),
        gene("LETHAL", "measured", "AVOID", 1.0),
        gene("RISKY", "none", "HIGH_CONCERN", 1.0),
        gene("INSUFFICIENT", "none", "CAUTION", 1.0, data_status="insufficient_data"),
        gene("FAILED", "none", "CAUTION", 1.0, lookup_failed=True),
        gene("NO_COMPOSITE", "none", "CAUTION", None),
    ]
    original = copy.deepcopy(genes)

    selected = select_potential_candidates(genes)

    assert [g["symbol"] for g in selected] == ["A", "B", "C", "D", "E"]
    assert genes == original


def test_candidates_are_empty_when_the_supported_score_is_equal_or_higher():
    genes = [gene("SUPPORTED", "essentiality", "SAFE", 0.90), gene("A", "none", "CAUTION", 0.90)]

    assert select_potential_candidates(genes) == []


def test_no_viable_supported_candidate_produces_no_duplicate_list():
    genes = [gene("LETHAL", "measured", "AVOID", 1.0), gene("A", "none", "CAUTION", 0.95)]

    assert select_potential_candidates(genes) == []


def test_evidence_none_is_not_the_same_as_insufficient_data():
    genes = [
        gene("SUPPORTED", "measured", "CAUTION", 0.50),
        gene("SCORED_BUT_UNMEASURED", "none", "CAUTION", 0.90),
        gene("UNSCORABLE", "none", "CAUTION", 0.99, data_status="insufficient_data"),
    ]

    assert [g["symbol"] for g in select_potential_candidates(genes)] == ["SCORED_BUT_UNMEASURED"]
