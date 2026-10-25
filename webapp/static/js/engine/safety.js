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

const LEVEL_ORDER = [SafetyLevel.SAFE, SafetyLevel.CAUTION, SafetyLevel.MODERATE_CONCERN, SafetyLevel.HIGH_CONCERN, SafetyLevel.AVOID];
const atLeast = (level, minimum) => (LEVEL_ORDER.indexOf(level) >= LEVEL_ORDER.indexOf(minimum) ? level : minimum);

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

// ------------------------------------------------------------------------------------------------
// verdicts from measured knockout evidence (port of SafetyRecommender._evidence_verdict and friends)
// ------------------------------------------------------------------------------------------------

function extraFindings(evidence) {
    const lines = [];
    const constraint = evidence.constraint;
    if (constraint && constraint.label === 'highly constrained') {
        lines.push(`Highly constrained in people (gnomAD LOEUF ${Number(constraint.loeuf)}): loss of one copy is rarely tolerated`);
    }
    return lines;
}

/** A close paralog may take over the work of the knocked-out gene and hide its phenotype. */
function paralogConcern(evidence) {
    const paralogs = evidence.paralogs;
    if (!paralogs || !paralogs.close.length) return null;
    const names = paralogs.close.join(', ');
    const noun = paralogs.close.length === 1 ? 'The close paralog' : 'The close paralogs';
    return `${noun} ${names} may take over its work and hide the phenotype: consider a double knockout`;
}

/** A gene needed for survival but expressed mainly in a few tissues can be removed in those tissues only. */
function tissueMitigation(evidence) {
    const expression = evidence.expression;
    if (!expression || !['tissue-specific', 'tissue-enriched'].includes(expression.label) || !expression.top_tissues.length) return null;
    return `Expression is concentrated in ${expression.top_tissues.slice(0, 2).join(', ')}: a tissue-specific conditional knockout may avoid the lethal effect`;
}

const organismBasis = (organism) => (organism.basis === 'direct' ? 'measured' : 'ortholog');
const round2 = (value) => Math.round(value * 100) / 100;

function organismConfidence(organism) {
    const { lethal, subviable, viable } = organism.counts;
    const total = lethal + subviable + viable;
    let confidence;
    if (organism.basis === 'direct') {
        confidence = organism.mixed ? 0.7 : (total >= 2 ? 0.9 : 0.8);
    } else {
        confidence = organism.ortholog.relation !== '1:1' ? 0.55 : (total >= 2 ? 0.75 : 0.7);
        if (organism.mixed) confidence -= 0.1;
    }
    return round2(confidence);
}

