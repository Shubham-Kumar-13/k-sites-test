/**
 * GO term -> genes (QuickGO), and the single-database per-gene GO lookup.
 * Port of k_sites/data_retrieval/go_gene_mapper.py.
 */

import { EVIDENCE_PRIORITY, classifyEvidence, isNotAnnotation } from './evidence.js';

export const QUICKGO_URL = 'https://www.ebi.ac.uk/QuickGO/services/annotation/search';
export const UNIPROT_URL = 'https://rest.uniprot.org/uniprotkb/search';
export const QUICKGO_PAGE_SIZE = 200;           // QuickGO rejects larger pages with HTTP 400
export const DEFAULT_MAX_ANNOTATIONS = 6000;    // safety limit; the user is warned when it stops the read

export class GoTermNotFoundError extends Error {
    constructor(message) { super(message); this.name = 'GoTermNotFoundError'; }
}
export class GeneRetrievalError extends Error {
    constructor(message) { super(message); this.name = 'GeneRetrievalError'; }
}

export function validateGoTerm(goTerm) {
    return /^GO:\d{7}$/.test(String(goTerm || '').toUpperCase());
}

async function getOrFail(http, url, params, what) {
    let response;
    try {
        response = await http.get(url, { params });
    } catch (error) {
        if (error && error.name === 'AbortError') throw error;
        throw new GeneRetrievalError(`${what} request failed: ${error.message}`);
    }
    return response;
}

/** One page of QuickGO annotations for a GO term. */
export async function fetchQuickGoPage(http, goTerm, taxid, page, pageSize = QUICKGO_PAGE_SIZE) {
    const response = await getOrFail(http, QUICKGO_URL, {
        goId: goTerm, taxonId: taxid, limit: pageSize, page, includeFields: 'name',
    }, 'QuickGO');
    if (response.status === 400 || response.status === 404) {
        throw new GoTermNotFoundError(`QuickGO rejected ${goTerm} for taxon ${taxid}: ${response.text.slice(0, 200)}`);
    }
    if (response.status !== 200) {
        throw new GeneRetrievalError(`QuickGO returned HTTP ${response.status} for ${goTerm}`);
    }
    const data = response.json();
    return { total: data.numberOfHits || 0, results: data.results || [] };
}

export function coverageInfo(total, read, limit) {
    const complete = read >= total;
    const info = {
        annotations_total: total,
        annotations_read: read,
        coverage: total === 0 ? 1.0 : Math.min(1.0, read / total),
        complete,
        limit,
        message: '',
    };
    if (!complete) {
        const percent = Math.min(99, Math.floor((100 * read) / total));   // never "100%" for an incomplete read
        info.message =
            `Only ${percent}% of annotations were read (${read.toLocaleString('en-US')} of ${total.toLocaleString('en-US')}). ` +
            'Genes that appear only in the unread part are missing from this analysis. ' +
            `Raise the limit (--max-annotations ${total}) to read everything; this takes longer.`;
    }
    return info;
}

function pickAccession(accessions) {
    const rank = (accession) => {
        const bare = accession.split(':').pop();
        return [bare.includes('-') ? 1 : 0, 'OPQ'.includes(bare.charAt(0)) && bare ? 0 : 1, bare.length, bare];
    };
    const sorted = [...accessions].sort((a, b) => {
        const ra = rank(a), rb = rank(b);
        for (let i = 0; i < ra.length; i++) {
            if (ra[i] < rb[i]) return -1;
            if (ra[i] > rb[i]) return 1;
        }
        return 0;
    });
    return sorted[0] || '';
}

const GENERIC_NAME_PARTS = ['isoform', 'domain-containing', 'cra_', 'fragment', 'uncharacterized'];

export function pickName(names, fallback = '') {
    for (const name of names) {
        if (name && !GENERIC_NAME_PARTS.some((part) => name.toLowerCase().includes(part))) return name;
    }
    return names.length ? names[0] : fallback;
}

/**
 * Merge QuickGO annotations into one entry per gene (QuickGO lists every protein variant of a
 * gene separately), applying the evidence filter and dropping NOT annotations.
 */
