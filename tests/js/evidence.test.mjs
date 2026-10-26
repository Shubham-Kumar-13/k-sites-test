// Measured knockout evidence in the browser engine: it must read the same files and give exactly the answers the
// Python package gives (tests/fixtures/evidence/golden.json is recorded from Python by tools/record_evidence_fixture.py).

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

import {
    EvidenceProvider, EvidenceUnavailable, assessGene, createEvidenceProvider, resolveContext,
} from '../../webapp/static/js/engine/knockoutEvidence.js';
import { getSafetyRecommendation } from '../../webapp/static/js/engine/safety.js';
import { ROOT } from './helpers.mjs';

const DIR = path.join(ROOT, 'tests', 'fixtures', 'evidence');
const readJson = async (name) => JSON.parse(fs.readFileSync(path.join(DIR, name), 'utf8'));
const provider = () => new EvidenceProvider(readJson);
const golden = JSON.parse(fs.readFileSync(path.join(DIR, 'golden.json'), 'utf8'));

test('the context follows the organism unless it is chosen', () => {
    assert.equal(resolveContext('9606'), 'cells');
    assert.equal(resolveContext('10090'), 'organism');
    assert.equal(resolveContext('9606', 'organism'), 'organism');
    assert.equal(resolveContext('10090', 'cells'), 'cells');
});

test('genes are found by symbol in any case and by an older name', async () => {
    const human = await provider().organism('9606');
    assert.ok(human.lookup('tdg'));
    assert.equal(human.lookup('AARS'), human.lookup('AARS1'));
    assert.equal(human.lookup('NOSUCHGENE'), null);
    assert.equal(human.lookup('constructor'), null);            // object properties are not genes
    assert.equal(human.lookup(''), null);
});

test('organisms without a file have no evidence; the two yeast taxon ids share one', async () => {
    const p = provider();
    assert.equal(await p.organism('3702'), null);
    assert.equal(await p.organism('4932'), await p.organism('559292'));
});

test('a different file format is refused', async () => {
    const odd = new EvidenceProvider(async () => ({ format: 99, organisms: {} }));
    await assert.rejects(() => odd.index(), /format 99/);
});

test('downloading failures are reported as EvidenceUnavailable', async () => {
    const offline = createEvidenceProvider('https://example.org/evidence-data/', async () => { throw new Error('offline'); });
    await assert.rejects(() => offline.index(), (error) => error instanceof EvidenceUnavailable && /offline/.test(error.message));

    const missing = createEvidenceProvider('https://example.org/evidence-data/', async () => ({ ok: false, status: 404 }));
    await assert.rejects(() => missing.index(), /HTTP 404/);
});

test('files are fetched once each', async () => {
    const calls = [];
    const counting = createEvidenceProvider('x/', async (url) => {
        calls.push(url);
        return { ok: true, json: async () => readJson(url.slice(2)) };
    });
    await assessGene(counting, '9606', 'TDG');
    await assessGene(counting, '9606', 'PCNA');
    assert.deepEqual(calls, ['x/index.json', 'x/9606.json']);
});

test('without a provider nothing is claimed', async () => {
    const evidence = await assessGene(null, '9606', 'TDG');
    assert.equal(evidence.has_measured, false);
    assert.equal(evidence.covered, false);
});

test('the golden cases recorded from Python are reproduced exactly (evidence and verdict)', async () => {
    assert.ok(golden.length > 100);
    const p = provider();
    for (const entry of golden) {
        const label = `${entry.taxid} ${entry.symbol} ${entry.context}`;
        const evidence = await assessGene(p, entry.taxid, entry.symbol, entry.context);
        assert.deepEqual(evidence, entry.evidence, label);

        const recommendation = getSafetyRecommendation({
            symbol: entry.symbol, pleiotropyScore: entry.pleiotropy, knockoutEvidence: evidence,
            crossSpecies: { conservation_score: 0.5 }, literatureSupport: 0.5,
        });
        const expected = entry.recommendation;
        assert.equal(recommendation.safety_level, expected.safety_level, label);
        assert.equal(recommendation.primary_recommendation, expected.primary_recommendation, label);
        assert.deepEqual(recommendation.alternative_recommendations, expected.alternative_recommendations, label);
        assert.deepEqual(recommendation.justification, expected.justification, label);
        assert.deepEqual(recommendation.concerns, expected.concerns, label);
        assert.deepEqual(recommendation.mitigation_strategies, expected.mitigation_strategies, label);
        assert.deepEqual(recommendation.experimental_considerations, expected.experimental_considerations, label);
        assert.equal(recommendation.confidence_score, expected.confidence_score, label);
        assert.equal(recommendation.evidence_basis, expected.evidence_basis, label);
    }
});

