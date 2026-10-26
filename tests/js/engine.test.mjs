// Unit tests for the in-browser engine pieces (no network).

import test from 'node:test';
import assert from 'node:assert/strict';

import { HttpClient, MemoryCache } from '../../webapp/static/js/engine/http.js';
import { classifyEvidence, isNotAnnotation, normalizeCode } from '../../webapp/static/js/engine/evidence.js';
import {
    coverageInfo, getGenesForGoTermWithCoverage, pickName, processAnnotations, GoTermNotFoundError, GeneRetrievalError,
} from '../../webapp/static/js/engine/goMapper.js';
import { combineBpTerms, combineEvidence, queryGeneFromAllDatabases } from '../../webapp/static/js/engine/multiDb.js';
import {
    DATA_INSUFFICIENT, DATA_OK, calculateEvidenceQuality, calculatePleiotropyScore, calculateSpecificityScore,
    literatureScoreFromCount, mapLimit, rankGenesBySpecificity, scoreGenePleiotropy, validateAcrossSpecies,
} from '../../webapp/static/js/engine/scorer.js';
import { enumText, getSafetyRecommendation } from '../../webapp/static/js/engine/safety.js';
import { comprehensiveCsv, geneSummaryCsv, htmlReport, safetyClass, safetyLabel } from '../../webapp/static/js/engine/report.js';
import { FALLBACK_ORGANISMS, resolveTaxid, searchGoTerms, searchOrganisms } from '../../webapp/static/js/engine/organisms.js';
import { MemoryStore } from '../../webapp/static/js/engine/store.js';

// ------------------------------------------------------------------ helpers

function response(status, body) {
    const text = typeof body === 'string' ? body : JSON.stringify(body);
    return { status, text: async () => text, headers: { get: () => null } };
}

/** An HttpClient on a scripted fetch: `handler(url)` returns a response or throws. */
function scripted(handler, extra = {}) {
    const calls = [];
    const http = new HttpClient({
        fetchImpl: async (url) => { calls.push(url); return handler(url); },
        sleep: async () => {}, rateLimits: {}, retries: 2, ...extra,
    });
    return { http, calls };
}

/** Pretend-database: answers UniProt, QuickGO and KEGG for a few genes. */
function fakeWorld(genes) {
    return (url) => {
        const u = new URL(url);
        const q = u.searchParams;
        if (u.host === 'rest.uniprot.org') {
            const query = q.get('query');
            const symbol = /gene:(\S+)/.exec(query)[1];
            const gene = genes[symbol];
            if (!gene) return response(200, { results: [] });
            if (q.get('fields') === 'accession') return response(200, { results: [{ primaryAccession: gene.acc }] });
            return response(200, { results: [{ primaryAccession: gene.acc, uniProtKBCrossReferences: (gene.uniprotBp || []).map(([id, name, ev]) => ({
                database: 'GO', id, properties: [{ key: 'GoTerm', value: `P:${name}` }, { key: 'GoEvidenceType', value: ev }] })) }] });
        }
        if (u.host === 'www.ebi.ac.uk') {
            const acc = q.get('geneProductId');
            const gene = Object.values(genes).find((g) => g.acc === acc);
            const results = (gene ? gene.quickgo : []).map(([id, ev, aspect = 'biological_process', qualifier = 'involved_in']) => ({
                goId: id, goEvidence: ev, goAspect: aspect, goName: id, qualifier }));
            return response(200, { numberOfHits: results.length, results });
        }
        return response(404, 'unexpected ' + url);
    };
}

const keggFor = (table) => async (taxid, symbol) => (table[symbol] === undefined ? { found: false, pathway_count: 0, pathways: [] }
    : { found: true, pathway_count: table[symbol], pathways: [] });

// ------------------------------------------------------------------ HTTP

test('HttpClient retries a busy server and then succeeds', async () => {
    let attempts = 0;
    const { http } = scripted(() => (++attempts < 3 ? response(503, 'busy') : response(200, '{"ok":true}')));

    const result = await http.get('https://example.org/x');

    assert.equal(result.status, 200);
    assert.equal(attempts, 3);
});

