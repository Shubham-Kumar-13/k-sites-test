"""
GO-Gene Mapper for K-Sites

This module retrieves genes associated with a specific GO term for a given organism
using the QuickGO API with evidence-based filtering.
"""

import logging
import requests
import os
import math
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import json
import time
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import hashlib

from k_sites.data_retrieval.http import http_get
from k_sites.data_retrieval.multi_database_client import MultiDatabaseClient, EVIDENCE_PRIORITY

# Set up logging
logger = logging.getLogger(__name__)

# Shared evidence-code classifier (same rules as the multi-database client)
_evidence_classifier = MultiDatabaseClient()

# Cache configuration
CACHE_DIR = Path.home() / ".k_sites_cache"
CACHE_DIR.mkdir(exist_ok=True)
GO_GENE_CACHE_FILE = CACHE_DIR / "go_gene_cache.json"

# In-memory cache for GO gene lookups
_go_gene_cache: Dict[str, any] = {}
_cache_loaded = False
_cache_lock = False


def _get_cache_key(go_term: str, taxid: str, evidence_filter: str) -> str:
    """Generate cache key for GO term lookup."""
    key = f"{go_term.upper()}:{taxid}:{evidence_filter}"
    return hashlib.md5(key.encode()).hexdigest()


def _load_cache():
    """Load cache from disk."""
    global _go_gene_cache, _cache_loaded, _cache_lock
    if _cache_loaded or _cache_lock:
        return
    
    _cache_lock = True
    try:
        if GO_GENE_CACHE_FILE.exists():
            with open(GO_GENE_CACHE_FILE, 'r') as f:
                _go_gene_cache = json.load(f)
            logger.info(f"Loaded {len(_go_gene_cache)} entries from GO gene cache")
    except Exception as e:
        logger.warning(f"Could not load cache: {e}")
        _go_gene_cache = {}
    finally:
        _cache_loaded = True
        _cache_lock = False


def _save_cache():
    """Save cache to disk."""
    try:
        # Limit cache size to prevent unlimited growth
        global _go_gene_cache
        if len(_go_gene_cache) > 1000:
            # Keep only most recent 500 entries
            keys = list(_go_gene_cache.keys())[-500:]
            _go_gene_cache = {k: _go_gene_cache[k] for k in keys}
        
        with open(GO_GENE_CACHE_FILE, 'w') as f:
            json.dump(_go_gene_cache, f)
    except Exception as e:
        logger.warning(f"Could not save cache: {e}")


class GoTermNotFoundError(Exception):
    """Raised when a GO term is not found."""
    pass


class GeneRetrievalError(Exception):
    """Raised when gene retrieval fails."""
    pass


def _fetch_quickgo_page(go_term: str, taxid: str, page: int, page_size: int, headers: dict) -> Tuple[int, List[Dict]]:
    """
    Fetch a single page from QuickGO API.
    
    Returns:
        Tuple of (total_hits, results)

    Raises:
        GoTermNotFoundError: If QuickGO rejects the GO term.
        GeneRetrievalError: If QuickGO could not be queried.
    """
    base_url = "https://www.ebi.ac.uk/QuickGO/services/annotation/search"
    
    params = {
        "goId": go_term,
        "taxonId": taxid,
        "limit": page_size,
        "page": page
    }
    
    try:
        response = http_get(base_url, params=params, headers=headers)
    except requests.RequestException as e:
        raise GeneRetrievalError(f"QuickGO request failed: {e}")

    if response.status_code in (400, 404):
        raise GoTermNotFoundError(f"QuickGO rejected {go_term} for taxon {taxid}: {response.text[:200]}")
    if response.status_code != 200:
        raise GeneRetrievalError(f"QuickGO returned HTTP {response.status_code} for {go_term}")

    data = response.json()
    return data.get("numberOfHits", 0), data.get("results", [])


