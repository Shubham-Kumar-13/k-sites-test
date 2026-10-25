/**
 * Where the browser keeps jobs, results and cached database answers.
 *
 * IndexedDB in a browser; MemoryStore in tests. Both have the same methods.
 */

const DB_NAME = 'ksites';
const DB_VERSION = 1;
const HTTP_TTL_MS = 24 * 60 * 60 * 1000;
const HTTP_MAX_ENTRIES = 4000;

export class MemoryStore {
    constructor() {
        this.jobs = new Map();
        this.results = new Map();
        this.http = new Map();
    }
    async putJob(job) { this.jobs.set(job.id, structuredClone(job)); }
    async getJob(id) { const job = this.jobs.get(id); return job ? structuredClone(job) : undefined; }
    async listJobs() { return [...this.jobs.values()].map((j) => structuredClone(j)); }
    async deleteJob(id) { this.jobs.delete(id); this.results.delete(id); }
    async putResults(id, results) { this.results.set(id, structuredClone(results)); }
    async getResults(id) { const r = this.results.get(id); return r ? structuredClone(r) : undefined; }

    /** Cache interface used by HttpClient. */
    get httpCache() {
        const map = this.http;
        return {
            async get(key) { return map.get(key); },
            async set(key, value) { map.set(key, value); },
        };
    }
}

function request(req) {
    return new Promise((resolve, reject) => {
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

export class IndexedDbStore {
    constructor(db) {
        this.db = db;
    }

    static async open() {
        const db = await new Promise((resolve, reject) => {
            const open = indexedDB.open(DB_NAME, DB_VERSION);
            open.onupgradeneeded = () => {
                const database = open.result;
                if (!database.objectStoreNames.contains('jobs')) database.createObjectStore('jobs', { keyPath: 'id' });
                if (!database.objectStoreNames.contains('results')) database.createObjectStore('results');
                if (!database.objectStoreNames.contains('http')) database.createObjectStore('http');
            };
            open.onsuccess = () => resolve(open.result);
            open.onerror = () => reject(open.error);
        });
        const store = new IndexedDbStore(db);
        store.pruneHttpCache().catch(() => {});
        return store;
    }

    _store(name, mode = 'readonly') {
        return this.db.transaction(name, mode).objectStore(name);
    }

    async putJob(job) { await request(this._store('jobs', 'readwrite').put(job)); }
    async getJob(id) { return request(this._store('jobs').get(id)); }
    async listJobs() { return request(this._store('jobs').getAll()); }
    async deleteJob(id) {
        await request(this._store('jobs', 'readwrite').delete(id));
        await request(this._store('results', 'readwrite').delete(id));
    }
    async putResults(id, results) { await request(this._store('results', 'readwrite').put(results, id)); }
    async getResults(id) { return request(this._store('results').get(id)); }

    get httpCache() {
        const self = this;
        return {
            async get(key) { try { return await request(self._store('http').get(key)); } catch (e) { return undefined; } },
            async set(key, value) { try { await request(self._store('http', 'readwrite').put(value, key)); } catch (e) { /* cache is optional */ } },
        };
    }

    /** Drop expired answers, and the oldest ones if the cache has grown large. */
    async pruneHttpCache() {
        const store = this._store('http', 'readwrite');
        const keys = await request(store.getAllKeys());
        if (!keys.length) return;
        const entries = await request(this._store('http').getAll());
        const now = Date.now();
        const rows = keys.map((key, i) => ({ key, time: (entries[i] && entries[i].time) || 0 }));
        const expired = rows.filter((r) => now - r.time > HTTP_TTL_MS);
        let doomed = expired.map((r) => r.key);
        const live = rows.filter((r) => now - r.time <= HTTP_TTL_MS).sort((a, b) => a.time - b.time);
        if (live.length > HTTP_MAX_ENTRIES) doomed = doomed.concat(live.slice(0, live.length - HTTP_MAX_ENTRIES).map((r) => r.key));
        if (!doomed.length) return;
        const writer = this._store('http', 'readwrite');
        for (const key of doomed) writer.delete(key);
    }
}

export async function openStore() {
    if (typeof indexedDB === 'undefined') return new MemoryStore();
    try {
        return await IndexedDbStore.open();
    } catch (error) {
        return new MemoryStore();   // private windows may block IndexedDB; jobs then last for this tab only
    }
}