test('without evidence the old rules apply unchanged', () => {
    const recommendation = getSafetyRecommendation({ symbol: 'X', pleiotropyScore: 1.0 });
    assert.equal(recommendation.safety_level, 'SAFE');
    assert.equal(recommendation.evidence_basis, 'none');
});

test('a lethal gene is never called safe however specific it looks', async () => {
    const evidence = await assessGene(provider(), '10090', 'Tdg');
    const recommendation = getSafetyRecommendation({ symbol: 'Tdg', pleiotropyScore: 0, knockoutEvidence: evidence });
    assert.equal(recommendation.safety_level, 'AVOID');
    assert.match(recommendation.justification[0], /^Knockout is lethal \(embryonic \/ prenatal\) in mice/);
});

// ------------------------------------------------------------------ paralogs, tissue-restricted expression, distant relatives

function tinyProvider(overrides = {}) {
    const mouseViable = { v: 'V', n: [0, 0, 3], src: 'M' };
    const mouseLethal = { v: 'L', n: [2, 0, 0], s: 'E', src: 'M', id: 'MGI:1', pm: [111] };
    const index = {
        format: 1, built: '2026-01-01', stages: { E: 'embryonic / prenatal', U: 'age not stated' }, systems: [], tissues: ['Liver', 'Brain', 'Heart'],
        sources: ['mgi', 'impc', 'alliance', 'depmap', 'gnomad', 'gtex', 'ensembl'].map((s) => ({ id: s, name: s.toUpperCase(), url: `https://example.org/${s}`, what: '' })),
        organisms: {
            9606: { name: 'Homo sapiens', file: '9606.json', layers: [] },
            10090: { name: 'Mus musculus', file: '10090.json', layers: [] },
            7227: { name: 'Drosophila melanogaster', file: '7227.json', layers: [], distant: true },
        },
    };
    const files = {
        'index.json': index,
        '9606.json': { genes: {
            TWIN1: { o: ['Twin1', '1:1'], m: mouseViable, c: ['', 1.0, 1178], p: [['TWIN2', 62], ['TWIN3', 44], ['OTHER', 33]] },
            LIVER1: { o: ['Liver1', '1:1'], m: mouseLethal, t: [0.9, 3, [0]] },
            BROAD1: { o: ['Broad1', '1:1'], m: mouseLethal, t: [0.2, 3, [0, 1]] },
        }, aliases: {} },
        '10090.json': { genes: { TWIN1: { ...mouseViable, p: [['TWIN2', 70]], ...overrides } }, aliases: {} },
        '7227.json': { genes: { LETHALFLY: { o: ['Liver1', '1:1'], m: mouseLethal }, VIABLEFLY: { o: ['Twin1', '1:1'], m: mouseViable } }, aliases: {} },
    };
    return new EvidenceProvider(async (name) => files[name]);
}

test('close paralogs are listed and warned about, without changing the level', async () => {
    const evidence = await assessGene(tinyProvider(), '9606', 'TWIN1');
    const recommendation = getSafetyRecommendation({ symbol: 'TWIN1', pleiotropyScore: 1.0, knockoutEvidence: evidence });

    assert.deepEqual(evidence.paralogs.genes.map((g) => g.symbol), ['TWIN2', 'TWIN3', 'OTHER']);
    assert.deepEqual(evidence.paralogs.close, ['TWIN2', 'TWIN3']);
    assert.equal(evidence.paralogs.text, 'Closest paralogs: TWIN2 (62% identical), TWIN3 (44% identical), OTHER (33% identical)');
    assert.equal(recommendation.safety_level, 'SAFE');
    assert.ok(recommendation.concerns.some((c) => c.includes('close paralogs TWIN2, TWIN3 may take over its work')));
    assert.ok(evidence.sources.some((s) => s.id === 'ensembl'));

    const mouse = await assessGene(tinyProvider(), '10090', 'Twin1');
    const single = getSafetyRecommendation({ symbol: 'Twin1', pleiotropyScore: 1.0, knockoutEvidence: mouse });
    assert.ok(single.concerns.some((c) => c.includes('The close paralog TWIN2 may take over its work')));
});

