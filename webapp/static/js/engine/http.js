/**
 * HTTP client for the K-Sites engine.
 *
 * - one polite request rate per host (NCBI allows 3 requests/second without a key),
 * - retries with back-off on HTTP 429/5xx and on network errors,
 * - an optional response cache so a repeated run is fast (see store.js).
 *
 * `fetchImpl`, `cache` and `sleep` can be replaced, which is how the tests run offline.
 */

export const DEFAULT_RATE_LIMITS = {
    'www.ebi.ac.uk': 8,
    'rest.uniprot.org': 8,
    'eutils.ncbi.nlm.nih.gov': 3,
};

const RETRY_STATUSES = new Set([429, 500, 502, 503, 504]);
const DAY_MS = 24 * 60 * 60 * 1000;

export class HttpClient {
    constructor(options = {}) {
        this.fetchImpl = options.fetchImpl || ((...args) => globalThis.fetch(...args));
        this.cache = options.cache || null;          // { get(key) -> value|undefined, set(key, value) }
        this.cacheTtlMs = options.cacheTtlMs ?? DAY_MS;
        this.retries = options.retries ?? 4;
        this.backoffMs = options.backoffMs ?? 800;
        this.sleep = options.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
        this.now = options.now || (() => Date.now());
        this.rateLimits = { ...DEFAULT_RATE_LIMITS, ...(options.rateLimits || {}) };
        this.signal = options.signal || null;
        this.nextSlot = {};
        this.requestCount = 0;
    }

    /** Requests per second for one host (e.g. 10 for NCBI once the user supplies an API key). */
    setRateLimit(host, perSecond) {
        this.rateLimits[host] = perSecond;
    }

    static cacheKey(url, params) {
        const entries = Object.entries(params || {})
            .filter(([, value]) => value !== undefined && value !== null)
            .map(([key, value]) => [key, String(value)])
            .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
        const query = entries.map(([key, value]) => `${key}=${value}`).join('&');
        return query ? `${url}?${query}` : url;
    }

    static buildUrl(url, params) {
        const query = new URLSearchParams();
        for (const [key, value] of Object.entries(params || {})) {
            if (value !== undefined && value !== null) query.append(key, String(value));
        }
        const text = query.toString();
        return text ? `${url}${url.includes('?') ? '&' : '?'}${text}` : url;
    }

    async _waitForSlot(host) {
        const perSecond = this.rateLimits[host];
        if (!perSecond) return;
        const interval = 1000 / perSecond;
        const now = this.now();
        const start = Math.max(now, this.nextSlot[host] || 0);
        this.nextSlot[host] = start + interval;
        if (start > now) await this.sleep(start - now);
    }

    _checkAborted() {
        if (this.signal && this.signal.aborted) {
            const error = new Error('The analysis was cancelled');
            error.name = 'AbortError';
            throw error;
        }
    }

    /**
     * GET a URL. Resolves to { status, ok, text, json() }. HTTP error statuses are returned,
     * not thrown, so callers can tell "not found" from "service failed"; only network
     * failures that survive every retry throw.
     */
    async get(url, { params, headers, useCache = true } = {}) {
        const key = HttpClient.cacheKey(url, params);

        if (useCache && this.cache) {
            const hit = await this.cache.get(key);
            if (hit && this.now() - hit.time < this.cacheTtlMs) {
                return HttpClient._response(hit.status, hit.text);
            }
        }

        const host = new URL(url).host;
        const fullUrl = HttpClient.buildUrl(url, params);
        let lastError = null;
        let lastResponse = null;

        for (let attempt = 0; attempt <= this.retries; attempt++) {
            this._checkAborted();
            await this._waitForSlot(host);
            this._checkAborted();
            this.requestCount++;
            try {
                const response = await this.fetchImpl(fullUrl, { headers: { Accept: 'application/json', ...(headers || {}) }, signal: this.signal || undefined });
                const text = await response.text();
                lastResponse = HttpClient._response(response.status, text);
                if (!RETRY_STATUSES.has(response.status)) {
                    if (useCache && this.cache && response.status === 200) {
                        await this.cache.set(key, { status: response.status, text, time: this.now() });
                    }
                    return lastResponse;
                }
                if (attempt < this.retries) {
                    const retryAfter = Number(response.headers && response.headers.get && response.headers.get('Retry-After'));
                    await this.sleep(retryAfter > 0 ? retryAfter * 1000 : this.backoffMs * 2 ** attempt);
                }
            } catch (error) {
                if (error && error.name === 'AbortError') throw error;
                lastError = error;
                if (attempt < this.retries) await this.sleep(this.backoffMs * 2 ** attempt);
            }
        }

        if (lastResponse) return lastResponse;
        throw lastError || new Error(`Request failed: ${fullUrl}`);
    }

    static _response(status, text) {
        return {
            status,
            ok: status >= 200 && status < 300,
            text,
            json() {
                return JSON.parse(text);
            },
        };
    }
}

/** Small in-memory cache (also used by the tests). */
export class MemoryCache {
    constructor() {
        this.map = new Map();
    }
    async get(key) {
        return this.map.get(key);
    }
    async set(key, value) {
        this.map.set(key, value);
    }
}
