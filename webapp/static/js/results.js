/**
 * K-Sites Web Application - Results Page JavaScript
 */

const CONTEXT_LABELS = { auto: 'Automatic', cells: 'Cultured cells', organism: 'Whole organism' };

// Global state
let currentJob = null;
let resultsData = null;
let statusCheckInterval = null;
let detailTaxids = null;   // taxids that have a built detailed-evidence file

// DOM Ready
document.addEventListener('DOMContentLoaded', function() {
    const jobId = document.getElementById('jobId')?.dataset.jobId
        || new URLSearchParams(window.location.search).get('job');

    if (!jobId) {
        showError('No job selected. Open a job from the Job History page.');
        return;
    }

    document.getElementById('jobId').dataset.jobId = jobId;
    fillJobFields({ id: jobId });
    const cancelButton = document.getElementById('cancelJobButton');
    if (cancelButton) cancelButton.addEventListener('click', () => cancelJob(jobId));

    // Load the list of organisms that have detailed source records
    loadDetailTaxids();

    // Check the job right away, then keep polling while it runs
    checkJobStatus(jobId).then(() => {
        if (currentJob && !['completed', 'failed'].includes(currentJob.status)) {
            startStatusPolling(jobId);
        }
    });
});

/** Fill the parameter table and header from the job record (the static page ships empty). */
function fillJobFields(job) {
    const values = {
        id: job.id,
        organism: job.organism,
        taxid: job.taxid,
        go_term: job.go_term,
        go_term_name: job.go_term_name,
        max_genes: job.max_genes,
        max_pleiotropy: job.max_pleiotropy,
        evidence_filter: job.evidence_filter,
        knockout_context: job.knockout_context === undefined ? undefined : (CONTEXT_LABELS[job.knockout_context] || job.knockout_context),
        predict_phenotypes: job.predict_phenotypes === undefined ? undefined : (job.predict_phenotypes ? 'Enabled' : 'Disabled'),
        selected_databases: job.selected_databases === undefined ? undefined : ((job.selected_databases || []).join(', ') || 'QuickGO'),
        total_genes_found: job.total_genes_found,
        genes_processed: job.genes_processed,
    };
    Object.keys(values).forEach(key => {
        const value = values[key];
        if (value === undefined) return;
        document.querySelectorAll(`[data-job-field="${key}"]`).forEach(el => {
            el.textContent = (value === null || value === '') ? '-' : value;
        });
    });
}

// ============================================================================
// Status Polling
// ============================================================================

function startStatusPolling(jobId) {
    statusCheckInterval = setInterval(() => {
        checkJobStatus(jobId);
    }, 3000); // Check every 3 seconds
}

function stopStatusPolling() {
    if (statusCheckInterval) {
        clearInterval(statusCheckInterval);
        statusCheckInterval = null;
    }
}

async function cancelJob(jobId) {
    if (!confirm('Stop this analysis? It cannot be resumed; you would start a new one.')) return;
    const btn = document.getElementById('cancelJobButton');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Cancelling...';
    }
    try {
        const response = await ksFetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            alert(data.error || 'Could not cancel the analysis.');
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-stop-circle me-2"></i>Cancel this analysis';
            }
            return;
        }
    } catch (error) {
        console.error('Error cancelling the job:', error);
        alert('Could not cancel the analysis. Please try again.');
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-stop-circle me-2"></i>Cancel this analysis';
        }
        return;
    }
    window.location.reload();
}

async function checkJobStatus(jobId) {
    try {
        const response = await ksFetch(`/api/jobs/${jobId}/status`);
        const data = await response.json();
        if (!response.ok) {
            showError(data.error || 'Could not load this job.');
            return;
        }
        
        currentJob = data;
        fillJobFields(data);
        updateStatusDisplay(data);
        updateProgressDisplay(data);
        
        if (data.status === 'completed') {
            stopStatusPolling();
            showResults(data);
            loadResults(jobId);
        } else if (data.status === 'failed') {
            stopStatusPolling();
            showError(data.error_message);
        } else if (data.status === 'cancelled' || data.status === 'cancelling') {
            stopStatusPolling();
            showCancelled(data);
        }
        
    } catch (error) {
        console.error('Error checking status:', error);
    }
}

function updateProgressDisplay(job) {
    // Update progress bar
    const progressBar = document.getElementById('progressBar');
    if (progressBar && job.progress_percent !== undefined) {
        progressBar.style.width = `${job.progress_percent}%`;
        progressBar.setAttribute('aria-valuenow', job.progress_percent);
        progressBar.textContent = `${job.progress_percent}%`;
    }
    
    // Update current step
    const currentStep = document.getElementById('currentStep');
    if (currentStep && job.current_step) {
        currentStep.textContent = job.current_step;
    }
    
    // Time elapsed (the run time depends on the databases, so no completion time is predicted)
    const elapsedDisplay = document.getElementById('elapsedDisplay');
    const elapsedTime = document.getElementById('elapsedTime');
    if (elapsedDisplay && elapsedTime && job.created_at) {
        const created = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(job.created_at) ? job.created_at : job.created_at + 'Z');
        const seconds = Math.max(0, Math.round((Date.now() - created.getTime()) / 1000));
        const minutes = Math.floor(seconds / 60);
        elapsedTime.textContent = minutes < 1 ? 'less than a minute' : `${minutes} min`;
        elapsedDisplay.style.display = 'block';
    }
    
    // Update step indicators
    const steps = [
        { pct: 5, selector: '#progressSteps li:nth-child(1)' },
        { pct: 15, selector: '#progressSteps li:nth-child(2)' },
        { pct: 30, selector: '#progressSteps li:nth-child(3)' },
        { pct: 60, selector: '#progressSteps li:nth-child(4)' },
        { pct: 85, selector: '#progressSteps li:nth-child(5)' },
        { pct: 100, selector: '#progressSteps li:nth-child(6)' }
    ];
    
    steps.forEach(step => {
        const el = document.querySelector(step.selector);
        if (el) {
            if (job.progress_percent >= step.pct) {
                el.classList.add('list-group-item-success');
                const icon = el.querySelector('i');
                if (icon) {
                    icon.className = 'fas fa-check-circle text-success me-2';
                }
            }
        }
    });
}

async function loadJobStatus(jobId) {
    try {
        const response = await ksFetch(`/api/jobs/${jobId}/status`);
        const data = await response.json();
        currentJob = data;
        
    } catch (error) {
        console.error('Error loading job status:', error);
    }
}

