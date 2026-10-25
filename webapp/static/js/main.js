/**
 * K-Sites Web Application - Main JavaScript
 * Enhanced version with hierarchical selection
 */

// Global state
let selectedKingdom = null;
let selectedOrganism = null;
let selectedCategory = null;
let selectedGoTerm = null;
let geneCountCheckTimeout = null;

// DOM Ready
document.addEventListener('DOMContentLoaded', function() {
    // Hosted mode remembers who is logged in; use that address for the job record
    const emailField = document.getElementById('user_email');
    if (emailField && !emailField.value && window.KSITES && window.KSITES.user().email) {
        emailField.value = window.KSITES.user().email;
    }

    loadKingdoms();
    loadGoCategories();
    loadDatabases();
    initializeEventListeners();
});

// ============================================================================
// Kingdom/Organism Selection
// ============================================================================

async function loadKingdoms() {
    try {
        const response = await ksFetch('/api/organisms/kingdoms');
        const data = await response.json();
        renderKingdoms(data.kingdoms);
    } catch (error) {
        console.error('Error loading kingdoms:', error);
        document.getElementById('kingdomContainer').innerHTML = `
            <div class="col-12 alert alert-danger">
                Error loading organism categories. Please refresh.
            </div>
        `;
    }
}

function renderKingdoms(kingdoms) {
    const container = document.getElementById('kingdomContainer');
    
    container.innerHTML = kingdoms.map(k => `
        <div class="col-md-4 col-lg-3">
            <div class="card kingdom-card h-100 cursor-pointer" 
                 data-kingdom="${k.name}" 
                 onclick="selectKingdom('${k.name}')"
                 style="cursor: pointer; transition: all 0.2s;">
                <div class="card-body text-center">
                    <i class="fas ${k.icon} fa-2x mb-2 text-primary"></i>
                    <h6 class="card-title mb-1">${k.name}</h6>
                    <p class="card-text small text-muted mb-0">${k.description}</p>
                </div>
            </div>
        </div>
    `).join('');
}

async function selectKingdom(kingdom) {
    selectedKingdom = kingdom;
    
    // Show loading state on the clicked card
    const cards = document.querySelectorAll('.kingdom-card');
    cards.forEach(card => {
        if (card.dataset.kingdom === kingdom) {
            card.classList.add('loading');
            card.innerHTML = `
                <div class="card-body text-center">
                    <div class="spinner-border text-primary mb-2" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <h6 class="card-title mb-1">Loading ${kingdom}...</h6>
                </div>
            `;
        } else {
            card.style.opacity = '0.5';
            card.style.pointerEvents = 'none';
        }
    });
    
    // Update UI
    document.getElementById('selectedKingdomName').textContent = kingdom;
    document.getElementById('kingdomContainer').style.display = 'none';
    document.getElementById('speciesSection').style.display = 'block';
    
    // Reset cards state
    cards.forEach(card => {
        card.classList.remove('loading');
        card.style.opacity = '1';
        card.style.pointerEvents = 'auto';
    });
    
    // Clear search and show prompt to search
    document.getElementById('speciesSearch').value = '';
    await loadSpecies(kingdom, '');
    
    // Focus on search input
    document.getElementById('speciesSearch').focus();
}

function resetKingdomSelection() {
    selectedKingdom = null;
    selectedOrganism = null;
    document.getElementById('kingdomContainer').style.display = 'flex';
    document.getElementById('speciesSection').style.display = 'none';
    document.getElementById('selectedOrganismDisplay').style.display = 'none';
    document.getElementById('organism').value = '';
    document.getElementById('taxid').value = '';
}

async function loadSpecies(kingdom, query = '') {
    const list = document.getElementById('speciesList');
    
    // Show enhanced loading state
    list.innerHTML = `
        <div class="list-loading">
            <div class="text-center">
                <div class="spinner-border text-primary mb-2" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
                <div class="text-muted small">
                    ${query ? `Searching for "${query}"...` : 'Loading species from KEGG database...'}
                </div>
            </div>
        </div>
    `;
    
    try {
        const url = `/api/organisms/by-kingdom?kingdom=${encodeURIComponent(kingdom)}${query ? '&q=' + encodeURIComponent(query) : ''}`;
        const response = await ksFetch(url);
        const data = await response.json();
        renderSpecies(data.results);
    } catch (error) {
        console.error('Error loading species:', error);
        list.innerHTML = '<div class="alert alert-danger"><i class="fas fa-exclamation-circle me-2"></i>Error loading species. Please try again.</div>';
    }
}

