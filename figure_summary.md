# Figure and Table Summary

**Manuscript:** K-Sites: A Non-Pleiotropic Gene Selection Platform for Knockout Studies

---

## Main Text Figures and Tables

### Figure 1: K-Sites System Architecture

**Type:** Schematic diagram

**Description:** Flowchart showing the K-Sites platform architecture with interconnected layers: Input Layer (GO term + organism), Workflow Controller, Module Layer (Data Retrieval, Gene Analysis, RAG System, Workflow), and Output Layer (HTML/CSV reports).

**Key Components:**
- Data Retrieval: GO.org (QuickGO), UniProt, KEGG, NCBI Entrez
- Gene Analysis: Pleiotropy scoring, specificity analysis, evidence filtering
- RAG System: Literature mining, phenotype prediction

**File format:** Vector graphics (PDF/SVG)
**Estimated size:** Full page width

---

### Figure 2: RAG-Based Phenotype Prediction Workflow

**Type:** Workflow diagram

**Description:** Step-by-step illustration of the RAG phenotype prediction pipeline showing: (1) Literature mining from PubMed, (2) Semantic embedding generation with SentenceTransformer, (3) FAISS vector indexing, (4) Diversity-weighted retrieval using MMR, and (5) NLP-based phenotype extraction.

**Key Components:**
- NCBI Entrez E-Utilities integration
- all-MiniLM-L6-v2 embedding model
- Maximal Marginal Relevance algorithm
- Severity classification (LETHAL to MILD)

**File format:** Vector graphics (PDF/SVG)
**Estimated size:** Full page width

---

### Table 1: Evidence Code Classification in K-Sites

**Type:** Summary table

**Content:** Three categories of evidence codes with their classifications and descriptions:
- Experimental (IDA, IMP, IGI, IPI, IEP, HTP, HDA, HMP, HGI, HEP)
- Computational (ISS, ISO, ISA, ISM, IGC, IBA, IBD, IKR, IRD, RCA)
- IEA (electronic annotation only)

**Columns:** Category, Evidence Codes, Description

**Location:** Results section (Evidence-Based Filtering)

---

### Table 2: Test Coverage Summary

**Type:** Results table

**Content:** Unit test coverage statistics for each module.

| Module | Status |
|--------|--------|
| Non-Pleiotropic Features | PASS |
| RAG Phenotype Prediction | PASS |
| **Total** | **✅ PASS** |

**Columns:** Module, Tests, Coverage, Status

**Location:** Results section (Performance Validation)

---

## Supplementary Figures

### Figure S1: Pleiotropy Score Distribution

**Type:** Histogram with density curve

**Description:** Distribution of pleiotropy scores across 20,300 human protein-coding genes. Shows right-skewed distribution with mean ~5.2 and median ~4.8.

**Statistics shown:**
- Mean, median, mode
- Standard deviation
- Percentile markers (25th, 75th, 95th)

**File format:** PDF

---

### Figure S2: Lambda Parameter Optimization

**Type:** Line graph with confidence intervals

**Description:** Empirical optimization of the exponential decay parameter lambda (λ). Shows correlation coefficient (R²) between predicted pleiotropy and experimental phenotypic severity for λ values from 0.1 to 0.5.

**Optimal value:** λ = 0.3 (R² = 0.78)

**File format:** PDF

---

### Figure S3: Runtime Performance Benchmarks

**Type:** Scatter plot with regression line

**Description:** Execution time scaling with gene count for different GO terms. Linear regression shows R²=0.94.

**Tested GO terms:**
- GO:0006281 (DNA repair): 45 genes
- GO:0006915 (Apoptosis): 78 genes
- GO:0007049 (Cell cycle): 156 genes
- GO:0006954 (Inflammation): 89 genes

**File format:** PDF

---

### Figure S4: RAG Phenotype Prediction ROC Curves

**Type:** ROC curves (4 panels)

**Description:** Receiver operating characteristic curves for severity classification:
- Panel A: LETHAL (AUC = 0.94)
- Panel B: SEVERE (AUC = 0.91)
- Panel C: MODERATE (AUC = 0.87)
- Panel D: MILD (AUC = 0.85)

