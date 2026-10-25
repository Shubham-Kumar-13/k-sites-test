/**
 * Organism and GO-term pickers, and organism -> NCBI taxonomy id.
 * Port of webapp/utils/hierarchical_data.py. The organism list comes from kegg-data/organisms.json
 * (built from KEGG by tools/build_kegg_data.py) because KEGG itself cannot be called from a browser.
 */

export const KINGDOMS = [
    { name: 'Animals', icon: 'fa-paw', description: 'Metazoans - multicellular animals' },
    { name: 'Plants', icon: 'fa-leaf', description: 'Viridiplantae - green plants' },
    { name: 'Microbes', icon: 'fa-bacterium', description: 'Bacteria, Archaea, and single-celled Eukaryotes' },
    { name: 'Fungi', icon: 'fa-mushroom', description: 'Fungi - yeasts, molds, mushrooms' },
    { name: 'Other Eukaryotes', icon: 'fa-dna', description: 'Protists and other eukaryotic organisms' },
];

export const GO_CATEGORIES = [
    { name: 'Biological Process', icon: 'fa-project-diagram', description: 'Larger biological programs accomplished by multiple molecular activities' },
    { name: 'Molecular Function', icon: 'fa-atom', description: 'Activities that occur at the molecular level' },
    { name: 'Cellular Component', icon: 'fa-cubes', description: 'Locations in the cell where gene products are active' },
];

/** Used when the organism list could not be loaded; taxids are known for these. */
export const FALLBACK_ORGANISMS = [
    { name: 'Homo sapiens', taxid: '9606', common_name: 'Human', kingdom: 'Animals', kegg_code: 'hsa' },
    { name: 'Mus musculus', taxid: '10090', common_name: 'House mouse', kingdom: 'Animals', kegg_code: 'mmu' },
    { name: 'Rattus norvegicus', taxid: '10116', common_name: 'Norway rat', kingdom: 'Animals', kegg_code: 'rno' },
    { name: 'Danio rerio', taxid: '7955', common_name: 'Zebrafish', kingdom: 'Animals', kegg_code: 'dre' },
    { name: 'Drosophila melanogaster', taxid: '7227', common_name: 'Fruit fly', kingdom: 'Animals', kegg_code: 'dme' },
    { name: 'Caenorhabditis elegans', taxid: '6239', common_name: 'Nematode worm', kingdom: 'Animals', kegg_code: 'cel' },
    { name: 'Arabidopsis thaliana', taxid: '3702', common_name: 'Thale cress', kingdom: 'Plants', kegg_code: 'ath' },
    { name: 'Saccharomyces cerevisiae', taxid: '559292', common_name: "Baker's yeast", kingdom: 'Fungi', kegg_code: 'sce' },
    { name: 'Escherichia coli', taxid: '83333', common_name: 'E. coli K-12', kingdom: 'Microbes', kegg_code: 'eco' },
];

/** Taxids the engine knows without asking NCBI (common model organisms and their synonyms). */
export const KNOWN_TAXIDS = {
    'homo sapiens': '9606', human: '9606', 'mus musculus': '10090', mouse: '10090',
    'rattus norvegicus': '10116', rat: '10116', 'danio rerio': '7955', zebrafish: '7955',
    'drosophila melanogaster': '7227', 'fruit fly': '7227', 'caenorhabditis elegans': '6239', worm: '6239',
    'arabidopsis thaliana': '3702', 'saccharomyces cerevisiae': '559292', yeast: '559292',
    'escherichia coli': '83333', 'bos taurus': '9913', 'sus scrofa': '9823', 'gallus gallus': '9031',
};

const NAMESPACES = {
    'Biological Process': 'biological_process',
    'Molecular Function': 'molecular_function',
    'Cellular Component': 'cellular_component',
};

