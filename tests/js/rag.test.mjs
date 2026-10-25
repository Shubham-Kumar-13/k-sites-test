// Phenotype prediction from literature: the pure logic, with a fake embedding model and fake PubMed.

import test from 'node:test';
import assert from 'node:assert/strict';
import { DOMParser } from 'linkedom';

import {
    DEFAULT_RELEVANCE_THRESHOLD, DiversityAwareVectorStore, RagPhenotypePredictor, calculateConfidenceScore, classifySeverity,
    detectLethalityStage, extractCompensatoryMechanisms, extractPhenotypesFromText, geneEvidenceSentences, parsePubmedArticle,
} from '../../webapp/static/js/engine/rag.js';
import { HttpClient } from '../../webapp/static/js/engine/http.js';

const parseXml = (text) => new DOMParser().parseFromString(text, 'text/xml');

// ------------------------------------------------------------------ PubMed XML

const article = (pmid, title, abstract) =>
    `<PubmedArticle><MedlineCitation><PMID>${pmid}</PMID><Article><Journal><Title>J Test</Title><JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue></Journal>`
    + `<ArticleTitle>${title}</ArticleTitle><Abstract><AbstractText>${abstract}</AbstractText></Abstract>`
    + `<AuthorList><Author><LastName>Smith</LastName><ForeName>Ann</ForeName></Author></AuthorList></Article></MedlineCitation>`
    + `<PubmedData><ArticleIdList><ArticleId IdType="doi">10.1/x</ArticleId><ArticleId IdType="pmc">PMC1</ArticleId></ArticleIdList></PubmedData></PubmedArticle>`;

test('a PubMed article keeps the text behind inline markup', () => {
    const doc = parseXml(`<PubmedArticleSet>${article('1', 'Loss of <i>Pold1</i> causes lethality', 'Mice lacking <i>Pold1</i> die at E8.5; heterozygotes are viable.')}</PubmedArticleSet>`);

    const record = parsePubmedArticle(doc.querySelector('PubmedArticle'));

    assert.equal(record.pmid, '1');
    assert.equal(record.title, 'Loss of Pold1 causes lethality');
    assert.equal(record.abstract, 'Mice lacking Pold1 die at E8.5; heterozygotes are viable.');
    assert.equal(record.journal, 'J Test');
    assert.equal(record.publication_date, '2020');
    assert.equal(record.doi, '10.1/x');
    assert.equal(record.pmcid, 'PMC1');
    assert.deepEqual(record.authors, ['Ann Smith']);
});

test('structured abstract sections are joined', () => {
    const doc = parseXml('<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>2</PMID><Article><ArticleTitle>T</ArticleTitle>'
        + '<Abstract><AbstractText Label="A">First.</AbstractText><AbstractText Label="B">Second <sub>x</sub> part.</AbstractText></Abstract>'
        + '</Article></MedlineCitation></PubmedArticle></PubmedArticleSet>');

    assert.equal(parsePubmedArticle(doc.querySelector('PubmedArticle')).abstract, 'First. Second x part.');
});

// ------------------------------------------------------------------ evidence sentences

test('only sentences that name the gene and describe losing it count as evidence', () => {
    const text = 'Xrcc1-deficient mice die early in embryogenesis. Brca1 loss is embryonic lethal. XRCC1 is expressed in the nucleus. '
        + 'PARP inhibitors are lethal to cells lacking XRCC1 under treatment.';

    const sentences = geneEvidenceSentences(text, 'XRCC1');

    assert.deepEqual(sentences, ['Xrcc1-deficient mice die early in embryogenesis.']);
});

test('a protein name works as an alias for the symbol', () => {
    const text = 'Mice deficient in DNA polymerase beta die neonatally.';

    assert.equal(geneEvidenceSentences(text, 'POLB').length, 0);
    assert.equal(geneEvidenceSentences(text, 'POLB', { aliases: ['DNA polymerase beta'] }).length, 1);
    assert.equal(geneEvidenceSentences(text, 'POLB', { aliases: ['Pol beta'] }).length, 0);   // too short to be a safe alias
});

test('a gene symbol is not matched inside another word', () => {
    assert.equal(geneEvidenceSentences('The knockout of POLBX is lethal.', 'POLB').length, 0);
    assert.equal(geneEvidenceSentences('The POLB-/- knockout is lethal.', 'POLB').length, 1);
});

// ------------------------------------------------------------------ severity

test('synthetic lethality and non-lethal phrases do not make a gene lethal', () => {
    const synthetic = 'Parp1 loss is synthetic lethal with Brca1 deficiency; the non-lethal mutant is sublethal.';
    const phenotypes = extractPhenotypesFromText(synthetic);

    assert.ok(!phenotypes.some((p) => p.term.includes('lethal')));
    assert.equal(classifySeverity(phenotypes, synthetic)[0], 'UNKNOWN');
});

