"""
CSV Export Module for K-Sites

Handles comprehensive CSV export functionality with all required fields
for further analysis and sharing.
"""

import csv
import os
from typing import Dict, List, Any
import logging

# Set up logging
logger = logging.getLogger(__name__)


def generate_comprehensive_csv_report(pipeline_output: Dict[str, Any], csv_path: str) -> None:
    """
    Generate a comprehensive CSV report with all results and metrics.
    
    Args:
        pipeline_output: Output dictionary from run_k_sites_pipeline
        csv_path: Path to save the CSV report
    """
    logger.info(f"Generating comprehensive CSV report at {csv_path}")
    
    try:
        genes = pipeline_output.get("genes", [])
        metadata = pipeline_output.get("metadata", {})
        statistics = pipeline_output.get("statistics", {})
        
        # Prepare CSV data
        rows = []
        
        # Add metadata as header comments
        header_comments = [
            ["# K-Sites Gene Selection Report"],
            [f"# GO Term: {metadata.get('go_term', 'N/A')}"],
            [f"# Organism: {metadata.get('organism', 'N/A')}"],
            [f"# Timestamp: {metadata.get('timestamp', 'N/A')}"],
            [f"# Execution Duration: {metadata.get('execution_duration', 'N/A')} seconds"],
            ["#"],
            ["# Columns:"],
            ["# - Gene_Symbol: Official gene symbol"],
            ["# - Gene_Description: Brief description of the gene"],
            ["# - Entrez_ID: NCBI Entrez Gene ID"],
            ["# - Pleiotropy_Score: Calculated pleiotropy score (0-10 scale)"],
            ["# - Specificity_Score: Inverse of pleiotropy score (higher is better)"],
            ["# - Evidence_Quality: Quality of supporting evidence (0-1 scale)"],
            ["# - Literature_Support: Estimated literature support (0-1 scale)"],
            ["# - Conservation_Score: Cross-species conservation score"],
            ["# - Composite_Score: Overall ranking score"],
            ["# - BP_Term_Count: Number of Biological Process GO terms"],
            ["# - Experimental_Evidence_Count: Number of experimental evidence codes"],
            ["# - Computational_Evidence_Count: Number of computational evidence codes"],
            ["# - IEA_Evidence_Count: Number of IEA (computational) evidence codes"],
            ["# - Phenotype_Severity: Predicted knockout phenotype severity"],
            ["# - Phenotype_Risk_Level: Risk level based on phenotype prediction"],
            ["# - Phenotype_Confidence: Confidence in phenotype prediction"],
            ["# - Phenotype_Lethality_Stage: Developmental stage of predicted lethality"],
            ["# - Safety_Recommendation: Recommended experimental approach"],
            ["#"]
        ]
        
        rows.extend(header_comments)
        
        # Add header row
        header = [
            "Gene_Symbol", "Gene_Description", "Entrez_ID", "Pleiotropy_Score", 
            "Specificity_Score", "Evidence_Quality", "Literature_Support", 
            "Conservation_Score", "Composite_Score", "BP_Term_Count",
            "Experimental_Evidence_Count", "Computational_Evidence_Count", 
            "IEA_Evidence_Count", "KEGG_Pathway_Count",
            "Phenotype_Severity", "Phenotype_Risk_Level", "Phenotype_Confidence",
            "Phenotype_Lethality_Stage", "Safety_Recommendation"
        ]
        rows.append(header)
        
        # Add data rows
        for gene in genes:
            gene_symbol = gene.get("symbol", "")
            gene_description = gene.get("description", "")
            entrez_id = gene.get("entrez_id", "")
            pleiotropy_score = gene.get("pleiotropy_score", "")
            specificity_score = gene.get("specificity_score", "")
            evidence_quality = gene.get("evidence_quality", "")
            literature_support = gene.get("literature_support", "")
            conservation_score = gene.get("conservation_score", "")
            composite_score = gene.get("composite_score", "")
            bp_term_count = gene.get("bp_term_count", "")
            exp_count = gene.get("experimental_evidence_count", "")
            comp_count = gene.get("computational_evidence_count", "")
            iea_count = gene.get("iea_evidence_count", "")
            kegg_count = gene.get("kegg_pathway_count", "")
            
            # Get phenotype prediction if available
            phenotype_pred = gene.get("phenotype_prediction", {})
            if phenotype_pred:
                phenotype_severity = phenotype_pred.get("severity", {}).value if hasattr(phenotype_pred.get("severity", {}), "value") else str(phenotype_pred.get("severity", ""))
                phenotype_risk = phenotype_pred.get("risk_level", {}).value if hasattr(phenotype_pred.get("risk_level", {}), "value") else str(phenotype_pred.get("risk_level", ""))
                phenotype_confidence = phenotype_pred.get("confidence_score", "")
                phenotype_stage = phenotype_pred.get("lethality_stage", "")
                confidence_reasoning = phenotype_pred.get("confidence_reasoning", "")
            else:
                phenotype_severity = ""
                phenotype_risk = ""
                phenotype_confidence = ""
                phenotype_stage = ""
                confidence_reasoning = ""
            
            # Determine safety recommendation based on phenotype and other factors
            if phenotype_pred and phenotype_risk in ["CRITICAL", "HIGH"]:
                safety_recommendation = "Conditional KO/CRISPRi preferred"
            elif pleiotropy_score > 5:
                safety_recommendation = "Consider heterozygous KO"
            else:
                safety_recommendation = "Standard KO acceptable"
            
            rows.append([
                gene_symbol, gene_description, entrez_id, pleiotropy_score,
                specificity_score, evidence_quality, literature_support,
                conservation_score, composite_score, bp_term_count,
                exp_count, comp_count, iea_count, kegg_count,
                phenotype_severity, phenotype_risk, phenotype_confidence,
                phenotype_stage, safety_recommendation
            ])
        
        # Add statistics summary
        rows.append([])
        rows.append(["# Analysis Statistics"])
        rows.append([f"# Total Genes Screened: {statistics.get('total_genes_screened', 0)}"])
        rows.append([f"# Genes Passed Filter: {statistics.get('genes_passed_filter', 0)}"])
        rows.append([f"# Average Pleiotropy Score: {statistics.get('avg_pleiotropy', 0):.2f}"])
        
        most_specific = statistics.get('most_specific_gene', {})
        if most_specific:
            rows.append([f"# Most Specific Gene: {most_specific.get('symbol', 'N/A')} (score: {most_specific.get('specificity_score', 0):.2f})"])
        
        least_specific = statistics.get('least_specific_gene', {})
        if least_specific:
            rows.append([f"# Least Specific Gene: {least_specific.get('symbol', 'N/A')} (score: {least_specific.get('specificity_score', 0):.2f})"])
        
        # Write CSV file
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerows(rows)
        
        logger.info(f"Successfully generated comprehensive CSV report at {csv_path}")
        
    except Exception as e:
        logger.error(f"Failed to generate comprehensive CSV report: {str(e)}")
        raise