function renderSpecies(species) {
    const list = document.getElementById('speciesList');
    
    if (species.length === 0) {
        list.innerHTML = '<div class="list-group-item text-muted">No species found</div>';
        return;
    }
    
    list.innerHTML = species.map(s => `
        <div class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
             onclick="selectOrganism('${s.name}', '${s.taxid}', '${s.common_name || ''}')"
             style="cursor: pointer;">
            <div>
                <strong>${s.name}</strong>
                ${s.common_name ? `<br><small class="text-muted">${s.common_name}</small>` : ''}
            </div>
            <span class="badge bg-secondary">TaxID: ${s.taxid}</span>
        </div>
    `).join('');
}

function selectOrganism(name, taxid, commonName) {
    selectedOrganism = { name, taxid, commonName };
    
    // Update hidden fields
    document.getElementById('organism').value = name;
    document.getElementById('taxid').value = taxid;
    
    // Update display
    document.getElementById('selectedOrganismName').textContent = name + (commonName ? ` (${commonName})` : '');
    document.getElementById('selectedOrganismTaxid').textContent = taxid;
    document.getElementById('selectedOrganismDisplay').style.display = 'block';
    document.getElementById('speciesSection').style.display = 'none';
    
    // Say what is known about knockouts in this organism, and check the gene count
    showEvidenceCoverage(taxid);
    checkGeneCount();
}

/** Tells the user, before the run, whether measured knockout data exist for the organism they picked. */
async function showEvidenceCoverage(taxid) {
    const note = document.getElementById('evidenceCoverageNote');
    if (!note) return;
    note.style.display = 'none';
    try {
        const response = await ksFetch(`/api/evidence/coverage?taxid=${encodeURIComponent(taxid)}`);
        const data = await response.json();
        let text;
        if (!data.available) {
            text = 'The measured knockout data could not be loaded, so verdicts will rest on annotations alone (nothing is rated better than CAUTION).';
        } else if (!data.covered) {
            text = 'There are no measured knockout data for this organism. Verdicts will be marked "Not verified" and rated at most CAUTION; '
                + 'check MGI, IMPC, FlyBase, WormBase or the literature yourself.';
        } else if (data.distant) {
            text = `Only the knockout of the mouse ortholog is known for ${data.name}. It is shown as a hint (a lethal mouse ortholog raises the concern), but verdicts are never better than CAUTION.`;
        } else {
            const phrases = {
                knockout: 'knockout viability', 'ortholog-knockout': "the mouse ortholog's knockout", 'cell-essentiality': 'cell-line screens (DepMap)',
                constraint: 'tolerance of loss-of-function variants (gnomAD)', paralogs: 'close paralogs',
                expression: String(taxid) === '9606' ? 'tissue expression (GTEx)' : 'tissue expression of the human ortholog (GTEx)',
            };
            const layers = (data.layers || []).map((l) => phrases[l]).filter(Boolean);
            // genes with a knockout result, not every gene that has a record (human records also hold expression-only genes)
            const measured = data.measured ?? data.genes;
            text = `Measured knockout data exist for ${data.name}: ${measured.toLocaleString()} genes` + (layers.length ? `, with ${layers.join(', ')}.` : '.');
        }
        note.textContent = text;
        note.style.display = 'block';
    } catch (error) {
        // the note is only a courtesy
    }
}

function resetOrganismSelection() {
    selectedOrganism = null;
    const coverageNote = document.getElementById('evidenceCoverageNote');
    if (coverageNote) coverageNote.style.display = 'none';
    document.getElementById('selectedOrganismDisplay').style.display = 'none';
    document.getElementById('speciesSection').style.display = 'block';
    document.getElementById('organism').value = '';
    document.getElementById('taxid').value = '';
    loadSpecies(selectedKingdom, document.getElementById('speciesSearch').value);
}

// ============================================================================
// GO Category/Term Selection
// ============================================================================

async function loadGoCategories() {
    try {
        const response = await ksFetch('/api/go-terms/categories');
        const data = await response.json();
        renderGoCategories(data.categories);
    } catch (error) {
        console.error('Error loading GO categories:', error);
    }
}

