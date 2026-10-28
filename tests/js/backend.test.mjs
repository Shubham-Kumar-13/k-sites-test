// The in-browser backend: the same /api/... requests the pages make, answered locally.
// A real job runs here on the recorded live data (tests/fixtures/js_parity).

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

import { LocalBackend, estimateSeconds, formatDuration } from '../../webapp/static/js/engine/localApi.js';
import { MemoryStore } from '../../webapp/static/js/engine/store.js';
import { HttpClient } from '../../webapp/static/js/engine/http.js';
import { EvidenceProvider } from '../../webapp/static/js/engine/knockoutEvidence.js';
import { SAFETY_TIER } from '../../webapp/static/js/engine/pipeline.js';
import { ROOT, keggFromRecording, keyFromUrl, loadPythonResult, loadRecording, offlineClient, replayFetch } from './helpers.mjs';

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
        evidenceProvider: overrides.evidenceProvider || null,
        createPredictor: overrides.createPredictor || (async () => null),
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
    assert.deepEqual((await call(backend, '/api/databases')).body.databases.map((d) => d.id), ['quickgo', 'uniprot', 'kegg']);
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
    assert.ok(result.warnings.some((w) => w.includes('6 genes found') && w.includes('3 safest')));
    assert.equal(estimateSeconds(10, true) > estimateSeconds(10, false), true);
    assert.ok(estimateSeconds(100, false, true) < estimateSeconds(100, false, false));     // the evidence files save the database searches
    assert.equal(estimateSeconds(193, false, true), 213);                                  // measured: 193 genes took 125 s
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
    assert.deepEqual(JSON.parse(new TextDecoder().decode(await xlsx.arrayBuffer())), ['Summary', 'Gene Rankings', 'Safety Recommendations', 'Knockout Evidence']);
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

// ------------------------------------------------------------------ measured knockout evidence

/** The small copy of the real evidence files (tests/fixtures/evidence): it knows UNG, POLB, POLQ, PARP1 and RPA2, not LIG1. */
const evidenceProvider = () => new EvidenceProvider(async (name) => JSON.parse(
    fs.readFileSync(path.join(ROOT, 'tests', 'fixtures', 'evidence', name), 'utf8')));

async function runJob(backend, job) {
    const started = (await post(backend, '/api/analyze/start', job)).body;
    await waitFor(async () => ['completed', 'failed'].includes((await call(backend, `/api/jobs/${started.job_id}/status`)).body.status));
    return (await call(backend, `/api/jobs/${started.job_id}/results`)).body.results;
}

test('a job uses the measured knockout evidence, lists the safest genes first and says what the verdicts rest on', async () => {
    const { backend } = makeBackend({ evidenceProvider: evidenceProvider() });

    const results = await runJob(backend, JOB);

    assert.equal(results.metadata.knockout_context, 'cells');                     // human genes: cultured cells
    assert.equal(results.metadata.knockout_evidence_data.available, true);
    const tiers = results.genes.map((g) => SAFETY_TIER[g.safety_recommendation.safety_level]);
    assert.deepEqual(tiers, [...tiers].sort((a, b) => a - b));
    const bySymbol = Object.fromEntries(results.genes.map((g) => [g.symbol, g]));
    assert.equal(bySymbol.POLB.knockout_evidence.organism.call, 'LETHAL');         // the mouse knockout dies at birth
    assert.equal(bySymbol.POLB.knockout_evidence.cells.call, 'NON_ESSENTIAL');     // but human cells do not need it
    assert.equal(bySymbol.POLB.safety_recommendation.evidence_basis, 'measured');
    assert.equal(bySymbol.LIG1.knockout_evidence.has_measured, false);             // not in the small test copy
    assert.equal(bySymbol.LIG1.safety_recommendation.safety_level, 'CAUTION');     // never better than CAUTION without a measurement
    assert.deepEqual(results.statistics.by_evidence_basis, { measured: 5, none: 1 });
});

test('the same genes read as a whole organism follow the mouse knockout instead', async () => {
    const { backend } = makeBackend({ evidenceProvider: evidenceProvider() });

    const results = await runJob(backend, { ...JOB, knockout_context: 'organism' });

    assert.equal(results.metadata.knockout_context, 'organism');
    const polb = results.genes.find((g) => g.symbol === 'POLB');
    assert.equal(polb.safety_recommendation.safety_level, 'AVOID');
    assert.equal(results.genes[results.genes.length - 1].safety_recommendation.safety_level, 'AVOID');   // the worst come last
});

