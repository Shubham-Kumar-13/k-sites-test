# K-Sites: Safe Gene Selection for Knockout Studies

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**K-Sites** helps scientists pick a **safe gene to delete**. Give it a biological process (a Gene Ontology term) and a species, and it ranks the genes involved in that process by how specific their function is and how risky a knockout is likely to be.

A *pleiotropic* gene takes part in many different processes, so deleting it causes side effects everywhere. K-Sites favours genes with a narrow function, well-supported evidence and no known severe knockout phenotype.

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
4. Per gene                              → cross-species check, optional phenotype
                                           prediction, skip genes above the pleiotropy cutoff
5. Safety recommendation                 → SAFE / CAUTION / MODERATE_CONCERN /
                                           HIGH_CONCERN / AVOID, with reasons
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
| **Phenotype prediction** (optional) | PubMed mining (SentenceTransformer + FAISS) | Predicted knockout severity and risk, with a confidence value. |

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
| `--species-validation` | TaxIDs for cross-species validation | pipeline default (human, mouse, rat, fly, worm) |
| `--predict-phenotypes` | Predict knockout phenotype from PubMed | off |
| `--rag-report` | Per-gene literature reports (needs `--predict-phenotypes`) | off |
| `--databases` | `quickgo`, `uniprot`, `ncbi`, `pubmed`, `kegg`, `all` | `all` |
| `--go-term-search` | Search GO terms by keyword | – |

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
)
generate_html_report(results, "report.html")
```

### Web application

A web interface (organism and GO-term pickers, live job progress, results, downloads) is in
[`webapp/`](webapp/README.md). Run it locally with `python webapp/app.py`.

For the lab it can be hosted for free: the website on GitHub Pages and the Python analysis on a
Hugging Face Space. See [DEPLOYMENT.md](DEPLOYMENT.md) for the step-by-step guide.

---

## Output files

For `--output report.html`:

| File | Description |
|---|---|
| `report.html` | Ranked genes with safety level and recommendation |
| `report_comprehensive.csv` | All metrics per gene |
| `report_gene_summary.csv` | Gene-level summary |
| `report_comprehensive.xlsx` | Excel workbook (needs `openpyxl`) |
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
- Phenotype prediction is keyword-based and often returns `UNKNOWN` for poorly studied genes.
- Annotation data can say a gene looks safe; it cannot guarantee safety in a particular cell line or animal. Always validate experimentally.

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

Gene Ontology Consortium, UniProt, KEGG and NCBI (PubMed, Entrez) for their open data.
