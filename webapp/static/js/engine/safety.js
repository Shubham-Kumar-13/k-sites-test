/**
 * Safety level and recommendation for deleting a gene.
 * Port of k_sites/workflow/safety_recommender.py.
 */

export const SafetyLevel = {
    SAFE: 'SAFE',                          // standard knockout acceptable
    CAUTION: 'CAUTION',                    // standard knockout with validation
    MODERATE_CONCERN: 'MODERATE_CONCERN',  // heterozygous knockout recommended
    HIGH_CONCERN: 'HIGH_CONCERN',          // conditional knockout / CRISPRi preferred
    AVOID: 'AVOID',                        // alternative strategies required
};

export const Recommendation = {
    STANDARD_KO: 'Standard Knockout',
    VALIDATED_KO: 'Standard KO with Validation',
    HETEROZYGOUS_KO: 'Heterozygous Knockout',
    CONDITIONAL_KO: 'Conditional Knockout (Cre-Lox)',
    CRISPRI: 'CRISPR Interference (CRISPRi)',
    TEMPORAL_CONTROL: 'Temporal Control (Tet-ON/OFF)',
    ALTERNATIVE_MODEL: 'Alternative Model System',
    MULTIPLE_STRATEGIES: 'Multiple Complementary Strategies',
};

/** "CRITICAL" for "CRITICAL", "RiskLevel.CRITICAL" or { value: "CRITICAL" }. */
export function enumText(value) {
    if (value === null || value === undefined) return '';
    if (typeof value === 'object' && !Array.isArray(value)) value = value.value ?? '';
    const text = String(value);
    return /^(RiskLevel|PhenotypeSeverity)\./.test(text) ? text.split('.').pop() : text;
}

const fixed1 = (n) => Number(n).toFixed(1);
const fixed2 = (n) => Number(n).toFixed(2);

function determineSafetyLevel(pleiotropy, phenotypeRisk, conservation, phenotypeConfidence) {
    const R = Recommendation;

    if (['CRITICAL', 'HIGH'].includes(phenotypeRisk) && phenotypeConfidence > 0.5) {
        if (pleiotropy > 8) {
            return [SafetyLevel.AVOID, R.MULTIPLE_STRATEGIES, [R.CRISPRI, R.CONDITIONAL_KO, R.ALTERNATIVE_MODEL]];
        }
        return [SafetyLevel.HIGH_CONCERN, R.CONDITIONAL_KO, [R.CRISPRI, R.HETEROZYGOUS_KO, R.TEMPORAL_CONTROL]];
    }

    if (phenotypeRisk === 'CRITICAL') {
        return [SafetyLevel.HIGH_CONCERN, R.CONDITIONAL_KO, [R.CRISPRI, R.TEMPORAL_CONTROL]];
    }

    if (phenotypeRisk === 'HIGH') {
        if (pleiotropy > 5) return [SafetyLevel.HIGH_CONCERN, R.CRISPRI, [R.CONDITIONAL_KO, R.HETEROZYGOUS_KO]];
        return [SafetyLevel.MODERATE_CONCERN, R.HETEROZYGOUS_KO, [R.VALIDATED_KO, R.CRISPRI]];
    }

    if (pleiotropy > 8) return [SafetyLevel.HIGH_CONCERN, R.CRISPRI, [R.HETEROZYGOUS_KO, R.CONDITIONAL_KO]];

    if (pleiotropy > 5) {
        if (conservation > 0.8) {
            return [SafetyLevel.MODERATE_CONCERN, R.HETEROZYGOUS_KO, [R.VALIDATED_KO, R.CONDITIONAL_KO]];
        }
        return [SafetyLevel.CAUTION, R.VALIDATED_KO, [R.STANDARD_KO]];
    }

    if (pleiotropy > 3) return [SafetyLevel.CAUTION, R.STANDARD_KO, [R.VALIDATED_KO]];

    return [SafetyLevel.SAFE, R.STANDARD_KO, []];
}

function buildJustification(pleiotropy, phenotypeRisk, conservation, literatureSupport, phenotypeConfidence) {
    const lines = [];

    if (pleiotropy > 8) lines.push(`Very high pleiotropy score (${fixed1(pleiotropy)}) indicates multiple biological functions`);
    else if (pleiotropy > 5) lines.push(`High pleiotropy score (${fixed1(pleiotropy)}) suggests multiple roles`);
    else if (pleiotropy > 3) lines.push(`Moderate pleiotropy score (${fixed1(pleiotropy)})`);
    else lines.push(`Low pleiotropy score (${fixed1(pleiotropy)}) indicates specific function`);

    if (phenotypeRisk) {
        if (phenotypeConfidence > 0.5) {
            lines.push(`Predicted ${phenotypeRisk} risk phenotype (confidence: ${fixed2(phenotypeConfidence)})`);
        } else {
            lines.push(`Low confidence phenotype prediction (${fixed2(phenotypeConfidence)})`);
        }
    }

    if (conservation > 0.8) lines.push(`Highly conserved across species (${fixed2(conservation)})`);
    else if (conservation < 0.3) lines.push(`Low conservation (${fixed2(conservation)}) - may indicate species-specific function`);

    if (literatureSupport && literatureSupport > 0.8) lines.push('Strong literature support for this gene');
    else if (literatureSupport && literatureSupport < 0.3) lines.push('Limited literature available - consider additional validation');

    return lines;
}

