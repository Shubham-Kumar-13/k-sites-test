/**
 * Knockout phenotype prediction from PubMed literature.
 * Port of k_sites/rag_system/literature_context.py.
 *
 * Steps: search PubMed -> embed the abstracts with MiniLM -> semantic search with diversity
 * (MMR) -> extract phenotype terms -> classify severity -> risk level and confidence.
 *
 * The embedding model and the XML parser are injected, so the same code runs in a browser
 * (transformers.js, DOMParser) and in Node tests.
 */

const EUTILS = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/';
export const MODEL_ID = 'Xenova/all-MiniLM-L6-v2';   // the same model as sentence-transformers all-MiniLM-L6-v2

export const SEVERITY = { LETHAL: 'LETHAL', SEVERE: 'SEVERE', MODERATE: 'MODERATE', MILD: 'MILD', UNKNOWN: 'UNKNOWN' };
export const RISK = { CRITICAL: 'CRITICAL', HIGH: 'HIGH', MEDIUM: 'MEDIUM', LOW: 'LOW', UNKNOWN: 'UNKNOWN' };
const RISK_FOR_SEVERITY = {
    LETHAL: RISK.CRITICAL, SEVERE: RISK.HIGH, MODERATE: RISK.MEDIUM, MILD: RISK.LOW, UNKNOWN: RISK.UNKNOWN,
};

// ---------------------------------------------------------------- PubMed

function searchQuery(symbol, type) {
    const g = `${symbol}[Gene]`;
    const queries = {
        knockout: `${g} AND (knockout[Title/Abstract] OR knockout[MeSH Terms] OR 'gene knockout'[Title/Abstract] OR deletion[Title/Abstract])`,
        phenotype: `${g} AND (phenotype[Title/Abstract] OR phenotypic[Title/Abstract] OR 'mutant phenotype'[Title/Abstract] OR morphological[Title/Abstract])`,
        viability: `${g} AND (viability[Title/Abstract] OR viable[Title/Abstract] OR lethal[Title/Abstract] OR lethality[Title/Abstract] OR survival[Title/Abstract] OR 'embryonic lethal'[Title/Abstract])`,
        compensatory: `${g} AND (compensatory[Title/Abstract] OR compensation[Title/Abstract] OR 'redundant gene'[Title/Abstract] OR paralog[Title/Abstract] OR 'genetic buffering'[Title/Abstract])`,
        mouse_knockout: `${g} AND (mice[MeSH Terms] OR mouse[Title/Abstract] OR murine[Title/Abstract]) AND (knockout[Title/Abstract] OR 'null mutation'[Title/Abstract] OR deficient[Title/Abstract] OR targeted[Title/Abstract]) AND (lethal[Title/Abstract] OR lethality[Title/Abstract] OR viable[Title/Abstract] OR embryonic[Title/Abstract] OR survival[Title/Abstract])`,
        comprehensive: `${g} AND (knockout[Title/Abstract] OR phenotype[Title/Abstract] OR mutant[Title/Abstract] OR viability[Title/Abstract] OR CRISPR[Title/Abstract])`,
    };
    return queries[type] || queries.comprehensive;
}

const text = (node) => (node && node.textContent) || '';

/** Parse one <PubmedArticle> into a literature record (inline markup such as <i> keeps its text). */
export function parsePubmedArticle(article) {
    const first = (selector) => article.querySelector(selector);
    const all = (selector) => [...article.querySelectorAll(selector)];

    const pmid = text(first('PMID'));
    let pmcid = null;
    let doi = null;
    for (const id of all('ArticleId')) {
        const type = id.getAttribute('IdType');
        if (type === 'pmc' && !pmcid) pmcid = text(id);
        if (type === 'doi' && !doi) doi = text(id);
    }

    const abstractParts = all('Abstract > AbstractText').map(text).filter((t) => t.trim());
    const authors = [];
    for (const author of all('Author')) {
        const last = text(author.querySelector('LastName'));
        if (!last) continue;
        const fore = text(author.querySelector('ForeName'));
        authors.push(fore ? `${fore} ${last}` : last);
    }

    return {
        pmid,
        pmcid,
        title: text(first('ArticleTitle')),
        abstract: abstractParts.join(' '),
        full_text: null,
        authors,
        journal: text(first('Journal > Title')),
        publication_date: text(first('PubDate > Year')),
        doi,
        keywords: all('Keyword').map(text).filter(Boolean),
        evidence_quality: 'unknown',
    };
}

