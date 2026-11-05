import math


UNVERIFIED_BASES = {"none", "predicted", "estimate"}
SUPPORTED_BASES = {"measured", "essentiality"}


def _scored(gene):
    composite = gene.get("composite_score")
    return (gene.get("data_status", "ok") == "ok" and not gene.get("lookup_failed")
            and isinstance(composite, (int, float)) and not isinstance(composite, bool) and math.isfinite(composite))


def select_potential_candidates(genes, limit=5):
    def recommendation(gene):
        return gene.get("safety_recommendation") or {}

    supported = next((gene for gene in genes if _scored(gene)
                      and recommendation(gene).get("safety_level") in {"SAFE", "CAUTION"}
                      and recommendation(gene).get("evidence_basis") in SUPPORTED_BASES), None)
    candidates = sorted(
        (gene for gene in genes if _scored(gene)
         and recommendation(gene).get("safety_level") == "CAUTION"
         and recommendation(gene).get("evidence_basis") in UNVERIFIED_BASES),
        key=lambda gene: (-gene["composite_score"], str(gene.get("symbol", ""))),
    )
    if supported is None or not candidates or candidates[0]["composite_score"] <= supported["composite_score"]:
        return []
    return candidates[:limit]
