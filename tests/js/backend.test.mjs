// The in-browser backend: the same /api/... requests the pages make, answered locally.
// A real job runs here on the recorded live data (tests/fixtures/js_parity).

import test from 'node:test';
import assert from 'node:assert/strict';

import { LocalBackend, estimateSeconds, formatDuration } from '../../webapp/static/js/engine/localApi.js';
import { MemoryStore } from '../../webapp/static/js/engine/store.js';
import { HttpClient } from '../../webapp/static/js/engine/http.js';
import { keggFromRecording, keyFromUrl, loadPythonResult, loadRecording, offlineClient, replayFetch } from './helpers.mjs';

const recording = loadRecording();
const { input, result: python } = loadPythonResult();
const SIX = new Set(python.genes.map((g) => g.symbol));

/** Replays the recording, but shows only the six recorded genes on the GO-term pages. */
function fetchForSixGenes(misses = []) {
    const base = replayFetch(recording, misses);
    const pages = Object.entries(recording).filter(([key]) => key.includes('goId=GO:0006284'));
    return async (url) => {
        if (keyFromUrl(url).includes('goId=GO:0006284')) {
            const results = pages.flatMap(([, hit]) => JSON.parse(hit.text).results).filter((r) => SIX.has(r.symbol));
            const body = JSON.stringify({ numberOfHits: results.length, results });
            return { status: 200, text: async () => body, headers: { get: () => null } };
        }
        return base(url);
    };
}

const ORGS = [{ name: 'Homo sapiens', common_name: 'human', taxid: '9606', kingdom: 'Animals', kegg_code: 'hsa' }];

function makeBackend(overrides = {}) {
    let counter = 0;
    const misses = [];
    const store = overrides.store || new MemoryStore();
    const backend = new LocalBackend({
        store,
        http: overrides.http || offlineClient(fetchForSixGenes(misses), { cache: null }),
        keggProvider: keggFromRecording(recording),
        loadOrganisms: async () => ORGS,
        createPredictor: async () => null,
        getNcbiApiKey: () => '',
        locks: overrides.locks || null,
        now: () => Date.now(),
        newId: () => `job-${++counter}`,
    });
    return { backend, store, misses };
}

const call = async (backend, path, options) => {
    const response = await backend.handle(path, options);
    return { status: response.status, body: await response.clone().json().catch(() => null), response };
};
const post = (backend, path, body) => call(backend, path, { method: 'POST', body: JSON.stringify(body) });

async function waitFor(check, timeoutMs = 20000) {
    const started = Date.now();
    for (;;) {
        const value = await check();
        if (value) return value;
        if (Date.now() - started > timeoutMs) throw new Error('timed out waiting');
        await new Promise((r) => setTimeout(r, 10));
    }
}

const JOB = {
    organism: 'Homo sapiens', taxid: '9606', go_term: 'GO:0006284', go_term_name: 'base-excision repair',
    max_genes: 10, max_pleiotropy: 10, evidence_filter: 'experimental', predict_phenotypes: false, databases: ['quickgo', 'uniprot', 'kegg'],
};

// ------------------------------------------------------------------ simple endpoints

test('health, databases and the pickers answer like the Flask app', async () => {
    const { backend } = makeBackend();

    assert.equal((await call(backend, '/api/health')).body.mode, 'browser');
    assert.deepEqual((await call(backend, '/api/databases')).body.databases.map((d) => d.id), ['quickgo', 'uniprot', 'ncbi', 'pubmed', 'kegg']);
    assert.equal((await call(backend, '/api/organisms/kingdoms')).body.kingdoms.length, 5);
    assert.equal((await call(backend, '/api/go-terms/categories')).body.categories.length, 3);

    const organisms = await call(backend, '/api/organisms/by-kingdom?kingdom=Animals&q=human');
    assert.deepEqual(organisms.body.results.map((o) => o.name), ['Homo sapiens']);
    assert.equal((await call(backend, '/api/organisms/by-kingdom?kingdom=Plants')).body.results.length, 0);

    const terms = await call(backend, '/api/go-terms/by-category?category=Biological%20Process');
    assert.ok(terms.body.results.some((t) => t.id === 'GO:0006281'));
    assert.equal((await call(backend, '/api/nonsense')).status, 404);
});

