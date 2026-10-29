/**
 * Phenotype prediction using the Kimi (Moonshot) LLM API.
 *
 * This is an optional, user-key-powered predictor. When a key is supplied the browser
 * sends PubMed abstracts to Kimi and asks it to classify the knockout phenotype.
 * The key never leaves the user's browser; the request goes directly to Moonshot's API.
 */

import { LiteratureMiner, RISK, SEVERITY } from './rag.js';

const KIMI_API_URL = 'https://api.moonshot.ai/v1/chat/completions';
const DEFAULT_MODEL = 'kimi-k2-0905-preview';
const MAX_PAPERS = 6;
const MAX_ABSTRACT_LENGTH = 2500;
const MAX_TOKENS = 1024;

const VALID_SEVERITY = new Set(Object.values(SEVERITY));
const VALID_RISK = new Set(Object.values(RISK));
const RISK_FOR_SEVERITY = {
    [SEVERITY.LETHAL]: RISK.CRITICAL,
    [SEVERITY.SEVERE]: RISK.HIGH,
    [SEVERITY.MODERATE]: RISK.MEDIUM,
    [SEVERITY.MILD]: RISK.LOW,
    [SEVERITY.UNKNOWN]: RISK.UNKNOWN,
};

function unknownPrediction(reason) {
    return {
        severity: SEVERITY.UNKNOWN,
        risk_level: RISK.UNKNOWN,
        confidence_score: 0.1,
        predicted_phenotypes: [],
        supporting_evidence: [],
        lethality_stage: null,
        compensatory_mechanisms: [],
        confidence_reasoning: reason || 'No literature-based prediction could be made',
    };
}

function normalizePrediction(raw) {
    const severity = VALID_SEVERITY.has(raw.severity) ? raw.severity : SEVERITY.UNKNOWN;
    const risk_level = VALID_RISK.has(raw.risk_level) ? raw.risk_level : (RISK_FOR_SEVERITY[severity] || RISK.UNKNOWN);
    return {
        severity,
        risk_level,
        confidence_score: typeof raw.confidence_score === 'number' ? Math.max(0, Math.min(1, raw.confidence_score)) : 0.5,
        predicted_phenotypes: Array.isArray(raw.predicted_phenotypes) ? raw.predicted_phenotypes : [],
        supporting_evidence: Array.isArray(raw.supporting_evidence) ? raw.supporting_evidence : [],
        lethality_stage: raw.lethality_stage || null,
        compensatory_mechanisms: Array.isArray(raw.compensatory_mechanisms) ? raw.compensatory_mechanisms : [],
        confidence_reasoning: raw.reasoning || 'Phenotype inferred by Kimi from PubMed abstracts',
    };
}

function buildPrompt(symbol, taxid, aliases, publications) {
    const aliasText = aliases.length ? `Aliases used in papers: ${aliases.join(', ')}.` : '';
    const abstractList = publications.map((pub, i) => {
        const title = pub.title || 'Untitled';
        const abstract = (pub.abstract || '').slice(0, MAX_ABSTRACT_LENGTH);
        return `[${i + 1}] Title: ${title}\nAbstract: ${abstract}`;
    }).join('\n\n');

    return `You are a biomedical literature analyst. A researcher wants to know the likely phenotype of knocking out the gene ${symbol} (NCBI TaxID ${taxid}). ${aliasText}

Read the PubMed abstracts below. Focus only on sentences that describe the effect of knocking out, deleting, mutating, or inactivating ${symbol}. Ignore drug-inhibition studies, synthetic lethality with other genes, and papers where ${symbol} is only mentioned in passing.

Return exactly one JSON object with this structure:
{
  "severity": "LETHAL" | "SEVERE" | "MODERATE" | "MILD" | "UNKNOWN",
  "risk_level": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN",
  "confidence_score": 0.0 to 1.0,
  "predicted_phenotypes": ["short phenotype term", ...],
  "lethality_stage": "Embryonic" | "Perinatal" | "Postnatal" | "Larval" | "Neonatal" | null,
  "compensatory_mechanisms": ["term", ...],
  "reasoning": "one-sentence explanation"
}

Severity guide:
- LETHAL: knockout causes death, non-viability, or complete lethality.
- SEVERE: major developmental or physiological defects, but not universally lethal.
- MODERATE: partial defects or reduced fitness.
- MILD: subtle or no observable phenotype.
- UNKNOWN: the abstracts do not clearly describe the knockout effect.

Risk mapping: LETHAL→CRITICAL, SEVERE→HIGH, MODERATE→MEDIUM, MILD→LOW, UNKNOWN→UNKNOWN.
Confidence score: higher when multiple independent papers agree and the evidence is direct.

Abstracts:
${abstractList}`;
}

