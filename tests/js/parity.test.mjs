// The JavaScript engine must reach the same results as the Python package on the same data.
// Fixture: tests/fixtures/js_parity (recorded by tools/record_parity_fixture.py).

import test from 'node:test';
import assert from 'node:assert/strict';

import { runKSitesPipeline } from '../../webapp/static/js/engine/pipeline.js';
import { diff, keggFromRecording, loadPythonResult, loadRecording, offlineClient, replayFetch } from './helpers.mjs';

const recording = loadRecording();
const { input, result: python } = loadPythonResult();

async function runJs(overrides = {}) {
    const misses = [];
    const http = offlineClient(replayFetch(recording, misses));
    const ctx = { http, keggProvider: keggFromRecording(recording) };

    // The Python run analysed only the first N genes of the GO term; do the same here
    const result = await runKSitesPipeline(ctx, {
        goTerm: input.go_term, organism: input.organism, taxid: input.organism,
        scientificName: 'Homo sapiens',
        maxPleiotropy: input.max_pleiotropy, evidenceFilter: input.evidence_filter,
        predictPhenotypes: false, geneLimit: input.genes, ...overrides,
    });
    return { result, misses };
}

test('the recording is usable', () => {
    assert.ok(Object.keys(recording).length > 50, 'recording has responses');
    assert.equal(python.genes.length, input.genes);
});

test('JavaScript scores every gene exactly like Python', async () => {
    const { result, misses } = await runJs();

    assert.deepEqual(misses, [], `the JS engine asked for responses Python never saw:\n${misses.slice(0, 5).join('\n')}`);

    const pythonGenes = python.genes.map((g) => ({
        symbol: g.symbol,
        pleiotropy_score: g.pleiotropy_score,
        specificity_score: g.specificity_score,
        evidence_quality: g.evidence_quality,
        literature_support: g.literature_support,
        conservation_score: g.conservation_score,
        composite_score: g.composite_score,
        bp_term_count: g.bp_term_count,
        kegg_pathway_count: g.kegg_pathway_count,
        experimental_evidence_count: g.experimental_evidence_count,
        computational_evidence_count: g.computational_evidence_count,
        iea_evidence_count: g.iea_evidence_count,
        description: g.description,
        entrez_id: g.entrez_id,
    }));
    const jsGenes = result.genes.map((g) => Object.fromEntries(Object.keys(pythonGenes[0]).map((k) => [k, g[k]])));

    const differences = diff(pythonGenes, jsGenes, 'genes');
    assert.deepEqual(differences, [], `scores differ:\n${differences.slice(0, 20).join('\n')}`);
});

test('JavaScript gives the same safety verdicts and advice as Python', async () => {
    const { result } = await runJs();

    const differences = diff(
        python.genes.map((g) => g.safety_recommendation),
        result.genes.map((g) => g.safety_recommendation),
        'safety',
    );
    assert.deepEqual(differences, [], `safety verdicts differ:\n${differences.slice(0, 20).join('\n')}`);
});

test('JavaScript gives the same cross-species result as Python', async () => {
    const { result } = await runJs();

    const differences = diff(
        python.genes.map((g) => g.cross_species_validation),
        result.genes.map((g) => g.cross_species_validation),
        'cross_species',
    );
    assert.deepEqual(differences, [], `cross-species results differ:\n${differences.slice(0, 20).join('\n')}`);
});

test('JavaScript reports the same statistics, warnings and unscored genes as Python', async () => {
    const { result } = await runJs();

    assert.deepEqual(diff(python.statistics.total_genes_screened, result.statistics.total_genes_screened), []);
    assert.equal(result.statistics.genes_passed_filter, python.statistics.genes_passed_filter);
    assert.equal(result.statistics.genes_insufficient_data, python.statistics.genes_insufficient_data);
    assert.ok(Math.abs(result.statistics.avg_pleiotropy - python.statistics.avg_pleiotropy) < 1e-9);
    assert.equal(result.statistics.most_specific_gene.symbol, python.statistics.most_specific_gene);
    assert.equal(result.statistics.least_specific_gene.symbol, python.statistics.least_specific_gene);
    assert.deepEqual(result.warnings, python.warnings);
    assert.deepEqual(diff(python.insufficient_data_genes, result.insufficient_data_genes, 'insufficient'), []);
});