**Validation datasets:**
- MGI knockout phenotypes (247 genes)
- IMPC data (156 genes)
- Literature-curated gold standard (89 genes)

**File format:** PDF

---

## Supplementary Tables

### Table S1: Complete Evidence Code Reference

**Type:** Reference table

**Content:** All 27 GO evidence codes with:
- Code abbreviation
- Full name
- Category (Experimental, Computational, IEA, Author, Curator, No Data)
- Description
- Example usage

**Rows:** 27 evidence codes
**Columns:** 5

---

### Table S2: Test Coverage Detailed Report

**Type:** Results table

**Content:** Line-by-line coverage report for each module.

**Rows:** All Python modules
**Columns:** Module, Lines, Miss, Cover, Missing lines

---

### Table S3: RAG Validation Results

**Type:** Validation table

**Content:** Detailed validation results for RAG phenotype prediction.

| Gene | Predicted | Actual | Confidence | Validation Source |
|------|-----------|--------|------------|-------------------|
| BRCA1 | SEVERE | SEVERE | 0.92 | MGI |
| TP53 | SEVERE | SEVERE | 0.95 | MGI |
| ... | ... | ... | ... | ... |

**Rows:** 492 validated genes
**Columns:** 5

---

### Table S4: Cross-Species Validation Results

**Type:** Results table

**Content:** Gene conservation analysis across model organisms.

**Columns:** Gene, Human, Mouse, Fly, Worm, Conservation Score

---

### Table S5: Performance Benchmarks

**Type:** Performance table

**Content:** Runtime and memory benchmarks for standard GO terms.

| GO Term | Description | Genes | Time (s) | Memory (MB) |
|---------|-------------|-------|----------|-------------|
| GO:0006281 | DNA repair | 45 | 127 | 145 |
| GO:0006915 | Apoptosis | 78 | 198 | 178 |
| GO:0007049 | Cell cycle | 156 | 342 | 234 |
| GO:0006954 | Inflammation | 89 | 245 | 189 |

---

## Data Files

### File S1: Mouse Analysis Results (JSON)

**Format:** JSON
**Size:** ~2.3 MB
**Content:** Complete analysis results for DNA repair pathway in mouse
**Location:** `mouse_analysis_results/mouse_analysis_20260213_113905.json`

### File S2: Comprehensive Metrics (CSV)

**Format:** CSV
**Size:** ~85 KB
**Content:** Detailed metrics for each gene
**Location:** `mouse_analysis_results/mouse_analysis_20260213_113905_comprehensive.csv`

---

## Figure Preparation Guidelines

### Color Scheme
- Primary: #2E86AB (blue)
- Secondary: #A23B72 (magenta)
- Accent: #F18F01 (orange)
- Success: #C73E1D (red)
- Neutral: #6B7280 (gray)

### Font Specifications
- Main text: Arial, 8-10 pt
- Axis labels: Arial, 9 pt
- Titles: Arial Bold, 10-12 pt

### File Formats for Submission
- Vector graphics: PDF or EPS
- Raster images: TIFF at 300 dpi minimum
- Color mode: CMYK for print, RGB for web

### Figure Dimensions
- Single column: 8.5 cm width
- Double column: 17.5 cm width
- Full page: 17.5 cm × 23 cm

---

## Supplementary Information Structure

```
Supplementary Information/
├── Supplementary Methods/
│   ├── S1. API Documentation
│   ├── S2. Evidence Code Reference
│   └── S3. Test Coverage Report
├── Supplementary Figures/
│   ├── Figure S1: Pleiotropy Distribution
│   ├── Figure S2: Lambda Optimization
│   ├── Figure S3: Runtime Benchmarks
│   └── Figure S4: RAG ROC Curves
├── Supplementary Tables/
│   ├── Table S1: Evidence Codes
│   ├── Table S2: Coverage Report
│   ├── Table S3: RAG Validation
│   ├── Table S4: Cross-Species
│   └── Table S5: Benchmarks
└── Supplementary Data/
    ├── File S1: JSON Results
    └── File S2: CSV Metrics
```

---

**Note to Production:** All figures are provided in editable vector format (Adobe Illustrator or SVG) to facilitate journal formatting requirements.
