/**
 * Wires the in-browser backend to the real browser: IndexedDB, fetch, Web Locks, the KEGG data
 * files that sit next to the site, and the phenotype model (transformers.js from a CDN).
 */

import { HttpClient } from './http.js';
import { createEvidenceProvider } from './knockoutEvidence.js';
import { HybridPhenotypePredictor } from './hybridPredictor.js';
import { LocalBackend } from './localApi.js';
import { RagPhenotypePredictor, createTransformersEmbedder } from './rag.js';
import { openStore } from './store.js';

// transformers.js runs the same MiniLM model as the Python package, in the browser (WebAssembly)
const TRANSFORMERS_URL = 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.0.2';

export async function createBrowserBackend({ siteBase, keggBase, evidenceBase }) {
    const store = await openStore();
    const http = new HttpClient({ cache: store.httpCache });

    const backend = new LocalBackend({
        store,
        http,
        evidenceProvider: evidenceBase ? createEvidenceProvider(evidenceBase) : null,
        async loadOrganisms() {
            const response = await fetch(`${keggBase}organisms.json`);
            if (!response.ok) throw new Error(`organisms.json: HTTP ${response.status}`);
            return response.json();
        },
        async createPredictor({ onStatus, llmProvider, llmApiKey }) {
            const miniLmFactory = async () => {
                const embedder = await createTransformersEmbedder(() => import(TRANSFORMERS_URL), { onStatus });
                return new RagPhenotypePredictor({
                    http,
                    embedder,
                    parseXml: (text) => new DOMParser().parseFromString(text, 'text/xml'),
                    ncbiApiKey: '',
                });
            };
            return new HybridPhenotypePredictor({
                miniLmFactory,
                http,
                parseXml: (text) => new DOMParser().parseFromString(text, 'text/xml'),
                ncbiApiKey: '',
                llmProvider,
                llmApiKey,
                onStatus,
            });
        },
        getNcbiApiKey: () => '',
        locks: typeof navigator !== 'undefined' ? navigator.locks || null : null,
        now: () => Date.now(),
        newId: () => (globalThis.crypto && crypto.randomUUID ? crypto.randomUUID() : `job-${Date.now()}-${Math.random().toString(16).slice(2)}`),
    });
    return backend;
}
