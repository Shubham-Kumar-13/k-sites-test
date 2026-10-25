#!/usr/bin/env python3
"""
Unified Command-Line Interface for K-Sites

This module serves as the entry point for K-Sites, a tool that helps
scientists pick a safe gene for knockout/deletion using GO, UniProt, KEGG
and PubMed evidence.
"""

import argparse
import os
import sys
import logging
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def validate_and_resolve_organism(organism_input):
    """
    Validate and resolve organism input to NCBI TaxID.
    
    Args:
        organism_input (str): Either NCBI TaxID or scientific name
        
    Returns:
        str: Resolved NCBI TaxID
        
    Raises:
        ValueError: If organism cannot be resolved
    """
    # Check if input is already a numeric tax ID
    if organism_input.isdigit():
        return organism_input
    
    # Try to resolve scientific name to TaxID using common mappings first
    common_organisms = {
        "Homo sapiens": "9606",
        "human": "9606",
        "Mus musculus": "10090",
        "mouse": "10090",
        "Saccharomyces cerevisiae": "4932",
        "yeast": "4932",
        "Drosophila melanogaster": "7227",
        "fruit fly": "7227",
        "Caenorhabditis elegans": "6239",
        "worm": "6239",
        "Danio rerio": "7955",
        "zebrafish": "7955",
        "hsa": "9606",  # KEGG code
        "mmu": "10090",  # KEGG code
        "cel": "6239",  # KEGG code
        "dre": "7955",  # KEGG code
        "sce": "4932"   # KEGG code
    }
    
    organism_normalized = organism_input.strip()
    if organism_normalized in common_organisms:
        return common_organisms[organism_normalized]
    
    # Attempt to resolve using NCBI Entrez (simplified approach)
    try:
        # Import here to avoid heavy dependencies if not needed
        from k_sites.data_retrieval.organism_resolver import resolve_organism_to_taxid
        taxid = resolve_organism_to_taxid(organism_input)
        logger.info(f"Resolved '{organism_input}' to TaxID: {taxid}")
        return taxid
    except ImportError:
        logger.warning("Could not import organism resolver, using common mappings only")
        raise ValueError(f"Organism '{organism_input}' not recognized. Please use either a valid NCBI TaxID or one of the common names: {list(common_organisms.keys())}")
    except Exception as e:
        logger.error(f"Failed to resolve organism '{organism_input}': {str(e)}")
        raise ValueError(f"Could not resolve organism '{organism_input}' to a valid NCBI TaxID")


def validate_go_term(go_term):
    """
    Validate GO term format.
    
    Args:
        go_term (str): GO term to validate
        
    Returns:
        str: Validated GO term
        
    Raises:
        ValueError: If GO term format is invalid
    """
    import re
    
    # GO terms are formatted as GO: followed by 7 digits
    pattern = r'^GO:\d{7}$'
    if not re.match(pattern, go_term.upper()):
        raise ValueError(f"Invalid GO term format: {go_term}. Expected format: GO:0000000")
    
    return go_term.upper()