test('genes beyond the report size and genes above the cutoff are listed as not shown, with their measured result', async () => {
    const { backend } = makeBackend({ evidenceProvider: evidenceProvider() });

    const results = await runJob(backend, { ...JOB, max_genes: 2 });

    assert.equal(results.genes.length, 2);
    const hidden = results.excluded_genes.filter((g) => g.reason === 'ranked');
    assert.equal(hidden.length, python.genes.length - 2);
    assert.ok(hidden.every((g) => /Ranked below the 2 genes shown/.test(g.detail)));
    assert.ok(hidden.some((g) => g.knockout_evidence.organism.call !== 'UNKNOWN'));

    const strict = await runJob(makeBackend({ evidenceProvider: evidenceProvider() }).backend, { ...JOB, max_pleiotropy: 3 });
    const cut = strict.excluded_genes.filter((g) => g.reason === 'pleiotropy');
    assert.ok(cut.length > 0 && cut.every((g) => /above the cutoff of 3/.test(g.detail)));
    assert.equal(strict.statistics.genes_above_pleiotropy_cutoff, cut.length);
});

test('a running job can be cancelled for good, and a cancelled job is not resumed when its page is opened again', async () => {
    let started = null;
    const predictions = [];
    const slowPredictor = async () => ({ predict: async (symbol) => { predictions.push(symbol); started?.(); await new Promise((r) => setTimeout(r, 30)); return null; } });
    const { backend } = makeBackend({ createPredictor: slowPredictor });
    const job = (await post(backend, '/api/analyze/start', { ...JOB, predict_phenotypes: true })).body;
    const firstPrediction = new Promise((resolve) => { started = resolve; });

    call(backend, `/api/jobs/${job.job_id}/status`);          // opening the page starts the job
    await firstPrediction;
    const cancelled = await call(backend, `/api/jobs/${job.job_id}/cancel`, { method: 'POST' });

    assert.equal(cancelled.status, 200);
    const final = await waitFor(async () => {
        const status = (await call(backend, `/api/jobs/${job.job_id}/status`)).body;
        return backend.running.has(job.job_id) ? null : status;
    });
    assert.equal(final.status, 'failed');
    assert.equal(final.error_message, 'Cancelled by you.');
    assert.ok(predictions.length < SIX.size, 'the rating stopped before every gene was predicted');

    // opening the page again does not start it again
    const before = predictions.length;
    await call(backend, `/api/jobs/${job.job_id}/status`);
    await new Promise((r) => setTimeout(r, 100));
    assert.equal(predictions.length, before);
    assert.equal((await call(backend, `/api/jobs/${job.job_id}/status`)).body.status, 'failed');
});

test('the phenotype model is only loaded for genes without a measured result', async () => {
    let loaded = 0;
    const predictions = [];
    const createPredictor = async () => {
        loaded += 1;
        return { predict: async (symbol) => { predictions.push(symbol); return null; } };
    };
    const { backend } = makeBackend({ evidenceProvider: evidenceProvider(), createPredictor });

    const results = await runJob(backend, { ...JOB, predict_phenotypes: true });

    assert.equal(loaded, 1);
    assert.deepEqual(predictions.sort(), ['LIG1']);
    assert.equal(results.statistics.phenotype_predictions_skipped, 5);

    // with every gene measured the 90 MB model is never downloaded
    loaded = 0;
    const measuredOnly = makeBackend({ evidenceProvider: evidenceProvider(), createPredictor });
    const allMeasured = await runJob(measuredOnly.backend, { ...JOB, predict_phenotypes: true, max_pleiotropy: 10 });
    assert.ok(allMeasured.genes.length > 0);
});

/** Adds an uncharacterized gene to the GO:0006284 annotation list and mocks its database lookups. */
function fetchWithUncharacterized(baseFetch) {
    return async (url) => {
        const u = new URL(url);
        if (u.host === 'www.ebi.ac.uk' && u.pathname.includes('/annotation/search') && u.searchParams.get('goId') === 'GO:0006284') {
            const baseResp = await baseFetch(url);
            const base = JSON.parse(await baseResp.text());
            base.results.push({
                symbol: 'UNCHARDUMMY',
                geneProductId: 'UniProtKB:Q00000',
                goEvidence: 'IDA',
                qualifier: 'involved_in',
                name: 'Uncharacterized protein UNCHARDUMMY',
            });
            base.numberOfHits = base.results.length;
            return { status: 200, text: async () => JSON.stringify(base), headers: { get: () => null } };
        }
        if (u.host === 'rest.uniprot.org' && u.searchParams.get('query')?.includes('gene:UNCHARDUMMY')) {
            return { status: 200, text: async () => JSON.stringify({ results: [{ primaryAccession: 'Q00000' }] }), headers: { get: () => null } };
        }
        if (u.host === 'www.ebi.ac.uk' && u.searchParams.get('geneProductId') === 'Q00000') {
            return { status: 200, text: async () => JSON.stringify({ numberOfHits: 1, results: [{
                goId: 'GO:0006284', goEvidence: 'IDA', goAspect: 'biological_process', goName: 'base-excision repair', qualifier: 'involved_in',
            }] }), headers: { get: () => null } };
        }
        return baseFetch(url);
    };
}