export class LiteratureMiner {
    constructor({ http, parseXml, ncbiApiKey = '', ncbiEmail = '' }) {
        this.http = http;
        this.parseXml = parseXml;
        this.apiKey = ncbiApiKey;
        this.email = ncbiEmail;
        this.errors = [];
    }

    _params(params) {
        const out = { ...params };
        if (this.email) out.email = this.email;
        if (this.apiKey) out.api_key = this.apiKey;
        return out;
    }

    async _get(endpoint, params) {
        try {
            const response = await this.http.get(EUTILS + endpoint, { params: this._params(params) });
            if (!response.ok) {
                this.errors.push(`NCBI ${endpoint} returned HTTP ${response.status}`);
                return null;
            }
            return response;
        } catch (error) {
            if (error && error.name === 'AbortError') throw error;
            this.errors.push(`NCBI ${endpoint} failed: ${error.message}`);
            return null;
        }
    }

    async searchPubmed(symbol, searchType = 'comprehensive', retmax = 100) {
        const search = await this._get('esearch.fcgi', {
            db: 'pubmed', term: searchQuery(symbol, searchType), retmax, retmode: 'json', sort: 'relevance',
        });
        if (!search) return [];
        let ids = [];
        try {
            ids = search.json().esearchresult?.idlist || [];
        } catch (error) {
            this.errors.push('PubMed search answer could not be read');
            return [];
        }
        if (!ids.length) return [];
        return this._fetchDetails(ids.slice(0, Math.min(50, retmax)));
    }

    async _fetchDetails(pmids) {
        const response = await this._get('efetch.fcgi', { db: 'pubmed', id: pmids.join(','), retmode: 'xml' });
        if (!response) return [];
        try {
            const doc = this.parseXml(response.text);
            return [...doc.querySelectorAll('PubmedArticle')].map(parsePubmedArticle);
        } catch (error) {
            this.errors.push(`PubMed records could not be parsed: ${error.message}`);
            return [];
        }
    }
}

// ---------------------------------------------------------------- vector store

/**
 * Minimum cosine similarity between a query and an abstract for the abstract to count as relevant.
 * Short queries against abstracts rarely exceed 0.5 with MiniLM (the median is about 0.25), so the
 * earlier cut-off of 0.6 on 1/(1+d^2), which equals a cosine of 0.67, kept nothing.
 */
export const DEFAULT_RELEVANCE_THRESHOLD = 0.30;

/** Brute-force nearest-neighbour search over unit vectors (squared L2 distance, like FAISS IndexFlatL2). */
export class DiversityAwareVectorStore {
    constructor(embedder) {
        this.embedder = embedder;
        this.documents = [];
        this.embeddings = [];
    }

    clear() {
        this.documents = [];
        this.embeddings = [];
    }

    async addDocuments(documents) {
        if (!documents.length) return;
        const texts = documents.map((doc) => {
            let t = `${doc.title}. ${doc.abstract}`;
            if (doc.full_text) t += ` ${doc.full_text.slice(0, 2000)}`;
            return t;
        });
        const vectors = await this.embedder.embed(texts);
        this.embeddings.push(...vectors);
        this.documents.push(...documents);
    }

    static squaredL2(a, b) {
        let sum = 0;
        for (let i = 0; i < a.length; i++) { const d = a[i] - b[i]; sum += d * d; }
        return sum;
    }