async function callKimi(prompt, apiKey, model, fetchImpl = globalThis.fetch.bind(globalThis)) {
    const response = await fetchImpl(KIMI_API_URL, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
            model,
            messages: [
                { role: 'system', content: 'You return only valid JSON.' },
                { role: 'user', content: prompt },
            ],
            temperature: 0.1,
            max_tokens: MAX_TOKENS,
            response_format: { type: 'json_object' },
        }),
    });

    const text = await response.text().catch(() => '');
    const ok = response.status >= 200 && response.status < 300;
    if (!ok) {
        throw new Error(`Kimi API returned HTTP ${response.status}: ${text.slice(0, 200)}`);
    }

    const data = JSON.parse(text);
    const content = data.choices?.[0]?.message?.content || '';
    if (!content.trim()) throw new Error('Kimi response had no content');

    // The model may wrap JSON in markdown; try to extract the first JSON object.
    const jsonMatch = content.match(/\{[\s\S]*\}/);
    if (!jsonMatch) throw new Error('Kimi response did not contain a JSON object');
    return JSON.parse(jsonMatch[0]);
}

export class KimiPhenotypePredictor {
    /**
     * @param {object} deps
     *   http: HttpClient (used for PubMed calls; its fetchImpl is used for Kimi if available)
     *   parseXml(text) -> Document
     *   apiKey: the user's Kimi API key
     *   ncbiApiKey?: NCBI API key for PubMed rate limits
     *   model?: Kimi model name
     */
    constructor({ http, parseXml, apiKey, ncbiApiKey = '', model = DEFAULT_MODEL }) {
        this.http = http;
        this.parseXml = parseXml;
        this.apiKey = apiKey;
        this.ncbiApiKey = ncbiApiKey;
        this.model = model;
        this.fetchImpl = http && http.fetchImpl ? http.fetchImpl.bind(http) : globalThis.fetch.bind(globalThis);
    }

    async predict(symbol, taxid = '9606', includeCompensatory = true, aliases = []) {
        const miner = new LiteratureMiner({
            http: this.http,
            parseXml: this.parseXml,
            ncbiApiKey: this.ncbiApiKey,
        });

        const searchTypes = ['knockout', 'phenotype', 'viability', 'mouse_knockout'];
        if (includeCompensatory) searchTypes.push('compensatory');

        const seen = new Set();
        const publications = [];
        for (const type of searchTypes) {
            for (const pub of await miner.searchPubmed(symbol, type, 20)) {
                if (!seen.has(pub.pmid)) {
                    seen.add(pub.pmid);
                    publications.push(pub);
                }
            }
        }

        if (!publications.length) {
            return unknownPrediction(miner.errors.length
                ? `The literature search failed (${miner.errors[0]}); no papers could be checked`
                : `No PubMed papers found for ${symbol}`);
        }

        const selected = publications.slice(0, MAX_PAPERS);
        const prompt = buildPrompt(symbol, taxid, aliases, selected);
        const raw = await callKimi(prompt, this.apiKey, this.model, this.fetchImpl);
        const prediction = normalizePrediction(raw);

        // Attach lightweight supporting evidence from the papers we sent.
        if (!prediction.supporting_evidence || !prediction.supporting_evidence.length) {
            prediction.supporting_evidence = selected.map((pub) => ({
                pmid: pub.pmid,
                title: pub.title,
                publication_date: pub.publication_date,
                journal: pub.journal,
                evidence_quality: 'high',
            }));
        }
        return prediction;
    }
}