function organismVerdict(evidence, pleiotropy) {
    const R = Recommendation;
    const organism = evidence.organism;
    const { call, mixed, counts } = organism;
    const yeast = ['559292', '4932'].includes(evidence.taxid);
    const orthologNote = organism.basis === 'ortholog' && organism.ortholog.relation !== '1:1';
    const stage = !['U', null, undefined].includes(organism.stage) ? organism.stage_text : null;
    const justification = [organism.text];
    const concerns = [];
    const mitigation = [];
    const considerations = [];
    let level;
    let primary;
    let alternatives;

    if (call === 'LETHAL') {
        level = SafetyLevel.AVOID;
        if (orthologNote) {
            level = SafetyLevel.HIGH_CONCERN;
            concerns.push('The mouse ortholog is not a one-to-one match, so confirm the lethality in your organism');
        }
        primary = R.CONDITIONAL_KO;
        alternatives = [R.CRISPRI, R.TEMPORAL_CONTROL, R.ALTERNATIVE_MODEL];
        if (yeast) {
            concerns.unshift('The deletion is inviable: a haploid knockout strain cannot be kept');
            mitigation.push('Use a conditional allele (degron tag or repressible promoter) or a heterozygous diploid',
                'Study a temperature-sensitive allele instead of a deletion');
        } else {
            concerns.unshift('Homozygous knockouts do not survive, so a complete knockout line cannot be kept');
            mitigation.push('Use a conditional (Cre-lox) or inducible allele so the gene is lost only after the critical stage',
                'Knock the gene down (CRISPRi, RNAi) to keep some function instead of knocking it out',
                'Maintain the line from heterozygotes');
        }
        if (stage) considerations.push(`Death occurs ${stage}: collect samples before that stage`);
        const tissue = tissueMitigation(evidence);
        if (tissue) mitigation.push(tissue);
    } else if (call === 'SUBVIABLE') {
        level = SafetyLevel.HIGH_CONCERN;
        primary = R.CONDITIONAL_KO;
        alternatives = [R.HETEROZYGOUS_KO, R.CRISPRI];
        concerns.push('Fewer homozygous knockouts survive than expected, so experiments need more breeding');
        mitigation.push('Use a conditional allele, or plan larger crosses to obtain enough homozygotes');
        const tissue = tissueMitigation(evidence);
        if (tissue) mitigation.push(tissue);
    } else {
        if (mixed && counts.lethal) {
            level = SafetyLevel.HIGH_CONCERN;
            primary = R.CONDITIONAL_KO;
            alternatives = [R.VALIDATED_KO, R.CRISPRI];
            concerns.push('Some knockout lines are lethal, so lethality depends on the strain or the allele');
            mitigation.push('Check which strain and allele were lethal and use a conditional allele if yours is similar');
        } else if (mixed) {
            level = SafetyLevel.CAUTION;
            primary = R.VALIDATED_KO;
            alternatives = [R.CONDITIONAL_KO];
            concerns.push('Some knockout lines survive in reduced numbers: the outcome depends on the strain or the allele');
        } else {
            level = SafetyLevel.SAFE;
            primary = R.STANDARD_KO;
            alternatives = [];
        }
        if (organism.reduced_lifespan) {
            level = atLeast(level, SafetyLevel.CAUTION);
            if (primary === R.STANDARD_KO) { primary = R.VALIDATED_KO; alternatives = [R.CONDITIONAL_KO]; }
            concerns.push('A shortened lifespan was reported for the viable knockouts');
            considerations.push('Plan ageing cohorts and watch the animals for early death');
        }
        if (organism.infertile) {
            level = atLeast(level, SafetyLevel.CAUTION);
            if (primary === R.STANDARD_KO) { primary = R.VALIDATED_KO; alternatives = [R.CONDITIONAL_KO]; }
            concerns.push('Infertility was reported, so the knockout line must be kept from heterozygotes');
        }
        if (level === SafetyLevel.SAFE && pleiotropy > 5) {
            level = SafetyLevel.CAUTION;
            primary = R.VALIDATED_KO;
            alternatives = [R.STANDARD_KO];
            concerns.push('The knockout is viable, but the gene has many annotated roles, so expect broad phenotypes');
        }
        const paralog = paralogConcern(evidence);
        if (paralog) concerns.push(paralog);
    }
    justification.push(...extraFindings(evidence));
    return { level, primary, alternatives, basis: organismBasis(organism), justification, concerns, mitigation,
        considerations, confidence: organismConfidence(organism) };
}

function organismVerdictFromCells(evidence) {
    const R = Recommendation;
    return {
        level: SafetyLevel.HIGH_CONCERN, primary: R.CONDITIONAL_KO, alternatives: [R.CRISPRI, R.TEMPORAL_CONTROL], basis: 'measured',
        justification: [evidence.cells.text],
        concerns: ['The gene is essential in human cells, so a whole-organism knockout is likely lethal'],
        mitigation: ['Use a conditional or inducible allele instead of a complete knockout'],
        considerations: [], confidence: 0.6,
    };
}