test('HttpClient returns the last error status after the retries are used up', async () => {
    const { http } = scripted(() => response(503, 'busy'));

    const result = await http.get('https://example.org/x');

    assert.equal(result.status, 503);
    assert.equal(result.ok, false);
});

test('HttpClient does not retry a 404 and does not cache it', async () => {
    const { http, calls } = scripted(() => response(404, 'nope'), { cache: new MemoryCache() });

    await http.get('https://example.org/missing');
    await http.get('https://example.org/missing');

    assert.equal(calls.length, 2);
});

test('HttpClient throws when the network is down after every retry', async () => {
    const { http } = scripted(() => { throw new Error('offline'); });

    await assert.rejects(() => http.get('https://example.org/x'), /offline/);
});

test('HttpClient answers a repeated request from the cache', async () => {
    const { http, calls } = scripted(() => response(200, '{"n":1}'), { cache: new MemoryCache() });

    await http.get('https://example.org/x', { params: { b: 2, a: 1 } });
    const again = await http.get('https://example.org/x', { params: { a: 1, b: 2 } });

    assert.equal(calls.length, 1);
    assert.deepEqual(again.json(), { n: 1 });
});

test('HttpClient keeps a host to its request rate', async () => {
    let clock = 0;
    const waits = [];
    const { http } = scripted(() => response(200, '{}'), {
        rateLimits: { 'example.org': 4 }, now: () => clock, sleep: async (ms) => { waits.push(ms); clock += ms; },
    });

    await Promise.all([http.get('https://example.org/1'), http.get('https://example.org/2'), http.get('https://example.org/3')]);

    assert.deepEqual(waits, [250, 250]);   // 4 requests/second -> one every 250 ms (slots at 0, 250, 500)
});

test('HttpClient stops when cancelled', async () => {
    const controller = new AbortController();
    const { http } = scripted(() => response(200, '{}'), { signal: controller.signal });
    controller.abort();

    await assert.rejects(() => http.get('https://example.org/x'), { name: 'AbortError' });
});

// ------------------------------------------------------------------ evidence codes

test('evidence codes are classified like the Python package', () => {
    const cases = [
        [['IDA'], 'experimental'], [['IMP'], 'experimental'], [['EXP'], 'experimental'], [['IDA:UniProtKB'], 'experimental'],
        [['ida'], 'experimental'], [['ISS'], 'computational'], [['TAS:ProtInc'], 'curatorial'], [['IEA'], 'IEA'],
        [['IEA', 'IDA'], 'experimental'], [['ECO:0000314'], 'unknown'], [[], 'unknown'], [[''], 'unknown'],
    ];
    for (const [codes, expected] of cases) assert.equal(classifyEvidence(codes), expected, JSON.stringify(codes));
    assert.equal(classifyEvidence('IDA'), 'experimental');
    assert.equal(normalizeCode('IDA:UniProtKB'), 'IDA');
});

test('NOT annotations are recognised', () => {
    assert.equal(isNotAnnotation('NOT|involved_in'), true);
    assert.equal(isNotAnnotation('involved_in'), false);
    assert.equal(isNotAnnotation(undefined), false);
});

// ------------------------------------------------------------------ GO term -> genes

const ann = (symbol, id, ev, extra = {}) => ({ symbol, geneProductId: id, goEvidence: ev, reference: 'PMID:1', qualifier: 'involved_in', ...extra });

test('protein variants of one gene become one entry with the strongest evidence', () => {
    const genes = processAnnotations([
        ann('MUTYH', 'UniProtKB:Q9UIF7', 'IDA', { name: 'Adenine DNA glycosylase' }),
        ann('MUTYH', 'UniProtKB:Q9UIF7-2', 'IEA', { name: 'Adenine DNA glycosylase isoform 2' }),
        ann('MUTYH', 'UniProtKB:A0A0S2Z3J8', 'IEA', { name: 'Adenine DNA glycosylase, isoform CRA_a' }),
        ann('UNG', 'UniProtKB:P13051', 'IDA'),
    ], 'all');

    assert.deepEqual(genes.map((g) => g.symbol).sort(), ['MUTYH', 'UNG']);
    const mutyh = genes.find((g) => g.symbol === 'MUTYH');
    assert.equal(mutyh.entrez_id, 'UniProtKB:Q9UIF7');
    assert.equal(mutyh.description, 'Adenine DNA glycosylase');
    assert.equal(mutyh.go_evidence_type, 'experimental');
    assert.equal(mutyh.uniprot_accessions.length, 3);
});