test('the organism list falls back to a short built-in list if the data file is missing', async () => {
    const { backend } = makeBackend();
    backend.d.loadOrganisms = async () => { throw new Error('404'); };

    const result = await call(backend, '/api/organisms/by-kingdom?kingdom=Animals');

    assert.ok(result.body.results.some((o) => o.taxid === '9606'));
});

// ------------------------------------------------------------------ validation

test('validation rejects bad input with the same messages as the server', async () => {
    const { backend } = makeBackend();
    const errors = async (data) => (await post(backend, '/api/analyze/validate', data)).body.errors;

    assert.deepEqual(await errors({ organism: '', go_term: '', max_genes: 5 }), ['Organism is required', 'GO term is required']);
    assert.ok((await errors({ organism: 'x', go_term: 'abc', max_genes: 5 })).includes('GO term must be in format GO:XXXXXXX'));
    assert.ok((await errors({ organism: 'x', go_term: 'GO:0006281', max_pleiotropy: 11 })).includes('Max pleiotropy must be between 0 and 10'));
    assert.ok((await errors({ organism: 'x', go_term: 'GO:0006281', max_pleiotropy: -1 })).includes('Max pleiotropy must be between 0 and 10'));
    assert.ok((await errors({ organism: 'x', go_term: 'GO:0006281', max_pleiotropy: 'abc' })).includes('Max pleiotropy must be between 0 and 10'));
    assert.ok((await errors({ organism: 'x', go_term: 'GO:0006281', evidence_filter: 'bogus' })).includes('Evidence filter must be experimental, computational or all'));
    assert.ok((await errors({ organism: 'x', go_term: 'GO:0006281', max_genes: 501 })).includes('Genes to report must be at most 500'));
    assert.ok((await errors({ organism: 'x', go_term: 'GO:0006281', max_genes: 0 })).includes('Maximum genes must be at least 1'));
});

test('validation counts the genes and estimates the time', async () => {
    const { backend } = makeBackend();

    const result = (await post(backend, '/api/analyze/validate', { ...JOB, max_genes: 3 })).body;

    assert.equal(result.valid, true);
    assert.equal(result.gene_count, 6);
    assert.equal(result.taxid, '9606');
    assert.equal(result.estimated_time_seconds, estimateSeconds(6, false));
    assert.ok(result.warnings.some((w) => w.includes('6 genes found') && w.includes('top 3')));
    assert.equal(estimateSeconds(10, true) > estimateSeconds(10, false), true);
    assert.equal(formatDuration(45), '45 seconds');
    assert.equal(formatDuration(600), '10 minutes');
    assert.equal(formatDuration(3720), '1 hour 2 min');
});

test('validation says when a GO term has no genes, and reports a failed lookup', async () => {
    const empty = makeBackend({ http: offlineClient(async () => ({ status: 200, text: async () => '{"numberOfHits":0,"results":[]}', headers: { get: () => null } })) });
    assert.match((await post(empty.backend, '/api/analyze/validate', JOB)).body.errors[0], /No genes found for GO:0006284/);

    const down = makeBackend({ http: offlineClient(async () => ({ status: 503, text: async () => 'down', headers: { get: () => null } })) });
    const result = (await post(down.backend, '/api/analyze/validate', JOB)).body;
    assert.equal(result.valid, true);                       // a lookup problem is a warning, the user may still try
    assert.match(result.warnings[0], /Could not validate gene count/);
});

// ------------------------------------------------------------------ a whole job

