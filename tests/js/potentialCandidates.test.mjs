import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { parseHTML } from 'linkedom';

import { selectPotentialCandidates } from '../../webapp/static/js/engine/potentialCandidates.js';
import { ROOT } from './helpers.mjs';

const gene = (symbol, basis, level, composite, extra = {}) => ({
    symbol, composite_score: composite,
    safety_recommendation: { safety_level: level, evidence_basis: basis }, ...extra,
});

test('potential candidates are read-only, limited to five and exclude indirect or unscorable evidence', () => {
    const genes = [
        gene('SUPPORTED', 'measured', 'CAUTION', 0.70),
        gene('A', 'none', 'CAUTION', 0.95),
        gene('B', 'predicted', 'CAUTION', 0.90),
        gene('C', 'estimate', 'CAUTION', 0.85),
        gene('D', 'none', 'CAUTION', 0.80),
        gene('E', 'none', 'CAUTION', 0.75),
        gene('F', 'none', 'CAUTION', 0.70),
        gene('DISTANT', 'distant', 'CAUTION', 0.99),
        gene('ORTHOLOG', 'ortholog', 'CAUTION', 0.99),
        gene('LETHAL', 'measured', 'AVOID', 1.0),
        gene('RISKY', 'none', 'HIGH_CONCERN', 1.0),
        gene('INSUFFICIENT', 'none', 'CAUTION', 1.0, { data_status: 'insufficient_data' }),
        gene('FAILED', 'none', 'CAUTION', 1.0, { lookup_failed: true }),
        gene('NO_COMPOSITE', 'none', 'CAUTION', null),
    ];
    const originalOrder = genes.map((g) => g.symbol);

    const selected = selectPotentialCandidates(genes);

    assert.deepEqual(selected.map((g) => g.symbol), ['A', 'B', 'C', 'D', 'E']);
    assert.deepEqual(genes.map((g) => g.symbol), originalOrder);
});

test('the list is empty without a higher unverified score or a viable supported candidate', () => {
    assert.deepEqual(selectPotentialCandidates([
        gene('SUPPORTED', 'essentiality', 'SAFE', 0.90), gene('A', 'none', 'CAUTION', 0.90),
    ]), []);
    assert.deepEqual(selectPotentialCandidates([
        gene('LETHAL', 'measured', 'AVOID', 1.0), gene('A', 'none', 'CAUTION', 0.95),
    ]), []);
});

test('the panel shows candidates or exactly the requested empty message', () => {
    const source = fs.readFileSync(`${ROOT}/webapp/static/js/results.js`, 'utf8');
    const { document, window } = parseHTML('<html><body><div id="potentialContainer"></div></body></html>');
    const context = vm.createContext({ window, document, console });
    vm.runInContext(source, context);
    context.data = { potential_candidates: [] };
    vm.runInContext('renderPotentialCandidates(data)', context);
    assert.equal(document.getElementById('potentialContainer').textContent.trim(), 'No unverified genes outscored the best experimentally supported candidate');

    context.data = { potential_candidates: [gene('A', 'none', 'CAUTION', 0.95, {
        description: 'Example protein', specificity_score: 0.9, pleiotropy_score: 1.0,
    })] };
    vm.runInContext('renderPotentialCandidates(data)', context);
    const html = document.getElementById('potentialContainer').innerHTML;
    assert.ok(html.includes('Top 1 promising candidates — unverified'));
    assert.ok(html.includes('Example protein'));
    assert.ok(html.includes('not confirmed safe knockout targets'));
});