function renderGoCategories(categories) {
    const container = document.getElementById('goCategoryContainer');
    
    container.innerHTML = categories.map(c => `
        <div class="col-md-4">
            <div class="card go-category-card h-100 cursor-pointer" 
                 data-category="${c.name}" 
                 onclick="selectGoCategory('${c.name}')"
                 style="cursor: pointer; transition: all 0.2s;">
                <div class="card-body text-center">
                    <i class="fas ${c.icon} fa-2x mb-2 text-success"></i>
                    <h6 class="card-title mb-1">${c.name}</h6>
                    <p class="card-text small text-muted mb-0">${c.description}</p>
                </div>
            </div>
        </div>
    `).join('');
}

async function selectGoCategory(category) {
    selectedCategory = category;
    
    // Show loading state on the clicked card
    const cards = document.querySelectorAll('.go-category-card');
    cards.forEach(card => {
        if (card.dataset.category === category) {
            card.classList.add('loading');
            card.innerHTML = `
                <div class="card-body text-center">
                    <div class="spinner-border text-success mb-2" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <h6 class="card-title mb-1">Loading ${category}...</h6>
                </div>
            `;
        } else {
            card.style.opacity = '0.5';
            card.style.pointerEvents = 'none';
        }
    });
    
    // Update UI
    document.getElementById('selectedCategoryName').textContent = category;
    document.getElementById('goCategoryContainer').style.display = 'none';
    document.getElementById('goTermsSection').style.display = 'block';
    
    // Reset cards state
    cards.forEach(card => {
        card.classList.remove('loading');
        card.style.opacity = '1';
        card.style.pointerEvents = 'auto';
    });
    
    // Clear direct input
    document.getElementById('go_term_direct').value = '';
    
    // Clear search and show prompt to search
    document.getElementById('goTermSearch').value = '';
    await loadGoTerms(category, '');
    
    // Focus on search input
    document.getElementById('goTermSearch').focus();
}

function resetCategorySelection() {
    selectedCategory = null;
    selectedGoTerm = null;
    document.getElementById('goCategoryContainer').style.display = 'flex';
    document.getElementById('goTermsSection').style.display = 'none';
    document.getElementById('selectedGoTermDisplay').style.display = 'none';
    document.getElementById('go_term').value = '';
    document.getElementById('go_term_name').value = '';
}

async function loadGoTerms(category, query = '') {
    const list = document.getElementById('goTermsList');
    
    // Show enhanced loading state
    list.innerHTML = `
        <div class="list-loading">
            <div class="text-center">
                <div class="spinner-border text-success mb-2" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
                <div class="text-muted small">
                    ${query ? `Searching GO terms for "${query}"...` : `Loading ${category} terms...`}
                </div>
            </div>
        </div>
    `;
    
    try {
        const url = `/api/go-terms/by-category?category=${encodeURIComponent(category)}${query ? '&q=' + encodeURIComponent(query) : ''}`;
        const response = await ksFetch(url);
        const data = await response.json();
        renderGoTerms(data.results);
    } catch (error) {
        console.error('Error loading GO terms:', error);
        list.innerHTML = '<div class="alert alert-danger"><i class="fas fa-exclamation-circle me-2"></i>Error loading GO terms. Please try again.</div>';
    }
}

function renderGoTerms(terms) {
    const list = document.getElementById('goTermsList');
    
    if (terms.length === 0) {
        list.innerHTML = '<div class="list-group-item text-muted">No GO terms found</div>';
        return;
    }
    
    list.innerHTML = terms.map(t => `
        <div class="list-group-item list-group-item-action"
             onclick="selectGoTerm('${t.id}', '${t.name.replace(/'/g, "\\'")}')"
             style="cursor: pointer;">
            <div class="d-flex justify-content-between align-items-start">
                <div>
                    <strong>${t.name}</strong>
                    <br><small class="text-muted">${t.definition || ''}</small>
                </div>
                <span class="badge bg-success">${t.id}</span>
            </div>
        </div>
    `).join('');
}

function selectGoTerm(id, name) {
    selectedGoTerm = { id, name };
    
    // Update hidden fields
    document.getElementById('go_term').value = id;
    document.getElementById('go_term_name').value = name;
    
    // Update display
    document.getElementById('selectedGoTermId').textContent = id;
    document.getElementById('selectedGoTermName').textContent = name;
    document.getElementById('selectedGoTermDisplay').style.display = 'block';
    document.getElementById('goTermsSection').style.display = 'none';
    
    // Check gene count
    checkGeneCount();
}