def get_genes_for_go_term(go_term: str, taxid: str, evidence_filter: str = "experimental") -> List[Dict[str, str]]:
    """
    Retrieve genes associated with a specific GO term for a given organism
    with evidence-based filtering.
    
    OPTIMIZED: Uses parallel pagination and caching for 3-5x speed improvement.
    
    Args:
        go_term: GO term identifier (e.g., "GO:0006281")
        taxid: NCBI Taxonomy ID (e.g., "9606" for human)
        evidence_filter: Type of evidence to include ("experimental", "computational", "all")
        
    Returns:
        List of dictionaries containing gene information:
        [
            {
                "symbol": "BRCA1", 
                "entrez_id": "672", 
                "description": "BRCA1 DNA repair associated",
                "evidence_codes": ["IDA", "IMP"],
                "go_evidence_type": "experimental",  # "experimental", "computational", or "other"
                "qualifier": ["NOT"] if negative regulation, else []
            },
            ...
        ]
        
    Raises:
        GoTermNotFoundError: If the GO term is not found
        GeneRetrievalError: If gene retrieval fails
    """
    global _go_gene_cache
    
    # Load cache
    _load_cache()
    
    # Check cache first
    cache_key = _get_cache_key(go_term, taxid, evidence_filter)
    if cache_key in _go_gene_cache:
        cached = _go_gene_cache[cache_key]
        cache_time = cached.get("timestamp", 0)
        # Cache valid for 24 hours
        if time.time() - cache_time < 86400:
            logger.info(f"Using cached results for {go_term} in {taxid}")
            return cached.get("genes", [])
    
    logger.info(f"Fetching genes for GO term {go_term} in organism {taxid} with {evidence_filter} evidence")
    
    # Validate GO term format
    if not _validate_go_term(go_term):
        raise ValueError(f"Invalid GO term format: {go_term}. Expected format: GO:0000000")
    
    try:
        headers = {"Accept": "application/json"}
        page_size = 200
        
        # First request to get total count
        total_hits, first_results = _fetch_quickgo_page(go_term, taxid, 1, page_size, headers)
        
        if not first_results and total_hits == 0:
            logger.warning(f"No results found for GO term {go_term} in organism {taxid}")
            return []
        
        logger.info(f"QuickGO returned {total_hits} total hits for {go_term}")
        
        all_results = list(first_results)
        
        # Calculate total pages (limit to 10 pages = 2000 results max)
        total_pages = min((total_hits + page_size - 1) // page_size, 10)
        
        # Fetch remaining pages in parallel
        if total_pages > 1:
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_to_page = {
                    executor.submit(_fetch_quickgo_page, go_term, taxid, page, page_size, headers): page
                    for page in range(2, total_pages + 1)
                }
                
                for future in as_completed(future_to_page):
                    page_num = future_to_page[future]
                    _, results = future.result()  # a failed page must fail the whole lookup
                    all_results.extend(results)
                    logger.debug(f"Fetched page {page_num} with {len(results)} results")
        
        logger.info(f"Fetched {len(all_results)} annotations for {go_term}")
        
        # Process the results
        gene_list = _process_annotations(all_results, evidence_filter)
        
        # Cache results
        _go_gene_cache[cache_key] = {
            "timestamp": time.time(),
            "genes": gene_list,
            "total_hits": total_hits
        }
        _save_cache()
        
        logger.info(f"Retrieved {len(gene_list)} genes for GO term {go_term} in organism {taxid} with {evidence_filter} evidence")
        
        # If we got no results with strict evidence filtering, try with less strict filtering
        if not gene_list and evidence_filter == "experimental":
            logger.info("No experimental evidence results found, trying computational evidence...")
            return get_genes_for_go_term(go_term, taxid, "computational")
        
        return gene_list
        
    except (GoTermNotFoundError, GeneRetrievalError):
        raise
    except Exception as e:
        logger.error(f"Unexpected error retrieving genes for GO term {go_term} in organism {taxid}: {str(e)}")
        raise GeneRetrievalError(f"Unexpected error retrieving genes for GO term {go_term} in organism {taxid}: {str(e)}")


def _process_annotations(all_results: List[Dict], evidence_filter: str) -> List[Dict[str, str]]:
    """Process QuickGO annotations and extract gene information with evidence filtering."""
    genes = {}
    
    # Define evidence code categories
    experimental_codes = {"IDA", "IPI", "IMP", "IGI", "IEP", "HTP", "HDA", "HMP", "HGI", "HEP"}
    computational_codes = {"ISS", "ISO", "ISA", "ISM", "IGC", "IBA", "IBD", "IKR", "IRD", "RCA"}
    curatorial_codes = {"TAS", "NAS", "IC", "ND", "IEA"}
    
    for result in all_results:
        go_evidence = result.get("goEvidence", "")
        qualifier = result.get("qualifier", "")
        
        # Determine evidence type
        go_evidence_type = "other"
        if go_evidence in experimental_codes:
            go_evidence_type = "experimental"
        elif go_evidence in computational_codes:
            go_evidence_type = "computational"
        elif go_evidence in curatorial_codes:
            go_evidence_type = "curatorial"
        
        # Apply evidence filter
        if evidence_filter == "experimental" and go_evidence_type != "experimental":
            continue
        elif evidence_filter == "computational" and go_evidence_type not in ["computational", "curatorial"]:
            continue
        
        # Extract gene information
        gene_symbol = result.get("symbol", "") or result.get("geneProductSymbol", "")
        gene_product_id = result.get("geneProductId", "")
        reference = result.get("reference", "")
        
        if not gene_symbol or not gene_product_id:
            continue
        
        # Aggregate by gene
        if gene_product_id in genes:
            existing_codes = set(genes[gene_product_id]["evidence_codes"])
            if go_evidence:
                existing_codes.add(go_evidence)
            genes[gene_product_id]["evidence_codes"] = list(existing_codes)
            
            if go_evidence_type == "experimental":
                genes[gene_product_id]["go_evidence_type"] = "experimental"
            elif go_evidence_type == "computational" and genes[gene_product_id]["go_evidence_type"] == "other":
                genes[gene_product_id]["go_evidence_type"] = "computational"
        else:
            genes[gene_product_id] = {
                "symbol": gene_symbol,
                "entrez_id": gene_product_id,
                "description": reference,
                "evidence_codes": [go_evidence] if go_evidence else [],
                "go_evidence_type": go_evidence_type,
                "qualifier": qualifier
            }
    
    return list(genes.values())


def get_genes_with_cross_species_validation(go_term: str, taxids: List[str], evidence_filter: str = "experimental") -> List[Dict]:
    """
    Retrieve genes with cross-species validation across multiple organisms.
    
    Args:
        go_term: GO term identifier
        taxids: List of NCBI Taxonomy IDs to validate across
        evidence_filter: Type of evidence to include
        
    Returns:
        List of genes with cross-species conservation scores
    """
    logger.info(f"Performing cross-species validation for {go_term} across {len(taxids)} species")
    
    # Get genes for each species
    all_genes = {}
    species_counts = defaultdict(int)
    
    for taxid in taxids:
        try:
            genes = get_genes_for_go_term(go_term, taxid, evidence_filter)
            for gene in genes:
                gene_key = gene["symbol"].upper()  # Normalize gene symbol
                if gene_key not in all_genes:
                    all_genes[gene_key] = {
                        "symbol": gene["symbol"],
                        "entrez_id": gene["entrez_id"],
                        "description": gene["description"],
                        "species_found": [],
                        "evidence_types": set(),
                        "conservation_score": 0.0
                    }
                
                all_genes[gene_key]["species_found"].append(taxid)
                all_genes[gene_key]["evidence_types"].add(gene["go_evidence_type"])
                species_counts[gene_key] += 1
        except Exception as e:
            logger.warning(f"Could not retrieve genes for {go_term} in species {taxid}: {e}")
            continue
    
    # Calculate conservation scores and compile results
    results = []
    for gene_key, gene_data in all_genes.items():
        conservation_score = len(gene_data["species_found"]) / len(taxids)
        gene_data["conservation_score"] = conservation_score
        
        # Add weighted score based on evidence type and conservation
        evidence_weight = 1.0  # Experimental evidence
        if "computational" in gene_data["evidence_types"]:
            evidence_weight *= 0.7  # Reduce weight for computational
        if "curatorial" in gene_data["evidence_types"]:
            evidence_weight *= 0.5  # Further reduce for IEA only
        
        gene_data["weighted_score"] = conservation_score * evidence_weight
        
        # Convert evidence_types set to list for JSON serialization
        gene_data["evidence_types"] = list(gene_data["evidence_types"])
        
        results.append(gene_data)
    
    # Sort by weighted score (descending)
    results.sort(key=lambda x: x["weighted_score"], reverse=True)
    
    logger.info(f"Found {len(results)} genes with cross-species validation")
    return results


def get_pleiotropy_score_detailed(gene_symbol: str, taxid: str, go_term: str = None) -> Dict:
    """
    Calculate detailed pleiotropy score with multiple factors.
    
    Args:
        gene_symbol: Gene symbol to score
        taxid: NCBI Taxonomy ID
        go_term: Optional GO term for context
        
    Returns:
        Dictionary with detailed pleiotropy scoring information
    """
    logger.info(f"Calculating detailed pleiotropy score for {gene_symbol} in {taxid}")
    
    try:
        # Get all GO terms for this gene
        all_go_terms = _get_all_go_terms_for_gene(gene_symbol, taxid)
        
        # Count Biological Process terms specifically
        bp_terms = [term for term in all_go_terms if term.get("category") == "P"]  # P = Biological Process
        molecular_function_terms = [term for term in all_go_terms if term.get("category") == "F"]  # F = Molecular Function
        cellular_component_terms = [term for term in all_go_terms if term.get("category") == "C"]  # C = Cellular Component
        
        # Calculate exponential decay scoring for BP terms
        # Formula: 1 - exp(-lambda * n) where lambda adjusts the decay rate and n is the number of BP terms
        lambda_val = 0.3  # Decay rate - adjust as needed
        bp_score = 1 - math.exp(-lambda_val * (len(bp_terms) - 1)) if len(bp_terms) > 0 else 0
        
        # Calculate evidence-based score
        experimental_evidence_count = sum(1 for term in all_go_terms if term.get("evidence_type") == "experimental")
        computational_evidence_count = sum(1 for term in all_go_terms if term.get("evidence_type") == "computational")
        iea_evidence_count = sum(1 for term in all_go_terms if term.get("evidence_type") == "IEA")
        
        # Combine scores
        total_score = bp_score
        
        result = {
            "gene_symbol": gene_symbol,
            "taxid": taxid,
            "total_pleiotropy_score": total_score,
            "bp_term_count": len(bp_terms),
            "bp_score": bp_score,
            "experimental_evidence_count": experimental_evidence_count,
            "computational_evidence_count": computational_evidence_count,
            "iea_evidence_count": iea_evidence_count,
            "all_go_terms": all_go_terms,
            "biological_process_terms": bp_terms,
            "molecular_function_terms": molecular_function_terms,
            "cellular_component_terms": cellular_component_terms
        }
        
        logger.info(f"Pleiotropy score for {gene_symbol}: {total_score}")
        return result
        
    except Exception as e:
        logger.error(f"Error calculating pleiotropy score for {gene_symbol}: {str(e)}")
        raise


def _get_all_go_terms_for_gene(gene_symbol: str, taxid: str) -> List[Dict]:
    """
    Get all GO terms associated with a gene.

    Args:
        gene_symbol: Gene symbol
        taxid: NCBI Taxonomy ID

    Returns:
        List of GO terms (one per GO id, strongest evidence kept) with a 'category' field
        (P, F or C). An empty list means the gene has no annotations or is unknown to UniProt.

    Raises:
        GeneRetrievalError: If UniProt or QuickGO could not be queried.
    """
    gene_id = _resolve_gene_to_uniprot(gene_symbol, taxid)
    if not gene_id:
        logger.warning(f"Could not resolve {gene_symbol} to UniProt ID in taxid {taxid}")
        return []

    base_url = "https://www.ebi.ac.uk/QuickGO/services/annotation/search"
    PAGE_SIZE = 200  # QuickGO rejects larger pages with HTTP 400
    all_results = []
    page = 1

    while True:
        params = {
            "geneProductId": gene_id,
            "limit": PAGE_SIZE,
            "page": page,
            "includeFields": "goName",
        }

        time.sleep(0.34)  # Rate limiting
        try:
            response = http_get(base_url, params=params)
        except requests.RequestException as e:
            raise GeneRetrievalError(f"QuickGO request failed for {gene_symbol}: {e}")

        if response.status_code != 200:
            raise GeneRetrievalError(
                f"QuickGO returned HTTP {response.status_code} for {gene_symbol}: {response.text[:200]}"
            )

        data = response.json()
        results = data.get("results", [])
        if not results:
            break

        all_results.extend(results)

        total_hits = data.get("numberOfHits", 0)
        if len(all_results) >= total_hits or len(results) < PAGE_SIZE:
            break

        page += 1
        if page > 50:  # Safety limit
            break

    terms: Dict[str, Dict] = {}

    for result in all_results:
        go_id = result.get("goId", "")
        if not go_id:
            continue

        qualifier = result.get("qualifier", "")
        if "NOT" in str(qualifier).upper().split("|"):
            continue  # NOT annotations say the gene is NOT involved

        code = result.get("goEvidence", "")
        evidence_type = _evidence_classifier._classify_evidence([code])

        existing = terms.get(go_id)
        if existing is not None:
            if code and code not in existing["evidence_codes"]:
                existing["evidence_codes"].append(code)
            if EVIDENCE_PRIORITY.get(evidence_type, 0) > EVIDENCE_PRIORITY.get(existing["evidence_type"], 0):
                existing["evidence_type"] = evidence_type
            continue

        aspect = result.get("goAspect", "")

        # Normalize aspect to single letter (P, F, C); QuickGO returns full names
        category = "U"  # Unknown
        if aspect in ["biological_process", "P"]:
            category = "P"
        elif aspect in ["molecular_function", "F"]:
            category = "F"
        elif aspect in ["cellular_component", "C"]:
            category = "C"

        terms[go_id] = {
            "go_id": go_id,
            "go_name": result.get("goName") or "",
            "aspect": aspect,
            "category": category,  # CRITICAL: P, F, or C for filtering
            "evidence_codes": [code] if code else [],
            "evidence_type": evidence_type,
            "qualifiers": qualifier
        }

    go_terms = list(terms.values())
    logger.info(f"Found {len(go_terms)} GO terms for {gene_symbol}")
    return go_terms


def _resolve_gene_to_uniprot(gene_symbol: str, taxid: str) -> Optional[str]:
    """
    Resolve a gene symbol to a UniProt accession using the UniProt REST API.

    Args:
        gene_symbol: Gene symbol
        taxid: NCBI Taxonomy ID

    Returns:
        UniProt accession, or None if UniProt has no such gene.

    Raises:
        GeneRetrievalError: If UniProt could not be queried.
    """
    base_url = "https://rest.uniprot.org/uniprotkb/search"

    # Prefer the reviewed (Swiss-Prot) entry, then fall back to any entry
    for query in (
        f"gene:{gene_symbol} AND organism_id:{taxid} AND reviewed:true",
        f"gene:{gene_symbol} AND organism_id:{taxid}",
    ):
        params = {"query": query, "format": "json", "fields": "accession", "size": 1}

        time.sleep(0.34)  # Rate limiting
        try:
            response = http_get(base_url, params=params, timeout=15)
        except requests.RequestException as e:
            raise GeneRetrievalError(f"UniProt request failed for {gene_symbol}: {e}")

        if response.status_code != 200:
            raise GeneRetrievalError(f"UniProt returned HTTP {response.status_code} for {gene_symbol}")

        results = response.json().get("results", [])
        if results:
            return results[0].get("primaryAccession")

    return None


def _validate_go_term(go_term: str) -> bool:
    """
    Validate the format of a GO term.
    
    Args:
        go_term: GO term to validate
        
    Returns:
        True if valid, False otherwise
    """
    import re
    pattern = r'^GO:\d{7}$'
    return bool(re.match(pattern, go_term.upper()))


# Common GO terms for search functionality
COMMON_GO_TERMS = [
    {'id': 'GO:0006281', 'name': 'DNA repair', 'category': 'Biological Process'},
    {'id': 'GO:0006974', 'name': 'cellular response to DNA damage stimulus', 'category': 'Biological Process'},
    {'id': 'GO:0008152', 'name': 'metabolic process', 'category': 'Biological Process'},
    {'id': 'GO:0007165', 'name': 'signal transduction', 'category': 'Biological Process'},
    {'id': 'GO:0006915', 'name': 'apoptotic process', 'category': 'Biological Process'},
    {'id': 'GO:0007049', 'name': 'cell cycle', 'category': 'Biological Process'},
    {'id': 'GO:0006351', 'name': 'transcription, DNA-templated', 'category': 'Biological Process'},
    {'id': 'GO:0006412', 'name': 'translation', 'category': 'Biological Process'},
    {'id': 'GO:0006955', 'name': 'immune response', 'category': 'Biological Process'},
    {'id': 'GO:0006260', 'name': 'DNA replication', 'category': 'Biological Process'},
    {'id': 'GO:0007267', 'name': 'cell-cell signaling', 'category': 'Biological Process'},
    {'id': 'GO:0008219', 'name': 'cell death', 'category': 'Biological Process'},
    {'id': 'GO:0008283', 'name': 'cell proliferation', 'category': 'Biological Process'},
    {'id': 'GO:0016043', 'name': 'cellular component organization', 'category': 'Biological Process'},
    {'id': 'GO:0030154', 'name': 'cell differentiation', 'category': 'Biological Process'},
    {'id': 'GO:0042277', 'name': 'peptide binding', 'category': 'Molecular Function'},
    {'id': 'GO:0050896', 'name': 'response to stimulus', 'category': 'Biological Process'},
    {'id': 'GO:0051179', 'name': 'localization', 'category': 'Biological Process'},
    {'id': 'GO:0065007', 'name': 'biological regulation', 'category': 'Biological Process'},
    {'id': 'GO:0071840', 'name': 'cellular organization', 'category': 'Biological Process'},
]


def search_go_terms(query: str, limit: int = 20) -> list:
    """
    Search for GO terms by keyword or ID.
    
    Args:
        query: Search string (GO term name or partial ID)
        limit: Maximum number of results to return
        
    Returns:
        List of GO term dictionaries matching the query
    """
    query_lower = query.lower().strip()
    results = []
    seen_ids = set()
    
    # Check for exact GO ID match first
    if query.upper().startswith('GO:'):
        query_upper = query.upper()
        for term in COMMON_GO_TERMS:
            if query_upper in term['id'] and term['id'] not in seen_ids:
                results.append(term)
                seen_ids.add(term['id'])
            if len(results) >= limit:
                break
        return results
    
    # Search by name
    for term in COMMON_GO_TERMS:
        if term['id'] in seen_ids:
            continue
            
        if query_lower in term['name'].lower():
            results.append(term)
            seen_ids.add(term['id'])
            
        if len(results) >= limit:
            break
    
    return results