function updateStatusDisplay(job) {
    const badge = document.getElementById('statusBadge');
    if (badge) {
        badge.className = `status-badge status-${job.status}`;
        badge.textContent = job.status.toUpperCase();
    }
}

function showResults(job) {
    document.getElementById('loadingState').style.display = 'none';
    document.getElementById('errorState').style.display = 'none';
    document.getElementById('resultsContent').style.display = 'block';
    
    // Setup download links
    ksBindDownload('downloadHtml', job.id, 'html');
    ksBindDownload('downloadJson', job.id, 'json');
    ksBindDownload('downloadCsv', job.id, 'csv');
    ksBindDownload('downloadSummary', job.id, 'summary');
    ksBindDownload('downloadXlsx', job.id, 'xlsx');
}

function showError(message) {
    document.getElementById('loadingState').style.display = 'none';
    document.getElementById('resultsContent').style.display = 'none';
    document.getElementById('errorState').style.display = 'block';
    document.getElementById('errorMessage').textContent = message || 'Unknown error occurred';
}

function showCancelled(job) {
    document.getElementById('loadingState').style.display = 'none';
    document.getElementById('resultsContent').style.display = 'none';
    document.getElementById('errorState').style.display = 'block';
    const msg = job.status === 'cancelling'
        ? 'Cancelling the analysis... The page will update once it stops.'
        : 'This analysis was cancelled. You can start a new one from the home page.';
    document.getElementById('errorMessage').textContent = msg;
}

function addLogEntry(message) {
    const log = document.getElementById('progressLog');
    if (log) {
        const entry = document.createElement('div');
        entry.className = 'mb-1';
        entry.innerHTML = `<span class="text-muted">[${new Date().toLocaleTimeString()}]</span> ${message}`;
        log.appendChild(entry);
        log.scrollTop = log.scrollHeight;
    }
}

// ============================================================================
// Load and Display Results
// ============================================================================

function renderSafetyDist(genes) {
    const container = document.getElementById('safetyDist');
    if (!container) return;
    if (!genes || genes.length === 0) {
        container.innerHTML = '<span style="color:var(--ks-muted);font-size:12px;">No data</span>';
        return;
    }
    const order = ['SAFE', 'CAUTION', 'MODERATE_CONCERN', 'HIGH_CONCERN', 'AVOID'];
    const colors = {
        SAFE: 'var(--v-safe)',
        CAUTION: 'var(--v-info)',
        MODERATE_CONCERN: 'var(--v-warn)',
        HIGH_CONCERN: 'var(--v-bad)',
        AVOID: '#9e0059'
    };
    const counts = {};
    genes.forEach(g => {
        const level = (g.safety_recommendation || {}).safety_level || 'UNKNOWN';
        counts[level] = (counts[level] || 0) + 1;
    });
    const total = genes.length;
    const segments = order
        .filter(level => counts[level])
        .map(level => {
            const pct = (counts[level] / total) * 100;
            return `<i style="width:${pct.toFixed(2)}%;background:${colors[level]};" title="${esc(safetyLabel(level))}: ${counts[level]}"></i>`;
        }).join('');
    const legend = order
        .filter(level => counts[level])
        .map(level => `<span><b style="background:${colors[level]}"></b>${esc(safetyLabel(level))} ${counts[level]}</span>`)
        .join('');
    container.innerHTML = `<div class="bar">${segments}</div><div class="leg">${legend}</div>`;
}