    static dot(a, b) {
        let sum = 0;
        for (let i = 0; i < a.length; i++) sum += a[i] * b[i];
        return sum;
    }

    adaptK(query, baseK) {
        const lower = query.toLowerCase();
        const terms = ['viability', 'lethal', 'compensatory', 'compensation', 'phenotype', 'knockout', 'essential'];
        const score = terms.filter((t) => lower.includes(t)).length;
        if (score >= 2) return Math.min(baseK * 2, 20);
        if (score === 1) return Math.min(Math.trunc(baseK * 1.5), 15);
        return baseK;
    }

    async search(query, { k = 10, relevanceThreshold = DEFAULT_RELEVANCE_THRESHOLD, diversityWeight = 0.3, contextAware = true } = {}) {
        if (!this.documents.length) return [];
        if (contextAware) k = this.adaptK(query, k);

        const [queryVector] = await this.embedder.embed([query]);
        const searchK = Math.min(k * 3, this.documents.length);

        const ranked = this.embeddings
            .map((vector, index) => ({ index, distance: DiversityAwareVectorStore.squaredL2(queryVector, vector) }))
            .sort((a, b) => a.distance - b.distance || a.index - b.index)
            .slice(0, searchK);

        const candidates = [];
        for (const { index, distance } of ranked) {
            const similarity = 1.0 - distance / 2.0;   // cosine similarity of unit vectors
            if (similarity >= relevanceThreshold) candidates.push({ doc: this.documents[index], score: similarity, index });
        }
        if (!candidates.length) return [];

        const selected = diversityWeight > 0 && candidates.length > k
            ? this._mmr(candidates, k, diversityWeight)
            : candidates.slice(0, k);
        return selected.map(({ doc, score }) => ({ doc, score }));
    }

    /** Maximal marginal relevance: lambda * relevance - (1 - lambda) * similarity to what is already chosen. */
    _mmr(candidates, k, lambda) {
        const selected = [];
        const remaining = [...candidates];
        while (selected.length < k && remaining.length) {
            if (!selected.length) {
                let best = remaining[0];
                for (const c of remaining) if (c.score > best.score) best = c;
                selected.push(best);
                remaining.splice(remaining.indexOf(best), 1);
            } else {
                let best = null;
                let bestScore = -Infinity;
                for (const c of remaining) {
                    let maxSim = -Infinity;
                    for (const s of selected) {
                        maxSim = Math.max(maxSim, DiversityAwareVectorStore.dot(this.embeddings[s.index], this.embeddings[c.index]));
                    }
                    const mmr = lambda * c.score - (1 - lambda) * maxSim;
                    if (mmr > bestScore) { bestScore = mmr; best = c; }
                }
                selected.push(best);
                remaining.splice(remaining.indexOf(best), 1);
            }
        }
        return selected;
    }
}

// ---------------------------------------------------------------- phenotype extraction

const PHENOTYPE_PATTERNS = {
    lethality: [
        '\\blethal\\b', '\\blethality\\b', 'embryonic\\s+lethal', 'perinatal\\s+lethal', 'postnatal\\s+lethal', 'prenatal\\s+lethal',
        'early\\s+lethal', 'late\\s+lethal', 'neonatal\\s+lethal', '\\bdeath\\b', '\\bmortality\\b', '\\bsurvival\\b',
        'non-viable', 'inviable', 'sterile', '\\bsterility\\b',
    ],
    development: [
        'growth\\s+defect', 'developmental\\s+defect', 'morphogenetic\\s+defect', 'abnormal\\s+development', 'malformation',
        '\\bdysplasia\\b', 'congenital\\s+defect', 'birth\\s+defect', 'teratogenic', 'growth\\s+retardation',
        'developmental\\s+delay', 'organogenesis\\s+defect',
    ],
    behavior: [
        'behavioral\\s+defect', 'locomotion\\s+defect', 'motor\\s+defect', 'movement\\s+defect', 'coordination\\s+defect',
        'locomotor\\s+defect', 'activity\\s+defect', 'behavioral\\s+abnormality', 'neurological\\s+defect',
    ],
    physiology: [
        'metabolic\\s+defect', 'cardiac\\s+defect', 'cardiovascular\\s+defect', 'respiratory\\s+defect', 'neurological\\s+defect',
        'cognitive\\s+defect', 'immune\\s+defect', 'reproductive\\s+defect', 'sensory\\s+defect', 'vision\\s+defect',
        'hearing\\s+defect', 'digestive\\s+defect',
    ],
};

