/**
 * Query QuickGO, UniProt and KEGG for one gene at the same time.
 * Port of k_sites/data_retrieval/multi_database_client.py.
 *
 * Each lookup returns data when it worked (including "gene not found") and throws
 * LookupFailure when the database itself could not be queried.
 */

import { EVIDENCE_PRIORITY, classifyEvidence, isNotAnnotation, normalizeCode } from './evidence.js';
import { QUICKGO_PAGE_SIZE, QUICKGO_URL, UNIPROT_URL } from './goMapper.js';

export class LookupFailure extends Error {
    constructor(message) { super(message); this.name = 'LookupFailure'; }
}

async function request(http, url, params, label) {
    try {
        return await http.get(url, { params });
    } catch (error) {
        if (error && error.name === 'AbortError') throw error;
        throw new LookupFailure(`${label} request failed: ${error.message}`);
    }
}

/** Accession of the reviewed (Swiss-Prot) entry, or null. */
export async function resolveReviewedAccession(http, symbol, taxid) {
    const response = await request(http, UNIPROT_URL, {
        query: `gene:${symbol} AND organism_id:${taxid} AND reviewed:true`,
        format: 'json', fields: 'accession', size: 1,
    }, 'UniProt');
    if (response.status !== 200) throw new LookupFailure(`UniProt returned HTTP ${response.status}`);
    const results = response.json().results || [];
    return results.length ? results[0].primaryAccession : null;
}

/** Every Biological Process annotation of a UniProt accession (paginated). */
async function fetchQuickGoBpAnnotations(http, accession) {
    const collected = [];
    let page = 1;
    for (;;) {
        const response = await request(http, QUICKGO_URL, {
            geneProductId: accession, aspect: 'biological_process',
            limit: QUICKGO_PAGE_SIZE, page, includeFields: 'goName',
        }, 'QuickGO');
        if (response.status !== 200) {
            throw new LookupFailure(`QuickGO returned HTTP ${response.status}: ${response.text.slice(0, 200)}`);
        }
        const data = response.json();
        const results = data.results || [];
        collected.push(...results);
        const total = data.numberOfHits ?? collected.length;
        if (!results.length || collected.length >= total || page >= 50) break;
        page += 1;
    }
    return collected;
}

export async function queryQuickGo(http, symbol, taxid) {
    const accession = await resolveReviewedAccession(http, symbol, taxid);
    if (!accession) {
        return { found: false, uniprot_id: null, annotations: [], bp_terms: [], bp_term_count: 0, total_annotations: 0 };
    }

    const raw = await fetchQuickGoBpAnnotations(http, accession);
    const annotations = [];
    for (const result of raw) {
        if (isNotAnnotation(result.qualifier)) continue;   // a NOT annotation says the gene is NOT involved
        const code = result.goEvidence || '';
        annotations.push({
            go_id: result.goId || '',
            go_name: result.goName || '',
            aspect: result.goAspect || 'biological_process',
            evidence_codes: code ? [code] : [],
            evidence_type: classifyEvidence([code]),
            source: 'QuickGO',
        });
    }
    return {
        found: true,
        uniprot_id: accession,
        total_annotations: annotations.length,
        bp_term_count: new Set(annotations.map((a) => a.go_id)).size,
        annotations,
        bp_terms: annotations,   // the request is already limited to Biological Process
    };
}

