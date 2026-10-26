"""
Safety Recommendation Module for K-Sites

This module generates safety recommendations for gene knockout/deletion
based on pleiotropy scores, phenotype predictions, cross-species conservation
and literature support.
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class SafetyLevel(Enum):
    """Safety level classification for gene knockout."""
    SAFE = "SAFE"                          # Standard KO acceptable
    CAUTION = "CAUTION"                    # Standard KO with validation
    MODERATE_CONCERN = "MODERATE_CONCERN"  # Heterozygous KO recommended
    HIGH_CONCERN = "HIGH_CONCERN"          # Conditional KO/CRISPRi preferred
    AVOID = "AVOID"                        # Alternative strategies required


# mildest first
_LEVEL_ORDER = [SafetyLevel.SAFE, SafetyLevel.CAUTION, SafetyLevel.MODERATE_CONCERN, SafetyLevel.HIGH_CONCERN, SafetyLevel.AVOID]


class RecommendationType(Enum):
    """Types of safety recommendations."""
    STANDARD_KO = "Standard Knockout"
    VALIDATED_KO = "Standard KO with Validation"
    HETEROZYGOUS_KO = "Heterozygous Knockout"
    CONDITIONAL_KO = "Conditional Knockout (Cre-Lox)"
    CRISPRI = "CRISPR Interference (CRISPRi)"
    CRISPRA = "CRISPR Activation (CRISPRa)"
    BASE_EDITING = "Base Editing (C->T or A->G)"
    PRIME_EDITING = "Prime Editing"
    TEMPORAL_CONTROL = "Temporal Control (Tet-ON/OFF)"
    SPATIAL_CONTROL = "Spatial Control (Tissue-specific)"
    ALTERNATIVE_MODEL = "Alternative Model System"
    MULTIPLE_STRATEGIES = "Multiple Complementary Strategies"


@dataclass
class SafetyRecommendation:
    """Comprehensive safety recommendation for a gene knockout."""
    gene_symbol: str
    safety_level: SafetyLevel
    primary_recommendation: RecommendationType
    alternative_recommendations: List[RecommendationType]
    justification: List[str]
    concerns: List[str]
    mitigation_strategies: List[str]
    experimental_considerations: List[str]
    confidence_score: float  # 0.0-1.0
    supporting_evidence: Dict[str, Any]
    # What the verdict rests on: "measured" (knockout / screen data for this gene), "ortholog" (measured in the mouse
    # ortholog), "predicted" (read from the literature by keywords) or "none" (annotations only)
    evidence_basis: str = "none"


def _enum_text(value) -> str:
    """
    The plain text of an enum-like value: "CRITICAL" for RiskLevel.CRITICAL, for the string
    "RiskLevel.CRITICAL" (what str() or a JSON round trip gives) and for {"value": "CRITICAL"}.
    """
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("value", "")
    if hasattr(value, "value"):
        value = value.value
    text = str(value)
    return text.rsplit(".", 1)[-1] if text.startswith(("RiskLevel.", "PhenotypeSeverity.")) else text


class SafetyRecommender:
    """
    Generates safety recommendations for gene knockout experiments.
    
    Considers:
    - Pleiotropy score (multi-functionality)
    - Phenotype severity (lethal vs mild)
    - Cross-species conservation
    - Literature support
    """
    
    def __init__(self):
        self.thresholds = {
            "pleiotropy": {
                "low": 3,
                "moderate": 5,
                "high": 8
            },
            "conservation": {
                "low": 0.3,
                "moderate": 0.6,
                "high": 0.8
            }
        }
    
    def generate_recommendation(
        self,
        gene_symbol: str,
        pleiotropy_score: float,
        phenotype_prediction: Optional[Dict] = None,
        cross_species_validation: Optional[Dict] = None,
        literature_support: Optional[float] = None,
        knockout_evidence: Optional[Dict] = None
    ) -> SafetyRecommendation:
        """
        Generate comprehensive safety recommendation for a gene.

        Args:
            gene_symbol: Target gene symbol
            pleiotropy_score: Calculated pleiotropy score (0-10)
            phenotype_prediction: Phenotype prediction dict with severity, risk_level, etc.
            cross_species_validation: Cross-species validation data
            literature_support: Literature support score (0-1)
            knockout_evidence: What was measured about losing this gene (``assess_gene`` result). When it has a
                measured result for the knockout context, the verdict follows it; otherwise the verdict rests on the
                annotations and predictions and is never better than CAUTION.

        Returns:
            SafetyRecommendation with detailed guidance
        """
        concerns = []
        mitigation_strategies = []
        experimental_considerations = []
        justification = []

        # Extract phenotype information
        phenotype_severity = None
        phenotype_risk = None
        phenotype_confidence = 0.0
        lethality_stage = None
        compensatory_mechanisms = []

        if phenotype_prediction:
            phenotype_severity = _enum_text(phenotype_prediction.get("severity"))
            phenotype_risk = _enum_text(phenotype_prediction.get("risk_level"))
            phenotype_confidence = phenotype_prediction.get("confidence_score", 0.0)
            lethality_stage = phenotype_prediction.get("lethality_stage")
            compensatory_mechanisms = phenotype_prediction.get("compensatory_mechanisms", [])

        # Analyze conservation
        conservation_score = cross_species_validation.get("conservation_score", 0.0) if cross_species_validation else 0.0

        measured = self._evidence_verdict(knockout_evidence, pleiotropy_score) if knockout_evidence else None
        estimated = bool(measured) and measured["basis"] == "estimate"      # a model's estimate, not a measurement
        if measured:
            safety_level, primary_rec, alternative_recs = measured["level"], measured["primary"], measured["alternatives"]
            evidence_basis = measured["basis"]
        else:
            # Determine safety level and recommendations from annotations and predictions
            safety_level, primary_rec, alternative_recs = self._determine_safety_level(
                pleiotropy_score,
                phenotype_risk,
                conservation_score,
                phenotype_confidence
            )
            evidence_basis = "predicted" if phenotype_prediction else "none"

        # A distant relative (zebrafish, fly, worm, ...) only has its mouse ortholog's knockout as a hint. A hint of
        # lethality raises the level to MODERATE_CONCERN; nothing in it ever makes a gene safe.
        distant = None
        if knockout_evidence and not measured:
            candidate = knockout_evidence["organism"]
            if candidate.get("distant") and candidate["call"] != "UNKNOWN":
                distant = candidate
                evidence_basis = "distant"
        distant_risk = bool(distant and (distant["call"] in ("LETHAL", "SUBVIABLE") or distant["counts"]["lethal"] > 0))
        if distant_risk and _LEVEL_ORDER.index(safety_level) < _LEVEL_ORDER.index(SafetyLevel.MODERATE_CONCERN):
            safety_level = SafetyLevel.MODERATE_CONCERN
            primary_rec = RecommendationType.HETEROZYGOUS_KO
            alternative_recs = [RecommendationType.CONDITIONAL_KO, RecommendationType.VALIDATED_KO]

        # Without a measurement nothing shows that the knockout is safe: the verdict is never better than CAUTION,
        # and every such gene says that its lethality has not been measured
        unverified = bool(knockout_evidence) and (not measured or estimated)
        if unverified and safety_level == SafetyLevel.SAFE:
            safety_level = SafetyLevel.CAUTION
            primary_rec = RecommendationType.VALIDATED_KO
            alternative_recs = [RecommendationType.STANDARD_KO]

        # Build justification
        justification = self._build_justification(
            pleiotropy_score,
            phenotype_severity,
            phenotype_risk,
            conservation_score,
            literature_support,
            phenotype_confidence
        )
        if measured:
            # the measurement replaces the prediction; keep the lines about pleiotropy, conservation and literature
            justification = measured["justification"] + [
                line for line in justification if not line.startswith(("Predicted ", "Low confidence phenotype"))]
        else:
            if distant:
                justification.insert(0, distant["text"])
            if unverified:
                justification.insert(0, "No measured knockout data for this gene, so the safety of a knockout is unverified")

        # Build concerns list
        concerns = self._identify_concerns(
            pleiotropy_score,
            phenotype_severity,
            phenotype_risk,
            conservation_score,
            compensatory_mechanisms
        )

        # Build mitigation strategies
        mitigation_strategies = self._suggest_mitigation_strategies(
            safety_level,
            primary_rec,
            phenotype_risk,
            compensatory_mechanisms
        )

        # Build experimental considerations
        experimental_considerations = self._suggest_experimental_considerations(
            phenotype_severity,
            lethality_stage,
            primary_rec
        )
        if unverified:
            concerns = [c for c in concerns if c != "No major concerns identified"]
            concerns.insert(0, "Lethality has not been measured: check MGI, IMPC or DepMap before committing to a knockout")
        if distant_risk:
            concerns = [c for c in concerns if c != "No major concerns identified"]
            concerns.insert(0, "The mouse ortholog is needed for survival and essential genes are usually conserved, "
                               "so this gene may be essential here too, but that has not been tested")

        if measured:
            concerns = measured["concerns"] + [
                c for c in concerns if c not in ("No major concerns identified",)
                and not c.startswith(("Predicted ", "Potential lethality"))]
            mitigation_strategies = measured["mitigation"] + [
                s for s in mitigation_strategies if s != "Standard validation sufficient"]
            experimental_considerations = measured["considerations"] + experimental_considerations

        # Calculate confidence score
        confidence_score = (measured["confidence"] if measured else self._calculate_confidence(
            phenotype_confidence,
            literature_support,
            bool(cross_species_validation)
        ))

        # Compile supporting evidence
        supporting_evidence = {
            "pleiotropy_score": pleiotropy_score,
            "phenotype_severity": phenotype_severity,
            "phenotype_risk": phenotype_risk,
            "conservation_score": conservation_score,
            "compensatory_mechanisms": compensatory_mechanisms,
            "literature_support": literature_support
        }

        return SafetyRecommendation(
            gene_symbol=gene_symbol,
            safety_level=safety_level,
            primary_recommendation=primary_rec,
            alternative_recommendations=alternative_recs,
            justification=justification,
            concerns=concerns,
            mitigation_strategies=mitigation_strategies,
            experimental_considerations=experimental_considerations,
            confidence_score=confidence_score,
            supporting_evidence=supporting_evidence,
            evidence_basis=evidence_basis
        )

    # ------------------------------------------------------------------------------------------------
    # verdicts from measured knockout evidence
    # ------------------------------------------------------------------------------------------------

    def _evidence_verdict(self, evidence: Dict, pleiotropy_score: float) -> Optional[Dict[str, Any]]:
        """
        The verdict implied by what was measured, or None when nothing measured applies to the knockout context.

        Context 'cells' (cultured cells, the default for human): DepMap decides. Context 'organism' (animal, plant,
        yeast): the viability of the knockout organism decides. Where the context's own measurement is missing but
        the other one exists, it is used as a weaker indicator.
        """
        organism, cells = evidence["organism"], evidence["cells"]
        context = evidence.get("context", "organism")
        # a distant relative's mouse ortholog is a hint, never a measurement
        usable = organism["call"] != "UNKNOWN" and not organism.get("distant")
        if context == "cells":
            if cells["call"] != "UNKNOWN":
                return self._cells_verdict(evidence, pleiotropy_score)
            if usable:
                return self._cells_verdict_from_organism(evidence, pleiotropy_score)
            return None
        if usable:
            return self._organism_verdict(evidence, pleiotropy_score)
        if cells["call"] == "ESSENTIAL":
            return self._organism_verdict_from_cells(evidence)
        if evidence.get("estimate"):
            return self._estimate_verdict(evidence, pleiotropy_score)
        return None

    def _estimate_verdict(self, evidence: Dict, pleiotropy_score: float) -> Dict[str, Any]:
        """Nothing was measured, but the estimate of lethality is known: the verdict follows it and is never better
        than CAUTION."""
        estimate = evidence["estimate"]
        band = estimate["band"]
        justification = [estimate["text"]]
        concerns, mitigation = [], []
        if band == "likely":
            level, primary = SafetyLevel.HIGH_CONCERN, RecommendationType.CONDITIONAL_KO
            alternatives = [RecommendationType.CRISPRI, RecommendationType.HETEROZYGOUS_KO]
            concerns.append("A knockout is estimated to be lethal (not measured): plan for a conditional or inducible approach")
            mitigation += ["Use a conditional (Cre-lox) or inducible allele, or knock the gene down (CRISPRi, RNAi) instead of knocking it out",
                           "Look the gene up in MGI and IMPC: a knockout line may exist that is not in the data yet"]
            tissue = self._tissue_mitigation(evidence)
            if tissue:
                mitigation.append(tissue)
        elif band == "possible":
            level, primary = SafetyLevel.MODERATE_CONCERN, RecommendationType.HETEROZYGOUS_KO
            alternatives = [RecommendationType.CONDITIONAL_KO, RecommendationType.VALIDATED_KO]
            concerns.append("A knockout may be lethal (estimated, not measured): test a heterozygous or conditional allele first")
            mitigation.append("Start with a heterozygous or conditional allele and check how the homozygotes fare")
        else:
            level, primary, alternatives = SafetyLevel.CAUTION, RecommendationType.VALIDATED_KO, [RecommendationType.STANDARD_KO]
            concerns.append("No knockout has been measured; the estimate says lethality is unlikely, but check before committing")
        if pleiotropy_score > 5:
            concerns.append("The gene has many annotated roles, so expect broad phenotypes")
        paralog = self._paralog_concern(evidence)
        if paralog:
            concerns.append(paralog)
        justification += self._extra_findings(evidence)
        return {"level": level, "primary": primary, "alternatives": alternatives, "basis": "estimate",
                "justification": justification, "concerns": concerns, "mitigation": mitigation, "considerations": [],
                "confidence": {"likely": 0.6, "possible": 0.4, "unlikely": 0.5}[band]}

    @staticmethod
    def _extra_findings(evidence: Dict) -> List[str]:
        """Context lines that never change the verdict: gene constraint, and the mouse result for cell work."""
        lines = []
        constraint = evidence.get("constraint")
        if constraint and constraint["label"] == "highly constrained":
            lines.append(f"Highly constrained in people (gnomAD LOEUF {constraint['loeuf']:g}): loss of one copy is rarely tolerated")
        return lines

    @staticmethod
    def _paralog_concern(evidence: Dict) -> Optional[str]:
        """A close paralog may take over the work of the knocked-out gene and hide its phenotype."""
        paralogs = evidence.get("paralogs")
        if not paralogs or not paralogs["close"]:
            return None
        names = ", ".join(paralogs["close"])
        if len(paralogs["close"]) == 1:
            return f"The close paralog {names} may take over its work and hide the phenotype: consider a double knockout"
        return f"The close paralogs {names} may take over its work and hide the phenotype: consider a double knockout"

    @staticmethod
    def _tissue_mitigation(evidence: Dict) -> Optional[str]:
        """A gene needed for survival but expressed mainly in a few tissues can be removed in those tissues only."""
        expression = evidence.get("expression")
        if not expression or expression["label"] not in ("tissue-specific", "tissue-enriched") or not expression["top_tissues"]:
            return None
        where = ", ".join(expression["top_tissues"][:2])
        return f"Expression is concentrated in {where}: a tissue-specific conditional knockout may avoid the lethal effect"

    @staticmethod
    def _organism_basis(organism: Dict) -> str:
        return "measured" if organism["basis"] == "direct" else "ortholog"

    @staticmethod
    def _organism_confidence(organism: Dict) -> float:
        counts = organism["counts"]
        total = sum(counts.values())
        if organism["basis"] == "direct":
            confidence = 0.7 if organism["mixed"] else (0.9 if total >= 2 else 0.8)
        else:
            confidence = 0.55 if organism["ortholog"]["relation"] != "1:1" else (0.75 if total >= 2 else 0.7)
            if organism["mixed"]:
                confidence -= 0.1
        return round(confidence, 2)

    def _organism_verdict(self, evidence: Dict, pleiotropy_score: float) -> Dict[str, Any]:
        organism = evidence["organism"]
        call, mixed, counts = organism["call"], organism["mixed"], organism["counts"]
        yeast = evidence["taxid"] in ("559292", "4932")
        ortholog_note = organism["basis"] == "ortholog" and organism["ortholog"]["relation"] != "1:1"
        stage = organism["stage_text"] if organism["stage"] not in (None, "U") else None
        justification = [organism["text"]]
        concerns, mitigation, considerations = [], [], []

        if call == "LETHAL":
            level = SafetyLevel.AVOID
            if ortholog_note:
                level = SafetyLevel.HIGH_CONCERN
                concerns.append("The mouse ortholog is not a one-to-one match, so confirm the lethality in your organism")
            if organism.get("rnai_only"):
                level = SafetyLevel.HIGH_CONCERN
                concerns.append("Only RNAi knockdown was lethal; no mutant allele has been reported lethal, so confirm with a mutant")
            primary = RecommendationType.CONDITIONAL_KO
            alternatives = [RecommendationType.CRISPRI, RecommendationType.TEMPORAL_CONTROL, RecommendationType.ALTERNATIVE_MODEL]
            if yeast:
                concerns.insert(0, "The deletion is inviable: a haploid knockout strain cannot be kept")
                mitigation += ["Use a conditional allele (degron tag or repressible promoter) or a heterozygous diploid",
                               "Study a temperature-sensitive allele instead of a deletion"]
            else:
                concerns.insert(0, "Homozygous knockouts do not survive, so a complete knockout line cannot be kept")
                mitigation += ["Use a conditional (Cre-lox) or inducible allele so the gene is lost only after the critical stage",
                               "Knock the gene down (CRISPRi, RNAi) to keep some function instead of knocking it out",
                               "Maintain the line from heterozygotes"]
            if stage:
                considerations.append(f"Death occurs {stage}: collect samples before that stage")
            tissue = self._tissue_mitigation(evidence)
            if tissue:
                mitigation.append(tissue)
        elif call == "SUBVIABLE":
            level = SafetyLevel.HIGH_CONCERN
            primary = RecommendationType.CONDITIONAL_KO
            alternatives = [RecommendationType.HETEROZYGOUS_KO, RecommendationType.CRISPRI]
            concerns.append("Fewer homozygous knockouts survive than expected, so experiments need more breeding")
            mitigation.append("Use a conditional allele, or plan larger crosses to obtain enough homozygotes")
            tissue = self._tissue_mitigation(evidence)
            if tissue:
                mitigation.append(tissue)
        else:
            lethal_n = counts["lethal"]
            if mixed and lethal_n:
                level = SafetyLevel.HIGH_CONCERN
                primary = RecommendationType.CONDITIONAL_KO
                alternatives = [RecommendationType.VALIDATED_KO, RecommendationType.CRISPRI]
                concerns.append("Some knockout lines are lethal, so lethality depends on the strain or the allele")
                mitigation.append("Check which strain and allele were lethal and use a conditional allele if yours is similar")
            elif mixed:
                level = SafetyLevel.CAUTION
                primary = RecommendationType.VALIDATED_KO
                alternatives = [RecommendationType.CONDITIONAL_KO]
                concerns.append("Some knockout lines survive in reduced numbers: the outcome depends on the strain or the allele")
            else:
                level = SafetyLevel.SAFE
                primary = RecommendationType.STANDARD_KO
                alternatives = []
            if organism["reduced_lifespan"]:
                level = max(level, SafetyLevel.CAUTION, key=_LEVEL_ORDER.index)
                if primary == RecommendationType.STANDARD_KO:
                    primary, alternatives = RecommendationType.VALIDATED_KO, [RecommendationType.CONDITIONAL_KO]
                concerns.append("A shortened lifespan was reported for the viable knockouts")
                considerations.append("Plan ageing cohorts and watch the animals for early death")
            if organism["infertile"]:
                level = max(level, SafetyLevel.CAUTION, key=_LEVEL_ORDER.index)
                if primary == RecommendationType.STANDARD_KO:
                    primary, alternatives = RecommendationType.VALIDATED_KO, [RecommendationType.CONDITIONAL_KO]
                concerns.append("Infertility was reported, so the knockout line must be kept from heterozygotes")
            if level == SafetyLevel.SAFE and pleiotropy_score > 5:
                level, primary, alternatives = SafetyLevel.CAUTION, RecommendationType.VALIDATED_KO, [RecommendationType.STANDARD_KO]
                concerns.append("The knockout is viable, but the gene has many annotated roles, so expect broad phenotypes")
            paralog = self._paralog_concern(evidence)
            if paralog:
                concerns.append(paralog)
        justification += self._extra_findings(evidence)
        return {"level": level, "primary": primary, "alternatives": alternatives, "basis": self._organism_basis(organism),
                "justification": justification, "concerns": concerns, "mitigation": mitigation,
                "considerations": considerations, "confidence": self._organism_confidence(organism)}

    def _organism_verdict_from_cells(self, evidence: Dict) -> Dict[str, Any]:
        cells = evidence["cells"]
        return {"level": SafetyLevel.HIGH_CONCERN, "primary": RecommendationType.CONDITIONAL_KO,
                "alternatives": [RecommendationType.CRISPRI, RecommendationType.TEMPORAL_CONTROL], "basis": "measured",
                "justification": [cells["text"]],
                "concerns": ["The gene is essential in human cells, so a whole-organism knockout is likely lethal"],
                "mitigation": ["Use a conditional or inducible allele instead of a complete knockout"],
                "considerations": [], "confidence": 0.6}

    def _cells_verdict(self, evidence: Dict, pleiotropy_score: float) -> Dict[str, Any]:
        cells, organism = evidence["cells"], evidence["organism"]
        call, percent = cells["call"], cells["percent"]
        justification = [cells["text"]]
        concerns, mitigation, considerations = [], [], []
        if call == "ESSENTIAL":
            level = SafetyLevel.AVOID
            primary = RecommendationType.CRISPRI
            alternatives = [RecommendationType.TEMPORAL_CONTROL, RecommendationType.CONDITIONAL_KO, RecommendationType.ALTERNATIVE_MODEL]
            concerns.append("A complete knockout is expected to kill the cells")
            mitigation += ["Use an inducible knockout, a degron tag or CRISPRi so the cells survive until the gene is switched off",
                           "Check your own cell line in DepMap before starting"]
            considerations.append("Include a rescue construct to show that the phenotype comes from this gene")
        elif call == "SELECTIVE":
            if percent >= 25:
                level, primary, alternatives = SafetyLevel.MODERATE_CONCERN, RecommendationType.CRISPRI, [RecommendationType.VALIDATED_KO]
            else:
                level, primary, alternatives = SafetyLevel.CAUTION, RecommendationType.VALIDATED_KO, [RecommendationType.CRISPRI]
            concerns.append("The gene is essential in some cell types: confirm that yours is not one of them")
            mitigation.append("Look up your cell line in DepMap and keep a knockdown as a fallback")
        else:
            level, primary, alternatives = SafetyLevel.SAFE, RecommendationType.STANDARD_KO, []
            if pleiotropy_score > 5:
                level, primary, alternatives = SafetyLevel.CAUTION, RecommendationType.VALIDATED_KO, [RecommendationType.STANDARD_KO]
                concerns.append("The gene is not essential in cell lines, but it has many annotated roles, so expect broad phenotypes")
        if call != "ESSENTIAL":
            paralog = self._paralog_concern(evidence)
            if paralog:
                concerns.append(paralog)
        if organism["call"] in ("LETHAL", "SUBVIABLE"):
            justification.append(organism["text"])
            concerns.append("The knockout is not viable in mice: cultured cells can tolerate it, but a whole-animal knockout cannot be made")
        justification += self._extra_findings(evidence)
        confidence = 0.9 if (call == "ESSENTIAL" and cells["common_essential"]) or (call == "NON_ESSENTIAL" and percent < 5) else 0.75
        return {"level": level, "primary": primary, "alternatives": alternatives, "basis": "measured",
                "justification": justification, "concerns": concerns, "mitigation": mitigation,
                "considerations": considerations, "confidence": confidence}

    def _cells_verdict_from_organism(self, evidence: Dict, pleiotropy_score: float) -> Dict[str, Any]:
        """Cell work, but no cell-line screen result: the knockout of the whole organism is the only measurement."""
        organism = evidence["organism"]
        justification = [organism["text"], "No cell-line screen result for this gene, so essentiality in cells is unknown"]
        concerns, mitigation = [], []
        if organism["call"] in ("LETHAL", "SUBVIABLE") or organism["mixed"]:
            level, primary, alternatives = SafetyLevel.CAUTION, RecommendationType.VALIDATED_KO, [RecommendationType.CRISPRI]
            concerns.append("The gene is needed for the survival of the organism, so it may also be needed in cells")
            mitigation.append("Check the gene in DepMap or test a knockdown first")
        else:
            level, primary, alternatives = SafetyLevel.SAFE, RecommendationType.STANDARD_KO, []
            if pleiotropy_score > 5:
                level, primary, alternatives = SafetyLevel.CAUTION, RecommendationType.VALIDATED_KO, [RecommendationType.STANDARD_KO]
                concerns.append("The knockout organism is viable, but the gene has many annotated roles, so expect broad phenotypes")
            paralog = self._paralog_concern(evidence)
            if paralog:
                concerns.append(paralog)
        justification += self._extra_findings(evidence)
        return {"level": level, "primary": primary, "alternatives": alternatives, "basis": self._organism_basis(organism),
                "justification": justification, "concerns": concerns, "mitigation": mitigation,
                "considerations": [], "confidence": round(self._organism_confidence(organism) - 0.1, 2)}
    
    def _determine_safety_level(
        self,
        pleiotropy_score: float,
        phenotype_risk: Optional[str],
        conservation_score: float,
        phenotype_confidence: float
    ) -> tuple:
        """Determine safety level and primary/alternative recommendations."""
        
        # High concern conditions
        if phenotype_risk in ["CRITICAL", "HIGH"] and phenotype_confidence > 0.5:
            if pleiotropy_score > 8:
                return (
                    SafetyLevel.AVOID,
                    RecommendationType.MULTIPLE_STRATEGIES,
                    [RecommendationType.CRISPRI, RecommendationType.CONDITIONAL_KO, RecommendationType.ALTERNATIVE_MODEL]
                )
            else:
                return (
                    SafetyLevel.HIGH_CONCERN,
                    RecommendationType.CONDITIONAL_KO,
                    [RecommendationType.CRISPRI, RecommendationType.HETEROZYGOUS_KO, RecommendationType.TEMPORAL_CONTROL]
                )
        
        # Phenotype-based decisions
        if phenotype_risk == "CRITICAL":
            return (
                SafetyLevel.HIGH_CONCERN,
                RecommendationType.CONDITIONAL_KO,
                [RecommendationType.CRISPRI, RecommendationType.TEMPORAL_CONTROL]
            )
        
        if phenotype_risk == "HIGH":
            if pleiotropy_score > 5:
                return (
                    SafetyLevel.HIGH_CONCERN,
                    RecommendationType.CRISPRI,
                    [RecommendationType.CONDITIONAL_KO, RecommendationType.HETEROZYGOUS_KO]
                )
            else:
                return (
                    SafetyLevel.MODERATE_CONCERN,
                    RecommendationType.HETEROZYGOUS_KO,
                    [RecommendationType.VALIDATED_KO, RecommendationType.CRISPRI]
                )
        
        # Pleiotropy-based decisions
        if pleiotropy_score > 8:
            return (
                SafetyLevel.HIGH_CONCERN,
                RecommendationType.CRISPRI,
                [RecommendationType.HETEROZYGOUS_KO, RecommendationType.CONDITIONAL_KO]
            )
        
        if pleiotropy_score > 5:
            if conservation_score > 0.8:
                return (
                    SafetyLevel.MODERATE_CONCERN,
                    RecommendationType.HETEROZYGOUS_KO,
                    [RecommendationType.VALIDATED_KO, RecommendationType.CONDITIONAL_KO]
                )
            else:
                return (
                    SafetyLevel.CAUTION,
                    RecommendationType.VALIDATED_KO,
                    [RecommendationType.STANDARD_KO]
                )
        
        if pleiotropy_score > 3:
            return (
                SafetyLevel.CAUTION,
                RecommendationType.STANDARD_KO,
                [RecommendationType.VALIDATED_KO]
            )
        
        # Low concern - standard KO acceptable
        return (
            SafetyLevel.SAFE,
            RecommendationType.STANDARD_KO,
            []
        )
    
    def _build_justification(
        self,
        pleiotropy_score: float,
        phenotype_severity: Optional[str],
        phenotype_risk: Optional[str],
        conservation_score: float,
        literature_support: Optional[float],
        phenotype_confidence: float
    ) -> List[str]:
        """Build human-readable justification for recommendation."""
        justification = []
        
        # Pleiotropy justification
        if pleiotropy_score > 8:
            justification.append(f"Very high pleiotropy score ({pleiotropy_score:.1f}) indicates multiple biological functions")
        elif pleiotropy_score > 5:
            justification.append(f"High pleiotropy score ({pleiotropy_score:.1f}) suggests multiple roles")
        elif pleiotropy_score > 3:
            justification.append(f"Moderate pleiotropy score ({pleiotropy_score:.1f})")
        else:
            justification.append(f"Low pleiotropy score ({pleiotropy_score:.1f}) indicates specific function")
        
        # Phenotype justification
        if phenotype_risk:
            if phenotype_confidence > 0.5:
                justification.append(f"Predicted {phenotype_risk} risk phenotype (confidence: {phenotype_confidence:.2f})")
            else:
                justification.append(f"Low confidence phenotype prediction ({phenotype_confidence:.2f})")
        
        # Conservation justification
        if conservation_score > 0.8:
            justification.append(f"Highly conserved across species ({conservation_score:.2f})")
        elif conservation_score < 0.3:
            justification.append(f"Low conservation ({conservation_score:.2f}) - may indicate species-specific function")
        
        # Literature justification
        if literature_support and literature_support > 0.8:
            justification.append("Strong literature support for this gene")
        elif literature_support and literature_support < 0.3:
            justification.append("Limited literature available - consider additional validation")
        
        return justification
    
    def _identify_concerns(
        self,
        pleiotropy_score: float,
        phenotype_severity: Optional[str],
        phenotype_risk: Optional[str],
        conservation_score: float,
        compensatory_mechanisms: List[str]
    ) -> List[str]:
        """Identify specific concerns for the experiment."""
        concerns = []
        
        if phenotype_risk in ["CRITICAL", "HIGH"]:
            concerns.append(f"Predicted {phenotype_risk.lower()} risk phenotype - may cause lethality or severe defects")
        
        if phenotype_severity == "LETHAL":
            concerns.append("Potential lethality requires careful experimental design")
        
        if pleiotropy_score > 8:
            concerns.append("High pleiotropy may confound phenotype interpretation")
        
        if conservation_score > 0.8:
            concerns.append("Highly conserved gene - may be essential for basic cellular functions")
        
        if compensatory_mechanisms:
            concerns.append(f"Compensatory mechanisms detected ({len(compensatory_mechanisms)}) - phenotypes may be masked")
        
        return concerns if concerns else ["No major concerns identified"]
    
    def _suggest_mitigation_strategies(
        self,
        safety_level: SafetyLevel,
        primary_rec: RecommendationType,
        phenotype_risk: Optional[str],
        compensatory_mechanisms: List[str]
    ) -> List[str]:
        """Suggest strategies to mitigate risks."""
        strategies = []
        
        # Phenotype mitigation
        if phenotype_risk in ["CRITICAL", "HIGH"]:
            strategies.append("Start with conditional or inducible knockdown")
            strategies.append("Monitor phenotype progression carefully")
            strategies.append("Prepare rescue constructs for complementation studies")
        
        # Pleiotropy mitigation
        if primary_rec in [RecommendationType.CRISPRI, RecommendationType.HETEROZYGOUS_KO]:
            strategies.append("Use partial knockdown to study dose-dependent effects")
            strategies.append("Compare results with RNAi data if available")
        
        # Compensatory mechanism mitigation
        if compensatory_mechanisms:
            strategies.append("Consider double-knockout with paralog genes")
            strategies.append("Use time-course experiments to detect delayed compensation")
        
        # General strategies
        if safety_level in [SafetyLevel.HIGH_CONCERN, SafetyLevel.AVOID]:
            strategies.append("Phenotype Analysis of Stems cells & CRISPR-engineered (PASC) approach")
            strategies.append("Phenotype Suppression Screening to identify genetic interactors")
        
        return strategies if strategies else ["Standard validation sufficient"]
    
    def _suggest_experimental_considerations(
        self,
        phenotype_severity: Optional[str],
        lethality_stage: Optional[str],
        primary_rec: RecommendationType
    ) -> List[str]:
        """Suggest experimental design considerations."""
        considerations = []
        
        # Lethality stage considerations
        if lethality_stage:
            considerations.append(f"Plan for {lethality_stage.lower()} lethality - harvest samples before expected lethality")
        
        if phenotype_severity == "LETHAL":
            considerations.append("Use heterozygous crosses to maintain line")
            considerations.append("Consider inducible systems for temporal control")
        
        # Method-specific considerations
        if primary_rec == RecommendationType.CRISPRI:
            considerations.append("Optimize dCas9-KRAB expression levels")
            considerations.append("Verify knockdown efficiency at mRNA and protein levels")
        
        if primary_rec == RecommendationType.CONDITIONAL_KO:
            considerations.append("Verify Cre recombinase efficiency")
            considerations.append("Include littermate controls")
        
        if primary_rec == RecommendationType.HETEROZYGOUS_KO:
            considerations.append("Genotype all offspring carefully")
            considerations.append("Compare heterozygous vs homozygous phenotypes")
        
        # General considerations
        considerations.append("Include appropriate controls (wild-type and non-targeting controls)")
        considerations.append("Plan for phenotypic scoring at multiple developmental stages")
        
        return considerations
    
    def _calculate_confidence(
        self,
        phenotype_confidence: float,
        literature_support: Optional[float],
        has_validation: bool
    ) -> float:
        """Calculate overall confidence in the recommendation."""
        scores = [phenotype_confidence]
        
        if literature_support:
            scores.append(literature_support)
        
        if has_validation:
            scores.append(0.7)  # Cross-species validation adds confidence
        
        # Average with weighting
        return sum(scores) / len(scores) if scores else 0.5
    
    def generate_batch_recommendations(
        self,
        genes_data: List[Dict[str, Any]]
    ) -> List[SafetyRecommendation]:
        """
        Generate recommendations for multiple genes.
        
        Args:
            genes_data: List of gene data dictionaries
            
        Returns:
            List of SafetyRecommendation objects
        """
        recommendations = []
        
        for gene_data in genes_data:
            try:
                rec = self.generate_recommendation(
                    gene_symbol=gene_data.get("symbol", "unknown"),
                    pleiotropy_score=gene_data.get("pleiotropy_score", 10),
                    phenotype_prediction=gene_data.get("phenotype_prediction"),
                    cross_species_validation=gene_data.get("cross_species_validation"),
                    literature_support=gene_data.get("literature_support"),
                    knockout_evidence=gene_data.get("knockout_evidence")
                )
                recommendations.append(rec)
            except Exception as e:
                logger.error(f"Failed to generate recommendation for {gene_data.get('symbol', 'unknown')}: {e}")
                continue
        
        return recommendations
    
    def format_recommendation_text(self, recommendation: SafetyRecommendation) -> str:
        """Format recommendation as human-readable text."""
        lines = [
            f"Safety Recommendation for {recommendation.gene_symbol}",
            f"{'=' * 60}",
            f"Safety Level: {recommendation.safety_level.value}",
            f"Primary Recommendation: {recommendation.primary_recommendation.value}",
            f"Confidence Score: {recommendation.confidence_score:.2f}",
            f"",
            f"Justification:",
        ]
        
        for i, just in enumerate(recommendation.justification, 1):
            lines.append(f"  {i}. {just}")
        
        lines.extend([
            f"",
            f"Concerns:",
        ])
        
        for concern in recommendation.concerns:
            lines.append(f"  - {concern}")
        
        if recommendation.alternative_recommendations:
            lines.extend([
                f"",
                f"Alternative Strategies:",
            ])
            for alt in recommendation.alternative_recommendations:
                lines.append(f"  - {alt.value}")
        
        lines.extend([
            f"",
            f"Mitigation Strategies:",
        ])
        
        for strategy in recommendation.mitigation_strategies:
            lines.append(f"  - {strategy}")
        
        lines.extend([
            f"",
            f"Experimental Considerations:",
        ])
        
        for consideration in recommendation.experimental_considerations:
            lines.append(f"  - {consideration}")
        
        return "\n".join(lines)


# Convenience function for easy access
def get_safety_recommendation(
    gene_symbol: str,
    pleiotropy_score: float,
    phenotype_prediction: Optional[Dict] = None,
    cross_species_validation: Optional[Dict] = None,
    literature_support: Optional[float] = None,
    knockout_evidence: Optional[Dict] = None
) -> SafetyRecommendation:
    """Get safety recommendation for a single gene."""
    recommender = SafetyRecommender()
    return recommender.generate_recommendation(
        gene_symbol=gene_symbol,
        pleiotropy_score=pleiotropy_score,
        phenotype_prediction=phenotype_prediction,
        cross_species_validation=cross_species_validation,
        literature_support=literature_support,
        knockout_evidence=knockout_evidence
    )
