# K-Sites v1.2.0 - Feature Documentation

## Core Features

### 1. Multi-Database Integration

**Status:** ✅ Fully Implemented

K-Sites queries **GO.org (QuickGO), UniProt, and KEGG simultaneously** using parallel processing for comprehensive gene data retrieval.

**Implementation:**
- File: `k_sites/data_retrieval/multi_database_client.py`
- Class: `MultiDatabaseClient`
- Method: `query_all_databases_simultaneously()`

**Databases Queried:**
| Database | Purpose | Data Retrieved |
|----------|---------|----------------|
| **GO.org (QuickGO)** | Gene Ontology annotations | BP terms, evidence codes |
| **UniProt** | Protein knowledgebase | Protein function, domains |
| **KEGG** | Pathway database | Pathway annotations, pathway count |

**Evidence Code Classification:**
```python
EXPERIMENTAL_CODES = {
    "IDA",  # Inferred from Direct Assay
    "IMP",  # Inferred from Mutant Phenotype
    "IGI",  # Inferred from Genetic Interaction
    "IPI",  # Inferred from Physical Interaction
    "IEP",  # Inferred from Expression Pattern
    "HTP",  # High Throughput experimental
    "HDA",  # High Throughput Direct Assay
    "HMP",  # High Throughput Mutant Phenotype
    "HGI",  # High Throughput Genetic Interaction
    "HEP",  # High Throughput Expression Pattern
}

COMPUTATIONAL_CODES = {
    "ISS", "ISO", "ISA", "ISM", "IGC", "IBA", "IBD", "IKR", "IRD", "RCA"
}

IEA_CODE = {"IEA"}  # Inferred from Electronic Annotation (PREDICTION, not evidence)
```

**Usage:**
```bash
# Use all databases (default)
k-sites --go-term GO:0006281 --organism 9606 --output report.html

# Note: --databases is accepted for metadata tracking but currently all queries use QuickGO, UniProt and KEGG
k-sites --go-term GO:0006281 --organism 9606 --output report.html --databases quickgo
```

---

### 2. Pleiotropy Scoring Algorithm

**Status:** ✅ Fully Implemented

**Formula:** Exponential decay scoring based on number of associated Biological Process GO terms.

**Implementation:**
- File: `k_sites/gene_analysis/pleiotropy_scorer.py`
- Function: `calculate_pleiotropy_score()`

**Algorithm:**
```
For n = number of OTHER BP terms (excluding target GO term):
    
    if n = 0:     score = 0.0   (highly specific)
    if n ≥ 10:    score = 10.0  (highly pleiotropic)
    otherwise:    score = 10 × (1 - exp(-λ × n))
    
Where λ = 0.3 (decay rate)
```

**Score Interpretation:**
| Pleiotropy Score | Specificity Score | Interpretation |
|-----------------|-------------------|----------------|
| 0.0 | 1.00 | Highly specific (1 BP term) |
| 2.6 | 0.74 | Low pleiotropy (3 BP terms) |
| 4.5 | 0.55 | Moderate pleiotropy (5 BP terms) |
| 6.3 | 0.37 | High pleiotropy (8 BP terms) |
| 10.0 | 0.00 | Highly pleiotropic (10+ BP terms) |

**Specificity Score (0-1 scale):**
```
specificity = 1.0 - (pleiotropy / 10.0)
```

**Usage:**
```bash
# Filter by maximum pleiotropy (0-10 scale)
k-sites --go-term GO:0006281 --organism 9606 --output report.html --max-pleiotropy 3
```

---

### 3. Evidence-Based Filtering

**Status:** ✅ Fully Implemented

Distinguishes experimental evidence (IDA, IMP, IGI) from computational predictions (IEA).

**Implementation:**
- File: `k_sites/gene_analysis/pleiotropy_scorer.py`
- File: `k_sites/data_retrieval/multi_database_client.py`

**Evidence Classification:**

| Type | Codes | Weight | Description |
|------|-------|--------|-------------|
| **Experimental** | IDA, IMP, IGI, IPI, IEP, HTP, HDA, HMP, HGI, HEP | 1.0 | Direct experimental assays |
| **Computational** | ISS, ISO, ISA, ISM, IGC, IBA, IBD, IKR, IRD, RCA | 0.6 | Computational analysis |
| **Prediction** | IEA | 0.3 | Electronic annotation (NOT evidence) |

**Evidence Quality Formula:**
```python
quality = (
    (exp_count × 1.0) +
    (comp_count × 0.6) +
    (iea_count × 0.3)
) / total
```

**Usage:**
```bash
# Use only experimental evidence
k-sites --go-term GO:0006281 --organism 9606 --output report.html --evidence-filter experimental

# Use computational evidence
k-sites --go-term GO:0006281 --organism 9606 --output report.html --evidence-filter computational

# Use all evidence types
k-sites --go-term GO:0006281 --organism 9606 --output report.html --evidence-filter all
```

---

## Additional Features

### 4. Cross-Species Validation

Validates gene specificity across model organisms:
- **9606** - Homo sapiens (Human)
- **10090** - Mus musculus (Mouse)
- **7227** - Drosophila melanogaster (Fly)
- **6239** - Caenorhabditis elegans (Worm)

```bash
k-sites --go-term GO:0006281 --organism 9606 --output report.html \
        --species-validation 9606 10090 7227
```

### 5. RAG-Based Phenotype Prediction

Uses semantic literature mining to predict knockout phenotypes:
- PubMed integration (NCBI Entrez API)
- Semantic embeddings (SentenceTransformer)
- Vector search (FAISS)
- Severity classification: LETHAL, SEVERE, MODERATE, MILD, UNKNOWN

```bash
k-sites --go-term GO:0006281 --organism 9606 --output report.html \
        --predict-phenotypes --rag-report
```

## Output Files

| File | Description |
|------|-------------|
| `report.html` | Interactive HTML report with visualizations |
| `report_comprehensive.csv` | All genes and metrics |
| `report_gene_summary.csv` | Gene-level summary statistics |
| `rag_reports/*.html` | Per-gene literature analysis (with `--rag-report`) |

---

## Installation

```bash
# Basic installation
pip install k-sites

# With RAG phenotype prediction
pip install 'k-sites[rag]'

# With all features
pip install 'k-sites[all]'
```

## Quick Start

```bash
# Basic analysis
k-sites --go-term GO:0006281 --organism "Homo sapiens" --output report.html

# Full analysis with all features
k-sites --go-term GO:0006281 --organism 9606 --output report.html \
        --max-pleiotropy 5 \
        --evidence-filter experimental \
        --predict-phenotypes --rag-report
```

---

## Version History

| Version | Date | Features |
|---------|------|----------|
| 1.0.0 | 2026-02-05 | Initial release |
| 1.1.0 | 2026-02-13 | Web app, RAG system, enhanced reporting |
| 1.2.0 | 2026-02-13 | RAG reports, improved CLI |