export async function queryUniprot(http, symbol, taxid) {
    const response = await request(http, UNIPROT_URL, {
        query: `gene:${symbol} AND organism_id:${taxid}`,
        format: 'json',
        fields: 'accession,id,gene_names,protein_name,go_p,go_f,go_c,organism_name',
        size: 10,
    }, 'UniProt');
    if (response.status !== 200) {
        throw new LookupFailure(`UniProt returned HTTP ${response.status}: ${response.text.slice(0, 200)}`);
    }

    const entries = [];
    const bpTerms = [];
    for (const result of response.json().results || []) {
        const goAnnotations = [];
        for (const ref of result.uniProtKBCrossReferences || []) {
            if (ref.database !== 'GO') continue;
            const properties = {};
            for (const p of ref.properties || []) properties[p.key] = p.value;
            const goTerm = properties.GoTerm || '';
            const evidence = properties.GoEvidenceType || '';   // e.g. "IDA:UniProtKB"

            let aspect = 'unknown';
            if (goTerm.startsWith('P:')) {
                aspect = 'P';
                bpTerms.push({
                    go_id: ref.id || '',
                    go_name: goTerm.slice(2),
                    aspect: 'biological_process',
                    evidence_codes: [normalizeCode(evidence)],
                    evidence_type: classifyEvidence([evidence]),
                    source: 'UniProt',
                });
            } else if (goTerm.startsWith('F:')) aspect = 'F';
            else if (goTerm.startsWith('C:')) aspect = 'C';

            goAnnotations.push({ go_id: ref.id || '', go_term: goTerm, aspect, evidence });
        }
        entries.push({ accession: result.primaryAccession || '', go_annotations: goAnnotations });
    }
    return {
        found: entries.length > 0,
        total_entries: entries.length,
        bp_term_count: new Set(bpTerms.map((t) => t.go_id)).size,
        entries,
        bp_terms: bpTerms,
    };
}

/** Pathways come from the data file built from KEGG (see tools/build_kegg_data.py). */
export async function queryKegg(keggProvider, symbol, taxid) {
    if (!keggProvider) return { found: false, pathway_count: 0, pathways: [], note: 'No KEGG data available' };
    try {
        const hit = await keggProvider(taxid, symbol);
        if (!hit) return { found: false, pathway_count: 0, pathways: [], note: `No KEGG data for taxid ${taxid}` };
        return { found: hit.found, pathway_count: hit.pathway_count || 0, pathways: hit.pathways || [], kegg_gene_id: hit.kegg_gene_id };
    } catch (error) {
        throw new LookupFailure(`KEGG data could not be loaded: ${error.message}`);
    }
}

/** Merge the BP terms of every source; the strongest evidence wins when a term is seen twice. */
export function combineBpTerms(results) {
    const merged = new Map();
    for (const key of ['go_data', 'uniprot_data']) {
        for (const term of (results[key] || {}).bp_terms || []) {
            const goId = term.go_id || '';
            if (!goId) continue;
            const type = term.evidence_type || 'unknown';
            const existing = merged.get(goId);
            if (!existing) {
                merged.set(goId, { ...term });
            } else if ((EVIDENCE_PRIORITY[type] || 0) > (EVIDENCE_PRIORITY[existing.evidence_type || 'unknown'] || 0)) {
                existing.evidence_type = type;
                existing.evidence_codes = term.evidence_codes || existing.evidence_codes || [];
                if (!existing.go_name) existing.go_name = term.go_name || '';
            }
        }
    }
    return [...merged.values()];
}

export function combineEvidence(results) {
    const counts = { experimental: 0, computational: 0, IEA: 0, curatorial: 0, unknown: 0 };
    for (const term of results.combined_bp_terms || []) {
        const type = term.evidence_type || 'unknown';
        counts[type] = (counts[type] || 0) + 1;
    }
    return counts;
}

export async function queryGeneFromAllDatabases(http, keggProvider, symbol, taxid) {
    const results = {
        gene_symbol: symbol, taxid,
        go_data: {}, uniprot_data: {}, kegg_data: {},
        combined_bp_terms: [], combined_evidence: {},
        query_status: {}, data_issues: [],
    };

    const jobs = [
        ['go', queryQuickGo(http, symbol, taxid)],
        ['uniprot', queryUniprot(http, symbol, taxid)],
        ['kegg', queryKegg(keggProvider, symbol, taxid)],
    ];
    const settled = await Promise.allSettled(jobs.map(([, promise]) => promise));
    settled.forEach((outcome, index) => {
        const name = jobs[index][0];
        if (outcome.status === 'fulfilled') {
            results[`${name}_data`] = outcome.value;
            results.query_status[name] = 'success';
        } else {
            if (outcome.reason && outcome.reason.name === 'AbortError') throw outcome.reason;
            const message = outcome.reason && outcome.reason.message ? outcome.reason.message : String(outcome.reason);
            results.query_status[name] = `failed: ${message}`;
            results.data_issues.push(`${name} lookup failed: ${message}`);
        }
    });

    results.combined_bp_terms = combineBpTerms(results);
    results.combined_evidence = combineEvidence(results);
    return results;
}