test('severity is the highest one that has any evidence', () => {
    assert.equal(classifySeverity([], 'embryonic lethal at E8.5')[0], 'LETHAL');
    assert.equal(classifySeverity([], 'mice die shortly after birth')[0], 'LETHAL');
    assert.equal(classifySeverity([], 'a severe defect in growth')[0], 'SEVERE');
    assert.equal(classifySeverity([], 'a moderate reduction')[0], 'MODERATE');
    assert.equal(classifySeverity([], 'the knockout mice are viable and fertile')[0], 'MILD');
    assert.equal(classifySeverity([], 'nothing to see here')[0], 'UNKNOWN');
    assert.equal(classifySeverity([], 'non-viable embryos')[0], 'LETHAL');            // "viable" must not count when negated
    assert.equal(classifySeverity([], 'embryos were not viable')[0], 'UNKNOWN');
    assert.equal(classifySeverity([], '')[1], 'No phenotype data available');
});

test('the lethality stage is read from the text', () => {
    assert.equal(detectLethalityStage('embryonic lethal at E12.5'), 'Embryonic');
    assert.equal(detectLethalityStage('perinatal death occurred'), 'Perinatal');
    assert.equal(detectLethalityStage('postnatal lethality in adults'), 'Postnatal');
    assert.equal(detectLethalityStage('larval stage death'), 'Larval');
    assert.equal(detectLethalityStage('neonatal lethal'), 'Neonatal');
    assert.equal(detectLethalityStage('no stage here'), null);
});

test('compensatory mechanisms are found', () => {
    const found = extractCompensatoryMechanisms('A paralog may compensate; there is functional redundancy.').map((m) => m.term);

    assert.ok(found.includes('paralog') && found.includes('redundancy'));
});

test('confidence grows with the number of papers and phenotype terms', () => {
    const papers = (n) => Array.from({ length: n }, () => ({ evidence_quality: 'unknown' }));
    const [few] = calculateConfidenceScore(papers(2), [], false);
    const [many] = calculateConfidenceScore(papers(25), Array(8).fill({}), false);

    assert.equal(calculateConfidenceScore([], [], false)[0], 0.1);
    assert.ok(many > few);
    assert.ok(many <= 1.0);
});

// ------------------------------------------------------------------ vector store

/** Three-dimensional toy embeddings: each topic word points along its own axis. */
const AXES = { lethal: [1, 0, 0], viable: [0, 1, 0], paralog: [0, 0, 1] };
const toyEmbedder = {
    async embed(texts) {
        return texts.map((t) => {
            const v = [0.05, 0.05, 0.05];
            for (const [word, axis] of Object.entries(AXES)) if (t.toLowerCase().includes(word)) axis.forEach((x, i) => { v[i] += x; });
            const norm = Math.hypot(...v);
            return v.map((x) => x / norm);
        });
    },
};
const doc = (pmid, text) => ({ pmid, title: text, abstract: '', full_text: null });

test('relevance is the cosine similarity and the default cut-off is realistic for short queries', async () => {
    const store = new DiversityAwareVectorStore(toyEmbedder);
    await store.addDocuments([doc('a', 'lethal embryos'), doc('b', 'viable adults'), doc('c', 'paralog redundancy')]);

    const hits = await store.search('lethal', { k: 5, relevanceThreshold: 0.5, diversityWeight: 0, contextAware: false });

    assert.deepEqual(hits.map((h) => h.doc.pmid), ['a']);
    assert.ok(hits[0].score > 0.9 && hits[0].score <= 1);
    assert.equal(DEFAULT_RELEVANCE_THRESHOLD, 0.30);
});

test('diverse selection picks a different document over a near duplicate', async () => {
    const store = new DiversityAwareVectorStore({
        async embed(texts) {   // 0 and 1 almost identical, 2 different
            const table = { zero: [1, 0], one: [0.99, 0.141], two: [0, 1], q: [0.8, 0.6] };
            return texts.map((t) => { const v = table[t.split('.')[0]]; const n = Math.hypot(...v); return v.map((x) => x / n); });
        },
    });
    await store.addDocuments([doc('0', 'zero'), doc('1', 'one'), doc('2', 'two')]);

    const hits = await store.search('q', { k: 2, relevanceThreshold: 0.1, diversityWeight: 0.3, contextAware: false });

    assert.equal(hits.length, 2);
    // document 1 is the closest to the query, so it comes first; the near duplicate 0 is passed over for 2
    assert.deepEqual(hits.map((h) => h.doc.pmid), ['1', '2']);
});

