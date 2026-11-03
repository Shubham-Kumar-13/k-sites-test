"""
Organism Resolver for K-Sites

This module resolves organism identifiers (TaxID or scientific name) 
to standardized organism information using NCBI E-Utils.
"""

import os
import json
import logging
from typing import Dict, List, Optional
from pathlib import Path
import time

from k_sites.data_retrieval.http import http_get

# Set up logging
logger = logging.getLogger(__name__)

# Common organism mapping as fallback
COMMON_ORGANISMS = {
    "9606": {"taxid": "9606", "scientific_name": "Homo sapiens", "common_name": "human"},
    "human": {"taxid": "9606", "scientific_name": "Homo sapiens", "common_name": "human"},
    "Homo sapiens": {"taxid": "9606", "scientific_name": "Homo sapiens", "common_name": "human"},
    
    "10090": {"taxid": "10090", "scientific_name": "Mus musculus", "common_name": "mouse"},
    "mouse": {"taxid": "10090", "scientific_name": "Mus musculus", "common_name": "mouse"},
    "Mus musculus": {"taxid": "10090", "scientific_name": "Mus musculus", "common_name": "mouse"},
    
    "10116": {"taxid": "10116", "scientific_name": "Rattus norvegicus", "common_name": "rat"},
    "rat": {"taxid": "10116", "scientific_name": "Rattus norvegicus", "common_name": "rat"},
    "Rattus norvegicus": {"taxid": "10116", "scientific_name": "Rattus norvegicus", "common_name": "rat"},
    
    "7227": {"taxid": "7227", "scientific_name": "Drosophila melanogaster", "common_name": "fruit fly"},
    "fruit fly": {"taxid": "7227", "scientific_name": "Drosophila melanogaster", "common_name": "fruit fly"},
    "Drosophila melanogaster": {"taxid": "7227", "scientific_name": "Drosophila melanogaster", "common_name": "fruit fly"},
    
    "6239": {"taxid": "6239", "scientific_name": "Caenorhabditis elegans", "common_name": "worm"},
    "worm": {"taxid": "6239", "scientific_name": "Caenorhabditis elegans", "common_name": "worm"},
    "Caenorhabditis elegans": {"taxid": "6239", "scientific_name": "Caenorhabditis elegans", "common_name": "worm"},
    
    "7955": {"taxid": "7955", "scientific_name": "Danio rerio", "common_name": "zebrafish"},
    "zebrafish": {"taxid": "7955", "scientific_name": "Danio rerio", "common_name": "zebrafish"},
    "Danio rerio": {"taxid": "7955", "scientific_name": "Danio rerio", "common_name": "zebrafish"},
    
    "4932": {"taxid": "4932", "scientific_name": "Saccharomyces cerevisiae", "common_name": "yeast"},
    "yeast": {"taxid": "4932", "scientific_name": "Saccharomyces cerevisiae", "common_name": "yeast"},
    "Saccharomyces cerevisiae": {"taxid": "4932", "scientific_name": "Saccharomyces cerevisiae", "common_name": "yeast"},
    
    "hsa": {"taxid": "9606", "scientific_name": "Homo sapiens", "common_name": "human"},
    "mmu": {"taxid": "10090", "scientific_name": "Mus musculus", "common_name": "mouse"},
    "rno": {"taxid": "10116", "scientific_name": "Rattus norvegicus", "common_name": "rat"},
    "dme": {"taxid": "7227", "scientific_name": "Drosophila melanogaster", "common_name": "fruit fly"},
    "cel": {"taxid": "6239", "scientific_name": "Caenorhabditis elegans", "common_name": "worm"},
    "dre": {"taxid": "7955", "scientific_name": "Danio rerio", "common_name": "zebrafish"},
    "sce": {"taxid": "4932", "scientific_name": "Saccharomyces cerevisiae", "common_name": "yeast"},
    
    # Plants
    "39947": {"taxid": "39947", "scientific_name": "Oryza sativa Japonica Group", "common_name": "rice"},
    "Oryza sativa Japonica Group": {"taxid": "39947", "scientific_name": "Oryza sativa Japonica Group", "common_name": "rice"},
    "Oryza sativa japonica": {"taxid": "39947", "scientific_name": "Oryza sativa Japonica Group", "common_name": "rice"},
    "rice": {"taxid": "39947", "scientific_name": "Oryza sativa Japonica Group", "common_name": "rice"},
    
    "3702": {"taxid": "3702", "scientific_name": "Arabidopsis thaliana", "common_name": "thale cress"},
    "Arabidopsis thaliana": {"taxid": "3702", "scientific_name": "Arabidopsis thaliana", "common_name": "thale cress"},
    "arabidopsis": {"taxid": "3702", "scientific_name": "Arabidopsis thaliana", "common_name": "thale cress"},
    
    "4577": {"taxid": "4577", "scientific_name": "Zea mays", "common_name": "maize"},
    "Zea mays": {"taxid": "4577", "scientific_name": "Zea mays", "common_name": "maize"},
    "maize": {"taxid": "4577", "scientific_name": "Zea mays", "common_name": "maize"},
    "corn": {"taxid": "4577", "scientific_name": "Zea mays", "common_name": "maize"},
    
    "3847": {"taxid": "3847", "scientific_name": "Glycine max", "common_name": "soybean"},
    "Glycine max": {"taxid": "3847", "scientific_name": "Glycine max", "common_name": "soybean"},
    "soybean": {"taxid": "3847", "scientific_name": "Glycine max", "common_name": "soybean"},
    
    # Bacteria
    "83333": {"taxid": "83333", "scientific_name": "Escherichia coli K-12", "common_name": "E. coli"},
    "Escherichia coli": {"taxid": "83333", "scientific_name": "Escherichia coli K-12", "common_name": "E. coli"},
    "E. coli": {"taxid": "83333", "scientific_name": "Escherichia coli K-12", "common_name": "E. coli"},
    "eco": {"taxid": "83333", "scientific_name": "Escherichia coli K-12", "common_name": "E. coli"},
    
    # Fungi
    "559292": {"taxid": "559292", "scientific_name": "Saccharomyces cerevisiae S288C", "common_name": "baker's yeast"},
    "Saccharomyces cerevisiae S288C": {"taxid": "559292", "scientific_name": "Saccharomyces cerevisiae S288C", "common_name": "baker's yeast"},
}