test('the evidence filter and NOT annotations decide which genes are candidates', () => {
    const results = [
        ann('A', 'UniProtKB:P00001', 'IDA'), ann('B', 'UniProtKB:P00002', 'IEA'), ann('C', 'UniProtKB:P00003', 'ISS'),
        ann('D', 'UniProtKB:P00004', 'IDA', { qualifier: 'NOT|involved_in' }),
    ];
    const symbols = (filter) => processAnnotations(results, filter).map((g) => g.symbol).sort();

    assert.deepEqual(symbols('experimental'), ['A']);
    assert.deepEqual(symbols('computational'), ['B', 'C']);
    assert.deepEqual(symbols('all'), ['A', 'B', 'C']);
});

test('a specific protein name beats an isoform or generic one', () => {
    assert.equal(pickName(['X domain-containing protein', 'Thing isoform 1', 'Single-strand-selective uracil-DNA glycosylase 1']),
        'Single-strand-selective uracil-DNA glycosylase 1');
    assert.equal(pickName(['Isoform 2'], 'PMID:1'), 'Isoform 2');
    assert.equal(pickName([], 'PMID:1'), 'PMID:1');
});

test('coverage says how much of a large GO term was read', () => {
    const full = coverageInfo(100, 100, 2000);
    assert.equal(full.complete, true);
    assert.equal(full.message, '');

    const partial = coverageInfo(1000, 400, 400);
    assert.equal(partial.complete, false);
    assert.match(partial.message, /^Only 40% of annotations were read \(400 of 1,000\)/);
    assert.match(coverageInfo(201, 200, 200).message, /Only 99% of annotations/);   // never "100%" when incomplete
});

test('the safety limit stops the read and reports it', async () => {
    const page = Array.from({ length: 200 }, (_, i) => ann(`G${i}`, `UniProtKB:P${String(i).padStart(5, '0')}`, 'IDA'));
    const { http, calls } = scripted((url) => response(200, { numberOfHits: 1000, results: page }));
    const progress = [];

    const { genes, coverage } = await getGenesForGoTermWithCoverage(http, 'GO:0006281', '9606', 'all',
        { maxAnnotations: 400, onProgress: (...args) => progress.push(args) });

    assert.equal(calls.length, 2);
    assert.equal(coverage.annotations_read, 400);
    assert.equal(coverage.complete, false);
    assert.match(coverage.message, /Only 40% of annotations were read/);
    assert.equal(genes.length, 200);
    assert.deepEqual(progress[0], ['Reading GO annotations', 1, 2]);
    assert.deepEqual(progress.at(-1), ['Reading GO annotations', 2, 2]);
});

test('errors from QuickGO are raised, never turned into an empty gene list', async () => {
    const bad = scripted(() => response(400, 'invalid goId')).http;
    await assert.rejects(() => getGenesForGoTermWithCoverage(bad, 'GO:0000000', '9606'), GoTermNotFoundError);

    const down = scripted(() => response(503, 'unavailable')).http;
    await assert.rejects(() => getGenesForGoTermWithCoverage(down, 'GO:0006281', '9606'), GeneRetrievalError);

    const offline = scripted(() => { throw new Error('offline'); }).http;
    await assert.rejects(() => getGenesForGoTermWithCoverage(offline, 'GO:0006281', '9606'), GeneRetrievalError);

    await assert.rejects(() => getGenesForGoTermWithCoverage(bad, 'INVALID', '9606'), /Invalid GO term/);
});

test('a failed extra page fails the whole lookup', async () => {
    let page = 0;
    const { http } = scripted(() => (++page < 3 ? response(200, { numberOfHits: 450, results: [ann('A', 'UniProtKB:P00001', 'IDA')] }) : response(503, 'x')));

    await assert.rejects(() => getGenesForGoTermWithCoverage(http, 'GO:0006281', '9606'), GeneRetrievalError);
});