function renderLandscape(genes, cutoff) {
    const section = document.getElementById('geneLandscape');
    const svg = document.getElementById('geneLandscapeSvg');
    if (!section || !svg) return;
    if (!genes || genes.length === 0) {
        section.hidden = true;
        return;
    }
    const valid = genes.filter(g =>
        typeof g.pleiotropy_score === 'number' &&
        typeof g.composite_score === 'number' &&
        !isNaN(g.pleiotropy_score) &&
        !isNaN(g.composite_score)
    );
    if (valid.length === 0) {
        section.hidden = true;
        return;
    }
    section.hidden = false;

    const W = 680, H = 320, L = 50, R = 14, T = 12, B = 46;
    const pw = W - L - R, ph = H - T - B;
    const maxP = 10;
    const pleio = cutoff ?? 5;

    function X(v) { return L + (v / maxP) * pw; }
    function Y(v) { return T + (1 - v) * ph; }

    // Deterministic pseudo-random from a string so jitter is stable across re-renders.
    function hashRandom(s) {
        let h = 2166136261;
        for (let i = 0; i < s.length; i++) {
            h ^= s.charCodeAt(i);
            h = Math.imul(h, 16777619);
        }
        const n = (h >>> 0) / 4294967296;
        return n;
    }

    const levelClass = {
        SAFE: 's',
        CAUTION: 'c',
        MODERATE_CONCERN: 'm',
        HIGH_CONCERN: 'h',
        AVOID: 'h'
    };
    const levelName = {
        SAFE: 'Safe',
        CAUTION: 'Caution',
        MODERATE_CONCERN: 'Moderate concern',
        HIGH_CONCERN: 'High concern',
        AVOID: 'Avoid'
    };
    const shapes = {
        s: '<circle r="4.2"',
        c: '<rect x="-3.6" y="-3.6" width="7.2" height="7.2"',
        m: '<path d="M0-5.2L5.2 0 0 5.2-5.2 0z"',
        h: '<path d="M0-5.2L5 4h-10z"'
    };

    const pts = valid.map(g => {
        const r1 = hashRandom(g.symbol + 'x');
        const r2 = hashRandom(g.symbol + 'y');
        const xJitter = (r1 - 0.5) * 0.35;
        const yJitter = (r2 - 0.5) * 0.025;
        return {
            x: Math.max(0.05, Math.min(maxP - 0.05, g.pleiotropy_score + xJitter)),
            y: Math.max(0.02, Math.min(0.99, g.composite_score + yJitter)),
            rawX: g.pleiotropy_score,
            rawY: g.composite_score,
            symbol: g.symbol,
            level: (g.safety_recommendation || {}).safety_level || 'UNKNOWN',
            cls: levelClass[(g.safety_recommendation || {}).safety_level] || 'h'
        };
    });

    pts.sort((a, b) => b.y - a.y);
    pts.forEach((p, i) => { p.rank = i + 1; });

    const rank1 = pts[0];
    const passing = pts.filter(p => p.rawX <= pleio);
    const lastPass = passing.length ? passing[passing.length - 1] : null;
    const lastOverall = pts[pts.length - 1];
    [rank1, lastPass, lastOverall].forEach(p => { if (p) p.label = `${p.symbol} (#${p.rank})`; });

    pts.sort((a, b) => a.x - b.x);

    let o = `<rect class="ks-ex" x="${X(pleio)}" y="${T}" width="${X(maxP) - X(pleio)}" height="${ph}"/>`;
    [0, 0.25, 0.5, 0.75, 1].forEach(v => {
        o += `<line class="ks-gr" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/>`;
        o += `<text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end">${v.toFixed(2)}</text>`;
    });
    for (let v = 0; v <= maxP; v++) {
        const y2 = T + ph + (v % 2 === 0 ? 6 : 3);
        o += `<line class="ks-ax" x1="${X(v)}" x2="${X(v)}" y1="${T + ph}" y2="${y2}"/>`;
        if (v % 2 === 0) o += `<text x="${X(v)}" y="${T + ph + 19}" text-anchor="middle">${v}</text>`;
    }
    o += `<line class="ks-ax" x1="${L}" x2="${W - R}" y1="${T + ph}" y2="${T + ph}"/>`;
    o += `<line class="ks-ax" x1="${L}" x2="${L}" y1="${T}" y2="${T + ph}"/>`;
    o += `<line class="ks-cut" x1="${X(pleio)}" x2="${X(pleio)}" y1="${T}" y2="${T + ph}"/>`;
    o += `<text x="${X(pleio) + 6}" y="${T + 12}" style="fill:var(--ks-magenta,#e83e8c)">cutoff ${pleio}</text>`;
    o += `<text class="ks-ttl" x="${L + pw / 2}" y="${H - 6}" text-anchor="middle">Pleiotropy score (0 to 10)</text>`;
    o += `<text class="ks-ttl" transform="translate(12 ${T + ph / 2}) rotate(-90)" text-anchor="middle">Composite score (0 to 1)</text>`;

    pts.forEach((p, i) => {
        const labelRing = p.label ? `<circle r="9" fill="none" stroke="var(--ks-fg)" stroke-width="1.5"/>` : '';
        const aria = `${p.symbol} rank ${p.rank}: pleiotropy ${p.rawX.toFixed(2)}, composite ${p.rawY.toFixed(2)}, ${levelName[p.level] || 'unknown'}`;
        o += `<g transform="translate(${X(p.x).toFixed(1)} ${Y(p.y).toFixed(1)})">${labelRing}${shapes[p.cls]} class="ks-pt ${p.cls}" data-n="${esc(p.symbol)}" data-rank="${p.rank}" data-x="${p.rawX.toFixed(2)}" data-y="${p.rawY.toFixed(2)}" role="img" aria-label="${esc(aria)}"/></g>`;
    });
    pts.forEach(p => {
        if (p.label) o += `<text class="ks-pin" x="${X(p.x) + 9}" y="${Y(p.y) + 4}">${esc(p.label)}</text>`;
    });
    svg.innerHTML = o;

    const tip = document.getElementById('geneLandscapeTip');
    const wrap = svg.parentNode;
    svg.onmouseover = function (e) {
        const t = e.target.closest && e.target.closest('.ks-pt');
        if (!t || !tip) return;
        const a = t.getBoundingClientRect();
        const w = wrap.getBoundingClientRect();
        tip.innerHTML = `<b>${t.getAttribute('data-n')} (#${t.getAttribute('data-rank')})</b><br>Pleiotropy ${t.getAttribute('data-x')}<br>Composite ${t.getAttribute('data-y')}`;
        tip.style.left = (a.left + a.width / 2 - w.left) + 'px';
        tip.style.top = (a.top - w.top) + 'px';
        tip.hidden = false;
    };
    svg.onmouseout = function (e) {
        if (e.target.closest && e.target.closest('.ks-pt') && tip) tip.hidden = true;
    };
}

function renderPotentialCandidates(data) {
    const container = document.getElementById('potentialContainer');
    if (!container) return;
    const candidates = (data && data.potential_candidates) || [];
    if (!candidates.length) {
        container.innerHTML = '<div class="text-center py-5" style="color:var(--ks-muted);">No unverified genes outscored the best experimentally supported candidate</div>';
        return;
    }
    const cards = candidates.map((gene, index) => {
        const safety = gene.safety_recommendation || {};
        return `<article class="ks-gcard">
            <div class="ks-gbody">
                <div class="ks-ghead">
                    <div class="ks-rk">${index + 1}</div>
                    <div class="ks-gtitle">
                        <h5>${esc(gene.symbol)}</h5>
                        <p>${esc(gene.description || 'No description available')}</p>
                    </div>
                    <div class="ks-gright">
                        <div class="ks-gauge">
                            <span>Pleiotropy</span>
                            <span class="tr"><i style="width:${pleiotropyPercent(gene.pleiotropy_score)}%;background:${pleiotropyColor(gene.pleiotropy_score)}"></i></span>
                            <b>${gene.pleiotropy_score?.toFixed(2) || 'N/A'}</b>
                        </div>
                        <span class="ks-b ${safetyKsClass(safety.safety_level)}">${safetyLabel(safety.safety_level)}</span>
                    </div>
                </div>
                ${compositeFormulaLine(gene)}
                <p style="color:var(--ks-muted);font-size:13.5px;margin-top:10px;"><i class="fas fa-flask me-1"></i>Higher composite than the best viable experimentally supported candidate, but no direct knockout measurement for this gene.</p>
            </div>
        </article>`;
    }).join('');
    container.innerHTML = `<div class="ks-note ks-warn" style="margin-bottom:18px;">
        <i class="fas fa-exclamation-triangle"></i>
        <span class="ks-grow"><strong>Top ${candidates.length} promising candidates — unverified.</strong> These genes have favourable composite scores but no direct knockout measurement. They are candidates for experimental validation, not confirmed safe knockout targets.</span>
    </div>${cards}`;
}

