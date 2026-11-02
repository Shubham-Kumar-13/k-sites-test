/**
 * GO evidence-code classification (same rules as the Python package).
 *
 * IDA, IMP, IGI ... are experimental. IEA is an electronic *prediction* and never counts as
 * experimental evidence.
 */

export const EXPERIMENTAL_CODES = new Set(['IDA', 'IMP', 'IGI', 'IPI', 'IEP', 'EXP', 'HTP', 'HDA', 'HMP', 'HGI', 'HEP']);
export const COMPUTATIONAL_CODES = new Set(['ISS', 'ISO', 'ISA', 'ISM', 'IGC', 'IBA', 'IBD', 'IKR', 'IRD', 'RCA']);
export const CURATORIAL_CODES = new Set(['TAS', 'NAS', 'IC', 'ND']);
export const IEA_CODES = new Set(['IEA']);

/** Higher number = stronger evidence when the same GO term is seen several times. */
export const EVIDENCE_PRIORITY = { experimental: 4, computational: 3, curatorial: 2, IEA: 1, unknown: 0 };

/** Reduce 'IDA:UniProtKB' or 'ida' to the bare GO evidence code 'IDA'. */
export function normalizeCode(code) {
    if (!code) return '';
    return String(code).split(':')[0].trim().toUpperCase();
}

/** experimental > computational > curatorial > IEA > unknown, over a list of codes. */
export function classifyEvidence(codes) {
    const list = typeof codes === 'string' ? [codes] : (codes || []);
    const set = new Set(list.filter(Boolean).map(normalizeCode).filter(Boolean));
    if (set.size === 0) return 'unknown';
    for (const code of set) if (EXPERIMENTAL_CODES.has(code)) return 'experimental';
    for (const code of set) if (COMPUTATIONAL_CODES.has(code)) return 'computational';
    for (const code of set) if (CURATORIAL_CODES.has(code)) return 'curatorial';
    for (const code of set) if (IEA_CODES.has(code)) return 'IEA';
    return 'unknown';
}

/** A NOT qualifier says the gene is NOT involved in the process. */
export function isNotAnnotation(qualifier) {
    return String(qualifier || '').toUpperCase().split('|').includes('NOT');
}
