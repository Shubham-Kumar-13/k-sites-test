# K-Sites: Safe Gene Selection for Knockout Studies

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**K-Sites** helps scientists pick a **safe gene to delete**. Give it a biological process (a Gene Ontology term) and a species, and it ranks the genes involved in that process by how specific their function is and how risky a knockout is likely to be.

A *pleiotropic* gene takes part in many different processes, so deleting it causes side effects everywhere. K-Sites favours genes with a narrow function, well-supported evidence and no known severe knockout phenotype.

**The verdict rests on measurements, not guesses.** For every gene K-Sites looks up what has actually been measured when the gene is lost: the viability of knockout mice (MGI literature curation and the IMPC screen), yeast (SGD), zebrafish (ZFIN), fruit flies (FlyBase) and worms (WormBase), the effect of a CRISPR knockout on 1,178 human cancer cell lines (DepMap), tolerance of loss-of-function variants in people (gnomAD), tissue expression (GTEx) and close paralogs (Ensembl). A gene whose knockout is lethal is never rated safe, however specific it looks; a gene with no measurement gets an estimate of its lethality from the data of its human ortholog (tested on 12,021 mouse genes with a known outcome; AUC 0.84) or is marked "Not verified", and is never rated better than CAUTION. See [VALIDATION.md](VALIDATION.md) for how the data were checked against published knockouts.

> **Scope:** K-Sites selects *which gene* to delete. It does not design guide RNAs or predict off-targets; use a dedicated guide design tool (for example CRISPOR or CHOPCHOP) for the gene you choose.

---

## How it works

```
GO term + organism
      │
      ▼
1. Resolve organism                      → NCBI TaxID
2. Map GO term to genes (QuickGO)        → candidate genes, filtered by evidence type
3. Score and rank genes                  → pleiotropy, specificity, evidence quality,
                                           literature support, conservation, composite score
4. Per gene                              → cross-species check, measured knockout evidence,
                                           optional phenotype prediction (only where nothing
                                           is measured); genes above the pleiotropy cutoff
                                           are listed as "not shown", never dropped silently
5. Safety recommendation                 → SAFE / CAUTION / MODERATE_CONCERN /
                                           HIGH_CONCERN / AVOID, with reasons, listed safest first
6. Reports                               → HTML, CSV, Excel
```

### What is scored

| Signal | Source | Meaning |
|---|---|---|
| **Pleiotropy score (0–10)** | GO Biological Process terms (QuickGO, UniProt, KEGG) | How many other processes the gene takes part in. 0 = very specific. |
| **Specificity (0–1)** | `1 − pleiotropy / 10` | Inverse of pleiotropy. 1 = most specific. |
| **Evidence quality (0–1)** | GO evidence codes | Experimental evidence weighs 1.0, computational 0.6, IEA predictions 0.3. |
| **Literature support (0–1)** | PubMed publication count | More studied genes score higher. |
| **Conservation (0–1)** | Cross-species check | Whether the gene behaves similarly in other species. |
| **KEGG pathway count** | KEGG | Number of KEGG pathways the gene belongs to (reported per gene). |
| **Knockout viability** | MGI, IMPC (mouse), SGD (yeast), ZFIN (zebrafish), FlyBase (fly), WormBase (worm); human and rat genes use the one-to-one mouse ortholog; zebrafish, fly, worm and Xenopus genes without a measurement of their own get the mouse ortholog's knockout as a hint only | Lethal / subviable / viable, the stage of death, the number of knockout lines, the papers behind it. |
| **Cell-line essentiality** | DepMap 24Q4 CRISPR screens | In what percentage of 1,178 human cancer cell lines losing the gene kills the cells. |
| **Loss-of-function tolerance, expression, paralogs** | gnomAD v4.1, GTEx v8, Ensembl Compara | Context for the advice: constrained genes, tissue-restricted genes (tissue-specific knockout), close paralogs (double knockout). |
| **Phenotype prediction** (optional, experimental) | PubMed mining (SentenceTransformer + FAISS) | Used only for genes without a measured result and without a lethality estimate. In our test it found 7 of 30 lethal genes and wrongly flagged 4 of 30 viable ones ([VALIDATION.md](VALIDATION.md)). |

The safety verdict follows the measurement that matches what you will knock out (`--knockout-context`): **cultured cells** (DepMap decides, the default for human) or a **whole organism** (the knockout animal or yeast decides, the default for everything else). The other measurement is shown too: *TDG* and *POLB* kill the mouse embryo but human cell lines tolerate their loss.

