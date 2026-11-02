/**
 * The full K-Sites analysis: GO term -> genes -> scores -> measured knockout evidence -> safety recommendation.
 * Port of k_sites/workflow/pipeline.py. Produces the same result structure.
 */

import { DEFAULT_MAX_ANNOTATIONS, getGenesForGoTermWithCoverage } from './goMapper.js';
import { DATA_OK, mapLimit, rankGenesBySpecificity, validateAcrossSpecies } from './scorer.js';
import { getSafetyRecommendation } from './safety.js';
import { assessGene, resolveContext } from './knockoutEvidence.js';

/** Genes whose evidence and cross-species check are looked up at the same time. */
const ASSESS_CONCURRENCY = 4;
// The phenotype predictor reads PubMed abstracts and runs a language model for every gene it is asked about, up to a minute each.
// A zebrafish or Xenopus term has thousands of genes without a measurement, so it is limited and the user is told.
export const MAX_PREDICTIONS = 25;

export const DEFAULT_SPECIES_VALIDATION = ['9606', '10090', '10116', '7227', '6239'];

/** Genes are listed safest first. */
export const SAFETY_TIER = { SAFE: 0, CAUTION: 1, MODERATE_CONCERN: 2, HIGH_CONCERN: 3, AVOID: 4 };

/** A gene with no functional description is not a useful recommendation target. */
function hasNoFunctionalDescription(description) {
    if (!description || !description.trim()) return true;
    const lower = description.toLowerCase();
    return lower.includes('uncharacterized') || lower.includes('hypothetical') || lower.includes('unknown function');
}

/**
 * @param ctx   { http, keggProvider, ncbiApiKey, ncbiEmail,
 *                evidenceProvider?  (measured knockout data; none = verdicts rest on annotations alone),
 *                phenotypePredictor? | getPhenotypePredictor?  (the predictor, or a loader called on first use) }
 * @param opts  { goTerm, organism, taxid, scientificName, maxPleiotropy, evidenceFilter,
 *                speciesValidation, predictPhenotypes, databases, maxAnnotations, knockoutContext, onProgress }
 */
