/**
 * Pleiotropy scoring, evidence quality, literature support, cross-species validation and
 * gene ranking. Port of k_sites/gene_analysis/pleiotropy_scorer.py.
 *
 * `ctx` carries what a lookup needs: { http, keggProvider, ncbiApiKey, ncbiEmail }.
 */

import { getPleiotropyScoreDetailed } from './goMapper.js';
import { queryGeneFromAllDatabases } from './multiDb.js';

export const MODEL_ORGANISMS = {
    '9606': 'Homo sapiens',
    '10090': 'Mus musculus',
    '7227': 'Drosophila melanogaster',
    '6239': 'Caenorhabditis elegans',
};

export const DATA_OK = 'ok';
export const DATA_INSUFFICIENT = 'insufficient_data';

// Evidence types that count toward pleiotropy under each evidence filter (null = everything)
const ALLOWED_EVIDENCE = {
    experimental: new Set(['experimental']),
    computational: new Set(['computational', 'curatorial', 'IEA']),
    all: null,
};

const ESEARCH_URL = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi';

/** Exponential decay on the number of OTHER Biological Process terms: 0 = specific, 10 = broad. */
export function calculatePleiotropyScore(bpTermCount, maxTerms = 10, lambda = 0.3) {
    if (bpTermCount <= 0) return 0.0;
    if (bpTermCount === 1) return 0.0;
    const other = bpTermCount - 1;
    if (other >= maxTerms) return 10.0;
    return Math.min(10.0, 10.0 * (1 - Math.exp(-lambda * other)));
}

/** Inverse of pleiotropy on a 0-1 scale (1 = most specific). */
export function calculateSpecificityScore(pleiotropyScore) {
    return Math.max(0.0, Math.min(1.0, 1.0 - pleiotropyScore / 10.0));
}

/** Experimental evidence weighs 1.0, computational 0.6 and IEA predictions 0.3. */
export function calculateEvidenceQuality(scores) {
    const exp = scores.experimental_evidence_count || 0;
    const comp = scores.computational_evidence_count || 0;
    const iea = scores.iea_evidence_count || 0;
    const total = exp + comp + iea;
    if (total === 0) return 0.5;
    return Math.min(1.0, Math.max(0.0, (exp * 1.0 + comp * 0.6 + iea * 0.3) / total));
}

/**
 * Score one gene. `data_status` is "ok" or "insufficient_data"; a gene whose data could not be
 * retrieved gets no score (never a default that would make it look specific).
 */