function resetGoTermSelection() {
    selectedGoTerm = null;
    document.getElementById('selectedGoTermDisplay').style.display = 'none';
    document.getElementById('goTermsSection').style.display = 'block';
    document.getElementById('go_term').value = '';
    document.getElementById('go_term_name').value = '';
    loadGoTerms(selectedCategory, document.getElementById('goTermSearch').value);
}

// ============================================================================
// Database Selection
// ============================================================================

async function loadDatabases() {
    const container = document.getElementById('databaseContainer');
    
    try {
        const response = await ksFetch('/api/databases');
        const data = await response.json();
        
        container.innerHTML = data.databases.map(db => `
            <div class="col-md-6 col-lg-4">
                <div class="card database-card ${db.required ? 'selected' : ''} ${!db.enabled ? 'disabled opacity-50' : ''}"
                     data-id="${db.id}"
                     ${!db.enabled ? 'onclick="return false;" style="cursor: not-allowed;"' : 'onclick="toggleDatabase(this)" style="cursor: pointer;"'}>
                    <div class="card-body">
                        <div class="d-flex align-items-center mb-2">
                            <input type="checkbox" 
                                   class="form-check-input me-2 database-checkbox"
                                   value="${db.id}"
                                   ${db.required ? 'checked disabled' : ''}
                                   ${!db.enabled ? 'disabled' : ''}
                                   onchange="updateDatabaseCard(this)">
                            <h6 class="card-title mb-0">${db.name}</h6>
                        </div>
                        <p class="card-text small text-muted">${db.description}</p>
                        ${db.required ? '<span class="badge bg-primary">Required</span>' : ''}
                        ${!db.enabled ? '<span class="badge bg-secondary">Not Available</span>' : ''}
                    </div>
                </div>
            </div>
        `).join('');
        
    } catch (error) {
        console.error('Error loading databases:', error);
    }
}

function toggleDatabase(card) {
    const checkbox = card.querySelector('.database-checkbox:not(:disabled)');
    if (checkbox) {
        checkbox.checked = !checkbox.checked;
        card.classList.toggle('selected', checkbox.checked);
    }
}

function updateDatabaseCard(checkbox) {
    const card = checkbox.closest('.database-card');
    card.classList.toggle('selected', checkbox.checked);
}

// ============================================================================
// Event Listeners
// ============================================================================

function initializeEventListeners() {
    // Species search
    document.getElementById('speciesSearch')?.addEventListener('input', debounce(function() {
        if (selectedKingdom) {
            loadSpecies(selectedKingdom, this.value);
        }
    }, 300));
    
    // GO term search
    document.getElementById('goTermSearch')?.addEventListener('input', debounce(function() {
        if (selectedCategory) {
            loadGoTerms(selectedCategory, this.value);
        }
    }, 300));
    
    // Direct GO term input
    document.getElementById('go_term_direct')?.addEventListener('input', function() {
        const value = this.value.trim().toUpperCase();
        if (/^GO:\d{7}$/.test(value)) {
            selectGoTerm(value, 'Direct entry');
            // Reset category selection
            document.getElementById('goCategoryContainer').style.display = 'flex';
            document.getElementById('goTermsSection').style.display = 'none';
        }
    });
    
    // Parameter changes for gene count check
    ['max_genes', 'predict_phenotypes', 'evidence_filter'].forEach(id => {
        document.getElementById(id)?.addEventListener('change', () => {
            clearTimeout(geneCountCheckTimeout);
            geneCountCheckTimeout = setTimeout(checkGeneCount, 500);
        });
    });
    
    // Show every gene of the GO term in the report (the limit is 500)
    document.getElementById('showAllGenes')?.addEventListener('click', () => {
        const input = document.getElementById('max_genes');
        input.value = input.max || 500;
        input.dispatchEvent(new Event('change'));
    });

    // Refresh gene count
    document.getElementById('refreshGeneCount')?.addEventListener('click', checkGeneCount);
    
    // Form submission
    document.getElementById('analysisForm')?.addEventListener('submit', handleFormSubmit);
}

// ============================================================================
// Gene Count Validation
// ============================================================================