test('a tissue-restricted lethal gene gets a tissue-specific suggestion', async () => {
    const provider = tinyProvider();
    const verdict = async (symbol) => getSafetyRecommendation({
        symbol, pleiotropyScore: 1.0, knockoutEvidence: await assessGene(provider, '9606', symbol, 'organism'),
    });

    assert.ok((await verdict('LIVER1')).mitigation_strategies.some((m) => m.includes('concentrated in Liver') && m.includes('tissue-specific conditional knockout')));
    assert.ok(!(await verdict('BROAD1')).mitigation_strategies.some((m) => m.includes('concentrated in')));
});

test('the expression of a mouse gene is marked as coming from the human ortholog', async () => {
    const evidence = await assessGene(tinyProvider({ t: [0.7, 3, [1]] }), '10090', 'Twin1');
    assert.ok(evidence.expression.text.endsWith('(in the human ortholog)'));
});

test('a gene without a knockout result gets a lethality estimate from its human ortholog, never a measurement', async () => {
    const p = provider();
    const evidence = await assessGene(p, '10090', 'Pole');
    const recommendation = getSafetyRecommendation({ symbol: 'Pole', pleiotropyScore: 10.0, knockoutEvidence: evidence });

    assert.equal(evidence.organism.call, 'UNKNOWN');
    assert.equal(evidence.has_measured, false);
    assert.equal(evidence.estimate.band, 'likely');
    assert.equal(evidence.estimate.other_symbol, 'POLE');
    assert.ok(evidence.estimate.percent <= 99);
    assert.equal(recommendation.evidence_basis, 'estimate');
    assert.equal(recommendation.safety_level, 'HIGH_CONCERN');
    assert.equal(recommendation.justification[0], evidence.estimate.text);

    const measured = await assessGene(p, '10090', 'Tdg');
    assert.equal(measured.estimate, null);                                  // a measurement needs no estimate
});

test('no estimate is ever rated better than CAUTION, and the bands follow the probability', async () => {
    const p = provider();
    const mouse = await p.organism('10090');
    const seen = new Set();
    for (const [symbol, record] of Object.entries(mouse.genes)) {
        if (!record.pl || record.v) continue;
        const evidence = await assessGene(p, '10090', symbol);
        const recommendation = getSafetyRecommendation({ symbol, pleiotropyScore: 1.0, knockoutEvidence: evidence });
        const probability = record.pl[0];
        const band = probability >= 0.5 ? 'likely' : probability >= 0.3 ? 'possible' : 'unlikely';
        assert.equal(evidence.estimate.band, band);
        assert.equal(recommendation.safety_level, { likely: 'HIGH_CONCERN', possible: 'MODERATE_CONCERN', unlikely: 'CAUTION' }[band]);
        seen.add(band);
    }
    assert.deepEqual([...seen].sort(), ['likely', 'possible', 'unlikely']);
});

test('without a cell-line result a viable mouse ortholog is never enough for SAFE in cells', async () => {
    const files = {
        'index.json': { format: 1, built: '2026-01-01', stages: {}, systems: [], organisms: { 9606: { name: 'Homo sapiens', file: '9606.json', layers: [] } }, sources: [] },
        '9606.json': { genes: { RPS26: { o: ['Rps26', 'n:1'], m: { v: 'V', n: [0, 0, 2] } } }, aliases: {} },
    };
    const evidence = await assessGene(new EvidenceProvider(async (name) => files[name]), '9606', 'RPS26', 'cells');
    const recommendation = getSafetyRecommendation({ symbol: 'RPS26', pleiotropyScore: 2.0, knockoutEvidence: evidence });

    assert.equal(evidence.cells.call, 'UNKNOWN');
    assert.equal(recommendation.safety_level, 'CAUTION');
    assert.ok(recommendation.concerns.some((c) => c.includes('cells were not screened')));
    assert.ok(recommendation.concerns.some((c) => c.includes('not a one-to-one match')));
});

