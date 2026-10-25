/**
 * Downloadable results: HTML report, CSV tables, JSON and Excel.
 * Equivalent of k_sites/reporting/report_generator.py.
 */

const SAFETY_CLASSES = {
    SAFE: 'safety-safe', CAUTION: 'safety-caution', MODERATE_CONCERN: 'safety-concern',
    HIGH_CONCERN: 'safety-warning', AVOID: 'safety-critical',
};

export const safetyClass = (level) => SAFETY_CLASSES[String(level || '').toUpperCase()] || 'safety-unknown';

export function safetyLabel(level) {
    const text = String(level || '').trim();
    if (!text) return 'Unknown';
    const spaced = text.replace(/_/g, ' ').toLowerCase();
    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

const escapeHtml = (value) => String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

const enumText = (value) => {
    if (value === null || value === undefined) return '';
    const text = typeof value === 'object' ? (value.value ?? '') : String(value);
    return text.includes('.') && /^(RiskLevel|PhenotypeSeverity)\./.test(text) ? text.split('.').pop() : text;
};

const num = (value, digits) => (typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '');

// ------------------------------------------------------------------ measured knockout evidence (as report columns)

export const CONTEXT_LABELS = { cells: 'cultured cells', organism: 'whole organism' };
export const BASIS_LABELS = {
    measured: 'Measured', ortholog: 'Measured in the mouse ortholog', distant: 'Mouse ortholog only (distant relative)',
    predicted: 'Predicted from the literature', none: 'Not verified',
};
export const EVIDENCE_HEADERS = [
    'Evidence_Basis', 'Knockout_Context', 'Organism_Knockout', 'Organism_Knockout_Stage', 'Organism_Knockout_Lines',
    'Organism_Knockout_Basis', 'Organism_Knockout_Sources', 'Organism_Phenotype_Systems', 'Cell_Essentiality',
    'Cell_Lines_Dependent_Percent', 'LOEUF', 'Expression_Tau', 'Expression_Pattern', 'Close_Paralogs',
    'Knockout_References', 'Knockout_Evidence',
];
export const EXCLUDED_HEADERS = ['Gene_Symbol', 'Gene_Description', 'Reason', 'Detail', 'Pleiotropy_Score', 'Composite_Score',
    'Organism_Knockout', 'Organism_Knockout_Stage', 'Cell_Essentiality', 'Knockout_Evidence'];

/** One line with everything measured: the organism result, then the cell-line result. */
export function evidenceSummary(evidence) {
    if (!evidence) return '';
    const parts = [];
    if (evidence.organism.call !== 'UNKNOWN') parts.push(evidence.organism.text);
    if (evidence.cells.call !== 'UNKNOWN') parts.push(evidence.cells.text);
    return parts.join(' | ');
}

/** The values for EVIDENCE_HEADERS of one gene (empty cells where nothing was measured). */
export function evidenceCells(gene) {
    const values = Object.fromEntries(EVIDENCE_HEADERS.map((header) => [header, '']));
    values.Evidence_Basis = (gene.safety_recommendation || {}).evidence_basis ?? '';
    const evidence = gene.knockout_evidence;
    if (evidence) {
        const { organism, cells, constraint, expression, paralogs } = evidence;
        const known = organism.call !== 'UNKNOWN';
        const counts = organism.counts;
        values.Knockout_Context = evidence.context;
        if (known) {
            values.Organism_Knockout = organism.call;
            if (organism.stage !== 'U' && organism.stage_text) values.Organism_Knockout_Stage = organism.stage_text;
            values.Organism_Knockout_Lines = `${counts.lethal} lethal, ${counts.subviable} subviable, ${counts.viable} viable`;
            values.Organism_Knockout_Basis = organism.basis === 'direct' ? 'direct' : `ortholog ${organism.ortholog.symbol} (${organism.ortholog.relation})`;
            values.Organism_Knockout_Sources = evidence.sources.filter((s) => organism.sources.includes(s.id)).map((s) => s.name).join('; ');
            values.Organism_Phenotype_Systems = organism.systems.join('; ');
            values.Knockout_References = organism.references.map((p) => `PMID:${p}`).join('; ');
        }
        if (cells.call !== 'UNKNOWN') {
            values.Cell_Essentiality = cells.call;
            values.Cell_Lines_Dependent_Percent = cells.percent;
        }
        if (constraint) values.LOEUF = constraint.loeuf;
        if (expression) {
            if (expression.tau !== null && expression.tau !== undefined) values.Expression_Tau = expression.tau;
            values.Expression_Pattern = expression.label;
        }
        if (paralogs) values.Close_Paralogs = paralogs.genes.map((g) => `${g.symbol} (${g.identity}%)`).join('; ');
        values.Knockout_Evidence = evidenceSummary(evidence);
    }
    return EVIDENCE_HEADERS.map((header) => values[header]);
}

/** The values for EXCLUDED_HEADERS of one gene that is assessed but not shown. */
export function excludedCells(entry) {
    const evidence = entry.knockout_evidence;
    const organism = (evidence && evidence.organism) || {};
    const cells = (evidence && evidence.cells) || {};
    const known = (organism.call || 'UNKNOWN') !== 'UNKNOWN';
    return [
        entry.symbol ?? '', entry.description ?? '', entry.reason ?? '', entry.detail ?? '',
        entry.pleiotropy_score ?? '', entry.composite_score ?? '',
        known ? organism.call : '',
        known && organism.stage && organism.stage !== 'U' && organism.stage_text ? organism.stage_text : '',
        (cells.call || 'UNKNOWN') !== 'UNKNOWN' ? cells.call : '',
        evidenceSummary(evidence),
    ];
}

const dataInfo = (results) => (results.metadata || {}).knockout_evidence_data || {};

// ------------------------------------------------------------------ CSV

function csvCell(value) {
    if (value === null || value === undefined) return '';
    const text = Array.isArray(value) ? value.join('; ') : String(value);
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

const csvLine = (cells) => cells.map(csvCell).join(',');

export function comprehensiveCsv(results) {
    const meta = results.metadata || {};
    const lines = [
        '# K-Sites Gene Selection Report',
        `# GO Term: ${meta.go_term ?? 'N/A'}`,
        `# Organism: ${meta.organism ?? 'N/A'}`,
        `# Timestamp: ${meta.timestamp ?? 'N/A'}`,
        `# Evidence Filter: ${meta.evidence_filter ?? 'N/A'}`,
        `# Pleiotropy cutoff (0-10): ${meta.max_pleiotropy ?? 'N/A'}`,
    ];
    const info = dataInfo(results);
    if (meta.knockout_context) lines.push(`# Knockout context: ${CONTEXT_LABELS[meta.knockout_context] || meta.knockout_context}`);
    if (info.available) lines.push(`# Measured knockout data version: ${info.version}; sources: ${(info.sources || []).map((s) => s.name).join('; ')}`);
    for (const warning of results.warnings || []) lines.push(`# WARNING: ${warning}`);
    lines.push('#');
    lines.push(csvLine([
        'Gene_Symbol', 'Gene_Description', 'Entrez_ID', 'Pleiotropy_Score', 'Specificity_Score', 'Evidence_Quality',
        'Literature_Score', 'Conservation_Score', 'Composite_Score', 'BP_Term_Count', 'Experimental_Evidence_Count',
        'Computational_Evidence_Count', 'IEA_Evidence_Count', 'KEGG_Pathway_Count', 'PubMed_Count',
        'Phenotype_Severity', 'Phenotype_Risk_Level', 'Phenotype_Confidence', 'Phenotype_Lethality_Stage',
        'Safety_Level', 'Safety_Recommendation', 'Safety_Justification', ...EVIDENCE_HEADERS,
    ]));
    for (const gene of results.genes || []) {
        const phenotype = gene.phenotype_prediction || {};
        const safety = gene.safety_recommendation || {};
        lines.push(csvLine([
            gene.symbol, gene.description, gene.entrez_id, gene.pleiotropy_score, gene.specificity_score, gene.evidence_quality,
            gene.literature_score, gene.conservation_score, gene.composite_score, gene.bp_term_count,
            gene.experimental_evidence_count, gene.computational_evidence_count, gene.iea_evidence_count,
            gene.kegg_pathway_count, gene.pubmed_count,
            enumText(phenotype.severity), enumText(phenotype.risk_level), phenotype.confidence_score, phenotype.lethality_stage,
            safety.safety_level, safety.primary_recommendation, safety.justification, ...evidenceCells(gene),
        ]));
    }
    const excluded = results.excluded_genes || [];
    if (excluded.length) {
        lines.push('');
        lines.push('# Genes not shown above (above the pleiotropy cutoff, or ranked below the genes shown)');
        lines.push(csvLine(EXCLUDED_HEADERS));
        for (const entry of excluded) lines.push(csvLine(excludedCells(entry)));
    }
    // comment lines are single cells: quoted when they contain a comma, like the Python report
    return lines.map((line) => (line.startsWith('#') ? csvCell(line) : line)).join('\n') + '\n';
}

export function geneSummaryCsv(results) {
    const lines = [csvLine([
        'gene_symbol', 'gene_description', 'entrez_id', 'pleiotropy_score', 'specificity_score', 'composite_score',
        'evidence_quality', 'literature_score', 'conservation_score', 'bp_term_count', 'experimental_evidence_count',
        'computational_evidence_count', 'iea_evidence_count', 'kegg_pathway_count', 'pubmed_count',
        'phenotype_severity', 'phenotype_risk_level', 'safety_level', 'safety_recommendation', 'safety_justification',
        ...EVIDENCE_HEADERS.map((h) => h.toLowerCase()),
    ])];
    for (const gene of results.genes || []) {
        const phenotype = gene.phenotype_prediction || {};
        const safety = gene.safety_recommendation || {};
        lines.push(csvLine([
            gene.symbol, gene.description, gene.entrez_id, gene.pleiotropy_score, gene.specificity_score, gene.composite_score,
            gene.evidence_quality, gene.literature_score, gene.conservation_score, gene.bp_term_count,
            gene.experimental_evidence_count, gene.computational_evidence_count, gene.iea_evidence_count,
            gene.kegg_pathway_count, gene.pubmed_count, enumText(phenotype.severity), enumText(phenotype.risk_level),
            safety.safety_level, safety.primary_recommendation, safety.justification, ...evidenceCells(gene),
        ]));
    }
    return lines.join('\n') + '\n';
}

// ------------------------------------------------------------------ HTML report

const STYLE = `
:root{--primary:#2c3e50;--accent:#3498db;--border:#dee2e6;--muted:#6c757d}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;line-height:1.6;color:#212529;padding:20px}
.container{max-width:1200px;margin:0 auto}
header{text-align:center;margin-bottom:30px;padding-bottom:20px;border-bottom:2px solid var(--border)}
h1{color:var(--primary);margin-bottom:10px;font-size:2.2em}
.subtitle{color:var(--muted);font-size:1.1em;margin-bottom:8px}
.summary-card{background:linear-gradient(135deg,#f5f7fa,#e4edf9);border-radius:10px;padding:20px;margin:20px 0;border-left:4px solid var(--accent)}
.summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:16px;margin-top:15px}
.summary-item{text-align:center;padding:15px;background:#fff;border-radius:8px}
.summary-value{font-size:1.8em;font-weight:bold;color:var(--primary)}
.summary-label{font-size:.9em;color:var(--muted)}
.section{margin:30px 0}
.section-title{color:var(--primary);border-bottom:2px solid var(--accent);padding-bottom:10px;margin-bottom:20px;font-size:1.5em}
table{width:100%;border-collapse:collapse;margin-bottom:20px;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,.1)}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--border);vertical-align:top}
th{background:var(--primary);color:#fff;font-weight:600}
tr:nth-child(even){background:#f8f9fa}
.safety-level{display:inline-block;padding:4px 10px;border-radius:12px;font-size:.8em;font-weight:bold;text-transform:uppercase}
.safety-safe{background:#d4edda;color:#155724}.safety-caution{background:#fff3cd;color:#856404}
.safety-concern{background:#ffe5d0;color:#8a4b08}.safety-warning{background:#f8d7da;color:#721c24}
.safety-critical{background:#dc3545;color:#fff}.safety-unknown{background:#e2e3e5;color:#41464b}
.bar{height:10px;background:#e9ecef;border-radius:5px;overflow:hidden;width:100px}.bar>div{height:100%;background:#28a745}
.justification{background:#f8f9fa;padding:8px;border-radius:4px;font-size:.9em;margin-top:5px;border-left:3px solid var(--accent)}
.basis{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.75em;font-weight:bold;margin-bottom:4px}
.basis-measured{background:#d4edda;color:#155724}.basis-ortholog{background:#d1ecf1;color:#0c5460}
.basis-predicted{background:#fff3cd;color:#856404}.basis-none,.basis-distant{background:#e2e3e5;color:#41464b}
.evidence-line{font-size:.88em;margin-top:3px}.evidence-refs{font-size:.8em;color:var(--muted);margin-top:3px}
.sources-list{font-size:.9em;color:var(--muted)}
.report-warning{background:#fff3cd;color:#664d03;border-left:4px solid #f39c12;border-radius:6px;padding:12px 16px;margin:20px 0}
footer{text-align:center;margin-top:40px;padding-top:20px;border-top:1px solid var(--border);color:var(--muted);font-size:.9em}
@media print{body{padding:0}}
`;

/** The measured knockout evidence of a gene (or of a gene left out of the ranking) as report HTML. */
export function evidenceHtml(entry) {
    const evidence = entry.knockout_evidence;
    let basis = (entry.safety_recommendation || {}).evidence_basis;
    if ((basis === undefined || basis === null) && evidence) {
        // genes left out of the ranking carry no verdict, so the basis is read from the evidence itself
        basis = 'none';
        if (evidence.has_measured) basis = evidence.organism.basis === 'direct' || evidence.cells.call !== 'UNKNOWN' ? 'measured' : 'ortholog';
        else if (evidence.organism.call !== 'UNKNOWN' && evidence.organism.distant) basis = 'distant';
    }
    basis = basis || 'none';
    const parts = [`<span class="basis basis-${escapeHtml(basis)}">${escapeHtml(BASIS_LABELS[basis] || basis)}</span>`];
    if (evidence) {
        for (const part of [evidence.organism, evidence.cells]) {
            if (part.call !== 'UNKNOWN') parts.push(`<div class="evidence-line">${escapeHtml(part.text)}</div>`);
        }
        const links = evidence.organism.references.map((p) => `<a href="https://pubmed.ncbi.nlm.nih.gov/${Number(p)}/">PMID ${Number(p)}</a>`);
        if (evidence.organism.mgi_id) links.push(`<a href="https://www.informatics.jax.org/marker/${escapeHtml(evidence.organism.mgi_id)}">MGI</a>`);
        if (links.length) parts.push(`<div class="evidence-refs">${links.join(' | ')}</div>`);
    }
    return parts.join('');
}

export function htmlReport(results) {
    const meta = results.metadata || {};
    const genes = results.genes || [];
    const stats = results.statistics || {};
    const notScored = results.insufficient_data_genes || [];
    const excluded = results.excluded_genes || [];
    const info = dataInfo(results);
    const contextHtml = meta.knockout_context
        ? ` | Knockout context: <strong>${escapeHtml(CONTEXT_LABELS[meta.knockout_context] || meta.knockout_context)}</strong>` : '';
    const levelOf = (g) => (g.safety_recommendation || {}).safety_level || '';
    const safe = genes.filter((g) => levelOf(g) === 'SAFE').length;
    const caution = genes.filter((g) => ['CAUTION', 'MODERATE_CONCERN'].includes(levelOf(g))).length;
    const concern = genes.filter((g) => ['HIGH_CONCERN', 'AVOID'].includes(levelOf(g))).length;
    const organism = (meta.resolved_organism && meta.resolved_organism.scientific_name) || meta.organism || 'Unknown';

    const warnings = (results.warnings || [])
        .map((w) => `<div class="report-warning"><strong>Warning:</strong> ${escapeHtml(w)}</div>`).join('');

    const rows = genes.map((gene, index) => {
        const safety = gene.safety_recommendation || {};
        const phenotype = gene.phenotype_prediction;
        const specificity = Math.max(0, Math.min(1, gene.specificity_score ?? 0));
        const phenotypeCell = phenotype
            ? `${escapeHtml(enumText(phenotype.severity))} (${escapeHtml(enumText(phenotype.risk_level))} risk, confidence ${num(phenotype.confidence_score, 2)})`
            : '-';
        const justification = (safety.justification || []).length
            ? `<div class="justification">${escapeHtml(safety.justification.join('; '))}</div>` : '';
        return `<tr>
            <td>${index + 1}</td>
            <td><strong>${escapeHtml(gene.symbol)}</strong><div style="color:var(--muted);font-size:.85em">${escapeHtml(gene.description)}</div></td>
            <td>${num(gene.pleiotropy_score, 2)}</td>
            <td>${num(gene.specificity_score, 3)}<div class="bar"><div style="width:${(specificity * 100).toFixed(0)}%"></div></div></td>
            <td>${num(gene.composite_score, 3)}</td>
            <td><span class="safety-level ${safetyClass(safety.safety_level)}">${escapeHtml(safetyLabel(safety.safety_level))}</span></td>
            <td>${evidenceHtml(gene)}</td>
            <td>${gene.kegg_pathway_count ?? 'N/A'}</td>
            <td>${phenotypeCell}</td>
            <td>${escapeHtml(safety.primary_recommendation || '')}${justification}</td>
        </tr>`;
    }).join('\n');

    const notScoredSection = notScored.length ? `
        <div class="section">
            <h2 class="section-title">Genes Not Scored (Insufficient Data)</h2>
            <p style="margin-bottom:15px;color:var(--muted)">These genes could not be assessed, so they are not ranked and have no safety level.
            "Lookup failed" means a database could not be reached; the gene may be fine on retry.</p>
            <table><thead><tr><th>Gene Symbol</th><th>Reason</th><th>Lookup Failed</th></tr></thead><tbody>
            ${notScored.map((g) => `<tr><td><strong>${escapeHtml(g.symbol)}</strong></td><td>${escapeHtml((g.reasons || []).join('; ') || 'No data')}</td><td>${g.lookup_failed ? 'Yes' : 'No'}</td></tr>`).join('\n')}
            </tbody></table>
        </div>` : '';

    const excludedSection = excluded.length ? `
        <div class="section">
            <h2 class="section-title">Genes Assessed but Not Shown</h2>
            <p style="margin-bottom:15px;color:var(--muted)">These genes were assessed too, but are not in the ranking above: either their pleiotropy score is above
            the cutoff, or they rank below the genes shown. Their measured knockout result is listed so that nothing is hidden.</p>
            <table><thead><tr><th>Gene Symbol</th><th>Why Not Shown</th><th>Measured Knockout Evidence</th></tr></thead><tbody>
            ${excluded.map((g) => `<tr><td><strong>${escapeHtml(g.symbol)}</strong></td><td>${escapeHtml(g.detail)}</td><td>${evidenceHtml(g)}</td></tr>`).join('\n')}
            </tbody></table>
        </div>` : '';
    const sourcesSection = (info.sources || []).length ? `
        <div class="section">
            <h2 class="section-title">Data Sources</h2>
            <p class="sources-list">Measured knockout data version ${escapeHtml(info.version)}.</p>
            <ul class="sources-list">${info.sources.map((s) => `<li><a href="${escapeHtml(s.url)}">${escapeHtml(s.name)}</a>: ${escapeHtml(s.what || '')}</li>`).join('')}</ul>
        </div>` : '';

    return `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>K-Sites Gene Selection Report - ${escapeHtml(meta.go_term)}</title><style>${STYLE}</style></head>
<body><div class="container">
<header>
    <h1>K-Sites Gene Selection Report</h1>
    <div class="subtitle">GO Term: <strong>${escapeHtml(meta.go_term)}</strong> | Organism: <strong>${escapeHtml(organism)}</strong> | Generated: ${escapeHtml(meta.timestamp || '')}</div>
    <div class="subtitle">Evidence Filter: <strong>${escapeHtml(meta.evidence_filter)}</strong> | Pleiotropy cutoff (0-10): <strong>${escapeHtml(meta.max_pleiotropy)}</strong>${contextHtml}</div>
</header>
${warnings}
<div class="summary-card"><h2>Executive Summary</h2><div class="summary-grid">
    <div class="summary-item"><div class="summary-value">${stats.total_genes_screened ?? genes.length}</div><div class="summary-label">Genes Screened</div></div>
    <div class="summary-item"><div class="summary-value">${safe}</div><div class="summary-label">Safe to Delete</div></div>
    <div class="summary-item"><div class="summary-value">${caution}</div><div class="summary-label">Proceed with Caution</div></div>
    <div class="summary-item"><div class="summary-value">${concern}</div><div class="summary-label">High Concern / Avoid</div></div>
    <div class="summary-item"><div class="summary-value">${notScored.length}</div><div class="summary-label">Not Scored (Insufficient Data)</div></div>
</div></div>
<div class="section">
    <h2 class="section-title">Gene Rankings</h2>
    <p style="margin-bottom:15px;color:var(--muted)">Ranked by a composite of specificity (40%), evidence quality (25%), literature support (20%) and conservation (15%).
    Specificity is on a 0-1 scale (higher = more specific, less pleiotropic).</p>
    <table><thead><tr><th>Rank</th><th>Gene</th><th>Pleiotropy (0-10)</th><th>Specificity (0-1)</th><th>Composite</th><th>Safety Level</th><th>Measured Knockout Evidence</th><th>KEGG Pathways</th><th>Predicted Knockout Phenotype</th><th>Recommendation</th></tr></thead>
    <tbody>${rows}</tbody></table>
</div>
${excludedSection}
${notScoredSection}
${sourcesSection}
<footer><p>K-Sites Gene Selection Platform | Non-Pleiotropic Gene Identification System</p>
<p>Execution time: ${num(meta.execution_duration, 2)}s | Evidence: ${escapeHtml(meta.evidence_filter)} | Pleiotropy cutoff (0-10): ${escapeHtml(meta.max_pleiotropy)}</p></footer>
</div></body></html>`;
}

// ------------------------------------------------------------------ Excel (SheetJS loaded only when needed)

const XLSX_URL = 'https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js';

async function loadSheetJs() {
    if (globalThis.XLSX) return globalThis.XLSX;
    await new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = XLSX_URL;
        script.onload = resolve;
        script.onerror = () => reject(new Error('The Excel library could not be loaded'));
        document.head.appendChild(script);
    });
    return globalThis.XLSX;
}