async function loadResults(jobId) {
    try {
        const response = await ksFetch(`/api/jobs/${jobId}/results`);
        const data = await response.json();
        
        if (data.error) {
            showError(data.error);
            return;
        }
        
        resultsData = data.results;

        // "Automatic" is shown together with what it turned out to mean for this organism
        const resolved = resultsData.metadata && resultsData.metadata.knockout_context;
        if (resolved) {
            const chosen = (currentJob && currentJob.knockout_context) || 'auto';
            const label = chosen === 'auto' ? `Automatic (${CONTEXT_LABELS[resolved].toLowerCase()})` : CONTEXT_LABELS[chosen];
            document.querySelectorAll('[data-job-field="knockout_context"]').forEach(el => { el.textContent = label; });
        }

        renderGenes(resultsData.genes);
        renderSafetyDist(resultsData.genes);
        renderLandscape(resultsData.genes, currentJob?.max_pleiotropy ?? 5);
        renderExcluded(resultsData.excluded_genes);
        renderInsufficientData(resultsData.insufficient_data_genes);
        renderSources(resultsData.metadata);
        renderWarnings(resultsData.warnings);
        renderSummary(resultsData);
        renderPotentialCandidates(resultsData);
        updateRerunLink();
        
    } catch (error) {
        console.error('Error loading results:', error);
    }
}

function updateRerunLink() {
    if (!currentJob) return;
    const params = new URLSearchParams();
    params.set('rerun', '1');
    params.set('taxid', currentJob.taxid || '');
    params.set('organism', currentJob.organism || '');
    params.set('go_term', currentJob.go_term || '');
    params.set('go_term_name', currentJob.go_term_name || '');
    params.set('max_genes', String(currentJob.max_genes ?? 10));
    params.set('max_pleiotropy', String(currentJob.max_pleiotropy ?? 5));
    params.set('evidence_filter', currentJob.evidence_filter || 'experimental');
    params.set('knockout_context', currentJob.knockout_context || 'auto');
    params.set('predict_phenotypes', currentJob.predict_phenotypes ? 'true' : 'false');
    params.set('databases', (currentJob.selected_databases || ['quickgo']).join(','));
    const button = document.getElementById('rerunAnalysisButton');
    if (button) {
        button.href = (window.KSITES && window.KSITES.page ? window.KSITES.page('home') : '/') + '?' + params.toString();
        button.style.display = '';
    }
}

// ============================================================================
// Measured knockout evidence
// ============================================================================

function esc(value) {
    return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

const CALL_BADGES = {
    // Whole-animal context: is the gene required for survival/development?
    LETHAL: ['bg-danger', '<i class="fas fa-skull-crossbones me-1"></i>Essential for survival'],
    SUBVIABLE: ['bg-warning text-dark', '<i class="fas fa-exclamation-triangle me-1"></i>Partially essential'],
    VIABLE: ['bg-success', '<i class="fas fa-check-circle me-1"></i>Non-essential'],
    // Cell-line context: is the gene required for cell proliferation?
    ESSENTIAL: ['bg-danger', '<i class="fas fa-skull-crossbones me-1"></i>Essential in cells'],
    SELECTIVE: ['bg-warning text-dark', '<i class="fas fa-adjust me-1"></i>Context-dependent essential'],
    NON_ESSENTIAL: ['bg-success', '<i class="fas fa-check-circle me-1"></i>Non-essential in cells'],
    OBSERVATION: ['bg-info text-dark', '<i class="fas fa-eye me-1"></i>Observation'],
    UNKNOWN: ['bg-secondary', '<i class="fas fa-question-circle me-1"></i>No data'],
};
const BASIS_BADGES = {
    measured: ['bg-success', 'Direct knockout/deletion'],
    essentiality: ['bg-info text-dark', 'Experimental essentiality (not a clean knockout)'],
    ortholog: ['bg-info text-dark', 'Measured in the mouse ortholog'],
    distant: ['bg-secondary', 'Mouse ortholog only (distant relative)'],
    predicted: ['bg-warning text-dark', 'Predicted from the literature'], none: ['bg-secondary', 'Not verified'],
    estimate: ['bg-warning text-dark', 'Estimated from data (not measured)'],
};

function compositeFormulaLine(gene) {
    const s = (gene.specificity_score ?? 0).toFixed(2);
    const e = (gene.evidence_quality ?? 0).toFixed(2);
    const l = (gene.literature_support ?? 0).toFixed(2);
    const c = (gene.conservation_score ?? 0).toFixed(2);
    const comp = (gene.composite_score ?? 0).toFixed(2);
    return `<div class="ks-formula">
        <strong>Composite ${comp}</strong>
        <span style="color:var(--ks-muted);"> = 
            0.40 × Specificity <strong>${s}</strong> +
            0.25 × Evidence <strong>${e}</strong> +
            0.20 × Literature <strong>${l}</strong> +
            0.15 × Conservation <strong>${c}</strong>
        </span>
    </div>`;
}

function initializeTooltips(root = document) {
    root.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
        if (!bootstrap.Tooltip.getInstance(el)) {
            new bootstrap.Tooltip(el);
        }
    });
}

function callBadge(call) {
    const [cls, label] = CALL_BADGES[call] || CALL_BADGES.UNKNOWN;
    return `<span class="badge ${cls} me-1">${label}</span>`;
}

function geneInfoChip(icon, label, value, subtext) {
    return `<div class="ks-ichip">
        <span style="color:var(--ks-muted);display:block;margin-bottom:2px;"><i class="fas ${icon} me-1"></i>${esc(label)}</span>
        <b>${esc(value)}</b>
        ${subtext ? `<span>(${esc(subtext)})</span>` : ''}
    </div>`;
}

