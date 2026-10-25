"""
K-Sites Pipeline Module

This module orchestrates the complete K-Sites workflow by integrating all components:
- Organism resolution
- GO term to gene mapping
- Pleiotropy scoring
- Safety recommendation for gene knockout
"""

import logging
from typing import Dict, List, Any
from datetime import datetime
import traceback

# Set up logging
logger = logging.getLogger(__name__)


def run_k_sites_pipeline(
    go_term: str, 
    organism: str, 
    max_pleiotropy: int = 3, 
    evidence_filter: str = "experimental",
    species_validation: List[str] = None,
    predict_phenotypes: bool = False,
    databases: List[str] = None
) -> Dict[str, Any]:
    """
    Execute the complete K-Sites pipeline.
    
    Args:
        go_term: GO term identifier (e.g., "GO:0006281")
        organism: Organism identifier (TaxID or scientific name)
        max_pleiotropy: Maximum allowed pleiotropy score (default: 3)
        evidence_filter: Type of evidence to include ("experimental", "computational", "all")
        species_validation: List of species taxids for cross-species validation
        predict_phenotypes: Whether to predict knockout phenotypes using RAG (default: False)
        databases: List of databases to query (e.g., ['quickgo', 'uniprot', 'kegg'])
        
    Returns:
        Dictionary with pipeline results:
        {
            "metadata": {
                "go_term": "...",
                "organism": "...",
                "timestamp": "...",
                "max_pleiotropy": 3,
                "evidence_filter": "experimental",
                "species_validation": [...],
                "predict_phenotypes": false,
                "databases": [...]
            },
            "genes": [
                {
                    "symbol": "BRCA1",
                    "pleiotropy_score": 2,
                    "specificity_score": 8.0,
                    "evidence_quality": 0.9,
                    "conservation_score": 0.8,
                    "composite_score": 8.5,
                    "cross_species_validation": {...},
                    "phenotype_prediction": {...},  # Present if predict_phenotypes=True
                    "safety_recommendation": {...}
                }
            ],
            "insufficient_data_genes": [
                {"symbol": "...", "lookup_failed": true, "reasons": ["..."]}
            ],
            "statistics": {
                "total_genes_screened": 45,
                "genes_passed_filter": 12,
                "avg_pleiotropy": 1.8,
                "most_specific_gene": {...},
                "least_specific_gene": {...}
            }
        }
    """
    logger.info(f"Starting K-Sites pipeline for GO term {go_term} in organism {organism}")
    
    start_time = datetime.now()
    
    # Set default species for validation if not provided
    if species_validation is None:
        # Common model organisms for validation
        species_validation = ["9606", "10090", "10116", "7227", "6239"]  # human, mouse, rat, fly, worm
    
    try:
        # Step 1: Resolve organism
        logger.info("Step 1: Resolving organism...")
        from k_sites.data_retrieval.organism_resolver import resolve_organism
        organism_info = resolve_organism(organism)
        taxid = organism_info["taxid"]
        logger.info(f"Resolved organism: {organism_info['scientific_name']} (TaxID: {taxid})")
        
        # Step 2: Map GO term to genes with evidence filtering
        logger.info(f"Step 2: Mapping GO term to genes with {evidence_filter} evidence...")
        from k_sites.data_retrieval.go_gene_mapper import get_genes_for_go_term
        genes = get_genes_for_go_term(go_term, taxid, evidence_filter)
        logger.info(f"Found {len(genes)} genes associated with GO term {go_term} with {evidence_filter} evidence")
        
        # Step 3: Rank genes by specificity using multi-database integration
        logger.info("Step 3: Ranking genes by specificity (multi-database query)...")
        from k_sites.gene_analysis.pleiotropy_scorer import rank_genes_by_specificity
        ranked_genes = rank_genes_by_specificity(
            genes, 
            taxid,
            target_go_term=go_term,
            evidence_filter=evidence_filter,
            include_literature=True,  # Real PubMed queries
            include_cross_species=species_validation is not None,
            max_pleiotropy_threshold=max_pleiotropy
        )
        logger.info(f"Ranked {len(ranked_genes)} genes by specificity")
        
        # Genes whose data could not be retrieved are reported separately; they are never
        # treated as "specific" just because nothing came back.
        scored_genes = [g for g in ranked_genes if g.get("data_status", "ok") == "ok"]
        insufficient_genes = [g for g in ranked_genes if g.get("data_status", "ok") != "ok"]
        if insufficient_genes:
            logger.warning(
                f"{len(insufficient_genes)} of {len(ranked_genes)} genes have insufficient data and are not scored"
            )

        # Step 4: Process each gene
        processed_genes = []
        logger.info(f"Step 4: Processing {len(scored_genes)} scored genes...")

        # Initialize phenotype predictor if needed
        phenotype_predictor = None
        if predict_phenotypes:
            try:
                from k_sites.rag_system.literature_context import RAGPhenotypePredictor
                phenotype_predictor = RAGPhenotypePredictor()
                logger.info("Initialized RAG-based phenotype predictor")
            except ImportError as e:
                logger.warning(f"Could not initialize phenotype predictor: {e}")
                predict_phenotypes = False  # Disable if dependencies missing
        
        for i, gene_info in enumerate(scored_genes):
            gene_symbol = gene_info.get("symbol", "unknown")
            logger.info(f"Processing gene {i+1}/{len(scored_genes)}: {gene_symbol}")
            
            try:
                # a. Pleiotropy score from the ranking step (computed once, from the same data)
                pleiotropy_score = gene_info["pleiotropy_score"]

                # b. Skip if score exceeds threshold (before any further lookups)
                if pleiotropy_score > max_pleiotropy:
                    logger.info(f"Skipping {gene_symbol} (pleiotropy score {pleiotropy_score} > {max_pleiotropy})")
                    continue

                # c. Perform cross-species validation if requested
                cross_species_validation = {}
                if species_validation:
                    logger.debug(f"Performing cross-species validation for {gene_symbol}...")
                    from k_sites.gene_analysis.pleiotropy_scorer import validate_gene_specificity_across_species
                    cross_species_validation = validate_gene_specificity_across_species(
                        gene_symbol, go_term, species_validation
                    )

                # d. Predict phenotype if requested
                phenotype_prediction = None
                if predict_phenotypes and phenotype_predictor:
                    logger.debug(f"Predicting knockout phenotype for {gene_symbol}...")
                    try:
                        phenotype_prediction = phenotype_predictor.predict_phenotype(gene_symbol, taxid)
                    except Exception as e:
                        logger.warning(f"Failed to predict phenotype for {gene_symbol}: {str(e)}")

                # e. Generate comprehensive safety recommendation using the safety recommender
                from k_sites.workflow.safety_recommender import SafetyRecommender, get_safety_recommendation
                
                safety_rec = get_safety_recommendation(
                    gene_symbol=gene_symbol,
                    pleiotropy_score=pleiotropy_score,
                    phenotype_prediction=phenotype_prediction.__dict__ if phenotype_prediction else None,
                    cross_species_validation=cross_species_validation,
                    literature_support=gene_info.get("literature_score", 0.5)
                )
                
                logger.info(f"Safety recommendation for {gene_symbol}: {safety_rec.safety_level.value} - {safety_rec.primary_recommendation.value}")
                
                # Store safety recommendation in gene result
                gene_result = {
                    "symbol": gene_symbol,
                    "pleiotropy_score": pleiotropy_score,
                    "specificity_score": gene_info.get("specificity_score"),
                    "evidence_quality": gene_info.get("evidence_quality", 0.5),
                    "literature_support": gene_info.get("literature_score", 0.5),
                    "conservation_score": gene_info.get("conservation_score", 0.0),
                    "composite_score": gene_info.get("composite_score", 5.0),
                    "bp_term_count": gene_info.get("bp_term_count", 0),
                    "data_issues": gene_info.get("data_issues", []),
                    "kegg_pathway_count": gene_info.get("kegg_pathway_count", 0),
                    "experimental_evidence_count": gene_info.get("experimental_evidence_count", 0),
                    "computational_evidence_count": gene_info.get("computational_evidence_count", 0),
                    "iea_evidence_count": gene_info.get("iea_evidence_count", 0),
                    "cross_species_validation": cross_species_validation,
                    "phenotype_prediction": phenotype_prediction.__dict__ if phenotype_prediction else None,
                    "safety_recommendation": {
                        "safety_level": safety_rec.safety_level.value,
                        "primary_recommendation": safety_rec.primary_recommendation.value,
                        "alternative_recommendations": [alt.value for alt in safety_rec.alternative_recommendations],
                        "justification": safety_rec.justification,
                        "concerns": safety_rec.concerns,
                        "mitigation_strategies": safety_rec.mitigation_strategies,
                        "experimental_considerations": safety_rec.experimental_considerations,
                        "confidence_score": safety_rec.confidence_score
                    },
                    "safety_recommendation_object": safety_rec,  # Keep object for report generation
                    "description": gene_info.get("description", ""),
                    "entrez_id": gene_info.get("entrez_id", "")
                }
                
                processed_genes.append(gene_result)
                logger.info(f"Successfully processed {gene_symbol}")
                
            except Exception as e:
                logger.warning(f"Failed to process gene {gene_symbol}: {str(e)}")
                logger.debug(f"Traceback: {traceback.format_exc()}")
                continue  # Skip this gene and continue with others
        
        # Step 5: Aggregate results
        logger.info("Step 5: Aggregating results...")
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Calculate pipeline statistics
        statistics = {
            "total_genes_screened": len(ranked_genes),
            "genes_passed_filter": len(processed_genes),
            "genes_insufficient_data": len(insufficient_genes),
            "avg_pleiotropy": 0.0,
            "most_specific_gene": None,
            "least_specific_gene": None
        }
        
        if processed_genes:
            total_pleiotropy = sum(gene["pleiotropy_score"] for gene in processed_genes)
            statistics["avg_pleiotropy"] = total_pleiotropy / len(processed_genes)
            
            # Find most and least specific genes (lowest and highest pleiotropy scores)
            sorted_by_pleiotropy = sorted(processed_genes, key=lambda x: x["pleiotropy_score"])
            statistics["most_specific_gene"] = sorted_by_pleiotropy[0] if sorted_by_pleiotropy else None
            statistics["least_specific_gene"] = sorted_by_pleiotropy[-1] if sorted_by_pleiotropy else None
        
        results = {
            "metadata": {
                "go_term": go_term,
                "organism": organism,
                "resolved_organism": organism_info,
                "timestamp": start_time.isoformat(),
                "execution_duration": duration,
                "max_pleiotropy": max_pleiotropy,
                "evidence_filter": evidence_filter,
                "species_validation": species_validation,
                "predict_phenotypes": predict_phenotypes,
                "databases": databases or ['all']
            },
            "genes": processed_genes,
            "insufficient_data_genes": [
                {
                    "symbol": g.get("symbol", ""),
                    "description": g.get("description", ""),
                    "lookup_failed": g.get("lookup_failed", False),
                    "reasons": g.get("data_issues", []),
                }
                for g in insufficient_genes
            ],
            "statistics": statistics
        }
        
        logger.info(f"Pipeline completed successfully. Processed {len(processed_genes)} genes out of {len(ranked_genes)} total "
                    f"({len(insufficient_genes)} with insufficient data).")
        return results
        
    except Exception as e:
        logger.error(f"Pipeline failed: {str(e)}")
        logger.debug(f"Full traceback: {traceback.format_exc()}")
        raise