class OrganismNotFoundError(Exception):
    """Raised when an organism cannot be resolved."""
    pass


def resolve_organism(input_str: str) -> Dict[str, str]:
    """
    Resolve an organism identifier to standardized organism information.

    Uses the shared HTTP cache and NCBI E-Utils (esummary/esearch). Falls back
    to a built-in mapping for common organisms.

    Args:
        input_str: Either NCBI TaxID (e.g., "9606") or scientific name (e.g., "Homo sapiens")

    Returns:
        Dictionary with taxid, scientific_name, and common_name

    Raises:
        OrganismNotFoundError: If the organism cannot be resolved
    """
    input_clean = input_str.strip()

    # First check cache
    cached_result = _get_cached_result(input_clean)
    if cached_result:
        logger.debug(f"Found cached result for {input_clean}")
        return cached_result

    # Check common organisms mapping first
    if input_clean in COMMON_ORGANISMS:
        result = COMMON_ORGANISMS[input_clean]
        _cache_result(input_clean, result)
        logger.debug(f"Resolved {input_clean} using common organisms mapping")
        return result

    is_numeric = input_clean.isdigit()

    try:
        if is_numeric:
            # Use esummary (JSON) to look up the taxid directly
            response = http_get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                params={"db": "taxonomy", "id": input_clean, "retmode": "json"},
                timeout=10,
            )
            doc = response.json().get("result", {}).get(input_clean, {})
            scientific = doc.get("scientificname") or doc.get("ScientificName", "")
            if scientific:
                result = {
                    "taxid": str(doc.get("taxid", input_clean)),
                    "scientific_name": scientific,
                    "common_name": doc.get("commonname") or doc.get("CommonName", ""),
                }
                _cache_result(input_clean, result)
                logger.info(f"Resolved taxid {input_clean} to {result['scientific_name']}")
                return result
        else:
            # Search NCBI Taxonomy by name and prefer an exact scientific-name match
            results = search_organisms_ncbi(input_clean, limit=20)
            query_lower = input_clean.lower()
            match = None
            exact_match = False
            for candidate in results:
                if candidate["name"].lower() == query_lower:
                    match = candidate
                    exact_match = True
                    break
            if match is None and results:
                match = results[0]
            if match:
                result = {
                    "taxid": match["taxid"],
                    "scientific_name": match["name"],
                    "common_name": match.get("common_name", ""),
                }
                # Only cache name resolutions when they are an exact match, so a
                # broad search does not pin an inexact result forever.
                if exact_match:
                    _cache_result(input_clean, result)
                _cache_result(match["taxid"], result)
                logger.info(f"Resolved {input_clean} to taxid {match['taxid']}")
                return result

    except Exception as e:
        logger.warning(f"NCBI lookup failed for {input_clean}: {e}. Using fallback mapping.")

    # If NCBI failed, try the common organisms mapping again with variations
    for key, value in COMMON_ORGANISMS.items():
        if input_clean.lower() in key.lower() or key.lower() in input_clean.lower():
            result = value
            _cache_result(input_clean, result)
            logger.debug(f"Resolved {input_clean} using fuzzy match to {key}")
            return result

    # If we get here, the organism couldn't be resolved
    raise OrganismNotFoundError(f"Could not resolve organism: {input_clean}")


