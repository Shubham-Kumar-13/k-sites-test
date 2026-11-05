const UNVERIFIED_BASES = new Set(['none', 'predicted', 'estimate']);
const SUPPORTED_BASES = new Set(['measured', 'essentiality']);

function scored(gene) {
    return (gene.data_status === undefined || gene.data_status === 'ok') && !gene.lookup_failed
        && typeof gene.composite_score === 'number' && Number.isFinite(gene.composite_score);
}

export function selectPotentialCandidates(genes, limit = 5) {
    const recommendation = (gene) => gene.safety_recommendation || {};
    const supported = genes.find((gene) => scored(gene)
        && ['SAFE', 'CAUTION'].includes(recommendation(gene).safety_level)
        && SUPPORTED_BASES.has(recommendation(gene).evidence_basis));
    const candidates = genes.filter((gene) => scored(gene)
        && recommendation(gene).safety_level === 'CAUTION'
        && UNVERIFIED_BASES.has(recommendation(gene).evidence_basis));
    candidates.sort((a, b) => b.composite_score - a.composite_score || String(a.symbol || '').localeCompare(String(b.symbol || '')));
    if (!supported || !candidates.length || candidates[0].composite_score <= supported.composite_score) return [];
    return candidates.slice(0, limit);
}