const SEVERITY_INDICATORS = {
    LETHAL: [
        '\\blethal\\b', '\\blethality\\b', 'embryonic\\s+lethal', 'perinatal\\s+lethal', 'postnatal\\s+lethal', 'early\\s+lethal',
        '100%\\s+lethal', 'complete\\s+lethality', 'fully\\s+lethal', 'non-viable', 'inviable',
        '\\bdie[sd]?\\b', '(?:embryonic|perinatal|postnatal|neonatal|early|premature)\\s+(?:death|mortality|demise)',
        'fail(?:s|ed)?\\s+to\\s+survive',
    ],
    SEVERE: [
        '\\bsevere\\b', '\\bsevere\\s+defect\\b', 'major\\s+defect', 'profound\\s+impairment', 'significant\\s+defect',
        'substantial\\s+defect', 'extreme\\s+phenotype', 'drastic\\s+effect', 'dramatic\\s+change',
    ],
    MODERATE: [
        '\\bmoderate\\b', '\\bintermediate\\b', 'reduced\\s+fitness', 'partial\\s+defect', 'mild\\s+defect',
        'minor\\s+impairment', 'suboptimal', 'compromised',
    ],
    MILD: [
        '\\bmild\\b', '\\bsubtle\\b', '\\bminor\\b', '\\bslight\\b', '\\bsmall\\s+change\\b', '\\bminimal\\b', '\\bweak\\s+phenotype\\b',
        '(?<!non-)(?<!not\\s)\\bviable\\b', '\\bfertile\\b', 'normal\\s+(?:development|lifespan|viability)',
        'no\\s+(?:obvious|overt|apparent|detectable|gross)\\s+(?:phenotype|abnormalit)', '\\btolerated\\b',
    ],
};

const COMPENSATORY_PATTERNS = [
    'compensat(?:e|ion|ory)', 'redundancy', 'redundant\\s+gene', 'genetic\\s+buffering', 'paralog', 'paralogous',
    'backup\\s+gene', 'functional\\s+redundancy', 'gene\\s+duplication', 'homeostatic\\s+mechanism', 'feedback\\s+mechanism',
];

const LETHALITY_STAGES = [
    ['embryonic\\s+lethal|embryo\\s+lethal|prenatal\\s+lethal|e\\d+\\.\\d', 'Embryonic'],
    ['perinatal\\s+lethal|perinatal\\s+death|birth\\s+lethal', 'Perinatal'],
    ['postnatal\\s+lethal|adult\\s+lethal|juvenile\\s+lethal|p\\d+\\.\\d', 'Postnatal'],
    ['larval\\s+(?:stage\\s+)?(?:lethal|death)|l\\d+\\s+lethal', 'Larval'],
    ['neonatal\\s+lethal|newborn\\s+lethal', 'Neonatal'],
];

// "synthetic lethal", "non-lethal" and "sublethal" do not say the gene itself is lethal when deleted
const NOT_LETHAL_PHRASES = /(?:synthetic[\s-]+lethal(?:ity)?|non-?lethal|sub-?lethal)/gi;
const NOT_LETHAL_PREFIX = /(?:synthetic[\s-]+|non-?|sub-?)$/i;