test('an experimental search with no results falls back to computational evidence', async () => {
    const { http } = scripted(() => response(200, { numberOfHits: 1, results: [ann('A', 'UniProtKB:P00001', 'ISS')] }));

    const { genes } = await getGenesForGoTermWithCoverage(http, 'GO:0006281', '9606', 'experimental');

    assert.deepEqual(genes.map((g) => g.symbol), ['A']);
});

// ------------------------------------------------------------------ scoring

test('pleiotropy formula: exponential decay on the other Biological Process terms', () => {
    assert.equal(calculatePleiotropyScore(0), 0);
    assert.equal(calculatePleiotropyScore(1), 0);
    assert.ok(Math.abs(calculatePleiotropyScore(4) - 10 * (1 - Math.exp(-0.3 * 3))) < 1e-12);
    assert.equal(calculatePleiotropyScore(11), 10);
    assert.equal(calculatePleiotropyScore(500), 10);
    const scores = Array.from({ length: 10 }, (_, i) => calculatePleiotropyScore(i + 1));
    assert.deepEqual([...scores].sort((a, b) => a - b), scores);
});

test('specificity and evidence quality', () => {
    assert.equal(calculateSpecificityScore(0), 1);
    assert.equal(calculateSpecificityScore(10), 0);
    assert.equal(calculateSpecificityScore(2.5), 0.75);
    assert.equal(calculateSpecificityScore(-5), 1);
    assert.equal(calculateSpecificityScore(25), 0);
    assert.equal(calculateEvidenceQuality({ experimental_evidence_count: 2 }), 1.0);
    assert.equal(calculateEvidenceQuality({ iea_evidence_count: 2 }), 0.3);
    assert.equal(calculateEvidenceQuality({}), 0.5);
});

test('BP terms from every source are merged, strongest evidence wins', () => {
    const results = {
        go_data: { bp_terms: [{ go_id: 'GO:1', evidence_type: 'IEA', go_name: '' }] },
        uniprot_data: { bp_terms: [{ go_id: 'GO:1', evidence_type: 'experimental', go_name: 'x' }, { go_id: 'GO:2', evidence_type: 'computational' }] },
    };
    const terms = combineBpTerms(results);
    assert.equal(terms.length, 2);
    assert.equal(terms.find((t) => t.go_id === 'GO:1').evidence_type, 'experimental');
    results.combined_bp_terms = terms;
    const counts = combineEvidence(results);
    assert.equal(counts.experimental, 1);
    assert.equal(counts.computational, 1);
});

const WORLD = {
    NARROW: { acc: 'P1', quickgo: [['GO:1', 'IDA']], uniprotBp: [['GO:1', 'process 1', 'IDA:UniProtKB']] },
    BROAD: { acc: 'P2', quickgo: Array.from({ length: 8 }, (_, i) => [`GO:${i + 1}`, 'IDA']), uniprotBp: [] },
    PREDICTED: { acc: 'P3', quickgo: [['GO:1', 'IEA'], ['GO:2', 'IEA'], ['GO:3', 'IEA']], uniprotBp: [] },
    NOTHING: { acc: 'P4', quickgo: [], uniprotBp: [] },
};

test('a gene is scored from both databases and the KEGG count is carried along', async () => {
    const { http } = scripted(fakeWorld(WORLD));
    const ctx = { http, keggProvider: keggFor({ NARROW: 3 }) };

    const narrow = await scoreGenePleiotropy(ctx, 'NARROW', '9606', 'GO:1');
    const broad = await scoreGenePleiotropy(ctx, 'BROAD', '9606', 'GO:1');

    assert.equal(narrow.data_status, DATA_OK);
    assert.equal(narrow.pleiotropy_score, 0);
    assert.equal(narrow.specificity_score, 1);
    assert.equal(narrow.kegg_pathway_count, 3);
    assert.ok(broad.pleiotropy_score > narrow.pleiotropy_score);
    assert.equal(broad.bp_term_count, 8);
});