test('a job runs in the browser and gives the same genes and verdicts as the recorded Python run', async () => {
    const { backend, misses } = makeBackend();
    const started = (await post(backend, '/api/analyze/start', JOB)).body;
    assert.equal(started.success, true);

    // nothing runs until the results page asks for the status (a page change would stop it)
    assert.equal((await backend.d.store.getJob(started.job_id)).status, 'pending');

    const progress = new Set();
    const finished = await waitFor(async () => {
        const status = (await call(backend, `/api/jobs/${started.job_id}/status`)).body;
        progress.add(status.current_step);
        return status.status === 'completed' || status.status === 'failed' ? status : null;
    });

    assert.equal(finished.status, 'completed', finished.error_message);
    assert.equal(finished.progress_percent, 100);
    assert.equal(finished.taxid, '9606');
    assert.deepEqual(misses, []);
    assert.equal(finished.total_genes_found, python.statistics.total_genes_screened);
    assert.equal(finished.genes_processed, python.genes.length);
    assert.ok([...progress].some((step) => /^Scoring genes \(\d+\/6\)$/.test(step) || step === 'Completed'));

    const results = (await call(backend, `/api/jobs/${started.job_id}/results`)).body.results;
    assert.deepEqual(results.genes.map((g) => g.symbol), python.genes.map((g) => g.symbol));
    assert.deepEqual(results.genes.map((g) => g.safety_recommendation.safety_level), python.genes.map((g) => g.safety_recommendation.safety_level));
    for (const [index, gene] of results.genes.entries()) {
        assert.ok(Math.abs(gene.pleiotropy_score - python.genes[index].pleiotropy_score) < 1e-9, gene.symbol);
    }
});

test('the report is trimmed to the requested number of genes, after scoring them all', async () => {
    const { backend } = makeBackend();
    const started = (await post(backend, '/api/analyze/start', { ...JOB, max_genes: 2 })).body;
    await waitFor(async () => (await call(backend, `/api/jobs/${started.job_id}/status`)).body.status === 'completed');

    const results = (await call(backend, `/api/jobs/${started.job_id}/results`)).body.results;

    assert.equal(results.genes.length, 2);
    assert.equal(results.statistics.total_genes_screened, 6);
    assert.deepEqual(results.genes.map((g) => g.symbol), python.genes.slice(0, 2).map((g) => g.symbol));
});

test('every download type works, with a file name and the right content type', async () => {
    globalThis.XLSX = {
        utils: { book_new: () => ({ sheets: [] }), aoa_to_sheet: (rows) => rows, book_append_sheet: (book, sheet, name) => book.sheets.push([name, sheet]) },
        write: (book) => new TextEncoder().encode(JSON.stringify(book.sheets.map(([name]) => name))),
    };
    const { backend } = makeBackend();
    const started = (await post(backend, '/api/analyze/start', JOB)).body;
    await waitFor(async () => (await call(backend, `/api/jobs/${started.job_id}/status`)).body.status === 'completed');
    const get = (type) => backend.handle(`/api/jobs/${started.job_id}/download/${type}`);

    const html = await get('html');
    assert.match(html.headers.get('Content-Disposition'), /^attachment; filename=ksites_GO0006284_\d{14}\.html$/);
    assert.match(await html.text(), /K-Sites Gene Selection Report/);
    assert.equal(JSON.parse(await (await get('json')).text()).genes.length, python.genes.length);
    assert.match(await (await get('csv')).text(), /Gene_Symbol,Gene_Description/);
    assert.match(await (await get('summary')).text(), /gene_symbol,gene_description/);
    const xlsx = await get('xlsx');
    assert.match(xlsx.headers.get('Content-Type'), /spreadsheetml/);
    assert.deepEqual(JSON.parse(new TextDecoder().decode(await xlsx.arrayBuffer())), ['Summary', 'Gene Rankings', 'Safety Recommendations']);
    assert.equal((await get('exe')).status, 400);
    delete globalThis.XLSX;
});

test('results and downloads are refused until the job has finished', async () => {
    const { backend } = makeBackend();
    const started = (await post(backend, '/api/analyze/start', JOB)).body;

    assert.equal((await call(backend, `/api/jobs/${started.job_id}/results`)).body.status, 'pending');
    assert.equal((await call(backend, `/api/jobs/${started.job_id}/download/csv`)).status, 404);
    assert.equal((await call(backend, '/api/jobs/missing/status')).status, 404);
});

