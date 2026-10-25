// The downloadable reports of the browser engine against the ones the Python package writes for the same result
// (tests/fixtures/evidence/report_sample.*, recorded by tools/record_evidence_fixture.py).

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

import { comprehensiveCsv, excelWorkbook, geneSummaryCsv, htmlReport, EVIDENCE_HEADERS } from '../../webapp/static/js/engine/report.js';
import { ROOT } from './helpers.mjs';

const DIR = path.join(ROOT, 'tests', 'fixtures', 'evidence');
const read = (name) => fs.readFileSync(path.join(DIR, name), 'utf8');
const results = JSON.parse(read('report_sample.json'));

/** Rows of a CSV text (quoted cells may hold commas, quotes and line breaks). */
function parseCsv(text) {
    const rows = [];
    let row = [];
    let cell = '';
    let quoted = false;
    for (let i = 0; i < text.length; i++) {
        const c = text[i];
        if (quoted) {
            if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (c === '"') quoted = false; else cell += c;
        } else if (c === '"') quoted = true;
        else if (c === ',') { row.push(cell); cell = ''; }
        else if (c === '\n' || c === '\r') {
            if (c === '\r' && text[i + 1] === '\n') i++;
            row.push(cell); cell = '';
            rows.push(row); row = [];
        } else cell += c;
    }
    if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
    return rows.filter((r) => !(r.length === 1 && r[0] === ''));
}

/** Python writes 10.0 where JavaScript writes 10: numbers are compared as numbers. */
function sameCell(a, b) {
    if (a === b) return true;
    const x = Number(a);
    const y = Number(b);
    return a !== '' && b !== '' && Number.isFinite(x) && Number.isFinite(y) && x === y;
}

function assertSameCsv(actual, expected, label) {
    const a = parseCsv(actual);
    const e = parseCsv(expected);
    assert.equal(a.length, e.length, `${label}: number of rows`);
    a.forEach((row, i) => {
        assert.equal(row.length, e[i].length, `${label}: row ${i + 1} has ${row.length} cells, Python wrote ${e[i].length}`);
        row.forEach((cell, j) => assert.ok(sameCell(cell, e[i][j]), `${label}: row ${i + 1}, cell ${j + 1}: "${cell}" vs Python "${e[i][j]}"`));
    });
}

test('the comprehensive CSV is the same as the Python one, evidence columns included', () => {
    const python = read('report_sample_comprehensive.csv');
    assertSameCsv(comprehensiveCsv(results), python, 'comprehensive CSV');

    const header = parseCsv(comprehensiveCsv(results)).find((row) => row[0] === 'Gene_Symbol');
    assert.deepEqual(header.slice(-EVIDENCE_HEADERS.length), EVIDENCE_HEADERS);
    assert.ok(comprehensiveCsv(results).includes('# Genes not shown above'));
    assert.ok(comprehensiveCsv(results).includes('# Knockout context: cultured cells'));
});

test('the gene summary CSV is the same as the Python one', () => {
    assertSameCsv(geneSummaryCsv(results), read('report_sample_gene_summary.csv'), 'gene summary CSV');
});

test('the HTML report shows the evidence, the genes not shown and the sources, like the Python report', () => {
    const html = htmlReport(results);
    const python = read('report_sample.html');
    const expected = [
        'Measured Knockout Evidence', 'Genes Assessed but Not Shown', 'Data Sources', 'Knockout context: <strong>cultured cells</strong>',
        'basis basis-measured', 'basis basis-none', 'https://pubmed.ncbi.nlm.nih.gov/', 'https://www.informatics.jax.org/marker/',
        'Example warning, with a comma', 'Rarely essential: needed in',
    ];
    for (const text of expected) {
        assert.ok(html.includes(text), `the browser report lacks: ${text}`);
        assert.ok(python.includes(text), `the Python report lacks: ${text}`);
    }
    for (const gene of results.genes) assert.ok(html.includes(`<strong>${gene.symbol}</strong>`));
    // safest first, in the same order as the result
    const positions = results.genes.map((g) => html.indexOf(`<strong>${g.symbol}</strong>`));
    assert.deepEqual(positions, [...positions].sort((a, b) => a - b));
});

test('a gene that was never verified says so instead of showing an empty evidence cell', () => {
    const html = htmlReport(results);
    assert.ok(html.includes('Not verified'));
});

test('the Excel workbook has the knockout evidence and genes-not-shown sheets', async () => {
    const sheets = {};
    const XLSX = {
        utils: { book_new: () => ({ names: [] }), aoa_to_sheet: (rows) => rows, book_append_sheet: (book, sheet, name) => { book.names.push(name); sheets[name] = sheet; } },
        write: (book) => new TextEncoder().encode(JSON.stringify(book.names)),
    };
    const bytes = await excelWorkbook(results, XLSX);

    assert.deepEqual(JSON.parse(new TextDecoder().decode(bytes)), ['Summary', 'Gene Rankings', 'Safety Recommendations', 'Knockout Evidence', 'Genes Not Shown']);
    assert.deepEqual(sheets['Knockout Evidence'][0], ['Gene Symbol', ...EVIDENCE_HEADERS]);
    assert.equal(sheets['Knockout Evidence'].length, results.genes.length + 1);
    assert.equal(sheets['Genes Not Shown'].length, results.excluded_genes.length + 1);
    assert.ok(sheets.Summary.some((row) => row[0] === 'Knockout context:' && row[1] === 'cultured cells'));
});