test('the evidence filter changes which BP terms count', async () => {
    const { http } = scripted(fakeWorld(WORLD));
    const ctx = { http, keggProvider: keggFor({}) };

    const experimental = await scoreGenePleiotropy(ctx, 'PREDICTED', '9606', 'GO:1', 'experimental');
    const computational = await scoreGenePleiotropy(ctx, 'PREDICTED', '9606', 'GO:1', 'computational');
    const everything = await scoreGenePleiotropy(ctx, 'PREDICTED', '9606', 'GO:1', 'all');

    assert.equal(experimental.data_status, DATA_INSUFFICIENT);   // no experimentally supported BP term
    assert.match(experimental.data_issues[0], /experimental evidence/);
    assert.equal(computational.pleiotropy_score, calculatePleiotropyScore(3));
    assert.equal(everything.pleiotropy_score, calculatePleiotropyScore(3));
});

test('a gene that cannot be assessed gets no score, never a perfect one', async () => {
    const { http } = scripted(fakeWorld(WORLD));
    const ctx = { http, keggProvider: keggFor({}) };

    const empty = await scoreGenePleiotropy(ctx, 'NOTHING', '9606', 'GO:1');
    const unknown = await scoreGenePleiotropy(ctx, 'NOSUCHGENE', '9606', 'GO:1');

    for (const result of [empty, unknown]) {
        assert.equal(result.data_status, DATA_INSUFFICIENT);
        assert.equal(result.pleiotropy_score, null);
        assert.equal(result.specificity_score, null);
        assert.equal(result.lookup_failed, false);
    }
});

test('a failed database is reported as a lookup failure', async () => {
    const down = scripted(() => response(503, 'unavailable'), { retries: 0 }).http;

    const result = await scoreGenePleiotropy({ http: down, keggProvider: keggFor({}) }, 'ANY', '9606', 'GO:1');

    assert.equal(result.data_status, DATA_INSUFFICIENT);
    assert.equal(result.lookup_failed, true);
    assert.equal(result.pleiotropy_score, null);
    assert.ok(result.data_issues.some((issue) => /lookup failed/.test(issue)));
});

test('one failed source does not hide the data from the other', async () => {
    const world = fakeWorld(WORLD);
    const { http } = scripted((url) => (new URL(url).host === 'www.ebi.ac.uk' ? response(503, 'down') : world(url)), { retries: 0 });

    const db = await queryGeneFromAllDatabases(http, keggFor({}), 'NARROW', '9606');
    const scored = await scoreGenePleiotropy({ http, keggProvider: keggFor({}) }, 'NARROW', '9606', 'GO:1');

    assert.match(db.query_status.go, /^failed/);
    assert.equal(db.query_status.uniprot, 'success');
    assert.equal(scored.data_status, DATA_OK);
    assert.ok(scored.data_issues.some((issue) => /go lookup failed/.test(issue)));
});

test('conservation counts only the species that could be queried', async () => {
    const world = fakeWorld(WORLD);
    // human: found; mouse: not annotated; fly: database down
    const { http } = scripted((url) => {
        const u = new URL(url);
        const taxon = /organism_id:(\d+)/.exec(u.searchParams.get('query') || '');
        if (taxon && taxon[1] === '7227') return response(503, 'down');
        if (taxon && taxon[1] === '10090') return response(200, { results: [] });
        return world(url);
    }, { retries: 0 });

    const result = await validateAcrossSpecies({ http }, 'NARROW', 'GO:1', ['9606', '10090', '7227']);

    assert.equal(result.species_queried, 2);
    assert.equal(result.lookup_errors, 1);
    assert.equal(result.conservation_score, 0.5);
});

test('ranking puts scored genes first, by composite score, and unscored genes last', async () => {
    const { http } = scripted(fakeWorld(WORLD));
    const ctx = { http, keggProvider: keggFor({}) };

    const ranked = await rankGenesBySpecificity(ctx, [{ symbol: 'BROAD' }, { symbol: 'NOTHING' }, { symbol: 'NARROW' }], '9606', {
        targetGoTerm: 'GO:1', includeLiterature: false, includeCrossSpecies: false, maxPleiotropyThreshold: 9,
    });

    assert.deepEqual(ranked.map((g) => g.symbol), ['NARROW', 'BROAD', 'NOTHING']);
    assert.equal(ranked[2].data_status, DATA_INSUFFICIENT);
    assert.equal(ranked[2].passes_threshold, false);
    assert.equal(ranked[0].passes_threshold, true);
});

