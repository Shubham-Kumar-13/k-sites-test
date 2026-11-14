/**
 * K-Sites Web Application - Main JavaScript
 * Enhanced version with hierarchical selection
 */

// Global state
let selectedKingdom = null;
let selectedOrganism = null;
let selectedCategory = null;
let selectedGoTerm = null;
let kingdomOptions = [];
let geneCountCheckTimeout = null;
let geneCountAbortController = null;

// DOM Ready
document.addEventListener('DOMContentLoaded', async function() {
    // Hosted mode remembers who is logged in; use that address for the job record
    const emailField = document.getElementById('user_email');
    if (emailField && !emailField.value && window.KSITES && window.KSITES.user().email) {
        emailField.value = window.KSITES.user().email;
    }

    loadKingdoms();
    loadGoCategories();
    await loadDatabases();
    initializeEventListeners();
    applyRerunParameters();
});

/** If the page was opened with ?rerun=1, pre-fill the form with the previous run's parameters. */
function applyRerunParameters() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('rerun') !== '1') return;

    const taxid = params.get('taxid');
    const organism = params.get('organism');
    if (taxid && organism) {
        selectOrganism(organism, taxid, '', false);
    }

    const goTerm = params.get('go_term');
    const goTermName = params.get('go_term_name');
    if (goTerm) {
        selectGoTerm(goTerm, goTermName || '');
    }

    const maxGenes = params.get('max_genes');
    if (maxGenes) document.getElementById('max_genes').value = maxGenes;

    const maxPleiotropy = params.get('max_pleiotropy');
    if (maxPleiotropy) document.getElementById('max_pleiotropy').value = maxPleiotropy;

    const evidenceFilter = params.get('evidence_filter');
    if (evidenceFilter) document.getElementById('evidence_filter').value = evidenceFilter;

    const knockoutContext = params.get('knockout_context');
    if (knockoutContext) document.getElementById('knockout_context').value = knockoutContext;

    const predictPhenotypes = params.get('predict_phenotypes') === 'true';
    const ragCheckbox = document.getElementById('predict_phenotypes');
    if (ragCheckbox && ragCheckbox.checked !== predictPhenotypes) {
        ragCheckbox.checked = predictPhenotypes;
        ragCheckbox.dispatchEvent(new Event('change'));
    }

    const databases = (params.get('databases') || '').split(',').filter(Boolean);
    document.querySelectorAll('.database-checkbox').forEach(checkbox => {
        if (checkbox.disabled) return;
        const shouldCheck = databases.includes(checkbox.value);
        if (checkbox.checked !== shouldCheck) {
            checkbox.checked = shouldCheck;
            updateDatabaseCard(checkbox);
        }
    });
}

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
            <div style="grid-column:1 / -1;color:var(--ks-bad);padding:16px;">
                Error loading organism categories. Please refresh.
            </div>
        `;
    }
}

function kingdomIconSvg(name) {
    const map = {
        'Animals': `<svg viewBox="0 0 24 24"><ellipse cx="12" cy="16.5" rx="5.2" ry="4.1"/><ellipse cx="5.1" cy="11.2" rx="2" ry="2.8" transform="rotate(-18 5.1 11.2)"/><ellipse cx="9.1" cy="6.2" rx="2.1" ry="3"/><ellipse cx="14.9" cy="6.2" rx="2.1" ry="3"/><ellipse cx="18.9" cy="11.2" rx="2" ry="2.8" transform="rotate(18 18.9 11.2)"/></svg>`,
        'Plants': `<svg viewBox="0 0 24 24"><path d="M19.5 3C9.5 3 4 8.5 4 14.5c0 1.9.5 3.4 1.4 4.6C6.3 15.7 9.1 12.9 13.6 11 10.1 13.4 8 16.1 7 19.7c1.2.9 2.8 1.3 4.6 1.3C18.6 21 20.6 12 19.5 3z"/></svg>`,
        'Microbes': `<svg viewBox="0 0 24 24"><rect x="3.5" y="8.2" width="14.5" height="7.6" rx="3.8" transform="rotate(-35 10.7 12)"/><path d="M17.6 5.4l2.6-2.6M20.4 9.2l2.4-1.1M5.3 19l-2.6 2.6M3.4 15l-1.9 1.7" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`,
        'Fungi': `<svg viewBox="0 0 24 24"><path d="M2.5 12.5a9.5 8.5 0 0 1 19 0z"/><path d="M8.6 13.5h6.8v4.2a3.4 3.4 0 0 1-6.8 0z"/></svg>`,
        'Other Eukaryotes': `<svg class="st" viewBox="0 0 24 24"><path d="M7 3c0 5.2 10 5.2 10 9s-10 3.8-10 9"/><path d="M17 3c0 5.2-10 5.2-10 9s10 3.8 10 9"/><path d="M8 6.6h8M7.6 12h8.8M8 17.4h8"/></svg>`
    };
    return map[name] || '';
}

function renderKingdoms(kingdoms) {
    kingdomOptions = kingdoms;
    const container = document.getElementById('kingdomContainer');
    container.innerHTML = kingdoms.map(k => `
        <button type="button" class="ks-tile kingdom-card"
             data-kingdom="${k.name}"
             onclick="selectKingdom('${k.name}')">
            <i class="ki" aria-hidden="true">${kingdomIconSvg(k.name)}</i>
            <b>${k.name}</b>
            <span>${k.description}</span>
        </button>
    `).join('');
}

async function selectKingdom(kingdom) {
    selectedKingdom = kingdom;

    const cards = document.querySelectorAll('.kingdom-card');
    cards.forEach(card => {
        if (card.dataset.kingdom === kingdom) {
            card.classList.add('ks-loading');
            card.setAttribute('aria-busy', 'true');
        } else {
            card.style.opacity = '0.5';
            card.style.pointerEvents = 'none';
        }
    });

    document.getElementById('selectedKingdomName').textContent = kingdom;
    document.getElementById('kingdomContainer').style.display = 'none';
    document.getElementById('speciesSection').style.display = 'block';

    document.getElementById('speciesSearch').value = '';
    await loadSpecies(kingdom, '');
    document.getElementById('speciesSearch').focus();

    cards.forEach(card => {
        card.classList.remove('ks-loading');
        card.removeAttribute('aria-busy');
        card.style.opacity = '1';
        card.style.pointerEvents = 'auto';
    });
}

function resetKingdomSelection() {
    selectedKingdom = null;
    selectedOrganism = null;
    renderKingdoms(kingdomOptions);
    document.getElementById('kingdomContainer').style.display = '';
    document.getElementById('speciesSection').style.display = 'none';
    document.getElementById('selectedOrganismDisplay').style.display = 'none';
    document.getElementById('organismDirectSection').style.display = 'block';
    document.getElementById('evidenceCoverageNote').style.display = 'none';
    document.getElementById('organism').value = '';
    document.getElementById('taxid').value = '';
}

async function loadSpecies(kingdom, query = '') {
    const list = document.getElementById('speciesList');

    // Show custom loading state
    list.innerHTML = `
        <div class="li ks-list-loading">
            <span class="ks-spin" style="width:18px;height:18px;vertical-align:middle;margin-right:8px;"></span>
            <span style="color:var(--ks-muted);">${query ? `Searching for "${query}"...` : 'Loading species...'}</span>
        </div>
    `;
    
    try {
        const url = `/api/organisms/by-kingdom?kingdom=${encodeURIComponent(kingdom)}${query ? '&q=' + encodeURIComponent(query) : ''}`;
        const response = await ksFetch(url);
        const data = await response.json();
        renderSpecies(data.results);
    } catch (error) {
        console.error('Error loading species:', error);
        list.innerHTML = '<div class="li" style="color:var(--ks-bad);">Error loading species. Please try again.</div>';
    }
}

function renderSpecies(species) {
    const list = document.getElementById('speciesList');

    if (species.length === 0) {
        list.innerHTML = '<div class="li" style="color:var(--ks-muted);">No species found</div>';
        return;
    }

    list.innerHTML = species.map(s => {
        const code = s.code ? ` · ${s.code}` : '';
        return `
        <div class="li"
             onclick="selectOrganism('${s.name}', '${s.taxid}', '${s.common_name || ''}', true)"
             style="cursor: pointer;">
            <b><i>${s.name}</i></b>
            ${s.common_name ? `<em>${s.common_name}</em>` : ''}
            <span class="ks-r">${s.taxid}${code}</span>
        </div>
    `}).join('');
}

function selectOrganism(name, taxid, commonName, fromCategory = false) {
    if (!fromCategory) selectedKingdom = null;
    selectedOrganism = { name, taxid, commonName };

    // Update hidden fields
    document.getElementById('organism').value = name;
    document.getElementById('taxid').value = taxid;

    // Update display
    document.getElementById('selectedOrganismName').textContent = name + (commonName ? ` (${commonName})` : '');
    document.getElementById('selectedOrganismTaxid').textContent = taxid;
    document.getElementById('selectedOrganismDisplay').style.display = 'block';
    document.getElementById('speciesSection').style.display = 'none';
    document.getElementById('organismDirectSection').style.display = 'none';
    document.getElementById('kingdomContainer').style.display = 'none';

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
        } else if (data.distant && !(data.layers || []).includes('knockout')) {
            text = `Only the knockout of the mouse ortholog is known for ${data.name}. It is shown as a hint (a lethal mouse ortholog raises the concern), but verdicts are never better than CAUTION.`;
        } else {
            const phrases = {
                knockout: 'knockout viability', 'ortholog-knockout': "the mouse ortholog's knockout", 'cell-essentiality': 'cell-line screens (DepMap)',
                constraint: 'tolerance of loss-of-function variants (gnomAD)', paralogs: 'close paralogs',
                expression: String(taxid) === '9606' ? 'tissue expression (GTEx)' : 'tissue expression of the human ortholog (GTEx)',
                'lethality-estimate': 'an estimate of lethality for genes that were never knocked out',
            };
            const community = { 7955: 'ZFIN', 7227: 'FlyBase', 6239: 'WormBase' }[String(taxid)];
            if (community) phrases.knockout = `knockout viability (${community} mutants)`;
            const layers = (data.layers || []).map((l) => phrases[l]).filter(Boolean);
            // genes with a knockout result, not every gene that has a record (human records also hold expression-only genes)
            const measured = data.measured ?? data.genes;
            text = `Measured knockout data exist for ${data.name}: ${measured.toLocaleString()} genes` + (layers.length ? `, with ${layers.join(', ')}.` : '.');
            if (data.distant) {
                text += " Genes without a measurement of their own only have the mouse ortholog's knockout as a hint; verdicts for them are never better than CAUTION.";
            }
            const check = data.reliability;
            if (check) {
                // an independent test (DEG essential genes): a source that calls nearly everything lethal cannot tell essential genes apart
                text += ` Independent check: ${check.essential_called_lethal}% of ${check.essential_genes} known essential genes are called lethal here, `
                    + `against ${check.all_called_lethal}% of all genes with a result`
                    + (check.essential_called_lethal - check.all_called_lethal < 25 ? ', so a lethal call is only weak evidence.' : '.');
            }
            if (community) {
                // lethal results are reported far more often than viable ones in these databases (VALIDATION.md, section 8)
                text += ` ${community} reports lethal mutants far more often than viable ones, so a lethal call is a strong hint to confirm, not proof, and most genes have no result at all.`;
            }
        }
        note.textContent = text;
        note.style.display = 'block';
    } catch (error) {
        // the note is only a courtesy
    }
}

async function resetOrganismSelection() {
    selectedOrganism = null;
    const coverageNote = document.getElementById('evidenceCoverageNote');
    if (coverageNote) coverageNote.style.display = 'none';
    document.getElementById('selectedOrganismDisplay').style.display = 'none';
    document.getElementById('organismDirectSection').style.display = 'block';
    document.getElementById('organismDirectSearch').value = '';
    document.getElementById('organismDirectResults').innerHTML = '';
    document.getElementById('organism').value = '';
    document.getElementById('taxid').value = '';

    if (selectedKingdom) {
        document.getElementById('kingdomContainer').style.display = 'none';
        document.getElementById('speciesSection').style.display = 'block';
        document.getElementById('speciesSearch').value = '';
        await loadSpecies(selectedKingdom, '');
        document.getElementById('speciesSearch').focus();
    } else {
        renderKingdoms(kingdomOptions);
        document.getElementById('speciesSection').style.display = 'none';
        document.getElementById('kingdomContainer').style.display = '';
    }
}

async function searchOrganismDirect(query) {
    const list = document.getElementById('organismDirectResults');
    if (!query || query.length < 2) {
        list.innerHTML = '';
        return;
    }

    list.innerHTML = `
        <div class="li ks-list-loading">
            <span class="ks-spin" style="width:14px;height:14px;vertical-align:middle;margin-right:8px;"></span>
            <span style="color:var(--ks-muted);">Searching organisms...</span>
        </div>
    `;

    try {
        // 1. Fast local substring search over the KEGG organism list.
        const localResponse = await ksFetch(`/api/organisms/search?q=${encodeURIComponent(query)}`);
        const localData = await localResponse.json();
        const localResults = localData.results || [];

        // Show local matches immediately.
        renderOrganismDirectResults(localResults, true);

        // 2. Broader NCBI search to catch organisms not in the local list.
        const ncbiResponse = await ksFetch(`/api/organisms/ncbi-search?q=${encodeURIComponent(query)}`);
        const ncbiData = await ncbiResponse.json();
        const ncbiResults = ncbiData.results || [];

        // Merge: local results first, then NCBI results not already shown.
        const seen = new Set(localResults.map(r => r.taxid));
        const merged = [
            ...localResults,
            ...ncbiResults.filter(r => r.taxid && !seen.has(r.taxid))
        ];

        const ncbiStatus = ncbiData.external_status
            ? formatExternalStatus(ncbiData.external_status)
            : null;
        renderOrganismDirectResults(merged, false, ncbiStatus);
    } catch (error) {
        console.error('Error searching organisms:', error);
        list.innerHTML = '<div class="li" style="color:var(--ks-bad);">Error searching organisms.</div>';
    }
}

function formatExternalStatus(status) {
    if (!status) return null;
    const badge = (bg, color, border, text) =>
        `<span style="display:inline-flex;align-items:center;gap:6px;font:500 12px var(--ks-f-sans);padding:2px 8px;border-radius:4px;background:${bg};color:${color};border:1px solid ${border};">${text}</span>`;
    if (status.cache_hits > 0 && status.cache_misses === 0) {
        return badge('var(--ks-safe-bg)', 'var(--ks-safe)', 'var(--ks-safe)', 'cached');
    }
    if (status.cache_hits > 0 && status.cache_misses > 0) {
        return badge('var(--ks-info-bg)', 'var(--ks-info)', 'var(--ks-info)', `${status.cache_hits} cached, ${status.cache_misses} live`);
    }
    return badge('var(--ks-well)', 'var(--ks-muted)', 'var(--ks-line)', 'live data');
}

function renderOrganismDirectResults(results, isPartial, statusHtml = null) {
    const list = document.getElementById('organismDirectResults');
    if (results.length === 0) {
        if (isPartial) return; // Wait for NCBI before showing "No organisms found".
        list.innerHTML = '<div class="li" style="color:var(--ks-muted);">No organisms found</div>';
        return;
    }

    const items = results.map(s => {
        const safeName = String(s.name || '').replace(/'/g, "\\'");
        const safeCommon = String(s.common_name || '').replace(/'/g, "\\'");
        const code = s.code ? ` · ${s.code}` : '';
        return `
        <div class="li"
             onclick="selectOrganism('${safeName}', '${s.taxid}', '${safeCommon}')"
             style="cursor: pointer;">
            <b><i>${s.name}</i></b>
            ${s.common_name ? `<em>${s.common_name}</em>` : ''}
            <span class="ks-r">${s.taxid}${code}</span>
        </div>
        `;
    }).join('');

    const footer = statusHtml
        ? `<div class="li" style="text-align:right;padding:4px 14px;">${statusHtml}</div>`
        : '';
    list.innerHTML = items + footer;
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
        <button type="button" class="ks-tile go-category-card"
             data-category="${c.name}"
             onclick="selectGoCategory('${c.name}')">
            <b>${c.name}</b>
            <span>${c.description}</span>
        </button>
    `).join('');
}