def generate_gene_summary_csv(pipeline_output: Dict[str, Any], csv_path: str) -> None:
    """
    Generate a gene-focused CSV report with summary information for each gene.
    
    Args:
        pipeline_output: Output dictionary from run_k_sites_pipeline
        csv_path: Path to save the CSV report
    """
    logger.info(f"Generating gene summary CSV report at {csv_path}")
    
    try:
        genes = pipeline_output.get("genes", [])
        
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'gene_symbol', 'gene_description', 'entrez_id', 'pleiotropy_score',
                'specificity_score', 'evidence_quality', 'literature_support',
                'conservation_score', 'composite_score', 'bp_term_count',
                'experimental_evidence_count', 'computational_evidence_count',
                'iea_evidence_count', 'kegg_pathway_count', 'phenotype_severity',
                'phenotype_risk_level', 'safety_recommendation', 'safety_justification'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            for gene in genes:
                phenotype_pred = gene.get("phenotype_prediction", {})
                if phenotype_pred:
                    phenotype_severity = phenotype_pred.get("severity", {}).value if hasattr(phenotype_pred.get("severity", {}), "value") else str(phenotype_pred.get("severity", ""))
                    phenotype_risk = phenotype_pred.get("risk_level", {}).value if hasattr(phenotype_pred.get("risk_level", {}), "value") else str(phenotype_pred.get("risk_level", ""))
                else:
                    phenotype_severity = ""
                    phenotype_risk = ""
                
                # Use the comprehensive safety recommendation from pipeline
                safety_recommendation = gene.get("safety_recommendation", "")
                safety_justification = gene.get("safety_justification", "")
                
                writer.writerow({
                    'gene_symbol': gene.get('symbol', ''),
                    'gene_description': gene.get('description', ''),
                    'entrez_id': gene.get('entrez_id', ''),
                    'pleiotropy_score': gene.get('pleiotropy_score', ''),
                    'specificity_score': gene.get('specificity_score', ''),
                    'evidence_quality': gene.get('evidence_quality', ''),
                    'literature_support': gene.get('literature_support', ''),
                    'conservation_score': gene.get('conservation_score', ''),
                    'composite_score': gene.get('composite_score', ''),
                    'bp_term_count': gene.get('bp_term_count', ''),
                    'experimental_evidence_count': gene.get('experimental_evidence_count', ''),
                    'computational_evidence_count': gene.get('computational_evidence_count', ''),
                    'iea_evidence_count': gene.get('iea_evidence_count', ''),
                    'kegg_pathway_count': gene.get('kegg_pathway_count', ''),
                    'phenotype_severity': phenotype_severity,
                    'phenotype_risk_level': phenotype_risk,
                    'safety_recommendation': safety_recommendation,
                    'safety_justification': safety_justification
                })
        
        logger.info(f"Successfully generated gene summary CSV report at {csv_path}")
        
    except Exception as e:
        logger.error(f"Failed to generate gene summary CSV report: {str(e)}")
        raise