function referenceLinks(organism, symbol = '', taxid = '') {
    const links = (organism.references || []).map(p => `<a href="https://pubmed.ncbi.nlm.nih.gov/${Number(p)}/" target="_blank" rel="noopener">PMID ${Number(p)}</a>`);
    if (organism.mgi_id) links.push(`<a href="https://www.informatics.jax.org/marker/${esc(organism.mgi_id)}" target="_blank" rel="noopener">MGI</a>`);

    // Organism-specific model-organism database links when the gene symbol is known.
    const safeSymbol = encodeURIComponent(symbol);
    const dbLinks = {
        '10090': [`https://www.informatics.jax.org/search?term=${safeSymbol}`, 'MGI'],
        '10116': [`https://rgd.mcw.edu/rgdweb/elasticResults.html?term=${safeSymbol}`, 'RGD'],
        '7227': [`https://flybase.org/reports/${safeSymbol}.html`, 'FlyBase'],
        '6239': [`https://wormbase.org/species/c_elegans/gene/${safeSymbol}`, 'WormBase'],
        '7955': [`https://zfin.org/search?query=${safeSymbol}`, 'ZFIN'],
        '4932': [`https://www.yeastgenome.org/search?q=${safeSymbol}`, 'SGD'],
        '559292': [`https://www.yeastgenome.org/search?q=${safeSymbol}`, 'SGD'],
        '4896': [`https://www.pombase.org/search/ensembl/${safeSymbol}`, 'PomBase'],
        '3702': [`https://www.arabidopsis.org/servlets/Search?type=general&search_action=detail&name=${safeSymbol}`, 'TAIR'],
    };
    if (taxid && dbLinks[taxid]) {
        const [url, name] = dbLinks[taxid];
        links.push(`<a href="${url}" target="_blank" rel="noopener">${name}</a>`);
    }

    return links.length ? ` <span class="text-muted">(${links.join(', ')})</span>` : '';
}

function detailedEvidenceHtml(data) {
    const evidence = data.evidence;
    const records = evidence.records.map(record => {
        const insertion = record.experiment_type === 'transposon_insertion_essentiality' || record.experiment_type === 'Tn-seq essentiality';
        const evidenceLevel = insertion ? 'experimental insertion essentiality' : record.evidence_level;
        const metadata = [record.experiment_type, record.zygosity, evidenceLevel,
            record.stage ? `stage ${record.stage}` : null, ...(record.qualifiers || [])]
            .filter(Boolean).map(value => esc(String(value).replaceAll('_', ' '))).join(' · ');
        const references = (record.references || []).map(pmid =>
            `<a href="https://pubmed.ncbi.nlm.nih.gov/${Number(pmid)}/" target="_blank" rel="noopener">PMID ${Number(pmid)}</a>`).join(', ');
        const alleles = (record.alleles || []).map(allele => `${esc(allele.symbol)} (${esc(allele.class || 'unknown')})`).join(', ');
        const geneticDetails = [
            record.genotype ? `genotype ${esc(record.genotype)}` : '',
            alleles ? `alleles ${alleles}` : '',
            record.background ? `background ${esc(record.background)}` : ''
        ].filter(Boolean).join(' · ');
        const impc = [record.phenotyping_center, record.parameter_stable_id,
            record.p_value ? `p=${record.p_value}` : null].filter(Boolean).map(esc).join(' · ');
        const extra = [impc, references].filter(Boolean).join(' · ');
        return `<div class="ks-det">
            <div class="ks-dh">${callBadge(record.call)}<strong>${esc(record.source)}: ${esc(record.source_record_id)}</strong><span class="ks-dm">${metadata}${geneticDetails ? ` · ${geneticDetails}` : ''}</span></div>
            <div class="ks-dl">${esc(record.phenotype)}${extra ? `<span class="ks-dr"> · ${extra}</span>` : ''}</div>
        </div>`;
    }).join('');
    return `<div class="ks-note ks-plain" style="margin-bottom:8px;padding:8px 12px;"><i class="fas fa-database" style="color:var(--ks-muted);"></i><span class="ks-grow">${esc(evidence.call)} · ${evidence.records.length} source record(s) · release ${esc(data.version)}</span></div>${records}`;
}

async function loadDetailTaxids() {
    try {
        const response = await ksFetch('/api/evidence/details/available');
        if (!response.ok) return;
        const data = await response.json();
        detailTaxids = new Set(data.taxids || []);
    } catch (error) {
        detailTaxids = new Set();
    }
    // If results were already rendered before the list loaded, refresh the gene cards so
    // the "Detailed source records" button is shown or hidden accurately.
    if (resultsData && resultsData.genes) {
        renderGenes(resultsData.genes);
    }
}

async function loadDetailedEvidence(container) {
    const body = container.querySelector('.detailed-evidence-body');
    if (!body || container.dataset.loaded) return;
    container.dataset.loaded = 'loading';
    body.textContent = 'Loading detailed source records...';
    try {
        const response = await ksFetch(`/api/evidence/details?taxid=${encodeURIComponent(container.dataset.taxid)}&symbol=${encodeURIComponent(container.dataset.symbol)}`);
        const data = await response.json();
        if (!response.ok) {
            if (data.available === false) {
                body.innerHTML = 'Detailed source records for this organism are not built yet.';
            } else if (data.covered === false) {
                body.innerHTML = `This gene is not covered in the current detail build for this organism (release ${esc(data.version || 'unknown')}).`;
            } else {
                body.textContent = 'No detailed source records are available for this gene.';
            }
            delete container.dataset.loaded;
            return;
        }
        body.innerHTML = detailedEvidenceHtml(data);
        container.dataset.loaded = 'true';
    } catch (error) {
        body.textContent = 'No detailed source records are available for this gene.';
        delete container.dataset.loaded;
    }
}

/** Which measurement decides the verdict (mirrors the safety recommender). */
function verdictDriver(evidence) {
    const { organism, cells } = evidence;
    const organismKnown = organism.call !== 'UNKNOWN' && !organism.distant;   // a distant relative is only a hint
    if (evidence.context === 'cells') return cells.call !== 'UNKNOWN' ? 'cells' : (organismKnown ? 'organism' : '');
    if (organismKnown) return 'organism';
    if (cells.call === 'ESSENTIAL') return 'cells';
    return evidence.estimate ? 'estimate' : '';
}

