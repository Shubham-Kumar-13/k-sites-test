"""
Self-contained integration demo for Universal K-Sites pipeline.

This demo validates the full pipeline works end-to-end according to OpenClaw demo conventions.
"""

import os
import sys
import logging
from pathlib import Path
import csv
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add the k-sites package to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from k_sites.config import get_config
    from k_sites.data_retrieval.organism_resolver import resolve_organism
    from k_sites.data_retrieval.go_gene_mapper import get_genes_for_go_term
    from k_sites.workflow.pipeline import run_k_sites_pipeline
    from k_sites.reporting.report_generator import generate_html_report
except ImportError as e:
    logger.error(f"Failed to import K-Sites modules: {e}")
    logger.error("Make sure you're running this from the K-Sites root directory")
    sys.exit(1)


def check_prerequisites():
    """Check if all prerequisites are met for the demo."""
    logger.info("Checking prerequisites...")
    
    # Check if config is available
    try:
        config = get_config()
        logger.info("✓ Configuration loaded successfully")
    except Exception as e:
        logger.error(f"✗ Failed to load configuration: {e}")
        return False
    
    # Check if NCBI email is configured
    if not config.ncbi.email or config.ncbi.email == "user@example.com":
        logger.error("✗ NCBI email not configured properly")
        return False
    else:
        logger.info("✓ NCBI email configured")
    
    return True


def generate_csv_export(pipeline_output, output_path):
    """Generate a gene-level CSV export of the safety results."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', newline='') as csvfile:
        fieldnames = [
            'gene_symbol', 'gene_description', 'pleiotropy_score', 
            'specificity_score', 'composite_score', 'kegg_pathway_count',
            'safety_level', 'primary_recommendation'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for gene in pipeline_output.get('genes', []):
            safety_rec = gene.get('safety_recommendation', {})
            writer.writerow({
                'gene_symbol': gene.get('symbol', ''),
                'gene_description': gene.get('description', ''),
                'pleiotropy_score': gene.get('pleiotropy_score', ''),
                'specificity_score': gene.get('specificity_score', ''),
                'composite_score': gene.get('composite_score', ''),
                'kegg_pathway_count': gene.get('kegg_pathway_count', ''),
                'safety_level': safety_rec.get('safety_level', ''),
                'primary_recommendation': safety_rec.get('primary_recommendation', '')
            })
    
    logger.info(f"CSV export saved to {output_path}")


def run_demo():
    """Run the full integration demo."""
    logger.info("="*60)
    logger.info("UNIVERSAL K-SITES PIPELINE DEMO")
    logger.info("="*60)
    
    # Check prerequisites
    if not check_prerequisites():
        logger.error("Demo prerequisites not met. Exiting.")
        return False
    
    # Create output directory
    output_dir = Path("demo/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Define test case
    go_term = "GO:0006281"  # DNA repair
    organism = "Homo sapiens"
    max_pleiotropy = 3
    
    logger.info(f"\nRunning pipeline on test case:")
    logger.info(f"  GO term: {go_term}")
    logger.info(f"  Organism: {organism}")
    logger.info(f"  Max pleiotropy: {max_pleiotropy}")
    
    try:
        # Run the pipeline
        logger.info("\nExecuting K-Sites pipeline...")
        start_time = datetime.now()
        
        pipeline_output = run_k_sites_pipeline(
            go_term=go_term,
            organism=organism,
            max_pleiotropy=max_pleiotropy
        )
        
        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()
        
        logger.info(f"Pipeline completed in {execution_time:.2f} seconds")
        
        # Validate outputs
        logger.info("\nValidating outputs...")
        
        genes = pipeline_output.get('genes', [])
        total_genes = len(genes)
        
        logger.info(f"  ✓ {total_genes} genes passed pleiotropy filter")
        
        # Check that at least one gene passed
        if total_genes == 0:
            logger.error("✗ No genes passed the pleiotropy filter")
            return False
        
        logger.info("  ✓ At least one gene passed pleiotropy filter")
        
        # Generate HTML report
        html_report_path = output_dir / "report.html"
        logger.info(f"\nGenerating HTML report at {html_report_path}...")
        generate_html_report(pipeline_output, str(html_report_path))
        logger.info("  ✓ HTML report generated successfully")
        
        # Generate CSV export
        csv_path = output_dir / "genes.csv"
        logger.info(f"\nGenerating CSV export at {csv_path}...")
        generate_csv_export(pipeline_output, str(csv_path))
        logger.info("  ✓ CSV export generated successfully")
        
        # Display summary
        logger.info("\n" + "="*60)
        logger.info("DEMO SUMMARY")
        logger.info("="*60)
        logger.info(f"Input GO term: {go_term}")
        logger.info(f"Input organism: {organism}")
        logger.info(f"Max pleiotropy: {max_pleiotropy}")
        logger.info(f"Execution time: {execution_time:.2f} seconds")
        logger.info(f"Genes passing filter: {total_genes}")
        logger.info(f"Output HTML report: {html_report_path}")
        logger.info(f"Output CSV export: {csv_path}")
        
        # Show some sample results
        if genes:
            logger.info("\nSample results:")
            for i, gene in enumerate(genes[:3]):  # Show first 3 genes
                gene_symbol = gene.get('symbol', 'Unknown')
                gene_score = gene.get('pleiotropy_score', 'N/A')
                safety_level = (gene.get('safety_recommendation') or {}).get('safety_level', 'UNKNOWN')
                logger.info(f"  Gene {i+1}: {gene_symbol} (pleiotropy: {gene_score}, safety: {safety_level})")
        
        logger.info("\n✓ Demo completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"✗ Demo failed with error: {e}")
        import traceback
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        return False


if __name__ == "__main__":
    success = run_demo()
    sys.exit(0 if success else 1)