def make_progress_printer(stream=None):
    """
    Build a ``callback(stage, done, total)`` that shows progress on stderr.

    On a terminal it redraws one line; when output is redirected it prints a line about
    every 10% so logs stay short.
    """
    stream = stream or sys.stderr
    state = {"stage": None, "last": -1}

    def show(stage, done, total):
        total = max(total, 1)
        if stream.isatty():
            stream.write(f"\r  {stage}: {done}/{total}  ")
            if done >= total:
                stream.write("\n")
            stream.flush()
            return
        step = max(1, total // 10)
        if stage != state["stage"] or done >= total or done - state["last"] >= step:
            stream.write(f"  {stage}: {done}/{total} ({100 * done // total}%)\n")
            stream.flush()
            state["stage"], state["last"] = stage, done

    return show


def run_k_sites_analysis(args):
    """
    Execute the main K-Sites analysis workflow.
    
    Args:
        args: Parsed command-line arguments
    """
    logger.info(f"Starting K-Sites analysis for GO term: {args.go_term}, Organism: {args.organism}")
    
    # Validate inputs early
    try:
        taxid = validate_and_resolve_organism(args.organism)
        go_term = validate_go_term(args.go_term)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)
    
    # Import required modules
    try:
        # Import workflow components
        from k_sites.workflow.pipeline import run_k_sites_pipeline
        from k_sites.reporting.report_generator import generate_html_report
        
        # Prepare pipeline parameters
        pipeline_params = {
            'go_term': go_term,
            'organism': taxid,
            'max_pleiotropy': getattr(args, 'max_pleiotropy', 3),  # Default value
            'evidence_filter': getattr(args, 'evidence_filter', 'experimental'),  # Default evidence filter
            'species_validation': getattr(args, 'species_validation', None),  # Default species list
            'predict_phenotypes': getattr(args, 'predict_phenotypes', False),  # Default to False
            'databases': getattr(args, 'databases', ['all']),  # Databases to query
            'max_annotations': getattr(args, 'max_annotations', 2000),  # Safety limit on annotations read
            'knockout_context': getattr(args, 'knockout_context', 'auto'),  # cells or whole organism
            'use_measured_evidence': not getattr(args, 'no_measured_evidence', False),
            'progress_callback': make_progress_printer()
        }
        
        # Execute the main pipeline
        logger.info("Running analysis pipeline...")
        results = run_k_sites_pipeline(**pipeline_params)
        
        # Generate output report
        logger.info(f"Generating HTML report at {args.output}")
        generate_html_report(results, args.output)
        
        # Print summary statistics
        stats = results.get("statistics", {})
        if stats:
            print(f"\nAnalysis Summary:")
            print(f"- Total genes screened: {stats.get('total_genes_screened', 0)}")
            print(f"- Genes passed filter: {stats.get('genes_passed_filter', 0)}")
            print(f"- Genes not scored (insufficient data): {stats.get('genes_insufficient_data', 0)}")
            print(f"- Genes above the pleiotropy cutoff (listed as not shown): {stats.get('genes_above_pleiotropy_cutoff', 0)}")
            levels = stats.get('by_safety_level') or {}
            if levels:
                print("- Safety levels: " + ", ".join(f"{level}: {count}" for level, count in levels.items()))
            basis = stats.get('by_evidence_basis') or {}
            if basis:
                print("- Verdict rests on: " + ", ".join(f"{name}: {count}" for name, count in basis.items()))
            print(f"- Average pleiotropy score: {stats.get('avg_pleiotropy', 0):.2f}")
            most_specific = stats.get('most_specific_gene', {})
            if most_specific:
                print(f"- Most specific gene: {most_specific.get('symbol', 'N/A')} (score: {most_specific.get('specificity_score', 0):.2f})")
        
        for warning in results.get("warnings", []):
            print(f"\nWARNING: {warning}")

        # Generate RAG reports if requested
        if getattr(args, 'rag_report', False) and getattr(args, 'predict_phenotypes', False):
            logger.info("Generating detailed RAG literature reports...")
            try:
                from k_sites.reporting.rag_report_generator import generate_batch_rag_report
                import os
                
                output_dir = os.path.dirname(args.output) or '.'
                rag_output_dir = os.path.join(output_dir, 'rag_reports')
                
                gene_symbols = [gene.get('symbol') for gene in results.get('genes', []) if gene.get('symbol')]
                rag_results = generate_batch_rag_report(gene_symbols, taxid, rag_output_dir)
                
                successful = sum(1 for v in rag_results.values() if v)
                print(f"\n📚 RAG Reports Generated: {successful}/{len(rag_results)} genes")
                print(f"   Location: {rag_output_dir}/")
                
            except Exception as e:
                logger.warning(f"Could not generate RAG reports: {e}")
        
        # Show database usage info
        databases_used = getattr(args, 'databases', ['all'])
        if databases_used:
            print(f"\n🗄️  Databases Used: {', '.join(databases_used)}")
        
        logger.info("Analysis completed successfully!")
        
    except ImportError as e:
        logger.error(f"Import error: {str(e)}")
        logger.error("Make sure all required modules are implemented.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Analysis failed: {str(e)}")
        sys.exit(1)