function evidencePanel(gene) {
    const safety = gene.safety_recommendation || {};
    const evidence = gene.knockout_evidence;
    const driver = evidence ? verdictDriver(evidence) : '';
    const context = currentJob?.knockout_context || 'auto';
    const contextLabel = CONTEXT_LABELS[context] || 'Automatic';
    const decidesIcon = '<span class="ks-b warn" title="This evidence decided the verdict"><i class="fas fa-crown"></i>Decides verdict</span>';

    // Build the two context sections
    const sections = [];

    // Whole-animal context
    if (evidence && evidence.organism.call !== 'UNKNOWN') {
        const org = evidence.organism;
        const isDriver = driver === 'organism';
        const organismTitle = org.species ? (org.species === 'Mus musculus' ? 'Mouse whole-animal' : org.species) : 'Whole-animal';
        sections.push(`
            <div class="ks-ev ${isDriver ? 'driver' : ''}">
                <div class="t"><i class="fas fa-paw me-1"></i>${esc(organismTitle)}${isDriver ? decidesIcon : ''}</div>
                <div class="b">${callBadge(org.call)}</div>
                <div>${esc(org.text)}${referenceLinks(org, gene.symbol, currentJob?.taxid)}</div>
            </div>`);
    }

    // Cell-line context
    if (evidence && evidence.cells.call !== 'UNKNOWN') {
        const cells = evidence.cells;
        const isDriver = driver === 'cells';
        sections.push(`
            <div class="ks-ev ${isDriver ? 'driver' : ''}">
                <div class="t"><i class="fas fa-flask me-1"></i>Human cell lines${isDriver ? decidesIcon : ''}</div>
                <div class="b">${callBadge(cells.call)}</div>
                <div>${esc(cells.text)}</div>
            </div>`);
    }

    // Estimate fallback
    let estimateSection = '';
    if (evidence && evidence.estimate) {
        const estimate = evidence.estimate;
        const estClass = estimate.band === 'likely' ? 'bad' : estimate.band === 'possible' ? 'warn' : 'gray';
        const isDriver = driver === 'estimate';
        estimateSection = `
            <div class="ks-ev ${isDriver ? 'driver' : ''}">
                <div class="t"><i class="fas fa-calculator me-1"></i>Estimated${isDriver ? decidesIcon : ''}<span data-bs-toggle="tooltip" title="No direct knockout was measured for this gene. The lethality probability is estimated from cell-line, population, expression, and conservation data."><i class="fas fa-info-circle" style="margin-left:6px;cursor:pointer;"></i></span></div>
                <div><span class="ks-b ${estClass}">${esc(estimate.percent)}% lethal chance</span> ${esc(estimate.text)}</div>
            </div>`;
    }

    // No data fallback
    let noDataSection = '';
    if (!sections.length && !estimateSection) {
        noDataSection = `<div class="ks-note ks-plain" style="margin-bottom:10px;">
            <i class="fas fa-info-circle" style="color:var(--ks-muted);"></i><span class="ks-grow">No direct measured knockout data was found. The verdict is based on annotation evidence and the composite score.</span>
        </div>`;
        const phenotype = gene.phenotype_prediction;
        if (phenotype) {
            const sev = typeof phenotype.severity === 'object' ? phenotype.severity.value : phenotype.severity;
            noDataSection += `
                <div class="ks-note ks-warn" style="margin-bottom:10px;">
                    <i class="fas fa-brain"></i>
                    <span class="ks-grow"><strong>AI phenotype prediction from abstracts:</strong> ${esc(sev)} phenotype, confidence ${Number(phenotype.confidence_score).toFixed(2)}. <span data-bs-toggle="tooltip" title="RAG scans PubMed abstracts for phenotype keywords. UNKNOWN or low-confidence predictions should not override measured knockout evidence."><i class="fas fa-info-circle" style="cursor:pointer;"></i></span></span>
                </div>`;
        }
    }

    // Gene info chips
    const chips = [];
    if (evidence && evidence.constraint) {
        const parts = evidence.constraint.text.match(/^Loss-of-function variants are (.*?) in people \(gnomAD LOEUF ([0-9.]+), (.*?)\)$/);
        if (parts) {
            chips.push(geneInfoChip('fa-users', 'Population constraint', parts[1], `gnomAD LOEUF ${parts[2]}, ${parts[3]}`));
        } else {
            chips.push(geneInfoChip('fa-users', 'Population constraint', evidence.constraint.text, ''));
        }
    }
    if (evidence && evidence.expression) {
        const parts = evidence.expression.text.match(/^([^:]+): expressed in (\d+) of (\d+) tissues/);
        if (parts) {
            chips.push(geneInfoChip('fa-dna', 'Expression', `${parts[1]} · ${parts[2]}/${parts[3]} tissues`, evidence.expression.top_tissues?.slice(0, 3).join(', ')));
        } else {
            chips.push(geneInfoChip('fa-dna', 'Expression', evidence.expression.text, ''));
        }
    }
    if (evidence && evidence.paralogs) {
        chips.push(geneInfoChip('fa-clone', 'Paralogs', evidence.paralogs.text, ''));
    }

    // Organ systems
    let systemsSection = '';
    if (evidence && evidence.organism.systems && evidence.organism.systems.length) {
        const sysChips = evidence.organism.systems.map(sys => `<span class="ks-b gray">${esc(sys.replace(/ phenotype$/, ''))}</span>`).join('');
        systemsSection = `<details class="ks-mitigation"><summary>Organ systems with a reported phenotype (${evidence.organism.systems.length})</summary><div class="ks-ichips" style="margin-top:8px;">${sysChips}</div></details>`;
    }

    const taxid = String(currentJob?.taxid || '');
    const details = !detailTaxids || detailTaxids.has(taxid) ? `<details class="ks-mitigation detailed-evidence" data-taxid="${esc(currentJob.taxid)}" data-symbol="${esc(gene.symbol)}">
        <summary>Detailed source records</summary>
        <div class="detailed-evidence-body" style="margin-top:10px;">Expand to load detailed mutant and publication records.</div>
    </details>` : '';

    return `
        <div class="ks-evp">
            <div class="ks-evtop">
                <span style="font-size:12.5px;color:var(--ks-muted);"><i class="fas fa-microscope me-1"></i>Evidence basis · Context: <strong>${esc(contextLabel)}</strong></span>
                <span class="ks-b ${basisKsClass(safety.evidence_basis || 'none')}">${BASIS_BADGES[safety.evidence_basis || 'none'][1]}</span>
            </div>
            <div class="ks-evgrid">${sections.join('')}${estimateSection}</div>
            ${noDataSection}
            ${chips.length ? `<div class="ks-ichips" style="border-top:1px solid var(--ks-line);padding-top:10px;">${chips.join('')}</div>` : ''}
            ${systemsSection}
        </div>${details}`;
}

document.addEventListener('toggle', (event) => {
    const container = event.target.closest?.('.detailed-evidence');
    if (container && container.open) loadDetailedEvidence(container);
}, true);