test('a lethal mouse ortholog without a cell-line result gives MODERATE_CONCERN; subviable or disagreeing results stay at CAUTION', async () => {
    const level = async (m) => {
        const files = {
            'index.json': { format: 1, built: '2026-01-01', stages: {}, systems: [], organisms: { 9606: { name: 'Homo sapiens', file: '9606.json', layers: [] } }, sources: [] },
            '9606.json': { genes: { RPS26: { o: ['Rps26', '1:1'], m } }, aliases: {} },
        };
        const evidence = await assessGene(new EvidenceProvider(async (name) => files[name]), '9606', 'RPS26', 'cells');
        return getSafetyRecommendation({ symbol: 'RPS26', pleiotropyScore: 2.0, knockoutEvidence: evidence });
    };

    const lethal = await level({ v: 'L', n: [3, 0, 0], s: 'E' });
    assert.equal(lethal.safety_level, 'MODERATE_CONCERN');
    assert.equal(lethal.primary_recommendation, 'CRISPR Interference (CRISPRi)');
    assert.ok(lethal.concerns.some((c) => c.includes('about 30% of mouse-lethal genes')));
    assert.equal((await level({ v: 'S', n: [0, 2, 0], s: 'W' })).safety_level, 'CAUTION');
    assert.equal((await level({ v: 'L', n: [2, 0, 1], s: 'E', x: 1 })).safety_level, 'CAUTION');
});

test('an essential call for a gene no tissue expresses and people lose without harm is MODERATE_CONCERN, not AVOID', async () => {
    const level = async (record) => {
        const files = {
            'index.json': { format: 1, built: '2026-01-01', stages: {}, systems: [], organisms: { 9606: { name: 'Homo sapiens', file: '9606.json', layers: [] } }, sources: [] },
            '9606.json': { genes: { OR7A10: record }, aliases: {} },
        };
        const evidence = await assessGene(new EvidenceProvider(async (name) => files[name]), '9606', 'OR7A10', 'cells');
        return getSafetyRecommendation({ symbol: 'OR7A10', pleiotropyScore: 2.0, knockoutEvidence: evidence });
    };

    const artefact = await level({ c: ['C', 66.8, 1059], l: 1.84, t: [null, 0, []] });
    assert.equal(artefact.safety_level, 'MODERATE_CONCERN');
    assert.ok(artefact.concerns.some((c) => c.includes('artefact')));
    assert.equal((await level({ c: ['C', 99.0, 1059], l: 0.1, t: [null, 0, []] })).safety_level, 'AVOID');
});

test('a viable mouse knockout of a gene whose human ortholog is essential in cell lines is CAUTION, not SAFE', async () => {
    const level = async (record) => {
        const files = {
            'index.json': { format: 1, built: '2026-01-01', stages: {}, systems: [], organisms: { 10090: { name: 'Mus musculus', file: '10090.json', layers: [] } }, sources: [] },
            '10090.json': { genes: { RPL32: record }, aliases: {} },
        };
        const evidence = await assessGene(new EvidenceProvider(async (name) => files[name]), '10090', 'RPL32', 'organism');
        return getSafetyRecommendation({ symbol: 'RPL32', pleiotropyScore: 2.0, knockoutEvidence: evidence });
    };

    const conflict = await level({ v: 'V', n: [0, 0, 2], hc: 100.0 });
    assert.equal(conflict.safety_level, 'CAUTION');
    assert.ok(conflict.concerns.some((c) => c.includes('human ortholog is essential in 100% of cancer cell lines')));
    assert.equal((await level({ v: 'V', n: [0, 0, 2] })).safety_level, 'SAFE');
});