test('the number of results adapts to complex queries', () => {
    const store = new DiversityAwareVectorStore(toyEmbedder);
    assert.equal(store.adaptK('plain query', 5), 5);
    assert.equal(store.adaptK('gene phenotype', 5), 7);
    assert.equal(store.adaptK('knockout viability lethal', 5), 10);
});

// ------------------------------------------------------------------ the predictor, end to end with fake PubMed

function fakePubMed(papers) {
    const calls = [];
    const http = new HttpClient({
        fetchImpl: async (url) => {
            calls.push(url);
            const u = new URL(url);
            if (u.pathname.endsWith('esearch.fcgi')) {
                return { status: 200, text: async () => JSON.stringify({ esearchresult: { idlist: papers.map((p) => p.pmid) } }), headers: { get: () => null } };
            }
            const xml = `<PubmedArticleSet>${papers.map((p) => article(p.pmid, p.title, p.abstract)).join('')}</PubmedArticleSet>`;
            return { status: 200, text: async () => xml, headers: { get: () => null } };
        },
        sleep: async () => {}, rateLimits: {}, retries: 0,
    });
    return { http, calls };
}

const predictorFor = (papers) => {
    const { http, calls } = fakePubMed(papers);
    return { predictor: new RagPhenotypePredictor({ http, embedder: toyEmbedder, parseXml }), calls };
};

test('a gene whose knockout is lethal is predicted lethal, with the stage', async () => {
    const { predictor } = predictorFor([
        { pmid: '1', title: 'Xrcc1 knockout phenotype', abstract: 'Xrcc1-deficient mice are embryonic lethal. Embryos die at E8.5.' },
        { pmid: '2', title: 'Other work', abstract: 'XRCC1 knockout cells show lethal damage. Paralog compensation is unlikely for XRCC1.' },
    ]);

    const result = await predictor.predict('XRCC1');

    assert.equal(result.severity, 'LETHAL');
    assert.equal(result.risk_level, 'CRITICAL');
    assert.equal(result.lethality_stage, 'Embryonic');
    assert.ok(result.confidence_score > 0.1);
    assert.ok(result.predicted_phenotypes.some((t) => t.includes('lethal')));
    assert.ok(result.supporting_evidence.every((e) => e.pmid && e.similarity_score <= 1));
    assert.ok(result.compensatory_mechanisms.includes('paralog'));
});

test('a viable knockout is not called lethal even if other genes in the paper are', async () => {
    const { predictor } = predictorFor([
        { pmid: '3', title: 'Smug1 knockout mice', abstract: 'Smug1-deficient mice are viable and fertile. Loss of Brca1 is embryonic lethal. Mice lethal viable.' },
    ]);

    const result = await predictor.predict('SMUG1');

    assert.notEqual(result.severity, 'LETHAL');
    assert.equal(result.severity, 'MILD');
    assert.equal(result.risk_level, 'LOW');
});

test('drug-inhibition and synthetic-lethality papers do not make a gene lethal', async () => {
    const { predictor } = predictorFor([
        { pmid: '4', title: 'PARP1 inhibitors', abstract: 'PARP1 inhibition is synthetic lethal in BRCA-deficient cells. PARP1 trapping causes cell lethality in knockout lines.' },
    ]);

    const result = await predictor.predict('PARP1');

    assert.notEqual(result.severity, 'LETHAL');
});

test('no literature gives UNKNOWN with a low confidence, and says so', async () => {
    const { predictor } = predictorFor([]);

    const result = await predictor.predict('NOSUCHGENE');

    assert.equal(result.severity, 'UNKNOWN');
    assert.equal(result.confidence_score, 0.1);
    assert.equal(result.confidence_reasoning, 'No literature found for this gene');
});

test('a PubMed outage is reported as an outage, not as "no literature"', async () => {
    const http = new HttpClient({ fetchImpl: async () => ({ status: 503, text: async () => 'down', headers: { get: () => null } }), sleep: async () => {}, rateLimits: {}, retries: 0 });
    const predictor = new RagPhenotypePredictor({ http, embedder: toyEmbedder, parseXml });

    const result = await predictor.predict('XRCC1');

    assert.equal(result.severity, 'UNKNOWN');
    assert.match(result.confidence_reasoning, /literature search failed/);
});

test('the searches include one aimed at mouse knockout papers', async () => {
    const { predictor, calls } = predictorFor([{ pmid: '1', title: 't', abstract: 'a' }]);

    await predictor.predict('XRCC1');

    const searches = calls.filter((u) => u.includes('esearch.fcgi')).map((u) => decodeURIComponent(new URL(u).searchParams.get('term')));
    assert.ok(searches.some((t) => t.includes('mice[MeSH Terms]') && t.includes('lethal[Title/Abstract]')));
    assert.equal(searches.length, 5);   // knockout, phenotype, viability, mouse knockout, compensatory
});