function renderExcluded(entries) {
    if (!entries || entries.length === 0) return;
    const container = document.getElementById('genesContainer');
    const rows = entries.map(entry => {
        const evidence = entry.knockout_evidence;
        const lines = [];
        if (evidence && evidence.organism.call !== 'UNKNOWN') lines.push(`${callBadge(evidence.organism.call)}${esc(evidence.organism.text)}${referenceLinks(evidence.organism, entry.symbol, currentJob?.taxid)}`);
        if (evidence && evidence.cells.call !== 'UNKNOWN') lines.push(`${callBadge(evidence.cells.call)}${esc(evidence.cells.text)}`);
        if (evidence && evidence.estimate) lines.push(`<span class="ks-b warn">${esc(evidence.estimate.percent)}% lethal (estimate)</span> ${esc(evidence.estimate.text)}`);
        return `<tr><td><strong>${esc(entry.symbol)}</strong></td><td>${esc(entry.detail)}</td>
            <td>${lines.length ? lines.join('<br>') : '<span style="color:var(--ks-muted);">No measured knockout data</span>'}</td></tr>`;
    }).join('');
    container.insertAdjacentHTML('beforeend', `
        <section class="ks-panel" style="margin-top:24px;">
            <div class="ks-ph"><div><div class="ks-tag">Assessed but not ranked</div><h2><i class="fas fa-eye-slash me-2"></i>${entries.length} gene(s) not shown</h2></div></div>
            <div class="ks-pb">
                <p style="color:var(--ks-muted);font-size:13.5px;margin-bottom:14px;">These genes were assessed too. They are not in the ranking above because their pleiotropy score is above the cutoff, or because they rank below the genes shown. Their measured knockout result is listed so that nothing is hidden.</p>
                <div style="overflow-x:auto;">
                    <table class="ks-table">
                        <thead><tr><th>Gene</th><th>Why not shown</th><th>Measured knockout evidence</th></tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            </div>
        </section>`);
}

