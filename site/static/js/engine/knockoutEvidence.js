/**
 * Measured knockout evidence: what is known, from measurements, about losing one gene.
 * Port of k_sites/knockout_evidence (provider.py + assessment.py); the same data files are read.
 *
 * `assessGene` returns a plain object with up to four parts:
 *   organism    knockout of the whole organism: lethal / subviable / viable, stage, number of knockout lines
 *               (direct for mouse, yeast, zebrafish, fly and worm; read from the mouse ortholog for human and rat, and
 *               for the genes of zebrafish, fly and worm that have no measurement of their own)
 *   cells       how often losing the gene kills a human cancer cell line (DepMap CRISPR screens)
 *   constraint  how rarely loss-of-function variants are seen in people (gnomAD)
 *   expression  how many human tissues express the gene, and which most (GTEx)
 *   paralogs    the closest paralogs, which may take over the gene's work and hide the effect of a knockout (Ensembl)
 * A gene without a record gets UNKNOWN; nothing is guessed.
 */

export const CELL_ESSENTIAL_PERCENT = 50;
export const CELL_SELECTIVE_PERCENT = 10;
export const LOEUF_HIGHLY_CONSTRAINED = 0.35;
export const LOEUF_CONSTRAINED = 0.6;
export const TAU_RESTRICTED = 0.8;
export const TAU_ENRICHED = 0.5;
/** A paralog this similar (percent identity) is close enough to take over the gene's work. */
export const CLOSE_PARALOG_IDENTITY = 40;
export const FORMAT_VERSION = 1;

const SPECIES_NOUN = { 10090: 'mice', 10116: 'rats', 9606: 'humans', 559292: 'yeast', 7955: 'zebrafish', 7227: 'flies', 6239: 'worms' };
const SOURCE_OF_LETTER = { M: 'mgi', I: 'impc', S: 'sgd', Z: 'zfin', F: 'flybase', W: 'wormbase' };
/** What the counts of knockout lines are counts of: [one, many]. */
const LINE_NOUN = { 7955: ['mutant line', 'mutant lines'], 7227: ['allele', 'alleles'], 6239: ['allele or RNAi test', 'alleles or RNAi tests'] };
const CALL_OF_LETTER = { L: 'LETHAL', S: 'SUBVIABLE', V: 'VIABLE' };
const TAXID_ALIASES = { 4932: '559292' };

export class EvidenceUnavailable extends Error {}

/** 'cells' (cultured cells) or 'organism' (whole animal / plant / yeast); 'auto': cells for human. */
export function resolveContext(taxid, context = 'auto') {
    if (context === 'cells' || context === 'organism') return context;
    return String(taxid) === '9606' ? 'cells' : 'organism';
}

export class OrganismEvidence {
    constructor(taxid, info, genes, aliases) {
        this.taxid = taxid;
        this.info = info;
        this.genes = genes;
        this.aliases = aliases;
    }

    lookup(symbol) {
        const key = String(symbol ?? '').trim().toUpperCase();
        if (!key) return null;
        let record = Object.prototype.hasOwnProperty.call(this.genes, key) ? this.genes[key] : null;
        if (record === null && Object.prototype.hasOwnProperty.call(this.aliases, key)) {
            const current = String(this.aliases[key]).toUpperCase();
            record = Object.prototype.hasOwnProperty.call(this.genes, current) ? this.genes[current] : null;
        }
        return record;
    }
}

/** Reads index.json and the organism files through `readJson(name)` (the files are fetched once each). */
export class EvidenceProvider {
    constructor(readJson) {
        this.readJson = readJson;
        this._index = null;
        this._organisms = new Map();
    }

    async index() {
        if (!this._index) {
            this._index = this.readJson('index.json').then((index) => {
                if (index.format !== FORMAT_VERSION) {
                    throw new EvidenceUnavailable(`The knockout evidence files have format ${index.format}; this version of K-Sites reads format ${FORMAT_VERSION}`);
                }
                return index;
            });
            this._index.catch(() => { this._index = null; });
        }
        return this._index;
    }

    async organism(taxid) {
        const key = TAXID_ALIASES[String(taxid)] || String(taxid);
        if (!this._organisms.has(key)) {
            const loading = (async () => {
                const index = await this.index();
                const info = (index.organisms || {})[key];
                if (!info) return null;
                const data = await this.readJson(info.file);
                return new OrganismEvidence(key, info, data.genes || {}, data.aliases || {});
            })();
            this._organisms.set(key, loading);
            loading.catch(() => this._organisms.delete(key));
        }
        return this._organisms.get(key);
    }
}