test('where the evidence files know a gene, conservation and literature are read from them and nothing is searched', async () => {
    const urls = [];
    const world = fakeWorld(WORLD);
    const { http } = scripted((url) => { urls.push(new URL(url).host); return world(url); });
    const ctx = { http, keggProvider: keggFor({}) };
    const known = { NARROW: { conservation: 0.8, literature_count: 100 }, BROAD: { conservation: null, literature_count: null } };

    const ranked = await rankGenesBySpecificity(ctx, [{ symbol: 'NARROW' }], '9606', {
        targetGoTerm: 'GO:1', includeLiterature: true, includeCrossSpecies: true, factsLookup: async (symbol) => known[symbol],
    });

    assert.equal(ranked[0].conservation_score, 0.8);
    assert.equal(ranked[0].pubmed_count, 100);
    assert.ok(Math.abs(ranked[0].literature_score - Math.log10(100) / 3) < 1e-12);
    assert.ok(!urls.includes('eutils.ncbi.nlm.nih.gov'));            // no PubMed search
});

test('the literature score scale', () => {
    assert.deepEqual([0, 1, 1000, 50000].map(literatureScoreFromCount), [0, 0, 1, 1]);
    assert.ok(Math.abs(literatureScoreFromCount(100) - 2 / 3) < 1e-12);
    assert.ok(Math.abs(literatureScoreFromCount(10) - 1 / 3) < 1e-12);
});

test('ranking reports progress for every gene', async () => {
    const { http } = scripted(fakeWorld(WORLD));
    const events = [];

    await rankGenesBySpecificity({ http, keggProvider: keggFor({}) }, [{ symbol: 'NARROW' }, { symbol: 'BROAD' }, { symbol: 'NOTHING' }], '9606', {
        includeLiterature: false, includeCrossSpecies: false, onProgress: (...args) => events.push(args),
    });

    assert.deepEqual(events.map((e) => e[1]), [1, 2, 3]);
    assert.ok(events.every((e) => e[0] === 'Scoring genes' && e[2] === 3));
});

test('mapLimit keeps the input order and the concurrency limit', async () => {
    let active = 0;
    let peak = 0;
    const result = await mapLimit([5, 1, 4, 2, 3], 2, async (n) => {
        active++; peak = Math.max(peak, active);
        await new Promise((r) => setTimeout(r, n));
        active--;
        return n * 10;
    });

    assert.deepEqual(result, [50, 10, 40, 20, 30]);
    assert.ok(peak <= 2);
});

// ------------------------------------------------------------------ safety

const prediction = (severity, risk, confidence, stage = null) => ({ severity, risk_level: risk, confidence_score: confidence, lethality_stage: stage });

test('a lethal, high-confidence prediction is never called safe', () => {
    const rec = getSafetyRecommendation({ symbol: 'G', pleiotropyScore: 1.0, phenotypePrediction: prediction('LETHAL', 'CRITICAL', 0.9, 'Embryonic'),
        crossSpecies: { conservation_score: 0.9 }, literatureSupport: 0.9 });

    assert.equal(rec.safety_level, 'HIGH_CONCERN');
    assert.equal(rec.primary_recommendation, 'Conditional Knockout (Cre-Lox)');
    assert.ok(rec.concerns.some((c) => c.includes('critical risk phenotype')));
    assert.ok(rec.justification.some((j) => j.includes('Predicted CRITICAL risk phenotype')));
    assert.ok(rec.experimental_considerations.some((c) => c.startsWith('Plan for embryonic lethality')));
});

