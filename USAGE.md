# Universal K-Sites Usage Guide

K-Sites is a non-pleiotropic gene-selection platform that uses GO term analysis and measured knockout evidence to help scientists choose safe genes for knockout studies.

## Quick Start

Get started with K-Sites in 3 commands:

```bash
pip install -e .
export NCBI_EMAIL=you@example.com
k-sites --go-term GO:0006281 --organism "Homo sapiens" --output report.html
```

## Prerequisites

1. **Python 3.8+** with pip
2. **NCBI Account**: Register at [https://account.ncbi.nlm.nih.gov/](https://account.ncbi.nlm.nih.gov/) and get an API key (optional but recommended)

## Installation

### Basic Installation
```bash
# Clone or download the K-Sites repository
cd k-sites
pip install -e .
```

## Configuration

Set up your configuration in one of these ways:

### Option 1: Environment Variables
```bash
export NCBI_EMAIL=your.email@example.com
export NCBI_API_KEY=your_ncbi_api_key  # Optional, but increases rate limits
```

### Option 2: Configuration File
Create `k-sites.yaml` in your working directory or `~/.openclaw/workspace/k-sites/config/`:

```yaml
ncbi:
  email: "your.email@example.com"  # Required by NCBI E-Utils
  api_key: "${NCBI_API_KEY}"      # Optional but recommended

pipeline:
  max_pleiotropy: 3
  cache_dir: "~/.k_sites/.cache"

reporting:
  include_literature: true
  max_pubmed_results: 5
```

## Running Analyses

### Basic Command
```bash
k-sites --go-term GO:0006281 --organism "Homo sapiens" --output report.html
```

### Advanced Options
```bash
# Specify organism by TaxID
k-sites --go-term GO:0006281 --organism 9606 --output report.html

# Adjust pleiotropy threshold
k-sites --go-term GO:0006281 --organism "Homo sapiens" --output report.html --max-pleiotropy 2

# Use KEGG organism code
k-sites --go-term GO:0006281 --organism hsa --output report.html
```

## Input Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `--go-term` | GO term to analyze | `GO:0006281` (DNA repair) |
| `--organism` | Organism (name, TaxID, or KEGG code) | `"Homo sapiens"`, `9606`, `hsa` |
| `--output` | Output HTML report path | `report.html` |
| `--max-pleiotropy` | Max allowed pleiotropy score | `10` (default) |

## Output Files

### HTML Report (`*.html`)
- Interactive report with ranked gene tables
- Safety recommendations and measured knockout evidence
- Pathway context and literature information

### CSV Export
- Available within the HTML report interface
- Contains gene metrics and knockout evidence
- Suitable for further analysis or sharing

## Biological Interpretation

### Pleiotropy Score
- **Calculation**: Based on the number of GO Biological Process terms associated with the gene, excluding the target GO term
- **Formula**: `score = 10 × (1 − exp(−0.3 × other_BP_terms))`
- **Interpretation**: Lower scores indicate more specific targets
- **Threshold**: Adjust with `--max-pleiotropy` (default: 10)

## Common Use Cases

### 1. Pathway-Specific Gene Screening
```bash
# Find specific genes in DNA repair pathway
k-sites --go-term GO:0006281 --organism "Homo sapiens" --output dna_repair_report.html
```

### 2. Cancer Pathway Analysis
```bash
# Identify pathway-specific targets for cancer research
k-sites --go-term GO:0007165 --organism "Homo sapiens" --output signal_transduction_report.html
```

### 3. Comparative Analysis
```bash
# Run multiple GO terms and compare results
for go_term in GO:0006281 GO:0006974 GO:0042277; do
  k-sites --go-term $go_term --organism "Mus musculus" --output ${go_term}_mmu.html
done
```

## Troubleshooting

### Common Issues

**Error: "NCBI email not configured"**
- Solution: Set `NCBI_EMAIL` environment variable or configure in YAML file

**Slow performance**
- Solution: Use NCBI API key to increase rate limits

**No genes returned**
- Solution: Verify GO term exists and organism has annotated genes for that term

### Debugging
Run with increased verbosity:
```bash
export PYTHONPATH=$PYTHONPATH:$(pwd)
python -m k_sites.cli --go-term GO:0006281 --organism "Homo sapiens" --output report.html
```

## Wet-Lab Workflow

1. **Identify pathway of interest** (e.g., DNA repair, apoptosis)
2. **Find corresponding GO term** (use [AmiGO](http://amigo.geneontology.org/amigo) database)
3. **Run K-Sites analysis** with your organism
4. **Review HTML report** for the safest-ranked genes and their measured knockout evidence
5. **Choose a gene** based on the safety recommendation and supporting evidence
6. **Design guide RNAs separately** with a dedicated CRISPR design tool (e.g., CRISPOR or CHOPCHOP)