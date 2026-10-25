/**
 * The full K-Sites analysis: GO term -> genes -> scores -> safety recommendation.
 * Port of k_sites/workflow/pipeline.py. Produces the same result structure.
 */

import { DEFAULT_MAX_ANNOTATIONS, getGenesForGoTermWithCoverage } from './goMapper.js';
import { DATA_OK, rankGenesBySpecificity, validateAcrossSpecies } from './scorer.js';
import { getSafetyRecommendation } from './safety.js';

export const DEFAULT_SPECIES_VALIDATION = ['9606', '10090', '10116', '7227', '6239'];

/**
 * @param ctx   { http, keggProvider, ncbiApiKey, ncbiEmail, phenotypePredictor? }
 * @param opts  { goTerm, organism, taxid, scientificName, maxPleiotropy, evidenceFilter,
 *                speciesValidation, predictPhenotypes, databases, maxAnnotations, onProgress }
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
        onProgress = null,
        geneLimit = null,        // analyse only the first N genes (used by tests and previews)
    } = opts;
    const speciesValidation = opts.speciesValidation === undefined ? DEFAULT_SPECIES_VALIDATION : opts.speciesValidation;
    const log = ctx.log || (() => {});

    const started = new Date();
    log(`Starting K-Sites analysis for ${goTerm} in ${scientificName} (TaxID ${taxid})`);

    // Step 2: genes of the GO term
    const { genes: allGenes, coverage } = await getGenesForGoTermWithCoverage(ctx.http, goTerm, taxid, evidenceFilter, {
        maxAnnotations, onProgress,
    });
    const genes = geneLimit ? allGenes.slice(0, geneLimit) : allGenes;
    const warnings = [];
    if (coverage.message) warnings.push(coverage.message);
    log(`Found ${genes.length} genes for ${goTerm} with ${evidenceFilter} evidence`);

    // Step 3: score and rank
    const ranked = await rankGenesBySpecificity(ctx, genes, taxid, {
        targetGoTerm: goTerm,
        evidenceFilter,
        includeLiterature: true,
        includeCrossSpecies: speciesValidation !== null,
        maxPleiotropyThreshold: maxPleiotropy,
        onProgress,
    });

    // Genes whose data could not be retrieved are reported separately, never treated as "specific"
    const scored = ranked.filter((g) => (g.data_status || DATA_OK) === DATA_OK);
    const insufficient = ranked.filter((g) => (g.data_status || DATA_OK) !== DATA_OK);
    if (insufficient.length) log(`${insufficient.length} of ${ranked.length} genes have insufficient data and are not scored`);

    // Step 4: per-gene assessment
    const processed = [];
    let phenotypePredictor = ctx.phenotypePredictor || null;
    let phenotypesEnabled = predictPhenotypes;
    if (predictPhenotypes && !phenotypePredictor) {
        warnings.push('Phenotype prediction was requested but is not available in this browser, so it was skipped.');
        phenotypesEnabled = false;
    }

    for (let i = 0; i < scored.length; i++) {
        const geneInfo = scored[i];
        const symbol = geneInfo.symbol || 'unknown';
        if (onProgress) onProgress('Assessing genes', i, scored.length);

        try {
            const pleiotropy = geneInfo.pleiotropy_score;
            if (pleiotropy > maxPleiotropy) {
                log(`Skipping ${symbol} (pleiotropy score ${pleiotropy} > ${maxPleiotropy})`);
                continue;
            }

            let crossSpecies = {};
            if (speciesValidation && speciesValidation.length) {
                crossSpecies = await validateAcrossSpecies(ctx, symbol, goTerm, speciesValidation);
            }

            let phenotype = null;
            if (phenotypesEnabled && phenotypePredictor) {
                try {
                    // the protein name is how many papers refer to the gene ("DNA polymerase beta")
                    const description = geneInfo.description || '';
                    const aliases = description && !/^(PMID:|GO_REF:)/.test(description) ? [description] : [];
                    phenotype = await phenotypePredictor.predict(symbol, taxid, true, aliases);
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
                safety_recommendation: {
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

    // Step 5: aggregate
    const statistics = {
        total_genes_screened: ranked.length,
        genes_passed_filter: processed.length,
        genes_insufficient_data: insufficient.length,
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
            predict_phenotypes: phenotypesEnabled,
            databases: databases || ['all'],
            annotation_coverage: coverage,
        },
        genes: processed,
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