/** A provider reading `<baseUrl>index.json` etc. with fetch. */
export function createEvidenceProvider(baseUrl, fetchImpl = (...a) => globalThis.fetch(...a)) {
    return new EvidenceProvider(async (name) => {
        let response;
        try {
            response = await fetchImpl(`${baseUrl}${name}`);
        } catch (error) {
            throw new EvidenceUnavailable(`Could not download ${baseUrl}${name}: ${error.message}`);
        }
        if (!response.ok) throw new EvidenceUnavailable(`Could not download ${baseUrl}${name}: HTTP ${response.status}`);
        return response.json();
    });
}

const linesText = (count, total, taxid = '') => {
    const [one, many] = LINE_NOUN[taxid] || ['knockout line', 'knockout lines'];
    return `${count} of ${total} ${total === 1 ? one : many}`;
};
const numberText = (value) => String(Number(value));

function organismPart(index, taxid, record) {
    const part = {
        call: 'UNKNOWN', basis: 'none', distant: false, stage: null, stage_text: null,
        counts: { lethal: 0, subviable: 0, viable: 0 }, mixed: false, sources: [], species: null,
        ortholog: null, mgi_id: null, references: [], systems: [], reduced_lifespan: false,
        infertile: false, rnai_only: false, human_essential_percent: null, text: 'No measured knockout data for this gene',
    };
    if (!record) return part;
    let base;
    let basis;
    let speciesKey;
    if (record.v) {
        base = record;
        basis = 'direct';
        part.species = ((index.organisms || {})[taxid] || {}).name ?? null;
        speciesKey = taxid;
    } else if (record.m) {
        base = record.m;
        basis = 'ortholog';
        part.ortholog = { symbol: record.o[0], relation: record.o[1] };
        part.distant = !!((index.organisms || {})[taxid] || {}).distant;
        part.species = 'Mus musculus';
        speciesKey = '10090';
    } else {
        return part;
    }

    const [lethal, subviable, viable] = base.n;
    part.counts = { lethal, subviable, viable };
    part.call = CALL_OF_LETTER[base.v];
    part.basis = basis;
    part.mixed = !!base.x;
    part.stage = base.s ?? null;
    part.stage_text = part.stage ? ((index.stages || {})[part.stage] ?? null) : null;
    part.sources = [...(base.src || '')].filter((c) => SOURCE_OF_LETTER[c]).map((c) => SOURCE_OF_LETTER[c]);
    if (basis === 'ortholog') part.sources.push('alliance');
    part.mgi_id = base.id ?? null;
    part.references = [...(base.pm || [])];
    const names = index.systems || [];
    part.systems = (base.sys || []).filter((i) => i < names.length).map((i) => names[i]);
    part.reduced_lifespan = !!base.r;
    part.infertile = !!base.f;
    part.rnai_only = !!base.k;
    part.human_essential_percent = base.hc ?? null;

    const noun = SPECIES_NOUN[speciesKey] || 'the model organism';
    let where;
    if (basis === 'direct') where = noun;
    else if (part.distant) where = `${noun} (mouse ortholog ${part.ortholog.symbol}, ${part.ortholog.relation}; a distant relative, so only an indication)`;
    else where = `${noun} (mouse ortholog ${part.ortholog.symbol}, ${part.ortholog.relation})`;
    const stage = part.stage && part.stage !== 'U' ? ` (${part.stage_text})` : '';
    const total = lethal + subviable + viable;
    const yeast = speciesKey === '559292';
    const subject = yeast ? 'Deletion' : 'Knockout';
    const lethalWord = yeast ? 'inviable' : 'lethal';
    const linesTaxid = basis === 'direct' ? taxid : '';
    let text;
    if (part.call === 'LETHAL') {
        text = `${subject} is ${lethalWord}${stage} in ${where}: ${linesText(lethal, total, linesTaxid)}`;
    } else if (part.call === 'SUBVIABLE') {
        const detail = [part.stage !== 'U' ? part.stage_text : null, 'fewer homozygotes than expected'].filter(Boolean).join('; ');
        text = `${subject} is subviable (${detail}) in ${where}: ${linesText(subviable, total, linesTaxid)}`;
    } else {
        text = `${subject} is viable in ${where}: ${linesText(viable, total, linesTaxid)}`;
    }
    if (part.rnai_only && part.call === 'LETHAL') text += '; every lethal result comes from RNAi knockdown, none from a mutant';
    if (part.mixed) {
        const others = [[lethal, 'lethal', 'LETHAL'], [subviable, 'subviable', 'SUBVIABLE'], [viable, 'viable', 'VIABLE']]
            .filter(([n, , call]) => n && call !== part.call).map(([n, word]) => `${n} ${word}`);
        text += `; ${others.join(', ')} in other lines (strain or allele dependent)`;
    }
    part.text = text;
    return part;
}