async function selectGoCategory(category) {
    selectedCategory = category;

    // Show loading state on the clicked card
    const cards = document.querySelectorAll('.go-category-card');
    cards.forEach(card => {
        if (card.dataset.category === category) {
            card.classList.add('ks-loading');
            card.setAttribute('aria-busy', 'true');
        } else {
            card.style.opacity = '0.5';
            card.style.pointerEvents = 'none';
        }
    });

    // Update UI
    document.getElementById('selectedCategoryName').textContent = category;
    document.getElementById('goCategoryContainer').style.display = 'none';
    document.getElementById('goDirectInputSection').style.display = 'none';
    document.getElementById('goTermsSection').style.display = 'block';

    // Clear direct input
    document.getElementById('go_term_direct').value = '';

    // Clear search and load terms
    document.getElementById('goTermSearch').value = '';
    await loadGoTerms(category, '');

    // Reset cards state
    cards.forEach(card => {
        card.classList.remove('ks-loading');
        card.removeAttribute('aria-busy');
        card.style.opacity = '1';
        card.style.pointerEvents = 'auto';
    });

    // Focus on search input
    document.getElementById('goTermSearch').focus();
}

function resetCategorySelection() {
    selectedCategory = null;
    selectedGoTerm = null;
    document.getElementById('goCategoryContainer').style.display = '';
    document.getElementById('goDirectInputSection').style.display = 'block';
    document.getElementById('goTermsSection').style.display = 'none';
    document.getElementById('selectedGoTermDisplay').style.display = 'none';
    document.getElementById('go_term').value = '';
    document.getElementById('go_term_name').value = '';
}