test('a job whose GO term cannot be read fails with a clear message', async () => {
    const down = makeBackend({ http: offlineClient(async () => ({ status: 503, text: async () => 'down', headers: { get: () => null } })) });
    const started = (await post(down.backend, '/api/analyze/start', JOB)).body;

    const finished = await waitFor(async () => {
        const status = (await call(down.backend, `/api/jobs/${started.job_id}/status`)).body;
        return status.status === 'failed' ? status : null;
    });

    assert.equal(finished.current_step, 'Failed');
    assert.match(finished.error_message, /QuickGO returned HTTP 503/);
});

test('the job list is newest first and uses the same fields as the server', async () => {
    const { backend, store } = makeBackend();
    await store.putJob({ id: 'old', created_at: '2026-01-01T00:00:00Z', status: 'completed', organism: 'Homo sapiens', go_term: 'GO:1', genes_processed: 3 });
    await store.putJob({ id: 'new', created_at: '2026-02-01T00:00:00Z', status: 'failed', organism: 'Mus musculus', go_term: 'GO:2', error_message: 'x' });

    const jobs = (await call(backend, '/api/jobs')).body.jobs;

    assert.deepEqual(jobs.map((j) => j.id), ['new', 'old']);
    for (const field of ['id', 'status', 'current_step', 'progress_percent', 'organism', 'taxid', 'go_term', 'go_term_name', 'max_genes',
        'max_pleiotropy', 'evidence_filter', 'predict_phenotypes', 'selected_databases', 'total_genes_found', 'genes_processed', 'error_message']) {
        assert.ok(field in jobs[0], field);
    }
});

// ------------------------------------------------------------------ one tab per job

test('only one tab runs a job; a job nobody holds is shown as paused and resumes when opened', async () => {
    const held = new Set();
    const locks = {
        request: async (name, options, callback) => {
            if (held.has(name)) return callback(null);        // another tab has it
            held.add(name);
            try { return await callback({ name }); } finally { held.delete(name); }
        },
        query: async () => ({ held: [...held].map((name) => ({ name })) }),
    };
    const { backend, store } = makeBackend({ locks });
    const started = (await post(backend, '/api/analyze/start', JOB)).body;
    const jobId = started.job_id;

    // another tab holds the lock: status does not start a second run
    held.add(`ksites-job-${jobId}`);
    await call(backend, `/api/jobs/${jobId}/status`);
    await new Promise((r) => setTimeout(r, 30));
    assert.equal((await store.getJob(jobId)).status, 'pending');
    held.delete(`ksites-job-${jobId}`);

    // a running job whose tab was closed is listed as paused...
    await store.putJob({ ...(await store.getJob(jobId)), status: 'running', current_step: 'Scoring genes (3/6)' });
    const listed = (await call(backend, '/api/jobs')).body.jobs.find((j) => j.id === jobId);
    assert.equal(listed.status, 'pending');
    assert.match(listed.current_step, /Paused/);

    // ...and resumes (from the cache of earlier answers) when its page is opened
    const finished = await waitFor(async () => {
        const status = (await call(backend, `/api/jobs/${jobId}/status`)).body;
        return status.status === 'completed' ? status : null;
    });
    assert.equal(finished.genes_processed, python.genes.length);
});

test('a missing KEGG data file only removes the pathway count, it does not stop the job', async () => {
    const { backend } = makeBackend();
    backend.d.keggProvider = async () => { throw new Error('404'); };
    const started = (await post(backend, '/api/analyze/start', JOB)).body;

    const finished = await waitFor(async () => {
        const status = (await call(backend, `/api/jobs/${started.job_id}/status`)).body;
        return ['completed', 'failed'].includes(status.status) ? status : null;
    });

    assert.equal(finished.status, 'completed');
    const results = (await call(backend, `/api/jobs/${started.job_id}/results`)).body.results;
    assert.ok(results.genes.every((g) => g.kegg_pathway_count === 0));
    assert.ok(results.genes.length > 0);
});
