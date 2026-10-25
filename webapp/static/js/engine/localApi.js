/**
 * The in-browser "server": answers the same /api/... requests the website already makes, so the
 * pages work unchanged, but jobs run in this browser and results are kept in IndexedDB.
 *
 * Everything the backend needs (store, HTTP client, KEGG data, phenotype model) is injected, so it
 * is testable without a browser.
 */

import { getGenesForGoTermWithCoverage } from './goMapper.js';
import { runKSitesPipeline } from './pipeline.js';
import { GO_CATEGORIES, KINGDOMS, FALLBACK_ORGANISMS, resolveTaxid, searchGoTerms, searchOrganisms } from './organisms.js';
import { comprehensiveCsv, excelWorkbook, geneSummaryCsv, htmlReport } from './report.js';

export const VERSION = '1.2.1';
const EVIDENCE_FILTERS = ['experimental', 'computational', 'all'];

const DATABASES = [
    { id: 'quickgo', name: 'QuickGO', description: 'Gene Ontology annotations from EBI (always used)', enabled: true, required: true },
    { id: 'uniprot', name: 'UniProt', description: 'Protein knowledgebase with functional annotation', enabled: true, required: false },
    { id: 'ncbi', name: 'NCBI Entrez', description: 'Gene and genome database', enabled: true, required: false },
    { id: 'pubmed', name: 'PubMed', description: 'Literature mining for phenotype evidence', enabled: true, required: false },
    { id: 'kegg', name: 'KEGG', description: 'Pathway annotations (pathway count per gene)', enabled: true, required: false },
];

function jsonResponse(body, status = 200, headers = {}) {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });
}