function renderSources(metadata) {
    const info = metadata && metadata.knockout_evidence_data;
    if (!info || !info.sources || !info.sources.length) return;
    const container = document.getElementById('genesContainer');
    const items = info.sources.map(s => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a> — ${esc(s.what || '')}</li>`).join('');
    container.insertAdjacentHTML('beforeend', `
        <section class="ks-panel" style="margin-top:24px;">
            <div class="ks-ph"><div><div class="ks-tag">Provenance</div><h2><i class="fas fa-database me-2"></i>Data sources</h2></div></div>
            <div class="ks-pb ks-prov">
                <p>Measured knockout data, release <strong>${esc(info.version || 'unknown')}</strong>.</p>
                <ul>${items}</ul>
            </div>
        </section>`);
}

function safetyLabel(level, context) {
    if (!level) return 'Unknown';
    context = context || currentJob?.knockout_context || 'auto';
    const ctx = context === 'cells' ? 'cells' : context === 'organism' ? 'organism' : '';
    const suffix = ctx ? ` (${ctx})` : '';
    const text = String(level).replace(/_/g, ' ').toLowerCase();
    return text.charAt(0).toUpperCase() + text.slice(1) + suffix;
}

function renderWarnings(warnings) {
    if (!warnings || warnings.length === 0) return;
    const container = document.getElementById('genesContainer');
    const items = warnings.map(w => `<li style="margin-bottom:4px;">${esc(w)}</li>`).join('');
    container.insertAdjacentHTML('afterbegin', `
        <details class="ks-note ks-warn" style="margin-bottom:18px;">
            <summary style="cursor:pointer;font-weight:600;display:flex;align-items:center;gap:10px;">
                <i class="fas fa-exclamation-triangle"></i>
                <span>${warnings.length} data quality note${warnings.length > 1 ? 's' : ''}</span>
                <span class="ks-b warn" style="margin-left:auto;">Click to expand</span>
            </summary>
            <div style="margin-top:10px;padding-left:32px;color:var(--ks-muted);font-size:13.5px;">
                <ul style="margin:0;padding-left:18px;">${items}</ul>
            </div>
        </details>
    `);
}

function safetyBadgeClass(level) {
    switch (level) {
        case 'SAFE': return 'bg-success';
        case 'CAUTION': return 'bg-info';
        case 'MODERATE_CONCERN': return 'bg-warning text-dark';
        case 'HIGH_CONCERN':
        case 'AVOID': return 'bg-danger';
        default: return 'bg-secondary';
    }
}

function safetyKsClass(level) {
    switch (level) {
        case 'SAFE': return 'safe';
        case 'CAUTION': return 'info';
        case 'MODERATE_CONCERN': return 'warn';
        case 'HIGH_CONCERN':
        case 'AVOID': return 'bad';
        default: return 'gray';
    }
}

function basisKsClass(basis) {
    switch (basis) {
        case 'measured': return 'safe';
        case 'essentiality':
        case 'ortholog': return 'info';
        case 'predicted': return 'warn';
        default: return 'gray';
    }
}

function pleiotropyPercent(score) {
    if (!score && score !== 0) return 0;
    return Math.min(100, Math.max(0, (score / 10) * 100));
}

function pleiotropyColor(score) {
    if (!score && score !== 0) return 'var(--ks-muted)';
    if (score <= 2) return 'var(--v-safe)';
    if (score <= 5) return 'var(--v-info)';
    if (score <= 7) return 'var(--v-warn)';
    return 'var(--v-bad)';
}

function renderGenes(genes) {
    const container = document.getElementById('genesContainer');
    
    if (!genes || genes.length === 0) {
        container.innerHTML = `
            <div class="ks-note ks-warn">
                <span class="ks-grow">No genes passed the filters.</span>
            </div>
        `;
        return;
    }
    
    container.innerHTML = genes.map((gene, index) => {
        const safety = gene.safety_recommendation || {};
        const concerns = (safety.concerns || []).map(c => `<li>${esc(c)}</li>`).join('');
        const justification = (safety.justification || []).map(j => `<li>${esc(j)}</li>`).join('');
        const mitigation = (safety.mitigation_strategies || []).map(m => `<li>${esc(m)}</li>`).join('');
        const alternatives = (safety.alternative_recommendations || []).length
            ? ` <span style="color:var(--ks-muted);font-size:13px;">(alternatives: ${esc(safety.alternative_recommendations.join('; '))})</span>` : '';
        return `
        <article class="ks-gcard">
            <div class="ks-rk">${index + 1}</div>
            <div class="ks-gbody">
                <div class="ks-ghead">
                    <div class="ks-gtitle">
                        <h5>${esc(gene.symbol)}</h5>
                        <p>${esc(gene.description || 'No description available')}</p>
                    </div>
                    <div class="ks-gright">
                        <div class="ks-gauge">
                            <span>Pleiotropy</span>
                            <span class="tr"><i style="width:${pleiotropyPercent(gene.pleiotropy_score)}%;background:${pleiotropyColor(gene.pleiotropy_score)}"></i></span>
                            <b>${gene.pleiotropy_score?.toFixed(2) || 'N/A'}</b>
                        </div>
                        <span class="ks-b ${safetyKsClass(safety.safety_level)}">${safetyLabel(safety.safety_level)}</span>
                    </div>
                </div>
                ${compositeFormulaLine(gene)}
                ${evidencePanel(gene)}
                ${safety.primary_recommendation ? `<p class="ks-rec"><strong>Recommendation:</strong> ${esc(safety.primary_recommendation)}${alternatives}</p>` : ''}
                ${justification ? `<ul>${justification}</ul>` : ''}
                ${concerns ? `<div class="ks-concerns">Concerns:<ul>${concerns}</ul></div>` : ''}
                ${mitigation ? `<details class="ks-mitigation"><summary>What to do about it</summary><ul>${mitigation}</ul></details>` : ''}
            </div>
        </article>`;
    }).join('');
    initializeTooltips(container);
}

function renderInsufficientData(genes) {
    if (!genes || genes.length === 0) return;

    const container = document.getElementById('genesContainer');
    const rows = genes.map(g => `
        <tr>
            <td><strong>${esc(g.symbol)}</strong></td>
            <td>${esc((g.reasons || []).join('; ') || 'No data')}</td>
            <td>${g.lookup_failed ? '<span class="ks-b warn">Yes</span>' : '<span class="ks-b gray">No</span>'}</td>
        </tr>
    `).join('');

    container.insertAdjacentHTML('beforeend', `
        <section class="ks-panel" style="margin-top:24px;">
            <div class="ks-ph"><div><div class="ks-tag">Could not score</div><h2><i class="fas fa-exclamation-triangle me-2"></i>${genes.length} gene(s) with insufficient data</h2></div></div>
            <div class="ks-pb">
                <p style="color:var(--ks-muted);font-size:13.5px;margin-bottom:14px;">These genes are not ranked and have no safety level.</p>
                <div style="overflow-x:auto;">
                    <table class="ks-table">
                        <thead><tr><th>Gene</th><th>Reason</th><th>Lookup failed <span data-bs-toggle="tooltip" title="&quot;Lookup failed&quot; means a database could not be reached, so a retry may help."><i class="fas fa-question-circle" style="color:var(--ks-link);cursor:pointer;"></i></span></th></tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            </div>
        </section>
    `);
}

function renderSummary(data) {
    const container = document.getElementById('summaryContainer');
    const genes = data.genes || [];

    if (!genes.length) {
        container.innerHTML = '<div class="text-center py-5" style="color:var(--ks-muted);">No gene results to summarise.</div>';
        return;
    }

    const stats = {
        totalGenes: genes.length,
        avgPleiotropy: genes.reduce((sum, g) => sum + (g.pleiotropy_score || 0), 0) / genes.length || 0
    };
    const levelCounts = {};
    genes.forEach(g => { const level = (g.safety_recommendation || {}).safety_level; levelCounts[level] = (levelCounts[level] || 0) + 1; });
    const levelRows = ['SAFE', 'CAUTION', 'MODERATE_CONCERN', 'HIGH_CONCERN', 'AVOID'].filter(level => levelCounts[level]).map(level => `
        <tr>
            <td><span class="ks-b ${safetyKsClass(level)}">${safetyLabel(level)}</span></td>
            <td style="text-align:right;font-weight:600;">${levelCounts[level]}</td>
        </tr>`).join('');
    const basisOf = (g) => (g.safety_recommendation || {}).evidence_basis;
    const measuredCount = genes.filter(g => ['measured', 'essentiality'].includes(basisOf(g))).length;
    const orthologCount = genes.filter(g => basisOf(g) === 'ortholog').length;
    const estimateCount = genes.filter(g => basisOf(g) === 'estimate').length;

    const topSpecific = [...genes]
        .sort((a, b) => (b.specificity_score || 0) - (a.specificity_score || 0))
        .slice(0, 5)
        .map((g, i) => `
            <div class="ks-rank">
                <span class="ks-rank-n">${i + 1}</span>
                <span class="ks-rank-l">${esc(g.symbol)}</span>
                <span class="ks-rank-v">${g.specificity_score?.toFixed(2) || 'N/A'}</span>
            </div>`).join('');

    container.innerHTML = `
        <div class="ks-sum-grid">
            <section class="ks-panel">
                <div class="ks-ph"><div><div class="ks-tag">Overview</div><h2><i class="fas fa-chart-bar me-2"></i>Statistics</h2></div></div>
                <div class="ks-pb">
                    <table class="ks-table">
                        <tbody>
                            <tr><td>Total genes shown</td><td style="text-align:right;font-weight:600;">${stats.totalGenes}</td></tr>
                            <tr><td>Average pleiotropy</td><td style="text-align:right;font-weight:600;">${stats.avgPleiotropy.toFixed(2)}</td></tr>
                            <tr><td>Verdict based on a measurement</td><td style="text-align:right;font-weight:600;">${measuredCount + orthologCount} of ${stats.totalGenes}</td></tr>
                            ${estimateCount ? `<tr><td>Verdict based on an estimate</td><td style="text-align:right;font-weight:600;">${estimateCount} of ${stats.totalGenes}</td></tr>` : ''}
                            ${levelRows}
                        </tbody>
                    </table>
                </div>
            </section>

            <section class="ks-panel">
                <div class="ks-ph"><div><div class="ks-tag">Top performers</div><h2><i class="fas fa-trophy me-2"></i>Most Specific Genes</h2></div></div>
                <div class="ks-pb">
                    <div class="ks-ranks">${topSpecific}</div>
                </div>
            </section>
        </div>
    `;
}

// ============================================================================
// Helper Functions
// ============================================================================

function getPleiotropyClass(score) {
    if (!score && score !== 0) return 'score-medium';
    if (score <= 2) return 'score-high';  // Low pleiotropy is good
    if (score <= 5) return 'score-medium';
    return 'score-low';
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}