test('lethal and very pleiotropic means avoid; a mild phenotype stays safe', () => {
    assert.equal(getSafetyRecommendation({ symbol: 'G', pleiotropyScore: 9, phenotypePrediction: prediction('LETHAL', 'CRITICAL', 0.9) }).safety_level, 'AVOID');
    assert.equal(getSafetyRecommendation({ symbol: 'G', pleiotropyScore: 1, phenotypePrediction: prediction('MILD', 'LOW', 0.9) }).safety_level, 'SAFE');
});

test('the pleiotropy ladder without a phenotype prediction', () => {
    const level = (score, conservation = 0) => getSafetyRecommendation({ symbol: 'G', pleiotropyScore: score, crossSpecies: { conservation_score: conservation } }).safety_level;

    assert.equal(level(1), 'SAFE');
    assert.equal(level(4), 'CAUTION');
    assert.equal(level(6, 0.5), 'CAUTION');
    assert.equal(level(6, 0.9), 'MODERATE_CONCERN');
    assert.equal(level(9), 'HIGH_CONCERN');
});

test('every spelling of an enum value gives the same text', () => {
    for (const value of ['CRITICAL', 'RiskLevel.CRITICAL', { value: 'CRITICAL' }]) assert.equal(enumText(value), 'CRITICAL');
    assert.equal(enumText(null), '');
    assert.equal(enumText('PhenotypeSeverity.LETHAL'), 'LETHAL');
});

test('confidence averages the evidence that is actually there', () => {
    const none = getSafetyRecommendation({ symbol: 'G', pleiotropyScore: 1 });
    const withAll = getSafetyRecommendation({ symbol: 'G', pleiotropyScore: 1, phenotypePrediction: prediction('MILD', 'LOW', 0.8),
        crossSpecies: { conservation_score: 0.5 }, literatureSupport: 0.6 });

    assert.equal(none.confidence_score, 0);
    assert.ok(Math.abs(withAll.confidence_score - (0.8 + 0.6 + 0.7) / 3) < 1e-12);
});

// ------------------------------------------------------------------ reports

const SAMPLE = {
    metadata: { go_term: 'GO:0006281', organism: 'Homo sapiens', max_pleiotropy: 7, evidence_filter: 'experimental', timestamp: '2026-01-01T00:00:00Z', execution_duration: 12.5 },
    genes: [
        { symbol: 'A,1', description: 'has "quotes", commas', pleiotropy_score: 1, specificity_score: 0.9, composite_score: 0.5, evidence_quality: 1, literature_score: 0.8,
            conservation_score: 0.5, bp_term_count: 2, kegg_pathway_count: 3, pubmed_count: 100,
            phenotype_prediction: { severity: 'LETHAL', risk_level: 'CRITICAL', confidence_score: 0.6, lethality_stage: 'Embryonic' },
            safety_recommendation: { safety_level: 'MODERATE_CONCERN', primary_recommendation: 'Heterozygous Knockout', justification: ['one', 'two'] } },
    ],
    insufficient_data_genes: [{ symbol: 'BAD', lookup_failed: true, reasons: ['go lookup failed: HTTP 503'] }],
    warnings: ['Only 39% of annotations were read (2,000 of 5,120).'],
    statistics: { total_genes_screened: 40 },
};

test('safety levels have their own colour and a readable label', () => {
    const levels = ['SAFE', 'CAUTION', 'MODERATE_CONCERN', 'HIGH_CONCERN', 'AVOID'];
    assert.equal(new Set(levels.map(safetyClass)).size, 5);
    assert.equal(safetyClass(null), 'safety-unknown');
    assert.equal(safetyLabel('MODERATE_CONCERN'), 'Moderate concern');
    assert.equal(safetyLabel(''), 'Unknown');
});

test('CSV quotes commas and quotes, and carries the warning and the new columns', () => {
    const csv = comprehensiveCsv(SAMPLE);
    const lines = csv.split('\n');

    assert.ok(lines.includes('"# WARNING: Only 39% of annotations were read (2,000 of 5,120)."'));   // a comment line with a comma is quoted, as in the Python report
    assert.ok(lines.some((l) => l.startsWith('"A,1","has ""quotes"", commas"')));
    assert.ok(csv.includes('Embryonic'));
    assert.ok(geneSummaryCsv(SAMPLE).split('\n')[1].includes('Heterozygous Knockout'));
});

