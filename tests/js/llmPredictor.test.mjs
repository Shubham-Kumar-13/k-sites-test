import test from 'node:test';
import assert from 'node:assert/strict';
import { DOMParser } from 'linkedom';

import { HttpClient, MemoryCache } from '../../webapp/static/js/engine/http.js';
import { LlmPhenotypePredictor, LLM_PROVIDERS, supportedLlmProviders } from '../../webapp/static/js/engine/llmPredictor.js';
import { RISK, SEVERITY } from '../../webapp/static/js/engine/rag.js';
import { HybridPhenotypePredictor } from '../../webapp/static/js/engine/hybridPredictor.js';

const parseXml = (text) => new DOMParser().parseFromString(text, 'text/xml');

function pubmedXml(pmids) {
    const articles = pmids.map((pmid, i) => `
        <PubmedArticle>
            <MedlineCitation>
                <PMID>${pmid}</PMID>
                <Article>
                    <ArticleTitle>Knockout of TEST${i + 1}</ArticleTitle>
                    <Abstract><AbstractText>Mice lacking TEST${i + 1} die at E8.5; the knockout is embryonic lethal.</AbstractText></Abstract>
                    <Journal><Title>Test Journal</Title></Journal>
                    <AuthorList><Author><LastName>Smith</LastName></Author></AuthorList>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
    `).join('');
    return `<?xml version="1.0"?><PubmedArticleSet>${articles}</PubmedArticleSet>`;
}

function makeHttp(responseFactory, { status = 200 } = {}) {
    const cache = new MemoryCache();
    const fetchImpl = async (url, options) => {
        if (url.includes('eutils.ncbi.nlm.nih.gov')) {
            if (url.includes('esearch.fcgi')) {
                return { status: 200, text: async () => JSON.stringify({ esearchresult: { idlist: ['12345', '12346'] } }), headers: { get: () => null } };
            }
            if (url.includes('efetch.fcgi')) {
                return { status: 200, text: async () => pubmedXml(['12345', '12346']), headers: { get: () => null } };
            }
        }
        const response = typeof responseFactory === 'function' ? responseFactory(url, options) : responseFactory;
        return {
            status,
            text: async () => typeof response === 'string' ? response : JSON.stringify(response),
            headers: { get: () => null },
        };
    };
    return new HttpClient({ fetchImpl, sleep: async () => {}, rateLimits: {}, retries: 0, cache });
}

function openAiJson(payload) {
    return {
        choices: [{
            message: {
                content: JSON.stringify(payload),
            },
        }],
    };
}

function anthropicJson(payload) {
    return {
        content: [{
            text: JSON.stringify(payload),
        }],
    };
}

test('OpenAI predictor parses a lethal JSON response', async () => {
    const http = makeHttp(openAiJson({
        severity: 'LETHAL',
        risk_level: 'CRITICAL',
        confidence_score: 0.85,
        predicted_phenotypes: ['embryonic lethality'],
        lethality_stage: 'Embryonic',
        compensatory_mechanisms: [],
        reasoning: 'Abstracts describe embryonic lethality.',
    }));
    const predictor = new LlmPhenotypePredictor({ http, parseXml, provider: 'openai', apiKey: 'sk-test' });

    const result = await predictor.predict('TEST1', '10090');

    assert.equal(result.severity, SEVERITY.LETHAL);
    assert.equal(result.risk_level, RISK.CRITICAL);
    assert.ok(result.confidence_score > 0.8);
    assert.equal(result.lethality_stage, 'Embryonic');
    assert.ok(result.supporting_evidence.length > 0);
});