Pleiotropy uses exponential decay: `score = 10 × (1 − exp(−0.3 × other_BP_terms))`, where `other_BP_terms` is the number of Biological Process terms excluding the one you are studying.

The composite score weights specificity 40%, evidence quality 25%, literature support 20% and conservation 15%.

---

## Installation

```bash
git clone https://github.com/kkokay07/K-Sites.git
cd K-Sites
pip install -e .
```

Optional extras:

```bash
pip install -e '.[rag]'      # phenotype prediction (sentence-transformers, FAISS)
pip install -e '.[webapp]'   # web application
pip install -e '.[all]'      # everything
```

Set your email for NCBI (required) and, optionally, an API key for higher rate limits:

```bash
export NCBI_EMAIL="your.email@example.com"
export NCBI_API_KEY="your_ncbi_api_key"
```

---

## Usage

### Command line

```bash
k-sites --go-term GO:0006281 --organism "Homo sapiens" --output report.html
```

With options:

```bash
k-sites --go-term GO:0006281 --organism 9606 --output results/report.html \
        --max-pleiotropy 5 \
        --evidence-filter experimental \
        --species-validation 9606 10090 \
        --predict-phenotypes \
        --rag-report
```

Search for a GO term:

```bash
k-sites --go-term-search "DNA repair" --organism "Homo sapiens" --output report.html
```

### Options

| Option | Description | Default |
|---|---|---|
| `--go-term` | GO term to analyse (e.g. `GO:0006281`) | required |
| `--organism` | NCBI TaxID or scientific name | required |
| `--output` | Output HTML report path | required |
| `--max-pleiotropy` | Cutoff on the 0–10 pleiotropy score: genes scoring above it are excluded (0 = only the most specific genes, 10 = keep everything) | 10 |
| `--max-annotations` | Safety limit on GO annotations read for the GO term. If it cuts the read short, the report warns what share was read (e.g. "Only 39% of annotations were read"); raise it to read everything (slower) | 2000 |
| `--evidence-filter` | Which GO evidence counts: `experimental` (roles proven in lab experiments; strict, but can flatter poorly studied genes), `computational` (predicted roles only) or `all` (every known role; most cautious) | `experimental` |
| `--knockout-context` | `cells` (cultured cells: DepMap decides), `organism` (whole animal/plant/yeast: the knockout organism decides) or `auto` (cells for human, organism otherwise) | `auto` |
| `--no-measured-evidence` | Ignore the measured knockout data and rate genes from annotations and predictions alone | off |
| `--species-validation` | TaxIDs for cross-species validation | pipeline default (human, mouse, rat, fly, worm) |
| `--predict-phenotypes` | Predict knockout phenotype from PubMed, only for genes with no measured result (experimental) | off |
| `--rag-report` | Per-gene literature reports (needs `--predict-phenotypes`) | off |
| `--databases` | `quickgo`, `uniprot`, `ncbi`, `pubmed`, `kegg`, `all` | `all` |
| `--go-term-search` | Search GO terms by keyword | – |

The measured knockout data are published with the K-Sites website and downloaded once a month into `~/.k_sites/evidence-data`. To use a local copy (or work offline) build the files and point to them:

```bash
python tools/build_evidence_data.py --out evidence-data     # about 10 minutes, downloads about 280 MB once
export KSITES_EVIDENCE_DIR=evidence-data
# KSITES_EVIDENCE_URL=off switches the measured evidence off
```

### Python

```python
from k_sites.workflow.pipeline import run_k_sites_pipeline
from k_sites.reporting.report_generator import generate_html_report

results = run_k_sites_pipeline(
    go_term="GO:0006281",   # DNA repair
    organism="9606",        # human
    max_pleiotropy=5,
    evidence_filter="experimental",
    predict_phenotypes=False,
    knockout_context="auto",   # "cells", "organism" or "auto"
)
generate_html_report(results, "report.html")

# one gene on its own
from k_sites.knockout_evidence import default_provider, assess_gene
evidence = assess_gene(default_provider(), "9606", "TDG", context="cells")
print(evidence["organism"]["text"])   # Knockout is lethal (embryonic / prenatal) in mice (mouse ortholog Tdg, 1:1): 3 of 3 knockout lines
print(evidence["cells"]["text"])      # Rarely essential: needed in 3.7% of 1,178 human cancer cell lines
```

### Web application

