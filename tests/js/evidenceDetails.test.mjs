import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { parseHTML } from 'linkedom';
import { ROOT } from './helpers.mjs';

const source = fs.readFileSync(`${ROOT}/webapp/static/js/results.js`, 'utf8');
const payload = {
    version: '2026-11-04',
    evidence: {
        call: 'LETHAL', conflicting: false,
        records: [{
            source: 'tair', source_record_id: 'SALK_052897', call: 'LETHAL',
            experiment_type: 'mutant_not_otherwise_specified', zygosity: 'homozygous',
            evidence_level: 'qualified', qualifiers: [], phenotype: 'Homozygotes are embryo lethal.',
            references: ['26555280'],
        }],
    },
};

function setup() {
    const { document, window } = parseHTML('<html><body><div id="genesContainer"></div></body></html>');
    const context = vm.createContext({ window, document, console, encodeURIComponent,
        ksFetch: async () => ({ json: async () => payload }) });
    vm.runInContext(source, context);
    return { context, document };
}

test('detailed evidence renders the exact statement, metadata and publication link', () => {
    const { context } = setup();
    context.payload = payload;

    const html = vm.runInContext('detailedEvidenceHtml(payload)', context);

    assert.ok(html.includes('SALK_052897'));
    assert.ok(html.includes('Homozygotes are embryo lethal.'));
    assert.ok(html.includes('mutant not otherwise specified'));
    assert.ok(html.includes('homozygous'));
    assert.ok(html.includes('qualified'));
    assert.ok(html.includes('https://pubmed.ncbi.nlm.nih.gov/26555280/'));
});

test('Arabidopsis evidence panel offers lazy-loaded source details', () => {
    const { context } = setup();
    context.gene = { symbol: 'AT1G01040', safety_recommendation: {}, knockout_evidence: {
        organism: { call: 'UNKNOWN' }, cells: { call: 'UNKNOWN' },
    } };
    vm.runInContext("currentJob = { taxid: '3702' }", context);

    const html = vm.runInContext('evidencePanel(gene)', context);

    assert.ok(html.includes('Detailed source records'));
    assert.ok(html.includes('data-symbol="AT1G01040"'));
    assert.ok(html.includes('Expand to load'));
});

test('expanding details loads the API record once', async () => {
    const { context, document } = setup();
    const container = document.createElement('details');
    container.dataset.taxid = '3702';
    container.dataset.symbol = 'AT1G01040';
    container.innerHTML = '<div class="detailed-evidence-body"></div>';
    document.getElementById('genesContainer').appendChild(container);
    context.container = container;

    await vm.runInContext('loadDetailedEvidence(container)', context);
    await vm.runInContext('loadDetailedEvidence(container)', context);

    assert.equal(container.dataset.loaded, 'true');
    assert.ok(container.innerHTML.includes('SALK_052897'));
});

test('lookup failure explanation is collapsed behind a question mark', () => {
    const { context, document } = setup();
    context.genes = [{ symbol: 'Pv_tr_11548.t1', reasons: ['No Biological Process annotations found'], lookup_failed: false }];

    vm.runInContext('renderInsufficientData(genes)', context);

    const html = document.getElementById('genesContainer').innerHTML;
    assert.ok(html.includes('<details'));
    assert.ok(html.includes('aria-label="Explain lookup failed"'));
    assert.ok(!html.includes('<details open'));
    assert.ok(!html.includes('These genes are not ranked and have no safety level. "Lookup failed"'));
});

test('mouse observations render genotype, allele, background and IMPC metadata', () => {
    const { context } = setup();
    context.payload = {
        version: '2026-11-04', evidence: { call: 'OBSERVATION', records: [{
            source: 'impc', source_record_id: 'C1:PARAM1', call: 'OBSERVATION',
            experiment_type: 'impc_phenotype_assertion', zygosity: 'homozygote', evidence_level: 'direct',
            genotype: 'Tgfa<em1>/Tgfa<em1>', background: 'C57BL/6NCrl', stage: null, qualifiers: [],
            alleles: [{ symbol: 'Tgfa<em1>', class: 'ko' }], phenotype: 'increased airway resistance',
            references: [], phenotyping_center: 'CCP-IMG', parameter_stable_id: 'CCP_LFO_005_001', p_value: '0.0001',
        }] },
    };

    const html = vm.runInContext('detailedEvidenceHtml(payload)', context);

    assert.ok(html.includes('Observation'));
    assert.ok(html.includes('Tgfa&lt;em1&gt;/Tgfa&lt;em1&gt;'));
    assert.ok(html.includes('Tgfa&lt;em1&gt; (ko)'));
    assert.ok(html.includes('C57BL/6NCrl'));
    assert.ok(html.includes('CCP_LFO_005_001'));
    assert.ok(html.includes('p=0.0001'));
});

test('bacterial insertion evidence shows its method and source background, not a direct-knockout label', () => {
    const { context } = setup();
    context.gene = { symbol: 'AAAE', safety_recommendation: { evidence_basis: 'essentiality' }, knockout_evidence: {
        context: 'organism',
        organism: { call: 'VIABLE', basis: 'essentiality', text: 'TraDIS insertion screen: non-essential',
            references: [], systems: [], mgi_id: null },
        cells: { call: 'UNKNOWN' }, estimate: null, constraint: null, expression: null, paralogs: null,
    } };
    vm.runInContext("currentJob = { taxid: '573' }", context);

    const panel = vm.runInContext('evidencePanel(gene)', context);
    assert.ok(panel.includes('Experimental essentiality (not a clean knockout)'));
    assert.ok(panel.includes('data-taxid="573"'));
    assert.ok(panel.includes('Detailed source records'));

    context.payload = {
        version: '2026-11-05', evidence: { call: 'VIABLE', records: [{
            source: 'tradis', source_record_id: 'KP1', call: 'VIABLE',
            experiment_type: 'transposon_insertion_essentiality', zygosity: 'haploid', evidence_level: 'direct',
            genotype: 'Tn5 transposon insertion library', background: 'Klebsiella pneumoniae Ecl8',
            phenotype: 'non-essential', qualifiers: [], alleles: [], references: [],
        }] },
    };
    const details = vm.runInContext('detailedEvidenceHtml(payload)', context);
    assert.ok(details.includes('experimental insertion essentiality'));
    assert.ok(details.includes('Background: Klebsiella pneumoniae Ecl8'));
    assert.ok(!details.includes('· direct'));
});