test('Anthropic predictor uses the Messages API format', async () => {
    let capturedUrl = null;
    let capturedBody = null;
    const http = makeHttp((url, options) => {
        capturedUrl = url;
        capturedBody = JSON.parse(options.body);
        return anthropicJson({
            severity: 'MILD',
            risk_level: 'LOW',
            confidence_score: 0.6,
            predicted_phenotypes: ['viable'],
            lethality_stage: null,
            compensatory_mechanisms: [],
            reasoning: 'No severe phenotype reported.',
        });
    });
    const predictor = new LlmPhenotypePredictor({ http, parseXml, provider: 'anthropic', apiKey: 'sk-ant-test' });

    const result = await predictor.predict('TEST1', '10090');

    assert.equal(capturedUrl, LLM_PROVIDERS.anthropic.apiUrl);
    assert.equal(capturedBody.model, LLM_PROVIDERS.anthropic.defaultModel);
    assert.equal(capturedBody.system, 'You return only valid JSON.');
    assert.equal(capturedBody.messages.length, 1);
    assert.equal(capturedBody.messages[0].role, 'user');
    assert.equal(result.severity, SEVERITY.MILD);
    assert.equal(result.risk_level, RISK.LOW);
});

test('Kimi predictor extracts JSON wrapped in markdown', async () => {
    const http = makeHttp({
        choices: [{
            message: {
                content: '```json\n' + JSON.stringify({
                    severity: 'MILD',
                    risk_level: 'LOW',
                    confidence_score: 0.6,
                    predicted_phenotypes: ['viable'],
                    lethality_stage: null,
                    compensatory_mechanisms: [],
                    reasoning: 'No severe phenotype reported.',
                }) + '\n```',
            },
        }],
    });
    const predictor = new LlmPhenotypePredictor({ http, parseXml, provider: 'kimi', apiKey: 'sk-test' });

    const result = await predictor.predict('TEST1', '10090');

    assert.equal(result.severity, SEVERITY.MILD);
    assert.equal(result.risk_level, RISK.LOW);
});

test('LLM predictor throws when the API fails', async () => {
    const http = makeHttp('unauthorized', { status: 401 });
    const predictor = new LlmPhenotypePredictor({ http, parseXml, provider: 'kimi', apiKey: 'sk-bad' });

    await assert.rejects(
        () => predictor.predict('TEST1', '10090'),
        /401/,
    );
});

test('LLM predictor returns UNKNOWN when no papers are found', async () => {
    const cache = new MemoryCache();
    const fetchImpl = async (url) => {
        if (url.includes('esearch.fcgi')) {
            return { status: 200, text: async () => JSON.stringify({ esearchresult: { idlist: [] } }), headers: { get: () => null } };
        }
        return { status: 599, text: async () => 'not mocked', headers: { get: () => null } };
    };
    const http = new HttpClient({ fetchImpl, sleep: async () => {}, rateLimits: {}, retries: 0, cache });
    const predictor = new LlmPhenotypePredictor({ http, parseXml, provider: 'openai', apiKey: 'sk-test' });

    const result = await predictor.predict('NOPAPERS', '10090');

    assert.equal(result.severity, SEVERITY.UNKNOWN);
    assert.ok(result.confidence_reasoning.includes('No PubMed papers'));
});

test('Hybrid predictor falls back to MiniLM when the LLM fails', async () => {
    const http = makeHttp('unauthorized', { status: 401 });

    const miniLmPrediction = {
        severity: SEVERITY.MILD,
        risk_level: RISK.LOW,
        confidence_score: 0.5,
        predicted_phenotypes: ['viable'],
        supporting_evidence: [],
        lethality_stage: null,
        compensatory_mechanisms: [],
        confidence_reasoning: 'MiniLM fallback result',
    };
    const miniLmFactory = async () => ({ predict: async () => miniLmPrediction });

    const hybrid = new HybridPhenotypePredictor({
        miniLmFactory,
        http,
        parseXml,
        ncbiApiKey: '',
        llmProvider: 'openai',
        llmApiKey: 'sk-bad',
        onStatus: () => {},
    });

    const result = await hybrid.predict('TEST1', '10090');

    assert.equal(result.severity, SEVERITY.MILD);
    assert.ok(result.confidence_reasoning.includes('LLM API failed'));
    assert.ok(result.confidence_reasoning.includes('MiniLM fallback result'));
});

test('supportedLlmProviders lists all six providers', () => {
    const providers = supportedLlmProviders();
    const ids = providers.map((p) => p.id);
    assert.deepEqual(ids.sort(), ['anthropic', 'deepseek', 'grok', 'kimi', 'openai', 'qwen']);
});