export function processAnnotations(allResults, evidenceFilter) {
    const experimental = new Set(['EXP', 'IDA', 'IPI', 'IMP', 'IGI', 'IEP', 'HTP', 'HDA', 'HMP', 'HGI', 'HEP']);
    const computational = new Set(['ISS', 'ISO', 'ISA', 'ISM', 'IGC', 'IBA', 'IBD', 'IKR', 'IRD', 'RCA']);
    const curatorial = new Set(['TAS', 'NAS', 'IC', 'ND', 'IEA']);
    const typePriority = { experimental: 3, computational: 2, curatorial: 1, other: 0 };

    const genes = new Map();
    const accessions = new Map();
    const names = new Map();

    for (const result of allResults) {
        if (isNotAnnotation(result.qualifier)) continue;

        const goEvidence = result.goEvidence || '';
        let type = 'other';
        if (experimental.has(goEvidence)) type = 'experimental';
        else if (computational.has(goEvidence)) type = 'computational';
        else if (curatorial.has(goEvidence)) type = 'curatorial';

        if (evidenceFilter === 'experimental' && type !== 'experimental') continue;
        if (evidenceFilter === 'computational' && !['computational', 'curatorial'].includes(type)) continue;

        const symbol = result.symbol || result.geneProductSymbol || '';
        const productId = result.geneProductId || '';
        if (!symbol || !productId) continue;
        if (isUnnamedRecord(symbol, productId)) continue;      // an unreviewed protein record without a gene name: it cannot be scored

        const key = symbol.toUpperCase();
        if (!accessions.has(key)) accessions.set(key, []);
        if (!accessions.get(key).includes(productId)) accessions.get(key).push(productId);
        if (!names.has(key)) names.set(key, []);
        if (result.name && !names.get(key).includes(result.name)) names.get(key).push(result.name);

        const existing = genes.get(key);
        if (existing) {
            if (goEvidence && !existing.evidence_codes.includes(goEvidence)) existing.evidence_codes.push(goEvidence);
            if (typePriority[type] > typePriority[existing.go_evidence_type]) existing.go_evidence_type = type;
        } else {
            genes.set(key, {
                symbol,
                entrez_id: productId,
                description: result.reference || '',
                evidence_codes: goEvidence ? [goEvidence] : [],
                go_evidence_type: type,
                qualifier: result.qualifier || '',
            });
        }
    }

    for (const [key, gene] of genes) {
        gene.entrez_id = pickAccession(accessions.get(key)) || gene.entrez_id;
        gene.description = pickName(names.get(key) || [], gene.description);
        gene.uniprot_accessions = accessions.get(key);
    }
    return [...genes.values()];
}

/** An unreviewed UniProt entry without a gene name: QuickGO then uses the accession (A8K1L8) as the symbol. */
export function isUnnamedRecord(symbol, productId) {
    const accession = String(productId || '').split(':').pop().split('-')[0];
    return !!symbol && !!accession && String(symbol).toUpperCase() === accession.toUpperCase();
}

/** How many distinct protein records without a gene name the annotations contain (they are not genes and are left out). */
export function countUnnamedRecords(results) {
    const names = new Set();
    for (const r of results) {
        const symbol = r.symbol || r.geneProductSymbol || '';
        if (isUnnamedRecord(symbol, r.geneProductId || '')) names.add(symbol);
    }
    return names.size;
}

/**
 * Genes annotated to a GO term, plus a report of how much of the term's annotations were read.
 * The safety limit stops very large terms early; `coverage.message` then says how much was read.
 */
export async function getGenesForGoTermWithCoverage(http, goTerm, taxid, evidenceFilter = 'experimental', options = {}) {
    const maxAnnotations = options.maxAnnotations ?? DEFAULT_MAX_ANNOTATIONS;
    const onProgress = options.onProgress || null;

    if (!validateGoTerm(goTerm)) {
        throw new Error(`Invalid GO term format: ${goTerm}. Expected format: GO:0000000`);
    }

    const first = await fetchQuickGoPage(http, goTerm, taxid, 1);
    if (first.results.length === 0 && first.total === 0) {
        return { genes: [], coverage: coverageInfo(0, 0, maxAnnotations) };
    }

    const pagesNeeded = Math.ceil(first.total / QUICKGO_PAGE_SIZE);
    const pagesAllowed = Math.max(1, Math.ceil(maxAnnotations / QUICKGO_PAGE_SIZE));
    const totalPages = Math.min(pagesNeeded, pagesAllowed);

    const all = [...first.results];
    let pagesDone = 1;
    if (onProgress) onProgress('Reading GO annotations', 1, totalPages);

    if (totalPages > 1) {
        const pageNumbers = [];
        for (let page = 2; page <= totalPages; page++) pageNumbers.push(page);
        // a failed page must fail the whole lookup, so every page is awaited without swallowing errors
        const pages = await Promise.all(pageNumbers.map(async (page) => {
            const result = await fetchQuickGoPage(http, goTerm, taxid, page);
            pagesDone += 1;
            if (onProgress) onProgress('Reading GO annotations', pagesDone, totalPages);
            return result;
        }));
        for (const page of pages) all.push(...page.results);
    }

    const coverage = coverageInfo(first.total, all.length, maxAnnotations);
    coverage.unnamed_records = countUnnamedRecords(all);
    const genes = processAnnotations(all, evidenceFilter);

    if (genes.length === 0 && evidenceFilter === 'experimental') {
        return getGenesForGoTermWithCoverage(http, goTerm, taxid, 'computational', options);
    }
    return { genes, coverage };
}