export async function scoreGenePleiotropy(ctx, symbol, taxid, targetGoTerm = null, evidenceFilter = 'experimental', useMultiDatabase = true) {
    const result = {
        gene_symbol: symbol, taxid,
        data_status: DATA_INSUFFICIENT, data_issues: [], lookup_failed: false,
        bp_term_count: 0, other_bp_term_count: 0,
        pleiotropy_score: null, specificity_score: null,
        evidence_quality: 0.0,
        experimental_evidence_count: 0, computational_evidence_count: 0, iea_evidence_count: 0,
        kegg_pathway_count: 0, database_sources: [], bp_terms: [],
    };

    try {
        let bpTerms;
        let goSourcesFailed;

        if (useMultiDatabase) {
            const db = await queryGeneFromAllDatabases(ctx.http, ctx.keggProvider, symbol, taxid);
            bpTerms = db.combined_bp_terms || [];
            result.database_sources = Object.entries(db.query_status || {}).filter(([, v]) => v === 'success').map(([k]) => k);
            result.data_issues.push(...(db.data_issues || []));

            const evidence = db.combined_evidence || {};
            result.experimental_evidence_count = evidence.experimental || 0;
            result.computational_evidence_count = evidence.computational || 0;
            result.iea_evidence_count = evidence.IEA || 0;
            result.kegg_pathway_count = (db.kegg_data || {}).pathway_count || 0;

            goSourcesFailed = ['go', 'uniprot'].some((name) => String((db.query_status || {})[name] || '').startsWith('failed'));
        } else {
            const detailed = await getPleiotropyScoreDetailed(ctx.http, symbol, taxid);
            bpTerms = detailed.biological_process_terms || [];
            result.experimental_evidence_count = detailed.experimental_evidence_count || 0;
            result.computational_evidence_count = detailed.computational_evidence_count || 0;
            result.iea_evidence_count = detailed.iea_evidence_count || 0;
            result.database_sources = ['QuickGO'];
            goSourcesFailed = false;
        }

        result.bp_terms = bpTerms;
        result.bp_term_count = bpTerms.length;

        // Count only the BP terms supported by the requested evidence
        const allowed = ALLOWED_EVIDENCE[evidenceFilter];
        const counted = allowed ? bpTerms.filter((t) => allowed.has(t.evidence_type)) : bpTerms;
        const effective = counted.length;

        if (effective === 0) {
            if (bpTerms.length === 0) {
                if (goSourcesFailed) {
                    result.lookup_failed = true;
                    result.data_issues.push('No Biological Process data retrieved: a GO database could not be queried');
                } else {
                    result.data_issues.push('No Biological Process annotations found for this gene');
                }
            } else {
                result.data_issues.push(
                    `No Biological Process term has ${evidenceFilter} evidence (${bpTerms.length} term(s) found with other evidence)`);
            }
            return result;
        }

        result.other_bp_term_count = effective - 1;
        result.pleiotropy_score = calculatePleiotropyScore(effective);
        result.specificity_score = calculateSpecificityScore(result.pleiotropy_score);
        result.evidence_quality = calculateEvidenceQuality(result);
        result.data_status = DATA_OK;
        return result;
    } catch (error) {
        if (error && error.name === 'AbortError') throw error;
        result.error = String(error && error.message ? error.message : error);
        result.lookup_failed = true;
        result.data_issues.push(`Scoring failed: ${result.error}`);
        return result;
    }
}

/** Literature score (0-1) on a log scale: 1000 or more articles = 1.0, 100 = 0.67, 10 = 0.33, 1 or none = 0.0. */
export function literatureScoreFromCount(count) {
    if (count >= 1000) return 1.0;
    if (count > 0) return Math.min(1.0, Math.log10(count) / 3.0);
    return 0.0;
}

/** PubMed publication count -> a 0-1 literature score on a log scale (1000+ papers = 1.0). */
export async function getLiteratureSupport(ctx, symbol, taxid = '9606') {
    const result = { gene_symbol: symbol, pubmed_count: 0, literature_score: 0.0, query_status: 'pending' };
    try {
        const organism = taxid === '9606' ? 'human' : taxid === '10090' ? 'mouse' : '';
        const params = {
            db: 'pubmed',
            term: organism ? `${symbol}[Gene Name] AND ${organism}[Organism]` : `${symbol}[Gene Name]`,
            rettype: 'count',
            retmode: 'json',
        };
        if (ctx.ncbiApiKey) params.api_key = ctx.ncbiApiKey;

        const response = await ctx.http.get(ESEARCH_URL, { params });
        if (response.status === 200) {
            const count = parseInt(response.json().esearchresult?.count ?? 0, 10) || 0;
            result.pubmed_count = count;
            result.literature_score = literatureScoreFromCount(count);
            result.query_status = 'success';
        } else {
            result.query_status = `failed: HTTP ${response.status}`;
            result.literature_score = 0.5;
        }
    } catch (error) {
        if (error && error.name === 'AbortError') throw error;
        result.query_status = `failed: ${error.message}`;
        result.literature_score = 0.5;
    }
    return result;
}

async function validateInSpecies(ctx, symbol, targetGoTerm, taxid) {
    const result = {
        taxid, organism: MODEL_ORGANISMS[taxid] || 'Unknown', found: false,
        pleiotropy_score: null, specificity_score: null, bp_term_count: 0,
    };
    try {
        // "all" evidence: here we only ask whether the gene is annotated in this species
        const scoring = await scoreGenePleiotropy(ctx, symbol, taxid, targetGoTerm, 'all', false);
        if (scoring.data_status === DATA_OK) {
            result.found = true;
            result.pleiotropy_score = scoring.pleiotropy_score;
            result.specificity_score = scoring.specificity_score;
            result.bp_term_count = scoring.bp_term_count || 0;
        } else if (scoring.lookup_failed) {
            // the database could not be queried: this says nothing about the gene
            result.error = (scoring.data_issues || []).join('; ') || 'lookup failed';
        }
    } catch (error) {
        if (error && error.name === 'AbortError') throw error;
        result.error = String(error.message || error);
    }
    return result;
}