// a sentence is evidence about deleting a gene when it names the gene AND describes losing it
const LOSS_OF_FUNCTION = new RegExp(
    'knock-?out|knock-?down|\\bko\\b|\\bnull\\b|[-\u2212]/[-\u2212]|deficien|deletion|deleted|\\bablat|disrupt'
    + '|loss[\\s-]of|\\black(?:s|ing|ed)?\\b|inactivat|homozygous|mutant|essential', 'i');
// sentences about a DRUG acting on the gene product describe a treatment, not deleting the gene
const DRUG_CONTEXT = /inhibitor|inhibition|inhibiting|\bparpi?\b|olaparib|talazoparib|niraparib|rucaparib|trapping|therap|clinical|resistan/i;
const SENTENCE_BREAK = /(?<=[.!?])\s+(?=[A-Z0-9(\[])/;

const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * Sentences that mention the gene (by symbol or an alias such as its protein name) and, unless
 * requireLoss is false, describe losing it (knockout, null, deficient, deletion, -/- ...).
 */
export function geneEvidenceSentences(content, symbol, { requireLoss = true, aliases = [] } = {}) {
    if (!content || !symbol) return [];
    const names = [symbol, ...aliases.map((a) => (a || '').trim()).filter((a) => a.length >= 8)];
    const mention = new RegExp(`(?<![A-Za-z0-9])(?:${names.map(escapeRegExp).join('|')})(?![A-Za-z0-9])`, 'i');
    const sentences = [];
    for (const sentence of content.split(SENTENCE_BREAK)) {
        if (!mention.test(sentence)) continue;
        if (requireLoss && (!LOSS_OF_FUNCTION.test(sentence) || DRUG_CONTEXT.test(sentence))) continue;
        sentences.push(sentence.trim());
    }
    return sentences;
}

export function extractPhenotypesFromText(content) {
    if (!content) return [];
    const lower = content.toLowerCase();
    const phenotypes = [];
    for (const [category, patterns] of Object.entries(PHENOTYPE_PATTERNS)) {
        for (const pattern of patterns) {
            for (const match of lower.matchAll(new RegExp(pattern, 'gi'))) {
                if (match[0].includes('lethal') && NOT_LETHAL_PREFIX.test(lower.slice(Math.max(0, match.index - 12), match.index))) continue;
                const start = Math.max(0, match.index - 100);
                const end = Math.min(content.length, match.index + match[0].length + 100);
                phenotypes.push({
                    category,
                    term: match[0],
                    position: [match.index, match.index + match[0].length],
                    context: content.slice(start, end).trim(),
                    evidence_quality: content.length > 500 ? 'high' : 'medium',
                });
            }
        }
    }
    return phenotypes;
}

export function extractCompensatoryMechanisms(content) {
    if (!content) return [];
    const lower = content.toLowerCase();
    const found = [];
    for (const pattern of COMPENSATORY_PATTERNS) {
        for (const match of lower.matchAll(new RegExp(pattern, 'gi'))) {
            const start = Math.max(0, match.index - 150);
            const end = Math.min(content.length, match.index + match[0].length + 150);
            found.push({
                term: match[0],
                context: content.slice(start, end).trim(),
                confidence: match[0].includes('compensat') ? 'high' : 'medium',
            });
        }
    }
    return found;
}

/** Highest severity with at least one indicator wins. */
export function classifySeverity(phenotypes, content = '') {
    if (!phenotypes.length && !content) return [SEVERITY.UNKNOWN, 'No phenotype data available'];

    let combined = content.toLowerCase().replace(NOT_LETHAL_PHRASES, ' ');
    for (const p of phenotypes) combined += ' ' + (p.term || '').toLowerCase();

    const counts = {};
    for (const [severity, patterns] of Object.entries(SEVERITY_INDICATORS)) {
        counts[severity] = patterns.reduce((n, pattern) => n + (combined.match(new RegExp(pattern, 'gi')) || []).length, 0);
    }
    if (counts.LETHAL > 0) return [SEVERITY.LETHAL, `Lethality terms detected (${counts.LETHAL} instances)`];
    if (counts.SEVERE > 0) return [SEVERITY.SEVERE, `Severe phenotype terms detected (${counts.SEVERE} instances)`];
    if (counts.MODERATE > 0) return [SEVERITY.MODERATE, `Moderate phenotype terms detected (${counts.MODERATE} instances)`];
    if (counts.MILD > 0) return [SEVERITY.MILD, `Mild phenotype terms detected (${counts.MILD} instances)`];
    return [SEVERITY.UNKNOWN, 'No clear severity indicators found in literature'];
}

export function detectLethalityStage(content) {
    if (!content) return null;
    const lower = content.toLowerCase();
    for (const [pattern, stage] of LETHALITY_STAGES) {
        if (new RegExp(pattern, 'i').test(lower)) return stage;
    }
    return null;
}

export function calculateConfidenceScore(publications, phenotypes, hasFullText) {
    if (!publications.length) return [0.1, 'No publication evidence available'];

    const n = publications.length;
    const pubScore = n >= 20 ? 0.4 : n >= 10 ? 0.3 : n >= 5 ? 0.2 : 0.1;
    const highQuality = publications.filter((p) => p.evidence_quality === 'high').length;
    const evidenceScore = Math.min(0.3, highQuality * 0.1);
    const fullTextScore = hasFullText ? 0.2 : 0.0;
    const phenotypeScore = Math.min(0.2, phenotypes.length * 0.05);
    const total = Math.min(1.0, pubScore + evidenceScore + fullTextScore + phenotypeScore);

    const quality = total > 0.7 ? 'High' : total > 0.4 ? 'Medium' : 'Low';
    return [total,
        `Confidence based on ${n} publications (${highQuality} with full text), ${phenotypes.length} phenotype terms extracted. Evidence quality: ${quality}.`];
}

// ---------------------------------------------------------------- the predictor

export class RagPhenotypePredictor {
    /**
     * @param {object} deps  { http, embedder: { embed(texts) -> Promise<number[][]> }, parseXml(text) -> Document,
     *                         ncbiApiKey?, ncbiEmail? }
     */
    constructor(deps) {
        this.deps = deps;
    }

    _queries(symbol, includeCompensatory) {
        const queries = [
            `${symbol} knockout phenotype`,
            `${symbol} mutant viability`,
            `${symbol} gene deletion effect`,
            `Is ${symbol} essential for survival?`,
        ];
        if (includeCompensatory) {
            queries.push(`${symbol} compensatory mechanism`, `${symbol} genetic redundancy`, `${symbol} paralog compensation`);
        }
        return queries;
    }

    async predict(symbol, taxid = '9606', includeCompensatory = true, aliases = []) {
        const miner = new LiteratureMiner(this.deps);
        const store = new DiversityAwareVectorStore(this.deps.embedder);

        const searchTypes = ['knockout', 'phenotype', 'viability', 'mouse_knockout'];
        if (includeCompensatory) searchTypes.push('compensatory');

        const seen = new Set();
        const publications = [];
        for (const type of searchTypes) {
            for (const pub of await miner.searchPubmed(symbol, type, 30)) {
                if (!seen.has(pub.pmid)) { seen.add(pub.pmid); publications.push(pub); }
            }
        }

        if (!publications.length) {
            const failed = miner.errors.length > 0;
            return {
                severity: SEVERITY.UNKNOWN, risk_level: RISK.UNKNOWN, confidence_score: 0.1,
                predicted_phenotypes: [], supporting_evidence: [], lethality_stage: null,
                compensatory_mechanisms: [],
                confidence_reasoning: failed
                    ? `The literature search failed (${miner.errors[0]}); this says nothing about the gene`
                    : 'No literature found for this gene',
            };
        }

        await store.addDocuments(publications);

        const relevant = [];
        for (const query of this._queries(symbol, includeCompensatory)) {
            relevant.push(...await store.search(query, { k: 5, relevanceThreshold: DEFAULT_RELEVANCE_THRESHOLD, diversityWeight: 0.3, contextAware: true }));
        }
        const seenDocs = new Set();
        const unique = [];
        for (const item of relevant) {
            if (!seenDocs.has(item.doc.pmid)) { seenDocs.add(item.doc.pmid); unique.push(item); }
        }

        const allPhenotypes = [];
        const allCompensatory = [];
        const supporting = [];
        const evidenceTexts = [];
        let hasFullText = false;
        for (const { doc, score } of unique) {
            const parts = [doc.title, doc.abstract];
            if (doc.full_text) { parts.push(doc.full_text); hasFullText = true; }
            const content = parts.filter(Boolean).join(' ');

            // only sentences about losing THIS gene count as evidence
            const evidenceText = geneEvidenceSentences(content, symbol, { aliases }).join(' ');
            const geneText = geneEvidenceSentences(content, symbol, { requireLoss: false, aliases }).join(' ');
            evidenceTexts.push(evidenceText);

            const phenotypes = extractPhenotypesFromText(evidenceText);
            allPhenotypes.push(...phenotypes);
            allCompensatory.push(...extractCompensatoryMechanisms(geneText));
            supporting.push({
                pmid: doc.pmid, pmcid: doc.pmcid, title: doc.title, similarity_score: score,
                phenotypes_extracted: phenotypes.map((p) => p.term),
                evidence_quality: doc.evidence_quality,
                publication_date: doc.publication_date, journal: doc.journal,
            });
        }

        const combined = evidenceTexts.join(' ');
        let [severity, severityReasoning] = classifySeverity(allPhenotypes, combined);
        if (!combined.trim()) {
            severityReasoning = `None of the ${publications.length} retrieved papers has a sentence describing the effect of losing ${symbol}`;
        }
        const riskLevel = RISK_FOR_SEVERITY[severity] || RISK.UNKNOWN;
        const lethalityStage = severity === SEVERITY.LETHAL ? detectLethalityStage(combined) : null;
        const [confidence, confidenceReasoning] = calculateConfidenceScore(publications, allPhenotypes, hasFullText);

        return {
            severity,
            risk_level: riskLevel,
            confidence_score: confidence,
            predicted_phenotypes: [...new Set(allPhenotypes.map((p) => p.term))],
            supporting_evidence: supporting,
            lethality_stage: lethalityStage,
            compensatory_mechanisms: [...new Set(allCompensatory.map((m) => m.term))],
            confidence_reasoning: `${confidenceReasoning} ${severityReasoning}`,
        };
    }
}

// ---------------------------------------------------------------- browser embedding model

/**
 * Load the MiniLM model with transformers.js and return { embed(texts) }.
 * The model (about 90 MB) is downloaded once and then kept by the browser.
 * `loader` returns the transformers.js module (a CDN import in the page, an npm import in Node).
 */
export async function createTransformersEmbedder(loader, { onStatus = null, dtype = 'fp32' } = {}) {
    const transformers = await loader();
    if (onStatus) onStatus('Loading the phenotype model (about 90 MB, downloaded once)...');
    const extractor = await transformers.pipeline('feature-extraction', MODEL_ID, { dtype });
    if (onStatus) onStatus('Phenotype model ready');
    return {
        async embed(texts) {
            const vectors = [];
            // small batches keep the page responsive
            for (let i = 0; i < texts.length; i += 8) {
                const output = await extractor(texts.slice(i, i + 8), { pooling: 'mean', normalize: true });
                const [rows, dim] = output.dims;
                for (let r = 0; r < rows; r++) vectors.push(Array.from(output.data.slice(r * dim, (r + 1) * dim)));
            }
            return vectors;
        },
    };
}