def main():
    """
    Main entry point for the K-Sites CLI.
    """
    parser = argparse.ArgumentParser(
        description="K-Sites: helps scientists pick a safe gene for knockout by scoring "
                   "pleiotropy, evidence quality, conservation and literature support.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  %(prog)s --go-term GO:0006281 --organism "Homo sapiens" --output report.html
  
  # With RAG phenotype prediction and literature reports
  %(prog)s --go-term GO:0006281 --organism 9606 --output report.html --predict-phenotypes --rag-report
  
  # Select specific databases
  %(prog)s --go-term GO:0006281 --organism 9606 --output report.html --databases quickgo uniprot
  
  # Search for GO terms
  %(prog)s --go-term-search "DNA repair" --organism "Homo sapiens" --output report.html

Database Options (--databases):
  - quickgo:   Gene Ontology annotations (always used for GO term mapping)
  - uniprot:   Protein knowledgebase (protein function, domains)
  - ncbi:      NCBI Entrez gene database (gene summaries)
  - pubmed:    Literature support (PubMed citation counts)
  - kegg:      KEGG pathway database (pathway annotations)
  - all:       Use all available databases (default)

Note:
  - Organism can be NCBI TaxID (e.g., 9606) or scientific name (e.g., "Homo sapiens")
  - GO term format: GO:0000000 (7 digits after GO:)
  - Use --go-term-search to get GO term suggestions with gene count statistics
  - Use --rag-report to generate detailed literature analysis for each gene
        """
    )
    
    parser.add_argument(
        '--go-term',
        required=True,
        help='GO term to analyze (e.g., "GO:0006281" for DNA repair)'
    )
    
    parser.add_argument(
        '--organism',
        required=True,
        help='Organism as NCBI TaxID (e.g., "9606") or scientific name (e.g., "Homo sapiens")'
    )
    
    parser.add_argument(
        '--output',
        required=True,
        help='Output HTML report path'
    )
    
    parser.add_argument(
        '--max-pleiotropy',
        type=int,
        default=10,
        choices=range(0, 11),
        metavar="[0-10]",
        help='Pleiotropy cutoff on the 0-10 score (default: 10). Genes scoring above it are excluded: '
             '0 keeps only the most specific genes, 10 keeps everything.'
    )
    
    parser.add_argument(
        '--max-annotations',
        type=int,
        default=2000,
        help='Safety limit on GO annotations read for the GO term (default: 2000). Very large GO terms '
             'are cut off here and the report says what share was read; raise it to read everything '
             '(slower).'
    )

    parser.add_argument(
        '--evidence-filter',
        choices=['experimental', 'computational', 'all'],
        default='experimental',
        help='Which GO evidence counts: experimental = only roles proven in lab experiments '
             '(strict, but can make poorly studied genes look specific); computational = only '
             'predicted roles; all = every known role, the most cautious about pleiotropy '
             '(default: experimental)'
    )
    
    parser.add_argument(
        '--knockout-context',
        choices=['auto', 'cells', 'organism'],
        default='auto',
        help='What you will knock out: cells = cultured cells (the verdict follows the DepMap CRISPR screens), '
             'organism = a whole animal, plant or yeast (it follows the knockout organism), auto = cells for '
             'human and organism otherwise (default: auto)'
    )

    parser.add_argument(
        '--no-measured-evidence',
        action='store_true',
        help='Ignore the measured knockout data (MGI, IMPC, DepMap, ...) and rate genes from annotations and '
             'predictions alone. The data come from KSITES_EVIDENCE_DIR or KSITES_EVIDENCE_URL.'
    )

    parser.add_argument(
        '--species-validation',
        nargs='+',
        help='Species taxids for cross-species validation (space-separated, e.g., 9606 10090 10116)'
    )
    
    parser.add_argument(
        '--predict-phenotypes',
        action='store_true',
        help='Enable RAG-based phenotype prediction using literature mining (default: false)'
    )
    
    parser.add_argument(
        '--rag-report',
        action='store_true',
        help='Generate detailed RAG literature analysis reports for each gene (requires --predict-phenotypes)'
    )
    
    parser.add_argument(
        '--databases',
        nargs='+',
        choices=['quickgo', 'uniprot', 'ncbi', 'pubmed', 'kegg', 'all'],
        default=['all'],
        help='Select databases to query (default: all). Options: quickgo, uniprot, ncbi, pubmed, kegg, all'
    )
    
    parser.add_argument(
        '--go-term-search',
        type=str,
        help='Search for GO terms with autocomplete functionality and gene count statistics (e.g., "DNA repair")'
    )
    
    args = parser.parse_args()
    
    # Handle GO term search functionality
    if args.go_term_search:
        from k_sites.data_retrieval.go_autocomplete import get_go_term_suggestions, get_gene_count_for_go_term
        print(f"Searching for GO terms related to: '{args.go_term_search}'")
        suggestions = get_go_term_suggestions(args.go_term_search, limit=10)
        
        if suggestions:
            print(f"\nTop GO term suggestions for '{args.go_term_search}':")
            print("-" * 80)
            print(f"{'GO ID':<12} {'Term Name':<30} {'Genes in Human':<15} {'Aspect':<8}")
            print("-" * 80)
            
            for suggestion in suggestions:
                gene_count = get_gene_count_for_go_term(suggestion['id'], '9606')  # Human taxid
                print(f"{suggestion['id']:<12} {suggestion['name'][:30]:<30} {gene_count:<15} {suggestion['aspect']:<8}")
        else:
            print(f"No GO terms found matching '{args.go_term_search}'")
        
        return  # Exit after showing search results
    
    run_k_sites_analysis(args)


if __name__ == "__main__":
    main()