function cellsVerdict(evidence, pleiotropy) {
    const R = Recommendation;
    const { cells, organism } = evidence;
    const { call, percent } = cells;
    const justification = [cells.text];
    const concerns = [];
    const mitigation = [];
    const considerations = [];
    let level;
    let primary;
    let alternatives;
    if (call === 'ESSENTIAL') {
        level = SafetyLevel.AVOID;
        primary = R.CRISPRI;
        alternatives = [R.TEMPORAL_CONTROL, R.CONDITIONAL_KO, R.ALTERNATIVE_MODEL];
        concerns.push('A complete knockout is expected to kill the cells');
        mitigation.push('Use an inducible knockout, a degron tag or CRISPRi so the cells survive until the gene is switched off',
            'Check your own cell line in DepMap before starting');
        considerations.push('Include a rescue construct to show that the phenotype comes from this gene');
    } else if (call === 'SELECTIVE') {
        if (percent >= 25) {
            level = SafetyLevel.MODERATE_CONCERN; primary = R.CRISPRI; alternatives = [R.VALIDATED_KO];
        } else {
            level = SafetyLevel.CAUTION; primary = R.VALIDATED_KO; alternatives = [R.CRISPRI];
        }
        concerns.push('The gene is essential in some cell types: confirm that yours is not one of them');
        mitigation.push('Look up your cell line in DepMap and keep a knockdown as a fallback');
    } else {
        level = SafetyLevel.SAFE; primary = R.STANDARD_KO; alternatives = [];
        if (pleiotropy > 5) {
            level = SafetyLevel.CAUTION; primary = R.VALIDATED_KO; alternatives = [R.STANDARD_KO];
            concerns.push('The gene is not essential in cell lines, but it has many annotated roles, so expect broad phenotypes');
        }
    }
    if (call !== 'ESSENTIAL') {
        const paralog = paralogConcern(evidence);
        if (paralog) concerns.push(paralog);
    }
    if (['LETHAL', 'SUBVIABLE'].includes(organism.call)) {
        justification.push(organism.text);
        concerns.push('The knockout is not viable in mice: cultured cells can tolerate it, but a whole-animal knockout cannot be made');
    }
    justification.push(...extraFindings(evidence));
    const confidence = (call === 'ESSENTIAL' && cells.common_essential) || (call === 'NON_ESSENTIAL' && percent < 5) ? 0.9 : 0.75;
    return { level, primary, alternatives, basis: 'measured', justification, concerns, mitigation, considerations, confidence };
}

function cellsVerdictFromOrganism(evidence, pleiotropy) {
    const R = Recommendation;
    const organism = evidence.organism;
    const justification = [organism.text, 'No cell-line screen result for this gene, so essentiality in cells is unknown'];
    const concerns = [];
    const mitigation = [];
    let level;
    let primary;
    let alternatives;
    if (['LETHAL', 'SUBVIABLE'].includes(organism.call) || organism.mixed) {
        level = SafetyLevel.CAUTION; primary = R.VALIDATED_KO; alternatives = [R.CRISPRI];
        concerns.push('The gene is needed for the survival of the organism, so it may also be needed in cells');
        mitigation.push('Check the gene in DepMap or test a knockdown first');
    } else {
        level = SafetyLevel.SAFE; primary = R.STANDARD_KO; alternatives = [];
        if (pleiotropy > 5) {
            level = SafetyLevel.CAUTION; primary = R.VALIDATED_KO; alternatives = [R.STANDARD_KO];
            concerns.push('The knockout organism is viable, but the gene has many annotated roles, so expect broad phenotypes');
        }
        const paralog = paralogConcern(evidence);
        if (paralog) concerns.push(paralog);
    }
    justification.push(...extraFindings(evidence));
    return { level, primary, alternatives, basis: organismBasis(organism), justification, concerns, mitigation,
        considerations: [], confidence: round2(organismConfidence(organism) - 0.1) };
}

/** The verdict implied by what was measured, or null when nothing measured applies to the knockout context. */
function evidenceVerdict(evidence, pleiotropy) {
    const { organism, cells } = evidence;
    const context = evidence.context || 'organism';
    // a distant relative's mouse ortholog is a hint, never a measurement
    const usable = organism.call !== 'UNKNOWN' && !organism.distant;
    if (context === 'cells') {
        if (cells.call !== 'UNKNOWN') return cellsVerdict(evidence, pleiotropy);
        if (usable) return cellsVerdictFromOrganism(evidence, pleiotropy);
        return null;
    }
    if (usable) return organismVerdict(evidence, pleiotropy);
    if (cells.call === 'ESSENTIAL') return organismVerdictFromCells(evidence);
    return null;
}

/**
 * `phenotypePrediction` may be null; `crossSpecies` may be {} or null; `knockoutEvidence` is an `assessGene` result.
 * With a measured result for the knockout context the verdict follows it; without one it rests on annotations and
 * predictions and is never better than CAUTION (when evidence was consulted at all).
 */