/** Is the gene found, and equally specific, in other species? A failed lookup is not "absent". */
export async function validateAcrossSpecies(ctx, symbol, targetGoTerm, speciesList = null) {
    const species = speciesList || Object.keys(MODEL_ORGANISMS);
    const results = {
        gene_symbol: symbol, target_go_term: targetGoTerm,
        species_results: {}, conservation_score: 0.0, specificity_consistency: 0.0, found_in_species: 0,
    };

    const outcomes = await Promise.all(species.map(async (taxid) => {
        try {
            return [taxid, await validateInSpecies(ctx, symbol, targetGoTerm, taxid)];
        } catch (error) {
            if (error && error.name === 'AbortError') throw error;
            return [taxid, { found: false, error: String(error.message || error) }];
        }
    }));

    const specificityScores = [];
    for (const [taxid, speciesResult] of outcomes) {
        results.species_results[taxid] = speciesResult;
        if (speciesResult.found) {
            results.found_in_species += 1;
            specificityScores.push(speciesResult.specificity_score ?? 0.5);
        }
    }

    const queried = Object.values(results.species_results).filter((r) => !r.error);
    results.species_queried = queried.length;
    results.lookup_errors = species.length - queried.length;
    results.conservation_score = queried.length ? results.found_in_species / queried.length : 0.0;

    if (specificityScores.length) {
        const mean = specificityScores.reduce((a, b) => a + b, 0) / specificityScores.length;
        const variance = specificityScores.reduce((a, s) => a + (s - mean) ** 2, 0) / specificityScores.length;
        results.specificity_consistency = Math.max(0, 1 - Math.sqrt(variance));
    }
    return results;
}

export function insufficientDataRecord(geneInfo, scoring = {}) {
    return {
        symbol: geneInfo.symbol || '',
        description: geneInfo.description || '',
        entrez_id: geneInfo.entrez_id || '',
        data_status: DATA_INSUFFICIENT,
        data_issues: scoring.data_issues || [],
        lookup_failed: scoring.lookup_failed || false,
        pleiotropy_score: null, specificity_score: null,
        evidence_quality: 0.0, literature_score: 0.0, conservation_score: 0.0, composite_score: 0.0,
        bp_term_count: scoring.bp_term_count || 0,
        other_bp_term_count: 0,
        experimental_evidence_count: scoring.experimental_evidence_count || 0,
        computational_evidence_count: scoring.computational_evidence_count || 0,
        iea_evidence_count: scoring.iea_evidence_count || 0,
        kegg_pathway_count: scoring.kegg_pathway_count || 0,
        pubmed_count: 0, specificity_consistency: 0.0,
        database_sources: scoring.database_sources || [],
        passes_threshold: false,
    };
}