A web interface (organism and GO-term pickers, live job progress, results, downloads) is in
[`webapp/`](webapp/README.md). Run it locally with `python webapp/app.py`.

For the lab it can be hosted for free on GitHub Pages: the analysis runs in each visitor's browser, so
no server is needed. See [DEPLOYMENT.md](DEPLOYMENT.md) for the step-by-step guide and its limits.

---

## Output files

For `--output report.html`:

| File | Description |
|---|---|
| `report.html` | Ranked genes (safest first) with safety level, measured knockout evidence with links to the papers, recommendation; genes assessed but not shown; data sources |
| `report_comprehensive.csv` | All metrics per gene, including the knockout evidence columns (`Organism_Knockout`, `Cell_Essentiality`, `Close_Paralogs`, `Knockout_References`, ...) and a table of the genes not shown |
| `report_gene_summary.csv` | Gene-level summary |
| `report_comprehensive.xlsx` | Excel workbook with sheets for rankings, safety recommendations, knockout evidence and genes not shown (needs `openpyxl`) |
| `rag_reports/*.html` | Per-gene literature analysis (with `--rag-report`) |

---

## Project layout

```
k_sites/
├── cli.py                    # command line entry point
├── config/                   # configuration loading
├── data_retrieval/           # QuickGO, UniProt, KEGG, organism lookup
├── gene_analysis/            # pleiotropy scoring and ranking
├── rag_system/               # PubMed mining and phenotype prediction
├── workflow/
│   ├── pipeline.py           # pipeline orchestration
│   └── safety_recommender.py # safety level and recommendation
└── reporting/                # HTML, CSV, Excel and RAG reports
webapp/                       # Flask web application
tests/
demo/
```

---

## Known limitations

- Very large GO terms can have more annotations than the safety limit (`--max-annotations`). The tool then warns how much was read, and genes that appear only in the unread part are missing.
- Scores depend on live queries to QuickGO, UniProt, KEGG and PubMed. A gene whose data cannot be retrieved is listed as "not scored (insufficient data)" instead of being ranked; re-run if the reason says a lookup failed.
- The evidence type you choose (`--evidence-filter`) changes the result: under `experimental`, a poorly studied gene with few lab-proven roles can look more specific than it is. Compare with `all` when in doubt.
- Measured results exist for most genes of the common model organisms (about 14,400 mouse genes, 95% of human protein-coding genes through the mouse ortholog or DepMap, 5,700 yeast genes, and for zebrafish, fly and worm the genes that ZFIN, FlyBase and WormBase have curated: about 950 zebrafish, 4,900 fly and 4,100 worm genes) but not for every gene and not for most other species. A gene without a measurement is marked "Not verified" and rated at most CAUTION.
- Knockout results depend on the strain and the allele; the report shows how many lines agree and rates a gene at least HIGH_CONCERN when any line was lethal. Mouse results are carried to human and rat genes only through one-to-one orthologs, and a gene needed by the embryo may still be fine in cultured cells (both are shown).
- Cell-line essentiality comes from 1,178 cancer cell lines (DepMap 24Q4); your cell type may differ. Viable does not mean unaffected: shortened lifespan, infertility and affected organ systems are reported.
- Phenotype prediction is keyword-based, experimental and only used for genes without a measured result or a lethality estimate; it often returns `UNKNOWN`. [VALIDATION.md](VALIDATION.md) has its measured accuracy.
- Annotation data and even measurements cannot guarantee safety in a particular cell line or animal. Always validate experimentally.

---

## Testing

```bash
python -m pytest tests/
```

---

## Developers

- **Kanaka KK** – Lead Architect
- **Sandip Garai** – Neo4j Graph Integration Specialist (earlier prototype, since retired)
- **Jeevan C** – CRISPR Algorithm Developer
- **Tanzil Fatima** – Bioinformatics Analyst

## License

MIT License – see [LICENSE](LICENSE).

## Acknowledgments

Gene Ontology Consortium, UniProt, KEGG and NCBI (PubMed, Entrez) for their open data. The measured knockout evidence comes from Mouse Genome Informatics (MGI), the International Mouse Phenotyping Consortium (IMPC), the Alliance of Genome Resources, the Saccharomyces Genome Database (SGD), ZFIN (CC BY 4.0), FlyBase (CC BY 4.0), WormBase, DepMap (Broad Institute, 24Q4 Public, CC BY 4.0), gnomAD, GTEx, HGNC and Ensembl Compara; please cite those resources when you use the reports.
