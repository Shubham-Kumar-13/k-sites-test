/**
 * K-Sites Web Application - Results Page JavaScript
 */

// Global state
let currentJob = null;
let resultsData = null;
let statusCheckInterval = null;

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

async function loadResults(jobId) {
    try {
        const response = await ksFetch(`/api/jobs/${jobId}/results`);
        const data = await response.json();
        
        if (data.error) {
            showError(data.error);
            return;
        }
        
        resultsData = data.results;
        
        renderGenes(resultsData.genes);
        renderInsufficientData(resultsData.insufficient_data_genes);
        renderWarnings(resultsData.warnings);
        renderSummary(resultsData);
        
    } catch (error) {
        console.error('Error loading results:', error);
    }
}

function safetyLabel(level) {
    if (!level) return 'Unknown';
    const text = String(level).replace(/_/g, ' ').toLowerCase();
    return text.charAt(0).toUpperCase() + text.slice(1);
}

function renderWarnings(warnings) {
    if (!warnings || warnings.length === 0) return;
    const container = document.getElementById('genesContainer');
    const items = warnings.map(w => `<li>${w}</li>`).join('');
    container.insertAdjacentHTML('afterbegin', `
        <div class="alert alert-warning">
            <strong><i class="fas fa-exclamation-triangle me-2"></i>Warning</strong>
            <ul class="mb-0">${items}</ul>
        </div>
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

function renderGenes(genes) {
    const container = document.getElementById('genesContainer');
    
    if (!genes || genes.length === 0) {
        container.innerHTML = `
            <div class="alert alert-warning">
                <i class="fas fa-exclamation-triangle me-2"></i>No genes passed the filters.
            </div>
        `;
        return;
    }
    
    container.innerHTML = genes.map((gene, index) => {
        const safety = gene.safety_recommendation || {};
        const concerns = (safety.concerns || []).map(c => `<li>${c}</li>`).join('');
        const justification = (safety.justification || []).map(j => `<li>${j}</li>`).join('');
        return `
        <div class="card mb-3">
            <div class="card-body">
                <div class="d-flex justify-content-between align-items-start mb-3">
                    <div>
                        <h5 class="mb-1">
                            <span class="badge bg-secondary me-2">#${index + 1}</span>
                            ${gene.symbol}
                        </h5>
                        <p class="text-muted mb-0 small">${gene.description || 'No description available'}</p>
                    </div>
                    <div class="text-end">
                        <div class="mb-1">
                            <span class="score-badge ${getPleiotropyClass(gene.pleiotropy_score)}">
                                Pleiotropy: ${gene.pleiotropy_score?.toFixed(2) || 'N/A'}
                            </span>
                        </div>
                        <div>
                            <span class="badge ${safetyBadgeClass(safety.safety_level)}">
                                ${safetyLabel(safety.safety_level)}
                            </span>
                        </div>
                    </div>
                </div>
                
                <div class="row g-2 mb-3 small text-muted">
                    <div class="col-md-3">
                        <i class="fas fa-star me-1"></i>Specificity: ${gene.specificity_score?.toFixed(2) || 'N/A'}
                    </div>
                    <div class="col-md-3">
                        <i class="fas fa-chart-line me-1"></i>Composite: ${gene.composite_score?.toFixed(2) || 'N/A'}
                    </div>
                    <div class="col-md-3">
                        <i class="fas fa-check-circle me-1"></i>Evidence: ${gene.evidence_quality?.toFixed(2) || 'N/A'}
                    </div>
                    <div class="col-md-3">
                        <i class="fas fa-book me-1"></i>Literature: ${gene.literature_support?.toFixed(2) || 'N/A'}
                    </div>
                    <div class="col-md-3">
                        <i class="fas fa-project-diagram me-1"></i>KEGG pathways: ${gene.kegg_pathway_count ?? 'N/A'}
                    </div>
                </div>
                
                ${safety.primary_recommendation ? `<p class="mb-2"><strong>Recommendation:</strong> ${safety.primary_recommendation}</p>` : ''}
                ${justification ? `<ul class="small mb-2">${justification}</ul>` : ''}
                ${concerns ? `<div class="small text-muted">Concerns:<ul class="mb-0">${concerns}</ul></div>` : ''}
            </div>
        </div>`;
    }).join('');
}

function renderInsufficientData(genes) {
    if (!genes || genes.length === 0) return;
    
    const container = document.getElementById('genesContainer');
    const rows = genes.map(g => `
        <tr>
            <td><strong>${g.symbol}</strong></td>
            <td>${(g.reasons || []).join('; ') || 'No data'}</td>
            <td>${g.lookup_failed ? 'Yes' : 'No'}</td>
        </tr>
    `).join('');
    
    container.insertAdjacentHTML('beforeend', `
        <div class="alert alert-warning mt-4">
            <h6><i class="fas fa-exclamation-triangle me-2"></i>${genes.length} gene(s) could not be scored (insufficient data)</h6>
            <p class="small mb-2">These genes are not ranked and have no safety level. "Lookup failed" means a database could not be reached, so a retry may help.</p>
            <table class="table table-sm mb-0">
                <thead><tr><th>Gene</th><th>Reason</th><th>Lookup failed</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `);
}

function renderSummary(data) {
    const container = document.getElementById('summaryContainer');
    const genes = data.genes || [];
    
    // Calculate statistics
    const stats = {
        totalGenes: genes.length,
        avgPleiotropy: genes.reduce((sum, g) => sum + (g.pleiotropy_score || 0), 0) / genes.length || 0
    };
    
    container.innerHTML = `
        <div class="row g-4">
            <div class="col-md-6">
                <div class="card h-100">
                    <div class="card-header bg-primary text-white">
                        <h6 class="mb-0"><i class="fas fa-chart-bar me-2"></i>Statistics</h6>
                    </div>
                    <div class="card-body">
                        <table class="table table-borderless">
                            <tr>
                                <td class="text-muted">Total Genes:</td>
                                <td class="fw-bold">${stats.totalGenes}</td>
                            </tr>
                            <tr>
                                <td class="text-muted">Average Pleiotropy:</td>
                                <td class="fw-bold">${stats.avgPleiotropy.toFixed(2)}</td>
                            </tr>
                        </table>
                    </div>
                </div>
            </div>
            
            <div class="col-md-6">
                <div class="card h-100">
                    <div class="card-header bg-success text-white">
                        <h6 class="mb-0"><i class="fas fa-trophy me-2"></i>Most Specific Genes</h6>
                    </div>
                    <div class="card-body">
                        <h6 class="text-muted">Highest Specificity Genes</h6>
                        <ul class="list-group list-group-flush mb-3">
                            ${genes
                                .sort((a, b) => (b.specificity_score || 0) - (a.specificity_score || 0))
                                .slice(0, 3)
                                .map(g => `
                                    <li class="list-group-item d-flex justify-content-between">
                                        ${g.symbol}
                                        <span class="badge bg-success">${g.specificity_score?.toFixed(2)}</span>
                                    </li>
                                `).join('')}
                        </ul>
                    </div>
                </div>
            </div>
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
