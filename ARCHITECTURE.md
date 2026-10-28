# Universal K-Sites Architecture Document

## Overview
K-Sites is a non-pleiotropic gene-selection platform that uses GO term analysis, multi-database gene annotation, and measured knockout evidence to help scientists choose safe genes for knockout studies.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                INPUT LAYER                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  GO Term (e.g., "GO:0006281") + Organism (NCBI TaxID or scientific name)   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           WORKFLOW CONTROLLER                               │
├─────────────────────────────────────────────────────────────────────────────┤
│  Coordinates module execution, manages data flow                           │
│  Orchestrates GO and KEGG pathway integration                              │
│  Generates final HTML/CSV reports                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MODULE LAYER                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐            │
│  │  DATA RETRIEVAL │  │  GENE ANALYSIS  │  │    WORKFLOW     │            │
│  │                 │  │                 │  │                 │            │
│  │ • GO annotations│  │ • Pleiotropy    │  │ • Pipeline      │            │
│  │ • Gene data     │  │   scoring       │  │ • Data          │            │
│  │ • Organism data │  │ • Specificity   │  │   orchestration │            │
│  │ • KEGG mapping  │  │   analysis      │  │ • Integration   │            │
│  └─────────────────┘  │ • Evidence      │  └─────────────────┘            │
│                       │   filtering     │                                │
│                       └─────────────────┘                                │
│                              │                                             │
│                              ▼                                             │
│  ┌─────────────────┐  ┌─────────────────┐                                │
│  │   RAG SYSTEM    │  │     OTHER       │                                │
│  │                 │  │                 │                                │
│  │ • PubMed mining │  │ • Configuration │                                │
│  │ • Literature    │  │ • Logging       │                                │
│  │   context       │  │ • Error hand.   │                                │
│  └─────────────────┘  └─────────────────┘                                │
│           │                                                                │
│           ▼                                                                │
│  ┌─────────────────┐                                                       │
│  │     CLI         │                                                       │
│  │                 │                                                       │
│  │ • Command       │                                                       │
│  │   interface     │                                                       │
│  │ • Args parsing  │                                                       │
│  └─────────────────┘                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              OUTPUT LAYER                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  HTML Report: Gene-specific safety recommendations and pleiotropy metrics  │
│  CSV Export: Detailed gene metrics and knockout evidence                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Module Structure

### `k_sites/` (Root Package)
- `__init__.py`: Package initialization and version info

### `k_sites/data_retrieval/` (Data Access Layer)
- `entrez_client.py`: NCBI Entrez API integration
- `quickgo_client.py`: QuickGO API integration for GO annotations
- `organism_resolver.py`: Scientific name ↔ NCBI TaxID conversion
- `gene_fetcher.py`: Gene information retrieval
- `kegg_mapper.py`: KEGG pathway mapping for GO terms

### `k_sites/gene_analysis/` (Analysis Layer)
- `pleiotropy_scorer.py`: Pleiotropy scoring using GO Biological Process annotations
- `specificity_analyzer.py`: GO term specificity analysis
- `filter_engine.py`: Gene filtering based on integrated metrics

### `k_sites/rag_system/` (Knowledge Layer)
- `pubmed_miner.py`: PubMed literature mining
- `uniprot_client.py`: UniProt data integration
- `kegg_literature_miner.py`: KEGG-specific literature context
- `context_analyzer.py`: Combined literature and pathway context extraction

### `k_sites/workflow/` (Orchestration Layer)
- `pipeline.py`: Main workflow orchestration with GO and KEGG integration
- `report_generator.py`: HTML/CSV report generation with safety recommendations and knockout evidence
- `data_aggregator.py`: Results aggregation from all sources

### `k_sites/cli.py` (Interface Layer)
- Command-line interface implementation supporting both original and enhanced functionality

## Enhanced Data Flow

1. **Input Processing**: GO term and organism are validated and normalized
2. **Data Retrieval**: 
   - NCBI Entrez resolves organism TaxID
   - QuickGO provides GO annotations for the target term
   - UniProt provides protein-level annotations
   - KEGG provides pathway annotations
3. **Gene Filtering and Scoring**:
   - GO-based pleiotropy scoring
   - Evidence-quality filtering
   - Composite ranking by specificity, evidence, literature support, and conservation
4. **Measured Knockout Evidence**: Cross-species knockout viability and cell-line essentiality are assessed per gene
5. **Optional Phenotype Prediction**: RAG-based literature mining predicts phenotypes only for genes without measured evidence
6. **Report Generation**: HTML/CSV reports with safety recommendations and supporting evidence

## Technology Stack

- **Backend**: Python 3.8+
- **Data Retrieval**: NCBI Entrez E-Utilities, QuickGO REST API, UniProt REST API, KEGG API
- **Scientific Libraries**: Biopython, NumPy, Pandas
- **Web Requests**: requests library
- **Report Generation**: Jinja2 templates for HTML, built-in CSV module
- **Testing**: pytest for unit testing

## Integration Points

- **KEGG Pathway Mapping**: KEGG API and local mapping files provide pathway annotations used for pleiotropy context.
- **Measured Knockout Evidence**: Model-organism databases (MGI, IMPC, SGD, ZFIN, FlyBase, WormBase) and DepMap are integrated via the evidence provider.

## Deployment Considerations

- Modular design enables easy testing and maintenance
- API rate limiting handled appropriately
- Caching mechanisms for repeated queries
- Configuration management for API keys and email settings