"""
K-Sites Mouse Gene Analysis Example

This script runs the K-Sites pipeline on mouse genes associated with DNA repair (GO:0006281)
and ranks them by how safe they are to delete.
Results are saved to the mouse_analysis_results directory.
"""

import os
import sys
import logging
from pathlib import Path
import csv
import json
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Ensure K-Sites is on the path
sys.path.insert(0, str(Path(__file__).parent))

# Set required environment variables
os.environ["K_SITES_NCBI_EMAIL"] = "user@example.com"

from k_sites.workflow.pipeline import run_k_sites_pipeline
from k_sites.reporting.report_generator import generate_html_report


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


def generate_json_export(pipeline_output, output_path):
    """Generate a JSON export of the full results."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Create a copy without non-serializable objects
    export_data = {
        "metadata": pipeline_output.get("metadata", {}),
        "statistics": pipeline_output.get("statistics", {}),
        "genes": []
    }
    
    for gene in pipeline_output.get('genes', []):
        gene_data = {
            "symbol": gene.get("symbol"),
            "description": gene.get("description"),
            "entrez_id": gene.get("entrez_id"),
            "pleiotropy_score": gene.get("pleiotropy_score"),
            "specificity_score": gene.get("specificity_score"),
            "evidence_quality": gene.get("evidence_quality"),
            "literature_support": gene.get("literature_support"),
            "conservation_score": gene.get("conservation_score"),
            "composite_score": gene.get("composite_score"),
            "bp_term_count": gene.get("bp_term_count"),
            "experimental_evidence_count": gene.get("experimental_evidence_count"),
            "computational_evidence_count": gene.get("computational_evidence_count"),
            "iea_evidence_count": gene.get("iea_evidence_count"),
            "cross_species_validation": gene.get("cross_species_validation"),
            "safety_recommendation": gene.get("safety_recommendation"),
            "kegg_pathway_count": gene.get("kegg_pathway_count")
        }
        export_data["genes"].append(gene_data)
    
    with open(output_path, 'w') as f:
        json.dump(export_data, f, indent=2)
    
    logger.info(f"JSON export saved to {output_path}")


def run_mouse_analysis():
    """Run the K-Sites pipeline on mouse genes."""
    logger.info("="*70)
    logger.info("K-SITES MOUSE GENE ANALYSIS")
    logger.info("="*70)
    
    # Create output directory
    output_dir = Path("mouse_analysis_results")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Define test case for mice
    # Using DNA repair pathway (GO:0006281) in Mus musculus (mouse)
    go_term = "GO:0006281"  # DNA repair
    organism = "Mus musculus"  # Mouse - TaxID: 10090
    max_pleiotropy = 5  # Slightly higher to capture more genes for demo
    
    logger.info(f"\nAnalysis Parameters:")
    logger.info(f"  GO term: {go_term} (DNA repair)")
    logger.info(f"  Organism: {organism} (TaxID: 10090)")
    logger.info(f"  Max pleiotropy: {max_pleiotropy}")
    
    try:
        # Run the pipeline
        logger.info("\nExecuting K-Sites pipeline...")
        start_time = datetime.now()
        
        pipeline_output = run_k_sites_pipeline(
            go_term=go_term,
            organism=organism,
            max_pleiotropy=max_pleiotropy,
            evidence_filter="experimental",
            species_validation=["10090", "9606"],  # Validate in mouse and human
            predict_phenotypes=False  # Skip phenotype prediction for faster results
        )
        
        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()
        
        logger.info(f"\nPipeline completed in {execution_time:.2f} seconds")
        
        # Validate outputs
        genes = pipeline_output.get('genes', [])
        total_genes = len(genes)
        
        logger.info(f"\nResults Summary:")
        logger.info(f"  Genes passing pleiotropy filter: {total_genes}")
        
        if total_genes == 0:
            logger.warning("No genes passed the pleiotropy filter")
            return False
        
        # Generate outputs
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # HTML report
        html_report_path = output_dir / f"mouse_analysis_{timestamp}.html"
        logger.info(f"\nGenerating HTML report...")
        generate_html_report(pipeline_output, str(html_report_path))
        logger.info(f"  ✓ HTML report: {html_report_path}")
        
        # CSV export
        csv_path = output_dir / f"mouse_analysis_{timestamp}.csv"
        logger.info(f"\nGenerating CSV export...")
        generate_csv_export(pipeline_output, str(csv_path))
        logger.info(f"  ✓ CSV export: {csv_path}")
        
        # JSON export
        json_path = output_dir / f"mouse_analysis_{timestamp}.json"
        logger.info(f"\nGenerating JSON export...")
        generate_json_export(pipeline_output, str(json_path))
        logger.info(f"  ✓ JSON export: {json_path}")
        
        # Display detailed results
        logger.info("\n" + "="*70)
        logger.info("DETAILED RESULTS")
        logger.info("="*70)
        
        for i, gene in enumerate(genes):
            gene_symbol = gene.get('symbol', 'Unknown')
            pleiotropy = gene.get('pleiotropy_score', 'N/A')
            specificity = gene.get('specificity_score', 'N/A')
            composite = gene.get('composite_score', 'N/A')
            safety = gene.get('safety_recommendation', {})
            safety_level = safety.get('safety_level', 'UNKNOWN')
            
            logger.info(f"\nGene {i+1}: {gene_symbol}")
            logger.info(f"  Pleiotropy Score: {pleiotropy}")
            logger.info(f"  Specificity Score: {specificity}")
            logger.info(f"  Composite Score: {composite}")
            logger.info(f"  Safety Level: {safety_level}")
        
        logger.info("\n" + "="*70)
        logger.info("ANALYSIS COMPLETE")
        logger.info("="*70)
        logger.info(f"Output files saved to: {output_dir.absolute()}")
        logger.info(f"  - HTML Report: {html_report_path.name}")
        logger.info(f"  - CSV Export: {csv_path.name}")
        logger.info(f"  - JSON Export: {json_path.name}")
        
        return True
        
    except Exception as e:
        logger.error(f"Analysis failed with error: {e}")
        import traceback
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        return False


if __name__ == "__main__":
    success = run_mouse_analysis()
    sys.exit(0 if success else 1)