const POPULAR_TERMS = {
    'Biological Process': [
        ['GO:0006281', 'DNA repair', 'The process of restoring DNA after damage'],
        ['GO:0006974', 'cellular response to DNA damage stimulus', 'Any process that results in a change in state or activity of a cell'],
        ['GO:0006260', 'DNA replication', 'The cellular metabolic process in which a cell duplicates DNA'],
        ['GO:0006351', 'transcription, DNA-templated', 'The cellular synthesis of RNA on a template of DNA'],
        ['GO:0006412', 'translation', 'The cellular metabolic process in which a protein is formed'],
        ['GO:0006915', 'apoptotic process', 'A programmed cell death process'],
        ['GO:0007049', 'cell cycle', 'The progression of biochemical phases in a cell'],
        ['GO:0006955', 'immune response', 'Any immune system process functioning in response to stimulus'],
        ['GO:0007165', 'signal transduction', 'The cellular process conveying a signal to trigger change'],
        ['GO:0008152', 'metabolic process', 'The chemical reactions and pathways transforming substances'],
    ],
    'Molecular Function': [
        ['GO:0003674', 'molecular_function', 'The elemental activities of a gene product'],
        ['GO:0003677', 'DNA binding', 'Any molecular function involving selective DNA interaction'],
        ['GO:0003700', 'DNA-binding transcription factor activity', 'A protein interacting with a specific DNA sequence'],
        ['GO:0003723', 'RNA binding', 'Interacting selectively with an RNA molecule'],
        ['GO:0003824', 'catalytic activity', 'Catalysis of a biochemical reaction at physiological temperatures'],
        ['GO:0004871', 'signal transducer activity', 'A molecular function accepting and transmitting a signal'],
        ['GO:0004872', 'receptor activity', 'Receiving a signal to initiate a change in cell activity'],
        ['GO:0005215', 'transporter activity', 'Enables directed movement of substances'],
        ['GO:0005515', 'protein binding', 'Interacting selectively with any protein'],
        ['GO:0016787', 'hydrolase activity', 'Catalysis of the hydrolysis of various bonds'],
    ],
    'Cellular Component': [
        ['GO:0005575', 'cellular_component', 'A location in or near a cell'],
        ['GO:0005576', 'extracellular region', 'The space external to the outermost structure of a cell'],
        ['GO:0005622', 'intracellular', 'The living contents of a cell'],
        ['GO:0005634', 'nucleus', 'A membrane-bounded organelle of eukaryotic cells'],
        ['GO:0005737', 'cytoplasm', 'All cell contents excluding plasma membrane and nucleus'],
        ['GO:0005739', 'mitochondrion', 'A semiautonomous, self-replicating organelle'],
        ['GO:0005783', 'endoplasmic reticulum', 'The irregular network of unit membranes'],
        ['GO:0005794', 'Golgi apparatus', 'A membrane-bound cytoplasmic organelle'],
        ['GO:0005829', 'cytosol', 'The part of cytoplasm without organelles'],
        ['GO:0005886', 'plasma membrane', 'The membrane surrounding and separating the cell'],
    ],
};

const OLS_SEARCH = 'https://www.ebi.ac.uk/ols4/api/search';
const NCBI_ESEARCH = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi';

const byName = (a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase());

export function searchOrganisms(organisms, kingdom = null, query = null) {
    const q = query ? query.toLowerCase() : null;
    return organisms
        .filter((org) => !kingdom || org.kingdom === kingdom)
        .filter((org) => !q || org.name.toLowerCase().includes(q)
            || (org.common_name || '').toLowerCase().includes(q) || query === (org.taxid || ''))
        .sort(byName);
}

export async function searchGoTerms(http, category = null, query = null) {
    if (query) {
        try {
            const params = { q: query, ontology: 'go', rows: 50 };
            if (category && NAMESPACES[category]) {
                params.fq = `ontology_name:go AND type:class AND namespace:"${NAMESPACES[category]}"`;
            }
            const response = await http.get(OLS_SEARCH, { params });
            if (!response.ok) return [];
            const results = [];
            for (const doc of response.json().response?.docs || []) {
                const id = doc.obo_id || '';
                if (!id.startsWith('GO:')) continue;
                let termCategory = 'Biological Process';
                for (const [name, namespace] of Object.entries(NAMESPACES)) {
                    if (namespace === doc.namespace) termCategory = name;
                }
                if (category && termCategory !== category) continue;
                results.push({
                    id, name: doc.label || '',
                    definition: Array.isArray(doc.description) && doc.description.length ? doc.description[0] : '',
                    category: termCategory,
                });
            }
            return results.sort(byName);
        } catch (error) {
            return [];
        }
    }
    if (category && POPULAR_TERMS[category]) {
        return POPULAR_TERMS[category].map(([id, name, definition]) => ({ id, name, definition, category })).sort(byName);
    }
    return [];
}

/**
 * NCBI taxonomy id for an organism name or id. Known model organisms are answered locally;
 * anything else is looked up in NCBI Taxonomy.
 */
export async function resolveTaxid(http, organism, hint = '') {
    if (hint && /^\d+$/.test(String(hint))) return String(hint);
    const name = String(organism || '').trim();
    if (/^\d+$/.test(name)) return name;
    const known = KNOWN_TAXIDS[name.toLowerCase()];
    if (known) return known;

    const response = await http.get(NCBI_ESEARCH, {
        params: { db: 'taxonomy', term: `"${name}"[Scientific Name]`, retmode: 'json' },
    });
    if (response.ok) {
        const ids = response.json().esearchresult?.idlist || [];
        if (ids.length) return ids[0];
    }
    throw new Error(`Could not find the NCBI taxonomy id for "${name}". Choose the organism from the list or enter its numeric taxonomy id.`);
}