def _get_cached_result(input_str: str) -> Optional[Dict[str, str]]:
    """Retrieve cached organism resolution result."""
    cache_file = _get_cache_file_path()
    
    if not cache_file.exists():
        return None
    
    try:
        with open(cache_file, 'r') as f:
            cache_data = json.load(f)
        
        # Check if input_str exists in cache
        if input_str in cache_data:
            return cache_data[input_str]
        
        # Also check if input_str is a taxid that matches any cached taxid
        if input_str.isdigit():
            for cached_key, cached_value in cache_data.items():
                if cached_value.get("taxid") == input_str:
                    return cached_value
    
    except Exception as e:
        logger.warning(f"Could not read cache file: {str(e)}")
    
    return None


def _cache_result(input_str: str, result: Dict[str, str]):
    """Cache organism resolution result."""
    cache_file = _get_cache_file_path()
    
    # Create cache directory if it doesn't exist
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing cache
    cache_data = {}
    if cache_file.exists():
        try:
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)
        except Exception as e:
            logger.warning(f"Could not load existing cache: {str(e)}")
    
    # Add new result
    cache_data[input_str] = result
    
    # Write back to cache
    try:
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not write to cache file: {str(e)}")


def _get_cache_file_path() -> Path:
    """Get the path to the organism cache file."""
    cache_dir = Path.home() / ".openclaw" / "workspace" / "k-sites" / ".cache"
    return cache_dir / "organism_cache.json"


def search_organisms(query: str, limit: int = 20) -> list:
    """
    Search for organisms by name or taxid.
    
    Args:
        query: Search string (scientific name, common name, or taxid)
        limit: Maximum number of results to return
        
    Returns:
        List of organism dictionaries matching the query
    """
    query_lower = query.lower().strip()
    results = []
    
    # Search in common organisms
    seen_taxids = set()
    for key, org in COMMON_ORGANISMS.items():
        taxid = org['taxid']
        if taxid in seen_taxids:
            continue
            
        # Check if query matches any field
        if (query_lower in key.lower() or 
            query_lower in org['scientific_name'].lower() or
            query_lower in org.get('common_name', '').lower() or
            query_lower == taxid):
            
            results.append({
                'name': org['scientific_name'],
                'taxid': taxid,
                'common_name': org.get('common_name', '')
            })
            seen_taxids.add(taxid)
            
        if len(results) >= limit:
            break
    
    # If query is numeric, try exact taxid match via NCBI
    if query.isdigit() and len(results) == 0:
        try:
            result = resolve_organism(query)
            if result:
                results.append({
                    'name': result['scientific_name'],
                    'taxid': result['taxid'],
                    'common_name': result.get('common_name', '')
                })
        except OrganismNotFoundError:
            pass
    
    return results


def search_organisms_ncbi(query: str, limit: int = 10) -> List[Dict[str, str]]:
    """
    Search NCBI Taxonomy for organisms by scientific/common name or TaxID.

    Returns a list of organisms with ``name`` (scientific name), ``common_name``
    and ``taxid``. Results are cached through the shared HTTP cache.
    """
    query = query.strip()
    if not query or len(query) < 2:
        return []

    tax_ids: List[str] = []

    if query.isdigit():
        tax_ids = [query]
    else:
        try:
            response = http_get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={
                    "db": "taxonomy",
                    "term": query,
                    "retmode": "json",
                    "retmax": limit,
                },
                timeout=10,
            )
            data = response.json()
            tax_ids = data.get("esearchresult", {}).get("idlist", [])[:limit]
        except Exception as e:
            logger.warning(f"NCBI organism search failed for {query!r}: {e}")
            return []

    if not tax_ids:
        return []

    try:
        summary_response = http_get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            params={
                "db": "taxonomy",
                "id": ",".join(tax_ids),
                "retmode": "json",
            },
            timeout=10,
        )
        summary_data = summary_response.json()
    except Exception as e:
        logger.warning(f"Could not fetch organism summaries for {query!r}: {e}")
        return []

    results: List[Dict[str, str]] = []
    result_docs = summary_data.get("result", {})
    for taxid in tax_ids:
        doc = result_docs.get(str(taxid), {})
        if not doc:
            continue
        # NCBI esummary returns lowercase keys in JSON
        scientific = doc.get("scientificname") or doc.get("ScientificName", "")
        if not scientific:
            continue
        results.append({
            "name": scientific,
            "common_name": doc.get("commonname") or doc.get("CommonName", ""),
            "taxid": str(taxid),
        })

    return results