function identifyConcerns(pleiotropy, phenotypeSeverity, phenotypeRisk, conservation, compensatory) {
    const concerns = [];
    if (['CRITICAL', 'HIGH'].includes(phenotypeRisk)) {
        concerns.push(`Predicted ${phenotypeRisk.toLowerCase()} risk phenotype - may cause lethality or severe defects`);
    }
    if (phenotypeSeverity === 'LETHAL') concerns.push('Potential lethality requires careful experimental design');
    if (pleiotropy > 8) concerns.push('High pleiotropy may confound phenotype interpretation');
    if (conservation > 0.8) concerns.push('Highly conserved gene - may be essential for basic cellular functions');
    if (compensatory.length) {
        concerns.push(`Compensatory mechanisms detected (${compensatory.length}) - phenotypes may be masked`);
    }
    return concerns.length ? concerns : ['No major concerns identified'];
}

function suggestMitigation(safetyLevel, primary, phenotypeRisk, compensatory) {
    const strategies = [];
    if (['CRITICAL', 'HIGH'].includes(phenotypeRisk)) {
        strategies.push('Start with conditional or inducible knockdown');
        strategies.push('Monitor phenotype progression carefully');
        strategies.push('Prepare rescue constructs for complementation studies');
    }
    if ([Recommendation.CRISPRI, Recommendation.HETEROZYGOUS_KO].includes(primary)) {
        strategies.push('Use partial knockdown to study dose-dependent effects');
        strategies.push('Compare results with RNAi data if available');
    }
    if (compensatory.length) {
        strategies.push('Consider double-knockout with paralog genes');
        strategies.push('Use time-course experiments to detect delayed compensation');
    }
    if ([SafetyLevel.HIGH_CONCERN, SafetyLevel.AVOID].includes(safetyLevel)) {
        strategies.push('Phenotype Analysis of Stems cells & CRISPR-engineered (PASC) approach');
        strategies.push('Phenotype Suppression Screening to identify genetic interactors');
    }
    return strategies.length ? strategies : ['Standard validation sufficient'];
}

function suggestConsiderations(phenotypeSeverity, lethalityStage, primary) {
    const items = [];
    if (lethalityStage) items.push(`Plan for ${String(lethalityStage).toLowerCase()} lethality - harvest samples before expected lethality`);
    if (phenotypeSeverity === 'LETHAL') {
        items.push('Use heterozygous crosses to maintain line');
        items.push('Consider inducible systems for temporal control');
    }
    if (primary === Recommendation.CRISPRI) {
        items.push('Optimize dCas9-KRAB expression levels');
        items.push('Verify knockdown efficiency at mRNA and protein levels');
    }
    if (primary === Recommendation.CONDITIONAL_KO) {
        items.push('Verify Cre recombinase efficiency');
        items.push('Include littermate controls');
    }
    if (primary === Recommendation.HETEROZYGOUS_KO) {
        items.push('Genotype all offspring carefully');
        items.push('Compare heterozygous vs homozygous phenotypes');
    }
    items.push('Include appropriate controls (wild-type and non-targeting controls)');
    items.push('Plan for phenotypic scoring at multiple developmental stages');
    return items;
}

function calculateConfidence(phenotypeConfidence, literatureSupport, hasValidation) {
    const scores = [phenotypeConfidence];
    if (literatureSupport) scores.push(literatureSupport);
    if (hasValidation) scores.push(0.7);
    return scores.reduce((a, b) => a + b, 0) / scores.length;
}

/** `phenotypePrediction` may be null; `crossSpecies` may be {} or null. */
export function getSafetyRecommendation({ symbol, pleiotropyScore, phenotypePrediction = null, crossSpecies = null, literatureSupport = null }) {
    let phenotypeSeverity = null;
    let phenotypeRisk = null;
    let phenotypeConfidence = 0.0;
    let lethalityStage = null;
    let compensatory = [];

    if (phenotypePrediction) {
        phenotypeSeverity = enumText(phenotypePrediction.severity);
        phenotypeRisk = enumText(phenotypePrediction.risk_level);
        phenotypeConfidence = phenotypePrediction.confidence_score ?? 0.0;
        lethalityStage = phenotypePrediction.lethality_stage ?? null;
        compensatory = phenotypePrediction.compensatory_mechanisms || [];
    }

    const hasCrossSpecies = !!crossSpecies && Object.keys(crossSpecies).length > 0;
    const conservation = hasCrossSpecies ? (crossSpecies.conservation_score ?? 0.0) : 0.0;

    const [safetyLevel, primary, alternatives] = determineSafetyLevel(pleiotropyScore, phenotypeRisk, conservation, phenotypeConfidence);

    return {
        gene_symbol: symbol,
        safety_level: safetyLevel,
        primary_recommendation: primary,
        alternative_recommendations: alternatives,
        justification: buildJustification(pleiotropyScore, phenotypeRisk, conservation, literatureSupport, phenotypeConfidence),
        concerns: identifyConcerns(pleiotropyScore, phenotypeSeverity, phenotypeRisk, conservation, compensatory),
        mitigation_strategies: suggestMitigation(safetyLevel, primary, phenotypeRisk, compensatory),
        experimental_considerations: suggestConsiderations(phenotypeSeverity, lethalityStage, primary),
        confidence_score: calculateConfidence(phenotypeConfidence, literatureSupport, hasCrossSpecies),
    };
}