test('many annotated roles alone do not make a gene with a viable mouse ortholog HIGH_CONCERN in a distant organism', async () => {
    const level = async (mouse, pleiotropy) => {
        const files = {
            'index.json': { format: 1, built: '2026-01-01', stages: {}, systems: [], organisms: { 7955: { name: 'Danio rerio', file: '7955.json', layers: [], distant: true } }, sources: [] },
            '7955.json': { genes: { WNT8A: { o: ['wnt8a', '1:1'], m: mouse } }, aliases: {} },
        };
        const evidence = await assessGene(new EvidenceProvider(async (name) => files[name]), '7955', 'WNT8A', 'organism');
        return getSafetyRecommendation({ symbol: 'WNT8A', pleiotropyScore: pleiotropy, knockoutEvidence: evidence }).safety_level;
    };

    assert.ok(['CAUTION', 'MODERATE_CONCERN'].includes(await level({ v: 'V', n: [0, 0, 1] }, 10.0)));
    assert.ok(['MODERATE_CONCERN', 'HIGH_CONCERN', 'AVOID'].includes(await level({ v: 'L', n: [2, 0, 0], s: 'E' }, 2.0)));
});

test('conservation counts the model species that carry the gene; literature is the number of linked articles', async () => {
    const files = {
        'index.json': { format: 1, built: '2026-01-01', organisms: { 9606: { name: 'Homo sapiens', file: '9606.json', layers: [] } }, sources: [] },
        '9606.json': { genes: { PCNA: { cv: 27, lc: 6361 }, TINY: { cv: 1, lc: 0 }, NOCV: {} }, aliases: {} },
    };
    const p = new EvidenceProvider(async (name) => files[name]);

    const pcna = await assessGene(p, '9606', 'PCNA');
    const tiny = await assessGene(p, '9606', 'TINY');
    const none = await assessGene(p, '9606', 'NOCV');

    assert.equal(pcna.conservation.score, 0.8);
    assert.deepEqual(pcna.conservation.found_in, ['human', 'mouse', 'fly', 'worm']);
    assert.equal(pcna.conservation.text, 'Present in 4 of 5 model species (human, mouse, fly, worm)');
    assert.equal(pcna.literature.count, 6361);
    assert.equal(tiny.conservation.score, 0.2);
    assert.equal(tiny.literature.count, 0);
    assert.equal(none.conservation, null);
    assert.equal(none.literature, null);
});

test('an unmeasured gene that the old rules rated worse than CAUTION still says it was not measured', async () => {
    const evidence = await assessGene(tinyProvider(), '9606', 'NOSUCHGENE');
    const recommendation = getSafetyRecommendation({ symbol: 'NOSUCHGENE', pleiotropyScore: 9.0, knockoutEvidence: evidence });

    assert.equal(evidence.has_measured, false);
    assert.notEqual(recommendation.safety_level, 'SAFE');
    assert.ok(recommendation.justification[0].startsWith('No measured knockout data for this gene'));
    assert.ok(recommendation.concerns[0].startsWith('Lethality has not been measured'));
    assert.ok(!recommendation.concerns.includes('No major concerns identified'));
});

test('a distant relative gets a hint, never a measurement', async () => {
    const evidence = await assessGene(tinyProvider(), '7227', 'LETHALFLY');
    const recommendation = getSafetyRecommendation({ symbol: 'LETHALFLY', pleiotropyScore: 1.0, knockoutEvidence: evidence });

    assert.ok(evidence.organism.distant && evidence.organism.call === 'LETHAL');
    assert.equal(evidence.has_measured, false);
    assert.ok(evidence.organism.text.includes('a distant relative, so only an indication'));
    assert.equal(recommendation.evidence_basis, 'distant');
    assert.equal(recommendation.safety_level, 'MODERATE_CONCERN');
    assert.equal(recommendation.primary_recommendation, 'Heterozygous Knockout');
    assert.ok(recommendation.justification[0].startsWith('No measured knockout data for this gene'));
    assert.equal(recommendation.justification[1], evidence.organism.text);
    assert.ok(recommendation.concerns[0].includes('has not been tested'));
    assert.ok(recommendation.concerns[1].startsWith('Lethality has not been measured'));
});

test('a viable mouse ortholog does not make a distant gene safe', async () => {
    const evidence = await assessGene(tinyProvider(), '7227', 'VIABLEFLY');
    const recommendation = getSafetyRecommendation({ symbol: 'VIABLEFLY', pleiotropyScore: 0.5, knockoutEvidence: evidence });

    assert.equal(recommendation.evidence_basis, 'distant');
    assert.equal(recommendation.safety_level, 'CAUTION');
    assert.ok(recommendation.justification[0].startsWith('No measured knockout data for this gene'));
});