test('the HTML report shows warnings, readable labels, unscored genes and escapes text', () => {
    const html = htmlReport({ ...SAMPLE, genes: [{ ...SAMPLE.genes[0], symbol: '<b>X</b>' }] });

    assert.ok(html.includes('class="report-warning"'));
    assert.ok(html.includes('Only 39% of annotations were read'));
    assert.ok(html.includes('class="safety-level safety-concern">Moderate concern<'));
    assert.ok(html.includes('BAD') && html.includes('go lookup failed: HTTP 503'));
    assert.ok(html.includes('&lt;b&gt;X&lt;/b&gt;') && !html.includes('<b>X</b>'));
    assert.ok(html.includes('Pleiotropy cutoff (0-10): <strong>7</strong>'));
    assert.ok(html.includes('<div class="summary-value">40</div>'));
});

// ------------------------------------------------------------------ organisms and GO terms

const ORGS = [
    { name: 'Homo sapiens', common_name: 'human', taxid: '9606', kingdom: 'Animals', kegg_code: 'hsa' },
    { name: 'Mus musculus', common_name: 'house mouse', taxid: '10090', kingdom: 'Animals', kegg_code: 'mmu' },
    { name: 'Arabidopsis thaliana', common_name: 'thale cress', taxid: '3702', kingdom: 'Plants', kegg_code: 'ath' },
];

test('organism search filters by kingdom, name, common name or taxid, sorted by name', () => {
    assert.deepEqual(searchOrganisms(ORGS, 'Animals').map((o) => o.name), ['Homo sapiens', 'Mus musculus']);
    assert.deepEqual(searchOrganisms(ORGS, null, 'mouse').map((o) => o.name), ['Mus musculus']);
    assert.deepEqual(searchOrganisms(ORGS, null, '3702').map((o) => o.name), ['Arabidopsis thaliana']);
    assert.ok(FALLBACK_ORGANISMS.some((o) => o.taxid === '9606'));
});

test('taxonomy ids: known organisms locally, others from NCBI, nonsense is an error', async () => {
    const { http, calls } = scripted((url) => response(200, { esearchresult: { idlist: url.includes('Bos') ? ['9913'] : [] } }));

    assert.equal(await resolveTaxid(http, 'Homo sapiens'), '9606');
    assert.equal(await resolveTaxid(http, 'anything', '10090'), '10090');
    assert.equal(await resolveTaxid(http, '7227'), '7227');
    assert.equal(calls.length, 0);
    assert.equal(await resolveTaxid(http, 'Bos mutus'), '9913');
    await assert.rejects(() => resolveTaxid(http, 'Not a real organism'), /Could not find the NCBI taxonomy id/);
});

test('GO term search: popular terms without a query, OLS results with one', async () => {
    const { http } = scripted(() => response(200, { response: { docs: [
        { obo_id: 'GO:0006281', label: 'DNA repair', namespace: 'biological_process', description: ['Restoring DNA'] },
        { obo_id: 'CHEBI:1', label: 'not GO', namespace: 'x' },
        { obo_id: 'GO:0003677', label: 'DNA binding', namespace: 'molecular_function' },
    ] } }));

    const popular = await searchGoTerms(http, 'Biological Process', null);
    const found = await searchGoTerms(http, 'Biological Process', 'dna');

    assert.ok(popular.some((t) => t.id === 'GO:0006281'));
    assert.deepEqual(found.map((t) => t.id), ['GO:0006281']);     // other namespaces and non-GO ids are dropped
    assert.equal(found[0].definition, 'Restoring DNA');
});

// ------------------------------------------------------------------ the store

test('MemoryStore keeps copies, so a stored job cannot be changed by accident', async () => {
    const store = new MemoryStore();
    const job = { id: 'a', status: 'pending' };

    await store.putJob(job);
    job.status = 'changed';

    assert.equal((await store.getJob('a')).status, 'pending');
    assert.equal((await store.listJobs()).length, 1);
    await store.deleteJob('a');
    assert.equal(await store.getJob('a'), undefined);
});