export async function runKSitesPipeline(ctx, opts) {
    const {
        goTerm, organism, taxid,
        scientificName = organism,
        maxPleiotropy = 3,
        evidenceFilter = 'experimental',
        predictPhenotypes = false,
        databases = null,
        maxAnnotations = DEFAULT_MAX_ANNOTATIONS,
        knockoutContext = 'auto',
        onProgress = null,
        maxPredictions = MAX_PREDICTIONS,
        geneLimit = null,        // analyse only the first N genes (used by tests and previews)
    } = opts;
    const speciesValidation = opts.speciesValidation === undefined ? DEFAULT_SPECIES_VALIDATION : opts.speciesValidation;
    const log = ctx.log || (() => {});
    let provider = ctx.evidenceProvider || null;
    // Measured evidence was asked for: without it (the files could not be read) no gene is rated better than CAUTION
    const evidenceExpected = !!(provider || ctx.evidenceExpected);
    const context = resolveContext(taxid, knockoutContext);

    const started = new Date();
    log(`Starting K-Sites analysis for ${goTerm} in ${scientificName} (TaxID ${taxid})`);

    // Step 2: genes of the GO term
    const { genes: allGenes, coverage } = await getGenesForGoTermWithCoverage(ctx.http, goTerm, taxid, evidenceFilter, {
        maxAnnotations, onProgress,
    });
    const genes = geneLimit ? allGenes.slice(0, geneLimit) : allGenes;
    const warnings = [];
    if (coverage.message) warnings.push(coverage.message);
    if (coverage.unnamed_records) {
        warnings.push(`${coverage.unnamed_records} protein records without a gene name (unreviewed UniProt entries such as A8K1L8) `
            + 'were left out; they are not genes and cannot be scored.');
    }
    let organismCovered = false;
    if (provider) {
        try {
            await provider.index();
            organismCovered = (await provider.organism(taxid)) !== null;
        } catch (error) {
            // the analysis still runs, and says that its verdicts are not backed by measurements
            warnings.push('Measured knockout data could not be loaded, so every verdict rests on annotations and predictions '
                + `alone and none is rated better than CAUTION. (${error.message})`);
            provider = null;
        }
    }
    const evidenceIndex = provider ? await provider.index() : null;
    if (provider && !organismCovered) {
        warnings.push(`K-Sites has no measured knockout data for ${scientificName}, so every verdict rests on annotations and predictions `
            + 'alone and none is rated better than CAUTION.');
    }
    log(`Found ${genes.length} genes for ${goTerm} with ${evidenceFilter} evidence`);

    // What the evidence files know about each gene without searching a database: in how many model species it has an
    // ortholog (conservation) and how many PubMed articles are linked to it (literature)
    const factsLookup = provider ? async (symbol) => {
        const known = await assessGene(provider, taxid, symbol, context);
        return { conservation: known.conservation ? known.conservation.score : null, literature_count: known.literature ? known.literature.count : null };
    } : null;

    // Step 3: score and rank
    const ranked = await rankGenesBySpecificity(ctx, genes, taxid, {
        targetGoTerm: goTerm,
        evidenceFilter,
        includeLiterature: true,
        includeCrossSpecies: speciesValidation !== null,
        maxPleiotropyThreshold: maxPleiotropy,
        onProgress,
        factsLookup,
    });

    // Genes whose data could not be retrieved are reported separately, never treated as "specific"
    const scored = ranked.filter((g) => (g.data_status || DATA_OK) === DATA_OK);
    const insufficient = ranked.filter((g) => (g.data_status || DATA_OK) !== DATA_OK);
    if (insufficient.length) log(`${insufficient.length} of ${ranked.length} genes have insufficient data and are not scored`);

    // Step 4: per-gene assessment
    const processed = [];
    const excluded = [];
    let predictionsSkipped = 0;

    // The phenotype predictor (a language model) is only loaded when a gene has no measured knockout result
    let predictor = ctx.phenotypePredictor || null;
    let predictorTried = !!predictor;
    const getPredictor = async () => {
        if (predictor || predictorTried) return predictor;
        predictorTried = true;
        if (ctx.getPhenotypePredictor) {
            try {
                predictor = await ctx.getPhenotypePredictor();
            } catch (error) {
                if (error && error.name === 'AbortError') throw error;
                warnings.push(`The phenotype model could not be loaded: ${error.message}`);
                return null;
            }
        }
        if (!predictor) warnings.push('Phenotype prediction was requested but is not available in this browser, so it was skipped.');
        return predictor;
    };

    // Phase 1 (several genes at a time): the measured evidence and the cross-species check of each gene.
    // They only read databases, so they overlap; the results keep the order of the genes.
    let looked = 0;
    const lookups = await mapLimit(scored, ASSESS_CONCURRENCY, async (geneInfo) => {
        const symbol = geneInfo.symbol || 'unknown';
        try {
            const evidence = provider || evidenceExpected ? await assessGene(provider, taxid, symbol, context) : null;
            let crossSpecies = {};
            if (evidence && evidence.conservation) {
                // the orthologs in the evidence files answer this without a database search
                crossSpecies = { conservation_score: evidence.conservation.score, found_in: evidence.conservation.found_in, source: 'orthologs' };
            } else if (!(geneInfo.pleiotropy_score > maxPleiotropy) && speciesValidation && speciesValidation.length) {
                // genes above the cutoff are left out before the slower lookups
                crossSpecies = await validateAcrossSpecies(ctx, symbol, goTerm, speciesValidation);
            }
            return { geneInfo, evidence, crossSpecies };
        } catch (error) {
            if (error && error.name === 'AbortError') throw error;
            log(`Failed to look up ${symbol}: ${error.message}`);
            return { geneInfo, failed: true };
        } finally {
            looked += 1;
            if (onProgress) onProgress('Assessing genes', looked, scored.length);
        }
    });

    // Phase 2 (one gene at a time): the phenotype prediction where nothing was measured, then the verdict.
    let predictionsRun = 0;
    let predictionsOverLimit = 0;
    let rated = 0;
    for (const lookup of lookups) {
        const { geneInfo, evidence, crossSpecies } = lookup;
        const symbol = geneInfo.symbol || 'unknown';
        rated += 1;
        if (ctx.signal && ctx.signal.aborted) {
            const stopped = new Error('Cancelled');
            stopped.name = 'AbortError';
            throw stopped;
        }
        if (onProgress) onProgress('Rating genes', rated, lookups.length);
        if (lookup.failed) continue;

        try {
            const pleiotropy = geneInfo.pleiotropy_score;
            // a gene above the cutoff stays on the "not shown" list, with the measured result, so nothing disappears silently
            if (pleiotropy > maxPleiotropy) {
                log(`Skipping ${symbol} (pleiotropy score ${pleiotropy} > ${maxPleiotropy})`);
                excluded.push({
                    symbol,
                    description: geneInfo.description || '',
                    reason: 'pleiotropy',
                    detail: `Pleiotropy score ${Number(pleiotropy).toFixed(1)} is above the cutoff of ${maxPleiotropy}`,
                    pleiotropy_score: pleiotropy,
                    composite_score: geneInfo.composite_score ?? null,
                    knockout_evidence: evidence,
                });
                continue;
            }

            // Genes with no measured data, no literature, and no functional description are not scored.
            // They would otherwise be reported as CAUTION with no real evidence, which is misleading.
            const noMeasuredData = !evidence || !evidence.has_measured;
            const noLiterature = !geneInfo.pubmed_count || geneInfo.pubmed_count === 0;
            if (noMeasuredData && noLiterature && hasNoFunctionalDescription(geneInfo.description)) {
                log(`Moving ${symbol} to insufficient data (uncharacterized)`);
                insufficient.push({
                    symbol,
                    description: geneInfo.description || '',
                    data_issues: ['No measured knockout data, no literature, and no functional description'],
                    lookup_failed: false,
                });
                continue;
            }

            // a measurement is better than a guess from abstracts, and skipping the guess saves most of the time
            let phenotype = null;
            if (predictPhenotypes && evidence && (evidence.has_measured || evidence.estimate)) {
                predictionsSkipped += 1;
            } else if (predictPhenotypes && predictionsRun >= maxPredictions) {
                predictionsOverLimit += 1;
            } else if (predictPhenotypes && await getPredictor()) {
                predictionsRun += 1;
                try {
                    // the protein name is how many papers refer to the gene ("DNA polymerase beta")
                    const description = geneInfo.description || '';
                    const aliases = description && !/^(PMID:|GO_REF:)/.test(description) ? [description] : [];
                    phenotype = await predictor.predict(symbol, taxid, true, aliases);
                } catch (error) {
                    if (error && error.name === 'AbortError') throw error;
                    log(`Failed to predict phenotype for ${symbol}: ${error.message}`);
                }
            }

            const safety = getSafetyRecommendation({
                symbol,
                pleiotropyScore: pleiotropy,
                phenotypePrediction: phenotype,
                crossSpecies,
                literatureSupport: geneInfo.literature_score ?? 0.5,
                knockoutEvidence: evidence,
            });

            processed.push({
                symbol,
                pleiotropy_score: pleiotropy,
                specificity_score: geneInfo.specificity_score,
                evidence_quality: geneInfo.evidence_quality ?? 0.5,
                literature_support: geneInfo.literature_score ?? 0.5,
                literature_score: geneInfo.literature_score ?? 0.5,
                pubmed_count: geneInfo.pubmed_count ?? 0,
                conservation_score: geneInfo.conservation_score ?? 0.0,
                composite_score: geneInfo.composite_score ?? 5.0,
                bp_term_count: geneInfo.bp_term_count ?? 0,
                data_issues: geneInfo.data_issues || [],
                kegg_pathway_count: geneInfo.kegg_pathway_count ?? 0,
                experimental_evidence_count: geneInfo.experimental_evidence_count ?? 0,
                computational_evidence_count: geneInfo.computational_evidence_count ?? 0,
                iea_evidence_count: geneInfo.iea_evidence_count ?? 0,
                cross_species_validation: crossSpecies,
                phenotype_prediction: phenotype,
                knockout_evidence: evidence,
                safety_recommendation: {
                    evidence_basis: safety.evidence_basis,
                    safety_level: safety.safety_level,
                    primary_recommendation: safety.primary_recommendation,
                    alternative_recommendations: safety.alternative_recommendations,
                    justification: safety.justification,
                    concerns: safety.concerns,
                    mitigation_strategies: safety.mitigation_strategies,
                    experimental_considerations: safety.experimental_considerations,
                    confidence_score: safety.confidence_score,
                },
                description: geneInfo.description || '',
                entrez_id: geneInfo.entrez_id || '',
            });
        } catch (error) {
            if (error && error.name === 'AbortError') throw error;
            log(`Failed to process gene ${symbol}: ${error.message}`);
        }
    }
    if (onProgress) onProgress('Assessing genes', scored.length, scored.length);
    if (predictionsOverLimit) {
        warnings.push(`Phenotype prediction (it reads PubMed abstracts, a few seconds per gene) was run for the first ${maxPredictions} genes `
            + `without a measured result; the other ${predictionsOverLimit} were rated without it, so they are at most CAUTION.`);
    }

    // Safest genes first (measured evidence decides the tier), then by composite score as before
    const tier = (gene) => SAFETY_TIER[gene.safety_recommendation.safety_level] ?? Object.keys(SAFETY_TIER).length;
    processed.sort((a, b) => tier(a) - tier(b) || (b.composite_score || 0) - (a.composite_score || 0));

    // Step 5: aggregate
    const count = (key) => processed.reduce((acc, g) => { const k = g.safety_recommendation[key]; acc[k] = (acc[k] || 0) + 1; return acc; }, {});
    const statistics = {
        total_genes_screened: ranked.length,
        genes_passed_filter: processed.length,
        genes_insufficient_data: insufficient.length,
        genes_above_pleiotropy_cutoff: excluded.length,
        by_safety_level: count('safety_level'),
        by_evidence_basis: count('evidence_basis'),
        phenotype_predictions_skipped: predictionsSkipped,
        avg_pleiotropy: 0.0,
        most_specific_gene: null,
        least_specific_gene: null,
    };
    if (processed.length) {
        statistics.avg_pleiotropy = processed.reduce((a, g) => a + g.pleiotropy_score, 0) / processed.length;
        const byPleiotropy = [...processed].sort((a, b) => a.pleiotropy_score - b.pleiotropy_score);
        statistics.most_specific_gene = byPleiotropy[0];
        statistics.least_specific_gene = byPleiotropy[byPleiotropy.length - 1];
    }

    return {
        metadata: {
            go_term: goTerm,
            organism,
            resolved_organism: { taxid, scientific_name: scientificName },
            timestamp: started.toISOString(),
            execution_duration: (Date.now() - started.getTime()) / 1000,
            max_pleiotropy: maxPleiotropy,
            evidence_filter: evidenceFilter,
            species_validation: speciesValidation,
            predict_phenotypes: predictPhenotypes,
            databases: databases || ['all'],
            annotation_coverage: coverage,
            knockout_context: context,
            knockout_evidence_data: {
                available: !!provider,
                organism_covered: organismCovered,
                version: evidenceIndex ? (evidenceIndex.built ?? null) : null,
                sources: evidenceIndex ? (evidenceIndex.sources || []) : [],
            },
        },
        genes: processed,
        excluded_genes: excluded,
        insufficient_data_genes: insufficient.map((g) => ({
            symbol: g.symbol || '',
            description: g.description || '',
            lookup_failed: g.lookup_failed || false,
            reasons: g.data_issues || [],
        })),
        warnings,
        statistics,
    };
}