async function loadGoTerms(category, query = '') {
    const list = document.getElementById('goTermsList');

    // Show custom loading state
    list.innerHTML = `
        <div class="li ks-list-loading">
            <span class="ks-spin" style="width:18px;height:18px;vertical-align:middle;margin-right:8px;"></span>
            <span style="color:var(--ks-muted);">${query ? `Searching GO terms for "${query}"...` : `Loading ${category} terms...`}</span>
        </div>
    `;
    
    try {
        const url = `/api/go-terms/by-category?category=${encodeURIComponent(category)}${query ? '&q=' + encodeURIComponent(query) : ''}`;
        const response = await ksFetch(url);
        const data = await response.json();
        renderGoTerms(data.results);
    } catch (error) {
        console.error('Error loading GO terms:', error);
        list.innerHTML = '<div class="li" style="color:var(--ks-bad);">Error loading GO terms. Please try again.</div>';
    }
}

function renderGoTerms(terms) {
    const list = document.getElementById('goTermsList');

    if (terms.length === 0) {
        list.innerHTML = '<div class="li" style="color:var(--ks-muted);">No GO terms found</div>';
        return;
    }

    list.innerHTML = terms.map(t => `
        <div class="li"
             onclick="selectGoTerm('${t.id}', '${t.name.replace(/'/g, "\\'")}')"
             style="cursor: pointer;">
            <b>${t.name}</b>
            ${t.definition ? `<em>${t.definition}</em>` : ''}
            <span class="ks-r">${t.id}</span>
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
    document.getElementById('go_term').value = '';
    document.getElementById('go_term_name').value = '';
    if (selectedCategory) {
        // Came from the category/Step B flow: go back to Step B
        document.getElementById('goTermsSection').style.display = 'block';
        loadGoTerms(selectedCategory, document.getElementById('goTermSearch').value);
    } else {
        // Came from direct entry: go back to the initial category + direct input view
        document.getElementById('goCategoryContainer').style.display = '';
        document.getElementById('goDirectInputSection').style.display = 'block';
        document.getElementById('goTermsSection').style.display = 'none';
    }
}

// ============================================================================
// Database Selection
// ============================================================================

async function loadDatabases() {
    const container = document.getElementById('databaseContainer');
    
    try {
        const response = await ksFetch('/api/databases');
        const data = await response.json();
        
        container.innerHTML = data.databases.map(db => {
            const on = db.required;
            const disabled = !db.enabled;
            return `
            <div class="ks-dbrow ${on ? 'on' : ''} ${disabled ? 'disabled' : ''}"
                 role="checkbox"
                 aria-checked="${on}"
                 ${disabled ? 'aria-disabled="true"' : 'tabindex="0"'}
                 data-id="${db.id}"
                 ${disabled ? 'onclick="return false;"' : 'onclick="toggleDatabaseRow(this)"'}
                 ${disabled ? '' : 'onkeydown="if(event.key===\' \'||event.key===\'Enter\'){event.preventDefault();toggleDatabaseRow(this)}"'}>
                <span class="ks-cb">${on ? '&#10003;' : ''}</span>
                <div>
                    <b>${db.name}</b>
                    ${db.required ? '<span class="ks-req">Required</span>' : ''}
                    <small>${db.description}</small>
                </div>
                <input type="checkbox"
                       class="database-checkbox"
                       value="${db.id}"
                       ${on ? 'checked disabled' : ''}
                       ${disabled ? 'disabled' : ''}
                       onchange="updateDatabaseRow(this)"
                       style="position:absolute;opacity:0;width:1px;height:1px;">
            </div>
        `}).join('');
        
    } catch (error) {
        console.error('Error loading databases:', error);
    }
}

function toggleDatabaseRow(row) {
    const checkbox = row.querySelector('.database-checkbox:not(:disabled)');
    if (checkbox) {
        checkbox.checked = !checkbox.checked;
        updateDatabaseRow(checkbox);
    }
}

function updateDatabaseRow(checkbox) {
    const row = checkbox.closest('.ks-dbrow');
    const on = checkbox.checked;
    row.classList.toggle('on', on);
    row.setAttribute('aria-checked', on);
    row.querySelector('.ks-cb').innerHTML = on ? '&#10003;' : '';
}

// ============================================================================
// Event Listeners
// ============================================================================

function initializeEventListeners() {
    // Direct organism search
    document.getElementById('organismDirectSearch')?.addEventListener('input', debounce(function() {
        searchOrganismDirect(this.value.trim());
    }, 300));

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
    document.getElementById('go_term_direct')?.addEventListener('input', debounce(async function() {
        const value = this.value.trim().toUpperCase();
        if (/^GO:\d{7}$/.test(value)) {
            let name = 'Direct entry';
            try {
                const response = await ksFetch(`/api/go-terms/search?q=${encodeURIComponent(value)}`);
                const data = await response.json();
                const match = data.results?.find((t) => t.id === value);
                if (match?.name) name = match.name;
            } catch (error) {
                console.warn('Could not look up GO term name:', error);
            }
            selectGoTerm(value, name);
            // Reset category selection
            document.getElementById('goCategoryContainer').style.display = 'flex';
            document.getElementById('goTermsSection').style.display = 'none';
        }
    }, 300));
    
    // Parameter changes for gene count check — react quickly and cancel stale requests.
    ['max_genes', 'predict_phenotypes', 'evidence_filter', 'max_pleiotropy', 'knockout_context'].forEach(id => {
        const element = document.getElementById(id);
        if (!element) return;
        const eventType = element.type === 'checkbox' || element.tagName === 'SELECT' ? 'change' : 'input';
        element.addEventListener(eventType, () => {
            clearTimeout(geneCountCheckTimeout);
            geneCountCheckTimeout = setTimeout(checkGeneCount, 200);
        });
    });

    // Database selection also affects runtime.
    document.getElementById('databaseContainer')?.addEventListener('change', () => {
        clearTimeout(geneCountCheckTimeout);
        geneCountCheckTimeout = setTimeout(checkGeneCount, 200);
    });

    // RAG phenotype prediction: slide-out card, brain icon highlight, provider flow
    const llmProviderInput = document.getElementById('llm_provider');
    const llmApiKeyInput = document.getElementById('llm_api_key');
    const brainIcon = document.getElementById('ragBrainIcon');
    const llmKeySection = document.getElementById('llmKeySection');
    const predictCheckbox = document.getElementById('predict_phenotypes');
    // Start with no provider selected; the user must explicitly choose one to reveal the key field.
    if (llmProviderInput) llmProviderInput.value = 'kimi';
    const triggerText = document.getElementById('llmProviderTriggerText');
    if (triggerText) triggerText.textContent = 'Pick a model to read abstracts';
    // Set brain icon initial state to match the checkbox (rerun links may have it on).
    if (brainIcon && predictCheckbox) brainIcon.classList.toggle('active', predictCheckbox.checked);
    predictCheckbox?.addEventListener('change', function () {
        if (brainIcon) {
            brainIcon.classList.toggle('active', this.checked);
            if (this.checked) {
                brainIcon.classList.remove('pop');
                // force reflow so the animation can be re-triggered
                void brainIcon.offsetWidth;
                brainIcon.classList.add('pop');
                setTimeout(() => brainIcon.classList.remove('pop'), 350);
            }
        }
        const section = document.getElementById('llmKeySection');
        if (section) {
            section.classList.toggle('ks-hide', !this.checked);
            if (!this.checked) {
                const apiKeyWrapper = document.getElementById('llmApiKeyWrapper');
                const options = document.getElementById('llmProviderOptions');
                if (apiKeyWrapper) apiKeyWrapper.classList.add('ks-hide');
                if (options) options.classList.add('ks-hide');
            }
        }
    });
    
    // Show every gene of the GO term in the report (the limit is 500)
    document.getElementById('showAllGenes')?.addEventListener('click', () => {
        const input = document.getElementById('max_genes');
        input.value = input.max || 500;
        input.dispatchEvent(new Event('change'));
        const note = document.getElementById('showAllNote');
        if (note) note.style.display = 'inline';
    });
    // typing a smaller number again ends "show all"
    document.getElementById('max_genes')?.addEventListener('input', () => {
        const note = document.getElementById('showAllNote');
        if (note) note.style.display = 'none';
    });

    // Refresh gene count
    document.getElementById('refreshGeneCount')?.addEventListener('click', checkGeneCount);
    
    // Form submission
    document.getElementById('analysisForm')?.addEventListener('submit', handleFormSubmit);

    // Dock summary: keep it in sync with the form
    updateDockSummary();
    ['organism','go_term','max_genes','max_pleiotropy','predict_phenotypes'].forEach(id => {
        document.getElementById(id)?.addEventListener('change', updateDockSummary);
    });
    document.getElementById('databaseContainer')?.addEventListener('change', updateDockSummary);
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
    const maxPleiotropy = document.getElementById('max_pleiotropy')?.value || 5;
    const knockoutContext = document.getElementById('knockout_context')?.value || 'auto';
    const selectedDatabases = Array.from(
        document.querySelectorAll('.database-checkbox:checked')
    ).map(cb => cb.value);

    if (!organism || !goTerm) {
        document.getElementById('geneCountPreview').style.display = 'none';
        return;
    }

    // Cancel any in-flight request so the UI never shows stale data.
    if (geneCountAbortController) {
        geneCountAbortController.abort();
    }
    geneCountAbortController = new AbortController();

    try {
        const response = await ksFetch('/api/analyze/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: geneCountAbortController.signal,
            body: JSON.stringify({
                organism,
                go_term: goTerm,
                max_genes: maxGenes,
                max_pleiotropy: maxPleiotropy,
                predict_phenotypes: predictPhenotypes,
                evidence_filter: evidenceFilter,
                knockout_context: knockoutContext,
                databases: selectedDatabases
            })
        });

        const data = await response.json();

        const preview = document.getElementById('geneCountPreview');
        const value = document.getElementById('geneCountValue');
        const timeDiv = document.getElementById('estimatedTime');
        const timeValue = document.getElementById('estimatedTimeValue');
        const warning = document.getElementById('geneCountWarning');
        const warningText = document.getElementById('geneCountWarningText');
        const statusDiv = document.getElementById('geneCountStatus');
        const statusText = document.getElementById('geneCountStatusText');

        preview.style.display = 'block';

        if (data.gene_count !== undefined) {
            value.textContent = data.gene_count;

            if (data.estimated_time_formatted) {
                timeValue.textContent = data.estimated_time_formatted;
                timeDiv.style.display = 'block';
            } else {
                timeDiv.style.display = 'none';
            }

            if (data.warnings && data.warnings.length > 0) {
                warning.style.display = 'block';
                warningText.textContent = data.warnings.join('; ');
            } else {
                warning.style.display = 'none';
            }

            const statusHtml = data.external_status ? formatExternalStatus(data.external_status) : null;
            if (statusHtml) {
                statusDiv.style.display = 'block';
                statusText.innerHTML = statusHtml;
            } else {
                statusDiv.style.display = 'none';
            }
        }

    } catch (error) {
        if (error.name !== 'AbortError') {
            console.error('Error checking gene count:', error);
        }
    } finally {
        geneCountAbortController = null;
    }
}

// ============================================================================
// Form Submission
// ============================================================================

const FORM_REQUEST_TIMEOUT_MS = 90000;

function fetchWithTimeout(url, options) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), FORM_REQUEST_TIMEOUT_MS);
    return ksFetch(url, Object.assign({}, options, { signal: controller.signal }))
        .finally(() => clearTimeout(timeoutId));
}

async function handleFormSubmit(e) {
    e.preventDefault();

    // Show loading
    showLoading('Validating parameters...');

    // Collect form data
    const formData = collectFormData();

    // Validate
    try {
        const validation = await fetchWithTimeout('/api/analyze/validate', {
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

        const response = await fetchWithTimeout('/api/analyze/start', {
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
        if (error.name === 'AbortError') {
            showValidationErrors(['The request timed out. The analysis server may be waking up or the network is slow. Please try again in a moment.']);
        } else {
            console.error('Error:', error);
            showValidationErrors(['Network error. Please try again.']);
        }
    }
}

const LLM_PROVIDER_NAMES = {
    kimi: 'Kimi (Moonshot)',
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    qwen: 'Qwen (Alibaba)',
    deepseek: 'DeepSeek',
    grok: 'Grok (xAI)',
};

function updateLlmKeyPlaceholder(provider) {
    const input = document.getElementById('llm_api_key');
    if (!input) return;
    const placeholders = {
        openai: 'sk-proj-...',
        anthropic: 'sk-ant-...',
        kimi: 'sk-...',
        qwen: 'sk-...',
        deepseek: 'sk-...',
        grok: 'xai-...',
    };
    input.placeholder = placeholders[provider] || 'Paste your provider API key here';
}

function toggleLlmProviderPanel() {
    const options = document.getElementById('llmProviderOptions');
    const trigger = document.getElementById('llmProviderTrigger');
    const apiKeyWrapper = document.getElementById('llmApiKeyWrapper');
    if (!options || !trigger) return;
    const isOpen = !options.classList.contains('ks-hide');
    options.classList.toggle('ks-hide', isOpen);
    trigger.classList.toggle('open', !isOpen);
    // Hide the key field while the user is choosing a provider; it reappears after selection.
    if (!isOpen && apiKeyWrapper) apiKeyWrapper.classList.add('ks-hide');
}

function selectLlmProvider(provider, save = true) {
    const input = document.getElementById('llm_provider');
    const triggerText = document.getElementById('llmProviderTriggerText');
    const apiKeyWrapper = document.getElementById('llmApiKeyWrapper');
    const selectedName = document.getElementById('llmSelectedProviderName');
    if (input) input.value = provider;
    if (triggerText) triggerText.textContent = LLM_PROVIDER_NAMES[provider] || 'Select API key';
    if (selectedName) selectedName.textContent = LLM_PROVIDER_NAMES[provider] || provider;

    document.querySelectorAll('.provider-option').forEach((card) => {
        card.classList.toggle('selected', card.dataset.provider === provider);
    });

    // Hide the provider grid and show the API key field
    const options = document.getElementById('llmProviderOptions');
    const trigger = document.getElementById('llmProviderTrigger');
    if (options) options.classList.add('ks-hide');
    if (trigger) trigger.classList.remove('open');
    if (apiKeyWrapper) apiKeyWrapper.classList.remove('ks-hide');

    updateLlmKeyPlaceholder(provider);
    if (save) localStorage.setItem('ksites.llmProvider', provider);
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
        llm_provider: document.getElementById('llm_provider')?.value || 'kimi',
        llm_api_key: document.getElementById('llm_api_key')?.value?.trim() || '',
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


function updateDockSummary() {
    const organism = document.getElementById('organism')?.value?.trim() || '—';
    const goTerm = document.getElementById('go_term')?.value?.trim() || '—';
    const maxGenes = document.getElementById('max_genes')?.value || '10';
    const maxPleiotropy = document.getElementById('max_pleiotropy')?.value || '5';
    const ragOn = document.getElementById('predict_phenotypes')?.checked || false;

    const selectedDbs = Array.from(
        document.querySelectorAll('.database-checkbox:checked')
    ).map(cb => {
        const map = {
            quickgo: 'QuickGO',
            uniprot: 'UniProt',
            mygene: 'MyGene.info',
            ncbi: 'NCBI Gene'
        };
        return map[cb.value] || cb.value;
    });
    const dbLabel = selectedDbs.length > 0 ? selectedDbs.join(', ') : 'QuickGO';

    const orgEl = document.getElementById('dockOrg');
    const goEl = document.getElementById('dockGo');
    const dbEl = document.getElementById('dockDb');
    const nEl = document.getElementById('dockN');
    const pEl = document.getElementById('dockP');
    const ragEl = document.getElementById('dockRag');

    if (orgEl) orgEl.textContent = organism;
    if (goEl) goEl.textContent = goTerm;
    if (dbEl) dbEl.textContent = dbLabel;
    if (nEl) nEl.textContent = maxGenes;
    if (pEl) pEl.textContent = maxPleiotropy;
    if (ragEl) ragEl.textContent = ragOn ? 'RAG on' : 'RAG off';
}