/** Returns a Uint8Array with an .xlsx workbook: Summary, Gene Rankings, Safety Recommendations. */
export async function excelWorkbook(results, xlsxLibrary = null) {
    const XLSX = xlsxLibrary || await loadSheetJs();
    const meta = results.metadata || {};
    const stats = results.statistics || {};
    const genes = results.genes || [];

    const summary = [
        ['K-Sites Gene Selection Report'], [],
        ['GO Term:', meta.go_term], ['Organism:', meta.organism], ['Timestamp:', meta.timestamp],
        ['Evidence Filter:', meta.evidence_filter], ['Pleiotropy cutoff (0-10):', meta.max_pleiotropy], [],
        ['Statistics'],
        ['Total Genes Screened:', stats.total_genes_screened ?? 0],
        ['Genes Passed Filter:', stats.genes_passed_filter ?? 0],
        ['Genes Not Scored:', stats.genes_insufficient_data ?? 0],
        ['Average Pleiotropy:', num(stats.avg_pleiotropy ?? 0, 2)],
        ...(meta.knockout_context ? [['Knockout context:', CONTEXT_LABELS[meta.knockout_context] || meta.knockout_context]] : []),
        ...(results.warnings || []).map((w) => ['WARNING:', w]),
    ];
    const rankings = [
        ['Rank', 'Gene Symbol', 'Pleiotropy Score', 'Specificity Score', 'Composite Score', 'Evidence Quality', 'Literature Score',
            'Conservation Score', 'BP Term Count', 'KEGG Pathways', 'Safety Level', 'Evidence Basis'],
        ...genes.map((g, i) => [i + 1, g.symbol, g.pleiotropy_score, g.specificity_score, g.composite_score, g.evidence_quality,
            g.literature_score, g.conservation_score, g.bp_term_count, g.kegg_pathway_count,
            (g.safety_recommendation || {}).safety_level || '', (g.safety_recommendation || {}).evidence_basis || '']),
    ];
    const safety = [
        ['Gene Symbol', 'Safety Level', 'Primary Recommendation', 'Justification', 'Concerns', 'Mitigation Strategies'],
        ...genes.map((g) => {
            const s = g.safety_recommendation || {};
            return [g.symbol, s.safety_level, s.primary_recommendation, (s.justification || []).join('; '),
                (s.concerns || []).join('; '), (s.mitigation_strategies || []).join('; ')];
        }),
    ];

    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet(summary), 'Summary');
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet(rankings), 'Gene Rankings');
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet(safety), 'Safety Recommendations');
    const evidenceRows = [['Gene Symbol', ...EVIDENCE_HEADERS], ...genes.map((g) => [g.symbol, ...evidenceCells(g)])];
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet(evidenceRows), 'Knockout Evidence');
    const excluded = results.excluded_genes || [];
    if (excluded.length) {
        XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([EXCLUDED_HEADERS, ...excluded.map(excludedCells)]), 'Genes Not Shown');
    }
    return new Uint8Array(XLSX.write(workbook, { type: 'array', bookType: 'xlsx' }));
}