function cellsPart(record) {
    const part = { call: 'UNKNOWN', percent: null, lines: null, common_essential: false, source: 'depmap',
        text: 'No human cell-line screen data for this gene' };
    if (!record || !record.c) return part;
    const [flag, percent, lines] = record.c;
    part.percent = percent;
    part.lines = lines;
    part.common_essential = flag === 'C';
    if (percent === null || percent === undefined) return part;
    const count = Number(lines).toLocaleString('en-US');
    if (flag === 'C' || percent >= CELL_ESSENTIAL_PERCENT) {
        part.call = 'ESSENTIAL';
        part.text = `Essential in ${numberText(percent)}% of ${count} human cancer cell lines${flag === 'C' ? '; DepMap common essential' : ''}`;
    } else if (flag === 'N' || percent < CELL_SELECTIVE_PERCENT) {
        part.call = 'NON_ESSENTIAL';
        part.text = `Rarely essential: needed in ${numberText(percent)}% of ${count} human cancer cell lines`;
    } else {
        part.call = 'SELECTIVE';
        part.text = `Essential in ${numberText(percent)}% of ${count} human cancer cell lines; check that your cell type is not one of them`;
    }
    return part;
}

// the model species of the conservation score, in the order of the bits in a record's "cv" number
const CONSERVATION_SPECIES = ['human', 'mouse', 'rat', 'fly', 'worm'];

/** In how many of the model species the gene (or an ortholog) exists, or null when the gene is not in the orthology table. */
function conservationPart(record) {
    if (!record || record.cv === undefined || record.cv === null) return null;
    const found = CONSERVATION_SPECIES.filter((_, i) => (record.cv >> i) & 1);
    return {
        score: found.length / CONSERVATION_SPECIES.length, found_in: found,
        text: `Present in ${found.length} of ${CONSERVATION_SPECIES.length} model species (${found.join(', ')})`,
    };
}

/** The number of PubMed articles that NCBI Gene links to the gene, or null when it is not known. */
function literaturePart(record) {
    if (!record || record.lc === undefined || record.lc === null) return null;
    return { count: record.lc };
}

const ESTIMATE_LABELS = { likely: 'likely lethal', possible: 'possibly lethal', unlikely: 'unlikely to be lethal' };
const percentOf = (fraction) => Math.floor(fraction * 100 + 0.5);

/** The lethality estimate of a gene that has no knockout result (see k_sites/knockout_evidence/assessment.py), or null. */
function estimatePart(index, taxid, record, organism) {
    if (!record || !record.pl || organism.call !== 'UNKNOWN') return null;
    const [probability, other] = record.pl;
    const model = index.lethality_model || {};
    const likely = model.likely ?? 0.5;
    const possible = model.possible ?? 0.3;
    const band = probability >= likely ? 'likely' : probability >= possible ? 'possible' : 'unlikely';
    const percent = Math.max(1, Math.min(99, percentOf(probability)));      // an estimate is never shown as certain
    const fromHuman = taxid !== '9606';
    const source = fromHuman
        ? `the cell-line, population and expression data of its human ortholog ${other}`
        : `its own cell-line, population and expression data (its mouse ortholog ${other} has no knockout result)`;
    let text = `No measured knockout result. Estimated ${percent}% chance that a knockout is lethal in mice (${ESTIMATE_LABELS[band]}), from ${source}.`;
    const share = ((((model.tested || {}).bands || {})[band]) || {}).lethal_share;
    if (share !== undefined && share !== null && model.auc !== undefined && model.auc !== null) {
        text += ` Among tested mouse genes with such an estimate ${percentOf(share)}% were lethal (AUC ${model.auc}).`;
    }
    text += ' This is an estimate, not a measurement.';
    return { probability, percent, band, label: ESTIMATE_LABELS[band], other_symbol: other, from_human_ortholog: fromHuman, text };
}