export function getSafetyRecommendation({ symbol, pleiotropyScore, phenotypePrediction = null, crossSpecies = null, literatureSupport = null, knockoutEvidence = null }) {
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

    const measured = knockoutEvidence ? evidenceVerdict(knockoutEvidence, pleiotropyScore) : null;
    let safetyLevel;
    let primary;
    let alternatives;
    let evidenceBasis;
    if (measured) {
        ({ level: safetyLevel, primary, alternatives } = measured);
        evidenceBasis = measured.basis;
    } else {
        [safetyLevel, primary, alternatives] = determineSafetyLevel(pleiotropyScore, phenotypeRisk, conservation, phenotypeConfidence);
        evidenceBasis = phenotypePrediction ? 'predicted' : 'none';
    }

    // A distant relative (zebrafish, fly, worm, ...) only has its mouse ortholog's knockout as a hint. A hint of
    // lethality raises the level to MODERATE_CONCERN; nothing in it ever makes a gene safe.
    let distant = null;
    if (knockoutEvidence && !measured) {
        const candidate = knockoutEvidence.organism;
        if (candidate.distant && candidate.call !== 'UNKNOWN') {
            distant = candidate;
            evidenceBasis = 'distant';
        }
    }
    const distantRisk = !!(distant && (['LETHAL', 'SUBVIABLE'].includes(distant.call) || distant.counts.lethal > 0));
    if (distantRisk && LEVEL_ORDER.indexOf(safetyLevel) < LEVEL_ORDER.indexOf(SafetyLevel.MODERATE_CONCERN)) {
        safetyLevel = SafetyLevel.MODERATE_CONCERN;
        primary = Recommendation.HETEROZYGOUS_KO;
        alternatives = [Recommendation.CONDITIONAL_KO, Recommendation.VALIDATED_KO];
    }

    // Without a measurement nothing shows that the knockout is safe: the verdict is never better than CAUTION,
    // and every such gene says that its lethality has not been measured
    const unverified = !!knockoutEvidence && !measured;
    if (unverified && safetyLevel === SafetyLevel.SAFE) {
        safetyLevel = SafetyLevel.CAUTION;
        primary = Recommendation.VALIDATED_KO;
        alternatives = [Recommendation.STANDARD_KO];
    }

    let justification = buildJustification(pleiotropyScore, phenotypeRisk, conservation, literatureSupport, phenotypeConfidence);
    if (measured) {
        justification = [...measured.justification,
            ...justification.filter((line) => !line.startsWith('Predicted ') && !line.startsWith('Low confidence phenotype'))];
    } else {
        if (distant) justification.unshift(distant.text);
        if (unverified) justification.unshift('No measured knockout data for this gene, so the safety of a knockout is unverified');
    }

    let concerns = identifyConcerns(pleiotropyScore, phenotypeSeverity, phenotypeRisk, conservation, compensatory);
    let mitigation = suggestMitigation(safetyLevel, primary, phenotypeRisk, compensatory);
    let considerations = suggestConsiderations(phenotypeSeverity, lethalityStage, primary);
    if (unverified) {
        concerns = concerns.filter((c) => c !== 'No major concerns identified');
        concerns.unshift('Lethality has not been measured: check MGI, IMPC or DepMap before committing to a knockout');
    }
    if (distantRisk) {
        concerns = concerns.filter((c) => c !== 'No major concerns identified');
        concerns.unshift('The mouse ortholog is needed for survival and essential genes are usually conserved, '
            + 'so this gene may be essential here too, but that has not been tested');
    }
    if (measured) {
        concerns = [...measured.concerns, ...concerns.filter((c) => c !== 'No major concerns identified'
            && !c.startsWith('Predicted ') && !c.startsWith('Potential lethality'))];
        mitigation = [...measured.mitigation, ...mitigation.filter((s) => s !== 'Standard validation sufficient')];
        considerations = [...measured.considerations, ...considerations];
    }

    return {
        gene_symbol: symbol,
        safety_level: safetyLevel,
        primary_recommendation: primary,
        alternative_recommendations: alternatives,
        justification,
        concerns,
        mitigation_strategies: mitigation,
        experimental_considerations: considerations,
        confidence_score: measured ? measured.confidence : calculateConfidence(phenotypeConfidence, literatureSupport, hasCrossSpecies),
        evidence_basis: evidenceBasis,
    };
}