export function formatDuration(seconds) {
    if (seconds < 60) return `${seconds} seconds`;
    if (seconds < 3600) {
        const minutes = Math.floor(seconds / 60);
        return `${minutes} minute${minutes > 1 ? 's' : ''}`;
    }
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${hours} hour${hours > 1 ? 's' : ''} ${minutes} min`;
}

/** Rough run time: every gene of the GO term is scored (about 4 s each); phenotype prediction adds about 12 s each. */
export function estimateSeconds(geneCount, predictPhenotypes) {
    return Math.round(30 + geneCount * (4 + (predictPhenotypes ? 12 : 0)));
}

/** Where each pipeline stage sits on the 0-100% progress bar (same stops as the page's step list). */
const PROGRESS_RANGES = {
    'Reading GO annotations': [15, 15],
    'Scoring genes': [30, 30],
    'Assessing genes': [60, 25],
};

export class LocalBackend {
    /**
     * @param deps {
     *   store, http, keggProvider, loadOrganisms(), createPredictor(onStatus),
     *   getNcbiApiKey(), locks (navigator.locks or null), now(), newId()
     * }
     */
    constructor(deps) {
        this.d = deps;
        this.running = new Set();
        this.lastWrite = {};
        this._organisms = null;
    }

    // ------------------------------------------------------------ routing

    async handle(path, options = {}) {
        const url = new URL(path, 'http://ksites.local');
        const method = (options.method || 'GET').toUpperCase();
        const route = url.pathname;
        const params = url.searchParams;
        let body = {};
        if (options.body) {
            try { body = JSON.parse(options.body); } catch (e) { return jsonResponse({ error: 'Invalid request body' }, 400); }
        }

        try {
            if (route === '/api/health') return jsonResponse({ status: 'ok', mode: 'browser', hosted: false, version: VERSION });
            if (route === '/api/auth/check') return jsonResponse({ ok: true, hosted: false });
            if (route === '/api/databases') return jsonResponse({ databases: DATABASES });

            if (route === '/api/organisms/kingdoms') return jsonResponse({ kingdoms: KINGDOMS });
            if (route === '/api/organisms/by-kingdom') {
                const kingdom = params.get('kingdom');
                const query = (params.get('q') || '').trim();
                return jsonResponse({ results: searchOrganisms(await this._getOrganisms(), kingdom, query || null), kingdom, query });
            }
            if (route === '/api/organisms/search') {
                const query = (params.get('q') || '').trim();
                if (query.length < 2) return jsonResponse({ results: [] });
                return jsonResponse({ results: searchOrganisms(await this._getOrganisms(), null, query), query });
            }
            if (route === '/api/go-terms/categories') return jsonResponse({ categories: GO_CATEGORIES });
            if (route === '/api/go-terms/by-category') {
                const category = params.get('category');
                const query = (params.get('q') || '').trim();
                return jsonResponse({ results: await searchGoTerms(this.d.http, category, query || null), category, query });
            }
            if (route === '/api/go-terms/search') {
                const query = (params.get('q') || '').trim();
                if (query.length < 2) return jsonResponse({ results: [] });
                return jsonResponse({ results: await searchGoTerms(this.d.http, null, query), query });
            }

            if (route === '/api/analyze/validate' && method === 'POST') return jsonResponse(await this.validate(body));
            if (route === '/api/analyze/start' && method === 'POST') return await this.start(body);

            if (route === '/api/jobs') return jsonResponse({ jobs: await this.listJobs() });

            const match = /^\/api\/jobs\/([^/]+)\/(status|results|download)(?:\/([^/]+))?$/.exec(route);
            if (match) {
                const [, jobId, action, fileType] = match;
                if (action === 'status') return await this.status(jobId);
                if (action === 'results') return await this.results(jobId);
                return await this.download(jobId, fileType);
            }
            return jsonResponse({ error: 'Not found' }, 404);
        } catch (error) {
            return jsonResponse({ error: String(error && error.message ? error.message : error) }, 500);
        }
    }

    async _getOrganisms() {
        if (!this._organisms) {
            let list = null;
            try { list = await this.d.loadOrganisms(); } catch (e) { list = null; }
            this._organisms = list && list.length ? list : FALLBACK_ORGANISMS;
        }
        return this._organisms;
    }

    // ------------------------------------------------------------ validation

    async validate(data) {
        const organism = String(data.organism || '').trim();
        const goTerm = String(data.go_term || '').trim();
        const maxGenes = parseInt(data.max_genes ?? 10, 10);
        const evidenceFilter = data.evidence_filter || 'experimental';
        const maxPleiotropy = data.max_pleiotropy ?? 5;
        const errors = [];
        const warnings = [];

        if (!organism) errors.push('Organism is required');
        if (!goTerm) errors.push('GO term is required');
        else if (!goTerm.toUpperCase().startsWith('GO:')) errors.push('GO term must be in format GO:XXXXXXX');

        const cutoff = Number(maxPleiotropy);
        if (!Number.isInteger(cutoff) || cutoff < 0 || cutoff > 10) errors.push('Max pleiotropy must be between 0 and 10');
        if (!EVIDENCE_FILTERS.includes(evidenceFilter)) errors.push('Evidence filter must be experimental, computational or all');
        if (!(maxGenes >= 1)) errors.push('Maximum genes must be at least 1');
        else if (maxGenes > 500) errors.push('Genes to report must be at most 500');

        if (!organism || !goTerm || errors.length) return { valid: errors.length === 0, errors, warnings };

        try {
            const taxid = await resolveTaxid(this.d.http, organism, data.taxid);
            const { genes, coverage } = await getGenesForGoTermWithCoverage(this.d.http, goTerm.toUpperCase(), taxid, evidenceFilter);
            if (coverage.message) warnings.push(coverage.message);

            const total = genes.length;
            if (total === 0) {
                errors.push(`No genes found for ${goTerm} in ${organism}. Try a different GO term or organism.`);
            } else if (maxGenes > total) {
                warnings.push(`Only ${total} genes available. The report will include all of them.`);
            } else if (total > maxGenes) {
                warnings.push(`${total} genes found. All are scored; the report shows the top ${maxGenes} by composite score.`);
            }

            const seconds = estimateSeconds(total, !!data.predict_phenotypes);
            return {
                valid: errors.length === 0, errors, warnings, gene_count: total, organism_resolved: organism, taxid,
                estimated_time_seconds: seconds, estimated_time_formatted: formatDuration(seconds),
            };
        } catch (error) {
            warnings.push(`Could not validate gene count: ${error.message}`);
            return { valid: errors.length === 0, errors, warnings };
        }
    }

    // ------------------------------------------------------------ jobs

    _toDict(job) {
        return {
            id: job.id,
            created_at: job.created_at ?? null, updated_at: job.updated_at ?? null,
            status: job.status ?? 'pending', current_step: job.current_step ?? '', progress_percent: job.progress_percent ?? 0,
            estimated_completion: job.estimated_completion || null,
            user_id: null, user_email: job.user_email || null,
            organism: job.organism ?? '', taxid: job.taxid ?? '', go_term: job.go_term ?? '', go_term_name: job.go_term_name ?? '',
            max_genes: job.max_genes ?? null, max_pleiotropy: job.max_pleiotropy ?? null, evidence_filter: job.evidence_filter ?? 'experimental',
            predict_phenotypes: !!job.predict_phenotypes,
            selected_databases: job.selected_databases || [],
            total_genes_found: job.total_genes_found ?? null, genes_processed: job.genes_processed ?? null,
            results_path: null, error_message: job.error_message || null,
        };
    }

    async start(data) {
        const organism = String(data.organism || '').trim();
        const goTerm = String(data.go_term || '').trim().toUpperCase();
        if (!organism || !goTerm) return jsonResponse({ success: false, error: 'Organism and GO term are required' }, 400);

        const nowIso = new Date(this.d.now()).toISOString();
        const maxGenes = Math.max(1, Math.min(500, parseInt(data.max_genes ?? 10, 10) || 10));
        const job = {
            id: this.d.newId(),
            created_at: nowIso, updated_at: nowIso,
            status: 'pending', current_step: 'Initializing', progress_percent: 0,
            estimated_completion: new Date(this.d.now() + estimateSeconds(maxGenes, !!data.predict_phenotypes) * 1000).toISOString(),
            organism, taxid: data.taxid || '', go_term: goTerm, go_term_name: data.go_term_name || '',
            max_genes: maxGenes,
            max_pleiotropy: Math.max(0, Math.min(10, parseInt(data.max_pleiotropy ?? 5, 10) || 0)),
            evidence_filter: EVIDENCE_FILTERS.includes(data.evidence_filter) ? data.evidence_filter : 'experimental',
            predict_phenotypes: !!data.predict_phenotypes,
            selected_databases: data.databases || ['quickgo'],
            user_email: data.user_email || null,
        };
        await this.d.store.putJob(job);
        // The job runs when its results page opens (a page change would stop it if it ran here).
        return jsonResponse({ success: true, job_id: job.id, status: 'pending', estimated_completion: job.estimated_completion,
            message: 'Analysis started successfully' });
    }

    async _heldLocks() {
        const locks = this.d.locks;
        if (!locks || !locks.query) return null;
        try {
            const state = await locks.query();
            return new Set((state.held || []).map((l) => l.name));
        } catch (e) {
            return null;
        }
    }

    async listJobs() {
        const jobs = (await this.d.store.listJobs()).sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
        const held = await this._heldLocks();
        return jobs.map((job) => {
            const dict = this._toDict(job);
            // a job nobody is running (its tab was closed) resumes when it is opened
            if (job.status === 'running' && held && !held.has(`ksites-job-${job.id}`) && !this.running.has(job.id)) {
                dict.status = 'pending';
                dict.current_step = 'Paused (the tab was closed). Open it to resume.';
            }
            return dict;
        });
    }

    async status(jobId) {
        const job = await this.d.store.getJob(jobId);
        if (!job) return jsonResponse({ error: 'Job not found' }, 404);
        if (job.status === 'pending' || job.status === 'running') this._ensureRunning(jobId);
        return jsonResponse(this._toDict(job));
    }

    async results(jobId) {
        const job = await this.d.store.getJob(jobId);
        if (!job) return jsonResponse({ error: 'Job not found' }, 404);
        if (job.status !== 'completed') {
            return jsonResponse({ status: job.status, current_step: job.current_step, progress_percent: job.progress_percent,
                message: `Results not available (status: ${job.status})` });
        }
        const results = await this.d.store.getResults(jobId);
        if (!results) return jsonResponse({ error: 'Results not found in this browser' }, 404);
        return jsonResponse({ status: 'completed', results });
    }

    async download(jobId, fileType) {
        const job = await this.d.store.getJob(jobId);
        if (!job || job.status !== 'completed') return jsonResponse({ error: 'Results not available' }, 404);
        const results = await this.d.store.getResults(jobId);
        if (!results) return jsonResponse({ error: 'Results not found in this browser' }, 404);

        const stamp = (job.created_at || '').replace(/\D/g, '').slice(0, 14);   // YYYYMMDDHHMMSS
        const name = (suffix) => `ksites_${job.go_term.replace(':', '')}_${stamp}${suffix}`;
        const file = (content, type, filename) => new Response(content, {
            status: 200, headers: { 'Content-Type': type, 'Content-Disposition': `attachment; filename=${filename}` },
        });

        switch (fileType) {
            case 'html': return file(htmlReport(results), 'text/html', name('.html'));
            case 'json': return file(JSON.stringify(results, null, 2), 'application/json', name('.json'));
            case 'csv': return file(comprehensiveCsv(results), 'text/csv', name('_comprehensive.csv'));
            case 'summary': return file(geneSummaryCsv(results), 'text/csv', name('_gene_summary.csv'));
            case 'xlsx':
                try {
                    return file(await excelWorkbook(results), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', name('.xlsx'));
                } catch (error) {
                    return jsonResponse({ error: `Excel file could not be created: ${error.message}` }, 500);
                }
            default: return jsonResponse({ error: 'Invalid file type' }, 400);
        }
    }

    // ------------------------------------------------------------ running a job

    _ensureRunning(jobId) {
        if (this.running.has(jobId)) return;
        const run = async () => {
            this.running.add(jobId);
            try { await this._runJob(jobId); } finally { this.running.delete(jobId); }
        };
        const locks = this.d.locks;
        if (locks && locks.request) {
            // only one tab runs a job; the lock is released if the tab is closed, so another can resume it
            locks.request(`ksites-job-${jobId}`, { ifAvailable: true }, async (lock) => { if (lock) await run(); }).catch(() => {});
        } else {
            run().catch(() => {});
        }
    }

    async _update(job, patch, force = false) {
        Object.assign(job, patch, { updated_at: new Date(this.d.now()).toISOString() });
        const now = this.d.now();
        if (force || !this.lastWrite[job.id] || now - this.lastWrite[job.id] >= 400) {
            this.lastWrite[job.id] = now;
            await this.d.store.putJob(job);
        }
    }

    async _runJob(jobId) {
        const job = await this.d.store.getJob(jobId);
        if (!job || job.status === 'completed' || job.status === 'failed') return;

        try {
            await this._update(job, { status: 'running', current_step: 'Resolving organism', progress_percent: 5, error_message: null }, true);

            const taxid = await resolveTaxid(this.d.http, job.organism, job.taxid);
            await this._update(job, { taxid, current_step: 'Fetching GO genes', progress_percent: 15 }, true);

            let predictor = null;
            if (job.predict_phenotypes) {
                await this._update(job, { current_step: 'Loading the phenotype model (about 90 MB, downloaded once)' }, true);
                try {
                    predictor = await this.d.createPredictor((message) => this._update(job, { current_step: message }, true));
                } catch (error) {
                    predictor = null;
                    job.model_error = `The phenotype model could not be loaded: ${error.message}`;
                }
            }

            const apiKey = this.d.getNcbiApiKey ? this.d.getNcbiApiKey() : '';
            if (apiKey) this.d.http.setRateLimit('eutils.ncbi.nlm.nih.gov', 10);

            const ctx = {
                http: this.d.http, keggProvider: this.d.keggProvider, ncbiApiKey: apiKey,
                ncbiEmail: job.user_email || '', phenotypePredictor: predictor,
            };
            const onProgress = (stage, done, total) => {
                const [base, span] = PROGRESS_RANGES[stage] || [30, 0];
                const fraction = total ? done / total : 1;
                this._update(job, { current_step: `${stage} (${done}/${total})`, progress_percent: Math.floor(base + span * fraction) }).catch(() => {});
            };

            const results = await runKSitesPipeline(ctx, {
                goTerm: job.go_term, organism: job.organism, taxid, scientificName: job.organism,
                maxPleiotropy: job.max_pleiotropy, evidenceFilter: job.evidence_filter,
                predictPhenotypes: job.predict_phenotypes, databases: job.selected_databases, onProgress,
            });
            if (job.model_error) results.warnings.push(job.model_error);

            await this._update(job, { current_step: 'Generating reports', progress_percent: 90 }, true);

            // the report shows the top genes by composite score; every gene was scored first
            if (results.genes.length > job.max_genes) results.genes = results.genes.slice(0, job.max_genes);

            await this.d.store.putResults(job.id, results);
            await this._update(job, {
                status: 'completed', current_step: 'Completed', progress_percent: 100,
                total_genes_found: results.statistics.total_genes_screened, genes_processed: results.genes.length,
            }, true);
        } catch (error) {
            const cancelled = error && error.name === 'AbortError';
            await this._update(job, {
                status: cancelled ? 'pending' : 'failed',
                current_step: cancelled ? 'Cancelled' : 'Failed',
                error_message: cancelled ? null : String(error && error.message ? error.message : error),
            }, true);
        }
    }
}