async function rankSingleGene(ctx, geneInfo, taxid, targetGoTerm, evidenceFilter, includeLiterature, includeCrossSpecies, maxPleiotropy, factsLookup = null) {
    const symbol = geneInfo.symbol || '';
    if (!symbol) return null;

    try {
        const scoring = await scoreGenePleiotropy(ctx, symbol, taxid, targetGoTerm, evidenceFilter, true);
        if (scoring.data_status !== DATA_OK) return insufficientDataRecord(geneInfo, scoring);

        // Facts read from the evidence data files (the PubMed articles NCBI Gene links to the gene, and the model species
        // that carry an ortholog); a gene they do not know falls back to searching the databases
        const facts = (factsLookup ? await factsLookup(symbol) : null) || {};

        let literatureScore = 0.5;
        let pubmedCount = 0;
        if (includeLiterature) {
            if (facts.literature_count !== undefined && facts.literature_count !== null) {
                pubmedCount = facts.literature_count;
                literatureScore = literatureScoreFromCount(pubmedCount);
            } else {
                const literature = await getLiteratureSupport(ctx, symbol, taxid);
                literatureScore = literature.literature_score ?? 0.5;
                pubmedCount = literature.pubmed_count || 0;
            }
        }

        let conservationScore = 0.0;
        let specificityConsistency = 0.0;
        if (includeCrossSpecies) {
            if (facts.conservation !== undefined && facts.conservation !== null) {
                conservationScore = facts.conservation;
            } else {
                const cross = await validateAcrossSpecies(ctx, symbol, targetGoTerm);
                conservationScore = cross.conservation_score ?? 0.0;
                specificityConsistency = cross.specificity_consistency ?? 0.0;
            }
        }

        const specificity = scoring.specificity_score;
        const evidenceQuality = scoring.evidence_quality;
        const composite = specificity * 0.40 + evidenceQuality * 0.25 + literatureScore * 0.20 + conservationScore * 0.15;

        return {
            symbol,
            description: geneInfo.description || '',
            entrez_id: geneInfo.entrez_id || '',
            data_status: DATA_OK,
            data_issues: scoring.data_issues || [],
            pleiotropy_score: scoring.pleiotropy_score,
            specificity_score: specificity,
            evidence_quality: evidenceQuality,
            literature_score: literatureScore,
            conservation_score: conservationScore,
            composite_score: composite,
            bp_term_count: scoring.bp_term_count,
            other_bp_term_count: scoring.other_bp_term_count,
            experimental_evidence_count: scoring.experimental_evidence_count,
            computational_evidence_count: scoring.computational_evidence_count,
            iea_evidence_count: scoring.iea_evidence_count,
            kegg_pathway_count: scoring.kegg_pathway_count,
            pubmed_count: pubmedCount,
            specificity_consistency: specificityConsistency,
            database_sources: scoring.database_sources || [],
            passes_threshold: scoring.pleiotropy_score <= maxPleiotropy,
        };
    } catch (error) {
        if (error && error.name === 'AbortError') throw error;
        return insufficientDataRecord(geneInfo, { data_issues: [`Ranking failed: ${error.message}`], lookup_failed: true });
    }
}

/** Run `worker` over items with at most `limit` in flight; results keep the input order. */
export async function mapLimit(items, limit, worker) {
    const results = new Array(items.length);
    let next = 0;
    const runners = Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, async () => {
        for (;;) {
            const index = next++;
            if (index >= items.length) return;
            results[index] = await worker(items[index], index);
        }
    });
    await Promise.all(runners);
    return results;
}

/** Rank genes by a composite of specificity (40%), evidence (25%), literature (20%), conservation (15%). */
export async function rankGenesBySpecificity(ctx, geneList, taxid, options = {}) {
    const {
        targetGoTerm = null, evidenceFilter = 'experimental', includeLiterature = true,
        includeCrossSpecies = true, maxPleiotropyThreshold = 10, onProgress = null, concurrency = 6, factsLookup = null,
    } = options;

    let done = 0;
    const total = geneList.length;
    const records = await mapLimit(geneList, concurrency, async (geneInfo) => {
        const record = await rankSingleGene(ctx, geneInfo, taxid, targetGoTerm, evidenceFilter,
            includeLiterature, includeCrossSpecies, maxPleiotropyThreshold, factsLookup);
        done += 1;
        if (onProgress) onProgress('Scoring genes', done, total);
        return record;
    });

    const ranked = records.map((record, index) => ({ record, index })).filter(({ record }) => record);
    // scored genes first, highest composite score first (ties keep the GO-term order); unscorable genes last
    ranked.sort((a, b) => {
        const okA = a.record.data_status === DATA_OK ? 1 : 0;
        const okB = b.record.data_status === DATA_OK ? 1 : 0;
        if (okA !== okB) return okB - okA;
        if (a.record.composite_score !== b.record.composite_score) return b.record.composite_score - a.record.composite_score;
        return a.index - b.index;
    });
    return ranked.map(({ record }) => record);
}