/** UniProt accession for a gene symbol; null if UniProt has no such gene. Throws if UniProt cannot be queried. */
export async function resolveGeneToUniprot(http, symbol, taxid) {
    for (const query of [
        `gene:${symbol} AND organism_id:${taxid} AND reviewed:true`,
        `gene:${symbol} AND organism_id:${taxid}`,
    ]) {
        const response = await getOrFail(http, UNIPROT_URL, { query, format: 'json', fields: 'accession', size: 1 }, 'UniProt');
        if (response.status !== 200) throw new GeneRetrievalError(`UniProt returned HTTP ${response.status} for ${symbol}`);
        const results = response.json().results || [];
        if (results.length) return results[0].primaryAccession;
    }
    return null;
}

/** Every GO term of a gene (all aspects), one entry per GO id with the strongest evidence kept. */
export async function getAllGoTermsForGene(http, symbol, taxid) {
    const accession = await resolveGeneToUniprot(http, symbol, taxid);
    if (!accession) return [];

    const all = [];
    let page = 1;
    for (;;) {
        const response = await getOrFail(http, QUICKGO_URL, {
            geneProductId: accession, limit: QUICKGO_PAGE_SIZE, page, includeFields: 'goName',
        }, 'QuickGO');
        if (response.status !== 200) {
            throw new GeneRetrievalError(`QuickGO returned HTTP ${response.status} for ${symbol}: ${response.text.slice(0, 200)}`);
        }
        const data = response.json();
        const results = data.results || [];
        if (!results.length) break;
        all.push(...results);
        if (all.length >= (data.numberOfHits || 0) || results.length < QUICKGO_PAGE_SIZE) break;
        page += 1;
        if (page > 50) break;
    }

    const terms = new Map();
    for (const result of all) {
        const goId = result.goId;
        if (!goId) continue;
        if (isNotAnnotation(result.qualifier)) continue;

        const code = result.goEvidence || '';
        const evidenceType = classifyEvidence([code]);
        const existing = terms.get(goId);
        if (existing) {
            if (code && !existing.evidence_codes.includes(code)) existing.evidence_codes.push(code);
            if ((EVIDENCE_PRIORITY[evidenceType] || 0) > (EVIDENCE_PRIORITY[existing.evidence_type] || 0)) {
                existing.evidence_type = evidenceType;
            }
            continue;
        }

        const aspect = result.goAspect || '';
        let category = 'U';
        if (aspect === 'biological_process' || aspect === 'P') category = 'P';
        else if (aspect === 'molecular_function' || aspect === 'F') category = 'F';
        else if (aspect === 'cellular_component' || aspect === 'C') category = 'C';

        terms.set(goId, {
            go_id: goId,
            go_name: result.goName || '',
            aspect,
            category,
            evidence_codes: code ? [code] : [],
            evidence_type: evidenceType,
            qualifiers: result.qualifier || '',
        });
    }
    return [...terms.values()];
}

/** Single-database pleiotropy inputs for a gene (used by the cross-species check). */
export async function getPleiotropyScoreDetailed(http, symbol, taxid) {
    const allTerms = await getAllGoTermsForGene(http, symbol, taxid);
    const bp = allTerms.filter((t) => t.category === 'P');
    const count = (type) => allTerms.filter((t) => t.evidence_type === type).length;
    return {
        gene_symbol: symbol,
        taxid,
        bp_term_count: bp.length,
        experimental_evidence_count: count('experimental'),
        computational_evidence_count: count('computational'),
        iea_evidence_count: count('IEA'),
        all_go_terms: allTerms,
        biological_process_terms: bp,
    };
}