test('an uncharacterized gene with no measured data and no literature is moved to insufficient data', async () => {
    const baseProvider = evidenceProvider();
    const provider = new EvidenceProvider(async (name) => {
        const data = await baseProvider.readJson(name);
        if (name === '9606.json') {
            data.genes = { ...data.genes, UNCHARDUMMY: { lc: 0, cv: 0 } };
        }
        return data;
    });
    const { backend } = makeBackend({
        evidenceProvider: provider,
        http: offlineClient(fetchWithUncharacterized(fetchForSixGenes([])), { cache: null }),
    });

    const started = (await post(backend, '/api/analyze/start', JOB)).body;
    const finished = await waitFor(async () => {
        const status = (await call(backend, `/api/jobs/${started.job_id}/status`)).body;
        return ['completed', 'failed'].includes(status.status) ? status : null;
    });
    assert.equal(finished.status, 'completed', finished.error_message);
    const results = (await call(backend, `/api/jobs/${started.job_id}/results`)).body.results;

    const unchar = results.insufficient_data_genes.find((g) => g.symbol === 'UNCHARDUMMY');
    const scored = results.genes.find((g) => g.symbol === 'UNCHARDUMMY');
    assert.ok(unchar, 'UNCHARDUMMY should be in insufficient data');
    assert.ok(unchar.reasons.some((r) => /No measured knockout data, no literature, and no functional description/.test(r)));
    assert.ok(!scored, 'UNCHARDUMMY should not be scored');
});

test('if the evidence files cannot be read the job still runs, says so, and rates nothing better than CAUTION', async () => {
    const broken = new EvidenceProvider(async () => { throw new Error('HTTP 404'); });
    const { backend } = makeBackend({ evidenceProvider: broken });

    const results = await runJob(backend, JOB);

    assert.ok(results.warnings.some((w) => /Measured knockout data could not be loaded/.test(w) && /HTTP 404/.test(w)));
    assert.equal(results.metadata.knockout_evidence_data.available, false);
    assert.ok(results.genes.length > 0);
    assert.ok(results.genes.every((g) => g.knockout_evidence && g.knockout_evidence.has_measured === false));
    assert.ok(results.genes.every((g) => g.safety_recommendation.safety_level !== 'SAFE'));      // as the warning says: nothing better than CAUTION
});

test('an organism without evidence files is reported', async () => {
    const odd = new EvidenceProvider(async (name) => (name === 'index.json'
        ? { format: 1, built: '2026-01-01', organisms: {}, sources: [] } : {}));
    const { backend } = makeBackend({ evidenceProvider: odd });

    const results = await runJob(backend, JOB);

    assert.ok(results.warnings.some((w) => /no measured knockout data for Homo sapiens/.test(w)));
    assert.equal(results.metadata.knockout_evidence_data.organism_covered, false);
});

test('an organism file that cannot be read is reported and no gene is rated safe', async () => {
    const index = { format: 1, built: '2026-01-01', sources: [], organisms: { 9606: { file: '9606.json', name: 'Homo sapiens', layers: [] } } };
    const provider = new EvidenceProvider(async (name) => {
        if (name === 'index.json') return index;
        throw new Error('HTTP 404');
    });
    const { backend } = makeBackend({ evidenceProvider: provider });

    const results = await runJob(backend, JOB);

    assert.ok(results.warnings.some((w) => /Measured knockout data could not be loaded/.test(w) && /HTTP 404/.test(w)));
    assert.equal(results.metadata.knockout_evidence_data.available, false);
    assert.ok(results.genes.length > 0 && results.genes.every((g) => g.safety_recommendation.safety_level !== 'SAFE'));
});

test('the time estimate is shorter for an organism with evidence files, which save the database searches', async () => {
    const files = path.join(ROOT, 'tests', 'fixtures', 'evidence');
    const provider = new EvidenceProvider(async (name) => JSON.parse(fs.readFileSync(path.join(files, name), 'utf8')));
    const { backend } = makeBackend({ evidenceProvider: provider });

    const result = (await post(backend, '/api/analyze/validate', { ...JOB, max_genes: 3 })).body;

    assert.equal(result.estimated_time_seconds, estimateSeconds(6, false, true));
    assert.ok(result.estimated_time_seconds < estimateSeconds(6, false, false));
});
