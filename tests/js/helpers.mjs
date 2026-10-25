// Shared helpers for the JavaScript engine tests (run with: node --test tests/js/).

import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

import { HttpClient, MemoryCache } from '../../webapp/static/js/engine/http.js';

const here = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(here, '..', '..');
export const FIXTURES = path.join(ROOT, 'tests', 'fixtures', 'js_parity');

/** The same key the recorder (and HttpClient) use: base URL plus sorted, decoded parameters. */
export function keyFromUrl(fullUrl) {
    const url = new URL(fullUrl);
    const entries = [...url.searchParams.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    const query = entries.map(([k, v]) => `${k}=${v}`).join('&');
    const base = `${url.origin}${url.pathname}`;
    return query ? `${base}?${query}` : base;
}

export function loadRecording() {
    const raw = zlib.gunzipSync(fs.readFileSync(path.join(FIXTURES, 'recording.json.gz'))).toString('utf8');
    return JSON.parse(raw);
}

export function loadPythonResult() {
    return JSON.parse(fs.readFileSync(path.join(FIXTURES, 'python_result.json'), 'utf8'));
}

/** An offline fetch that answers from a recording and remembers what it could not answer. */
export function replayFetch(recording, misses = []) {
    return async (fullUrl) => {
        const key = keyFromUrl(fullUrl);
        const hit = recording[key];
        if (!hit) {
            misses.push(key);
            return { status: 599, text: async () => 'not recorded', headers: { get: () => null } };
        }
        return { status: hit.status, text: async () => hit.text, headers: { get: () => null } };
    };
}

/** An HttpClient that never waits and never touches the network. */
export function offlineClient(fetchImpl, extra = {}) {
    return new HttpClient({
        fetchImpl,
        sleep: async () => {},
        rateLimits: {},
        retries: 0,
        cache: new MemoryCache(),
        ...extra,
    });
}

const KEGG_CODES = { 9606: 'hsa', 10090: 'mmu', 7227: 'dme', 6239: 'cel', 10116: 'rno', 7955: 'dre' };

/** KEGG lookup that follows the Python client's rule (main symbol first), using recorded KEGG answers. */
export function keggFromRecording(recording) {
    return async (taxid, symbol) => {
        const code = KEGG_CODES[taxid];
        if (!code) return null;
        const find = recording[`https://rest.kegg.jp/find/${code}/${symbol}`];
        if (!find || find.status !== 200) return { found: false, pathway_count: 0, pathways: [] };
        // prefer the gene whose MAIN symbol is the query (LRIG1 merely lists "LIG1" as a synonym)
        let geneId = null;
        let synonymId = null;
        for (const line of find.text.trim().split('\n')) {
            const parts = line.split('\t');
            if (parts.length < 2) continue;
            const names = parts[1].split(';')[0].split(',').map((n) => n.trim().toUpperCase());
            if (names[0] === symbol.toUpperCase()) { geneId = parts[0]; break; }
            if (!synonymId && names.includes(symbol.toUpperCase())) synonymId = parts[0];
        }
        geneId = geneId || synonymId;
        if (!geneId) return { found: false, pathway_count: 0, pathways: [] };
        const link = recording[`https://rest.kegg.jp/link/pathway/${geneId}`];
        const pathways = link && link.status === 200
            ? link.text.trim().split('\n').filter(Boolean).map((l) => ({ pathway_id: l.split('\t')[1].replace('path:', ''), gene_id: geneId }))
            : [];
        return { found: true, kegg_gene_id: geneId, pathway_count: pathways.length, pathways };
    };
}

/** Compare two values; floats within a tolerance. Returns a list of "path: expected vs actual". */
export function diff(expected, actual, where = '', out = [], tolerance = 1e-9) {
    if (typeof expected === 'number' && typeof actual === 'number') {
        if (Math.abs(expected - actual) > tolerance) out.push(`${where}: python=${expected} js=${actual}`);
    } else if (Array.isArray(expected) && Array.isArray(actual)) {
        if (expected.length !== actual.length) out.push(`${where}: length python=${expected.length} js=${actual.length}`);
        for (let i = 0; i < Math.min(expected.length, actual.length); i++) diff(expected[i], actual[i], `${where}[${i}]`, out, tolerance);
    } else if (expected && actual && typeof expected === 'object' && typeof actual === 'object') {
        for (const key of new Set([...Object.keys(expected), ...Object.keys(actual)])) {
            if (!(key in expected)) out.push(`${where}.${key}: only in js`);
            else if (!(key in actual)) out.push(`${where}.${key}: only in python`);
            else diff(expected[key], actual[key], `${where}.${key}`, out, tolerance);
        }
    } else if (expected !== actual) {
        out.push(`${where}: python=${JSON.stringify(expected)} js=${JSON.stringify(actual)}`);
    }
    return out;
}