function constraintPart(record) {
    if (!record || record.l === undefined) return null;
    const loeuf = record.l;
    const label = loeuf < LOEUF_HIGHLY_CONSTRAINED ? 'highly constrained' : loeuf < LOEUF_CONSTRAINED ? 'constrained' : 'not constrained';
    return {
        loeuf, label,
        text: `Loss-of-function variants are ${loeuf < LOEUF_CONSTRAINED ? 'rare' : 'tolerated'} in people (gnomAD LOEUF ${numberText(loeuf)}, ${label})`,
    };
}

function expressionPart(index, record) {
    if (!record || !record.t) return null;
    const [tau, expressed, top] = record.t;
    const tissues = index.tissues || [];
    const names = top.filter((i) => i < tissues.length).map((i) => tissues[i]);
    if (tau === null || tau === undefined) {
        return { tau: null, label: 'barely expressed', tissues_expressed: expressed, top_tissues: [],
            text: 'Barely expressed (under 1 TPM in every GTEx tissue)' };
    }
    const label = tau >= TAU_RESTRICTED ? 'tissue-specific' : tau >= TAU_ENRICHED ? 'tissue-enriched' : 'broadly expressed';
    const where = names.length ? `; highest in ${names.join(', ')}` : '';
    return {
        tau, label, tissues_expressed: expressed, top_tissues: names,
        text: `${label.charAt(0).toUpperCase()}${label.slice(1)}: expressed in ${expressed} of ${tissues.length || 54} tissues (tau ${Number(tau).toFixed(2)})${where}`,
    };
}

function paralogsPart(record) {
    if (!record || !record.p || !record.p.length) return null;
    const genes = record.p.map(([symbol, identity]) => ({ symbol, identity }));
    const close = genes.filter((g) => g.identity >= CLOSE_PARALOG_IDENTITY).map((g) => g.symbol);
    const listing = genes.map((g) => `${g.symbol} (${g.identity}% identical)`).join(', ');
    return { genes, close, text: `Closest paralogs: ${listing}` };
}

function sourcesUsed(index, organism, cells, constraint, expression, paralogs, estimate) {
    const wanted = [...organism.sources];
    if (estimate) wanted.push('mgi', 'impc', 'depmap', 'gnomad', 'gtex');
    if (cells.call !== 'UNKNOWN') wanted.push('depmap');
    if (constraint) wanted.push('gnomad');
    if (expression) wanted.push('gtex');
    if (paralogs) wanted.push('ensembl');
    const byId = Object.fromEntries((index.sources || []).map((s) => [s.id, s]));
    return [...new Set(wanted)].filter((w) => byId[w]).map((w) => ({ id: w, name: byId[w].name, url: byId[w].url }));
}

/** Everything measured about losing `symbol` in the organism `taxid`. */
export async function assessGene(provider, taxid, symbol, context = 'auto') {
    taxid = String(taxid);
    const result = {
        symbol, taxid, context: resolveContext(taxid, context), covered: false, found: false,
        organism: organismPart({}, taxid, null), cells: cellsPart(null), constraint: null,
        expression: null, paralogs: null, estimate: null, conservation: null, literature: null,
        has_measured: false, sources: [], data_version: null,
    };
    if (!provider) return result;
    const index = await provider.index();
    result.data_version = index.built ?? null;
    const organism = await provider.organism(taxid);
    if (!organism) return result;
    result.covered = true;
    const record = organism.lookup(symbol);
    if (!record) return result;
    result.found = true;
    result.organism = organismPart(index, organism.taxid, record);
    result.cells = cellsPart(record);
    result.constraint = constraintPart(record);
    result.expression = expressionPart(index, record);
    if (result.expression && organism.taxid !== '9606') result.expression.text += ' (in the human ortholog)';
    result.paralogs = paralogsPart(record);
    result.estimate = estimatePart(index, organism.taxid, record, result.organism);
    result.conservation = conservationPart(record);
    result.literature = literaturePart(record);
    // a distant relative's mouse ortholog is a hint, not a measurement
    result.has_measured = (result.organism.call !== 'UNKNOWN' && !result.organism.distant) || result.cells.call !== 'UNKNOWN';
    result.sources = sourcesUsed(index, result.organism, result.cells, result.constraint, result.expression, result.paralogs, result.estimate);
    return result;
}
