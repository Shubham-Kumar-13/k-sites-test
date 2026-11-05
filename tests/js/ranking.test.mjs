import test from 'node:test';
import assert from 'node:assert/strict';

import { EvidenceProvider, assessGene } from '../../webapp/static/js/engine/knockoutEvidence.js';
import { compareGeneRankings } from '../../webapp/static/js/engine/pipeline.js';
import { getSafetyRecommendation } from '../../webapp/static/js/engine/safety.js';

const files = {
    'index.json': {
        format: 1, built: '2026-01-01', stages: {}, systems: [],
        organisms: { 1313: { name: 'Streptococcus pneumoniae', file: '1313.json', layers: ['knockout'] } },
        sources: [{ id: 'pneumonia_pan_genome', name: 'Tn-seq', url: 'https://example.org' }],
    },
    '1313.json': { genes: {
        ESSENTIAL: { v: 'L', n: [1, 0, 0], src: 'PN' },
        NONESSENTIAL: { v: 'V', n: [0, 0, 1], src: 'PN' },
        CONFLICT: { v: 'V', n: [1, 0, 2], x: 1, src: 'PN' },
        DIRECT: { v: 'V', n: [0, 0, 2], src: 'M' },
    }, aliases: {} },
};
const provider = new EvidenceProvider(async (name) => files[name]);
const recommendation = async (symbol) => getSafetyRecommendation({
    symbol, pleiotropyScore: 1, knockoutEvidence: await assessGene(provider, '1313', symbol, 'organism'),
});

test('insertion essentiality is labelled accurately and rated conservatively', async () => {
    const essential = await recommendation('ESSENTIAL');
    const nonessential = await recommendation('NONESSENTIAL');
    const conflict = await recommendation('CONFLICT');
    const direct = await recommendation('DIRECT');
    const evidence = await assessGene(provider, '1313', 'NONESSENTIAL', 'organism');

    assert.equal(essential.safety_level, 'HIGH_CONCERN');
    assert.equal(nonessential.safety_level, 'CAUTION');
    assert.equal(conflict.safety_level, 'HIGH_CONCERN');
    assert.equal(direct.safety_level, 'SAFE');
    assert.equal(direct.evidence_basis, 'measured');
    assert.equal(evidence.organism.basis, 'essentiality');
    assert.match(evidence.organism.text, /^Tn-seq insertion screen: non-essential/);
    assert.match(evidence.organism.text, /not clean whole-gene deletion viability/);
    assert.ok(!evidence.organism.text.startsWith('Knockout'));
    assert.match(conflict.justification[0], /1 essential and 2 non-essential/);
    assert.ok(conflict.concerns.some((line) => line.includes('differs between study strains')));
});

test('final ranking uses safety, then evidence reliability, then composite', () => {
    const gene = (symbol, safetyLevel, evidenceBasis, composite) => ({
        symbol, composite_score: composite,
        safety_recommendation: { safety_level: safetyLevel, evidence_basis: evidenceBasis },
    });
    const genes = [
        gene('LETHAL', 'AVOID', 'measured', 1.0),
        gene('NONE', 'CAUTION', 'none', 0.99),
        gene('INSERTION', 'CAUTION', 'essentiality', 0.95),
        gene('DIRECT', 'CAUTION', 'measured', 0.70),
    ];

    assert.deepEqual(genes.sort(compareGeneRankings).map((g) => g.symbol), ['DIRECT', 'INSERTION', 'NONE', 'LETHAL']);
});

test('UNKNOWN RAG results stay none and predictions receive no evidence-ranking advantage', async () => {
    const prediction = async (severity, risk) => getSafetyRecommendation({
        symbol: 'G', pleiotropyScore: 1,
        phenotypePrediction: { severity, risk_level: risk, confidence_score: 0.1, predicted_phenotypes: [], supporting_evidence: [] },
        knockoutEvidence: await assessGene(null, '9606', 'G'),
    });
    const unknown = await prediction('UNKNOWN', 'UNKNOWN');
    const mild = await prediction('MILD', 'LOW');
    const entry = (result) => ({ composite_score: 0.8, safety_recommendation: {
        safety_level: result.safety_level, evidence_basis: result.evidence_basis,
    } });

    assert.equal(unknown.evidence_basis, 'none');
    assert.equal(unknown.safety_level, 'CAUTION');
    assert.equal(mild.evidence_basis, 'predicted');
    assert.equal(compareGeneRankings(entry(unknown), entry(mild)), 0);
    assert.equal((await prediction('MILD', 'UNKNOWN')).evidence_basis, 'predicted');
});