async function checkGeneCount() {
    const organism = document.getElementById('organism').value.trim();
    const goTerm = document.getElementById('go_term').value.trim();
    const maxGenes = parseInt(document.getElementById('max_genes').value) || 10;
    const predictPhenotypes = document.getElementById('predict_phenotypes').checked;
    const evidenceFilter = document.getElementById('evidence_filter').value;
    
    if (!organism || !goTerm) {
        document.getElementById('geneCountPreview').style.display = 'none';
        return;
    }
    
    try {
        const response = await ksFetch('/api/analyze/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                organism, 
                go_term: goTerm, 
                max_genes: maxGenes,
                predict_phenotypes: predictPhenotypes,
                evidence_filter: evidenceFilter
            })
        });
        
        const data = await response.json();
        
        const preview = document.getElementById('geneCountPreview');
        const value = document.getElementById('geneCountValue');
        const timeDiv = document.getElementById('estimatedTime');
        const timeValue = document.getElementById('estimatedTimeValue');
        const warning = document.getElementById('geneCountWarning');
        const warningText = document.getElementById('geneCountWarningText');
        
        preview.style.display = 'block';
        
        if (data.gene_count !== undefined) {
            value.textContent = data.gene_count;
            
            if (data.estimated_time_formatted) {
                timeValue.textContent = data.estimated_time_formatted;
                timeDiv.style.display = 'block';
            }
            
            if (data.warnings && data.warnings.length > 0) {
                warning.style.display = 'block';
                warningText.textContent = data.warnings.join('; ');
            } else {
                warning.style.display = 'none';
            }
        }
        
    } catch (error) {
        console.error('Error checking gene count:', error);
    }
}

// ============================================================================
// Form Submission
// ============================================================================

async function handleFormSubmit(e) {
    e.preventDefault();
    
    // Show loading
    showLoading('Validating parameters...');
    
    // Collect form data
    const formData = collectFormData();
    
    // Validate
    try {
        const validation = await ksFetch('/api/analyze/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });
        
        const validationData = await validation.json();
        
        if (!validationData.valid) {
            hideLoading();
            showValidationErrors(validationData.errors);
            return;
        }
        
        if (validationData.warnings && validationData.warnings.length > 0) {
            showValidationWarnings(validationData.warnings);
        }
        
        // Start analysis
        showLoading('Starting analysis...');
        
        const response = await ksFetch('/api/analyze/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });
        
        const data = await response.json();
        
        hideLoading();
        
        if (data.success) {
            window.location.href = ksPage('results', { job: data.job_id });
        } else {
            showValidationErrors([data.error || 'Failed to start analysis']);
        }
        
    } catch (error) {
        hideLoading();
        console.error('Error:', error);
        showValidationErrors(['Network error. Please try again.']);
    }
}

function collectFormData() {
    const selectedDatabases = Array.from(
        document.querySelectorAll('.database-checkbox:checked')
    ).map(cb => cb.value);
    
    return {
        user_email: document.getElementById('user_email')?.value?.trim() || null,
        organism: document.getElementById('organism').value.trim(),
        taxid: document.getElementById('taxid').value,
        go_term: document.getElementById('go_term').value.trim(),
        go_term_name: document.getElementById('go_term_name').value,
        max_genes: parseInt(document.getElementById('max_genes').value) || 10,
        max_pleiotropy: parseInt(document.getElementById('max_pleiotropy').value) || 5,
        evidence_filter: document.getElementById('evidence_filter').value,
        knockout_context: document.getElementById('knockout_context')?.value || 'auto',
        predict_phenotypes: document.getElementById('predict_phenotypes').checked,
        databases: selectedDatabases
    };
}

function showValidationErrors(errors) {
    const container = document.getElementById('validationAlerts');
    container.innerHTML = errors.map(error => `
        <div class="alert alert-danger alert-dismissible fade show">
            <i class="fas fa-exclamation-circle me-2"></i>${error}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `).join('');
    
    container.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function showValidationWarnings(warnings) {
    const container = document.getElementById('validationAlerts');
    container.innerHTML += warnings.map(warning => `
        <div class="alert alert-warning alert-dismissible fade show">
            <i class="fas fa-exclamation-triangle me-2"></i>${warning}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `).join('');
}

function showLoading(text) {
    document.getElementById('loadingText').textContent = text;
    document.getElementById('loadingOverlay').style.display = 'flex';
}

function hideLoading() {
    document.getElementById('loadingOverlay').style.display = 'none';
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func.apply(this, args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}
