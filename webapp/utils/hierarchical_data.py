"""
Hierarchical data structures for organism and GO term selection
Uses KEGG API for organisms and QuickGO/OLS API for GO terms
"""

import requests
import logging
import re
import json
from pathlib import Path
from typing import List, Dict, Optional
from functools import lru_cache

logger = logging.getLogger(__name__)

# KEGG organism code -> NCBI taxonomy id mapping shipped with the repo
_TAXID_MAPPING_FILE = Path(__file__).resolve().parent.parent.parent / "tools" / "data" / "kegg_code_to_taxid.json"


def _load_taxid_mapping() -> Dict[str, str]:
    """Load the kegg_code -> NCBI taxid mapping shipped with the repo."""
    if _TAXID_MAPPING_FILE.exists():
        try:
            return json.loads(_TAXID_MAPPING_FILE.read_text(encoding="utf-8"))
        except Exception as error:
            logger.warning(f"Could not read {_TAXID_MAPPING_FILE}: {error}")
    return {}

# Kingdom categories with icons (no hardcoded species)
KINGDOMS = {
    "Animals": {
        "icon": "fa-paw",
        "description": "Metazoans - multicellular animals"
    },
    "Plants": {
        "icon": "fa-leaf",
        "description": "Viridiplantae - green plants"
    },
    "Microbes": {
        "icon": "fa-bacterium",
        "description": "Bacteria, Archaea, and single-celled Eukaryotes"
    },
    "Fungi": {
        "icon": "fa-mushroom",
        "description": "Fungi - yeasts, molds, mushrooms"
    },
    "Other Eukaryotes": {
        "icon": "fa-dna",
        "description": "Protists and other eukaryotic organisms"
    }
}

# GO Categories (namespaces)
GO_CATEGORIES = {
    "Biological Process": {
        "icon": "fa-project-diagram",
        "description": "Larger biological programs accomplished by multiple molecular activities"
    },
    "Molecular Function": {
        "icon": "fa-atom",
        "description": "Activities that occur at the molecular level"
    },
    "Cellular Component": {
        "icon": "fa-cubes",
        "description": "Locations in the cell where gene products are active"
    }
}

# Cache for KEGG organisms
_kegg_organisms_cache: Optional[List[Dict]] = None


def _classify_organism(kegg_class: str) -> str:
    """Classify organism into kingdom based on KEGG class field."""
    # KEGG taxonomy format: Eukaryotes;Animals;Mammals;Primates
    # or: Prokaryotes;Bacteria;Proteobacteria;Gammaproteobacteria
    parts = [p.strip() for p in kegg_class.split(';')]

    # Check for prokaryotes first
    if any(p in ['Bacteria', 'Archaea'] for p in parts):
        return "Microbes"

    # Check for plants
    if 'Plants' in parts or any('Plant' in p for p in parts):
        return "Plants"

    # Check for fungi
    if 'Fungi' in parts:
        return "Fungi"

    # Check for animals (includes Mammals, Birds, Fish, Insects, etc.)
    if 'Animals' in parts:
        return "Animals"

    # Default to Other Eukaryotes for protists, etc.
    return "Other Eukaryotes"


@lru_cache(maxsize=1)
def fetch_kegg_organisms() -> List[Dict]:
    """
    Fetch all organisms from KEGG database.
    Returns list of organism dictionaries with name, taxid, kegg_code, and kingdom.
    """
    global _kegg_organisms_cache

    if _kegg_organisms_cache is not None:
        return _kegg_organisms_cache

    try:
        # KEGG BRITE hierarchy endpoint for organism list
        url = "https://www.genome.jp/kegg-bin/download_htext?htext=br08601.keg&format=htext"
        response = requests.get(url, timeout=60)
        response.raise_for_status()

        taxid_mapping = _load_taxid_mapping()
        organisms = []
        levels = {}
        for line in response.text.splitlines():
            if not line or line[0] not in "ABCDE" or line.startswith("+"):
                continue
            letter, content = line[0], line[1:].strip()
            if not content:
                continue
            if letter != "E":
                level = "ABCDE".index(letter)
                levels[level] = re.sub(r"\s*\(\d+\)\s*$", "", content)
                for deeper in [k for k in levels if k > level]:
                    del levels[deeper]
                continue
            match = re.match(r"^(\S+)\s+(.+)$", content)
            if not match:
                continue
            code, label = match.groups()
            taxonomy = ";".join(levels[k] for k in sorted(levels))
            common_name = ""
            name = label
            paren = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", label)
            if paren:
                name, common_name = paren.group(1).strip(), paren.group(2).strip()
            taxid = taxid_mapping.get(code, "")
            organisms.append({
                "name": name,
                "common_name": common_name,
                "taxid": taxid,
                "kegg_code": code,
                "kingdom": _classify_organism(taxonomy),
                "taxonomy": taxonomy,
            })

        _kegg_organisms_cache = organisms
        logger.info(f"Fetched {len(organisms)} organisms from KEGG")
        return organisms

    except Exception as e:
        logger.error(f"Error fetching KEGG organisms: {e}")
        # Return fallback organisms if API fails
        return _get_fallback_organisms()


def _get_fallback_organisms() -> List[Dict]:
    """Fallback organisms if KEGG API fails."""
    return [
        {"name": "Homo sapiens", "taxid": "9606", "common_name": "Human", "kingdom": "Animals", "kegg_code": "hsa"},
        {"name": "Mus musculus", "taxid": "10090", "common_name": "House mouse", "kingdom": "Animals", "kegg_code": "mmu"},
        {"name": "Rattus norvegicus", "taxid": "10116", "common_name": "Norway rat", "kingdom": "Animals", "kegg_code": "rno"},
        {"name": "Arabidopsis thaliana", "taxid": "3702", "common_name": "Thale cress", "kingdom": "Plants", "kegg_code": "ath"},
        {"name": "Saccharomyces cerevisiae", "taxid": "559292", "common_name": "Baker's yeast", "kingdom": "Fungi", "kegg_code": "sce"},
        {"name": "Escherichia coli", "taxid": "83333", "common_name": "E. coli K-12", "kingdom": "Microbes", "kegg_code": "eco"},
        {"name": "Drosophila melanogaster", "taxid": "7227", "common_name": "Fruit fly", "kingdom": "Animals", "kegg_code": "dme"},
        {"name": "Caenorhabditis elegans", "taxid": "6239", "common_name": "Nematode worm", "kingdom": "Animals", "kegg_code": "cel"},
    ]


def search_organisms_by_kingdom(kingdom: str = None, query: str = None) -> List[Dict]:
    """
    Search organisms with optional kingdom filter.
    Fetches all organisms from KEGG database.
    Results are sorted alphabetically by scientific name.
    """
    all_organisms = fetch_kegg_organisms()
    results = []
    
    for org in all_organisms:
        # Filter by kingdom if specified
        if kingdom and org.get("kingdom") != kingdom:
            continue
        
        # Filter by query if specified
        if query:
            query_lower = query.lower()
            if not (query_lower in org["name"].lower() or 
                    query_lower in org.get("common_name", "").lower() or
                    query == org.get("taxid", "")):
                continue
        
        results.append(org)
    
    # Sort alphabetically by scientific name
    results.sort(key=lambda x: x["name"].lower())
    return results


def search_go_terms_by_category(category: str = None, query: str = None) -> List[Dict]:
    """
    Search GO terms with optional category filter.
    Uses OLS (Ontology Lookup Service) API to fetch GO terms dynamically.
    Results are sorted alphabetically by GO term name.
    """
    results = []
    
    # Map category names to GO namespaces
    namespace_map = {
        "Biological Process": "biological_process",
        "Molecular Function": "molecular_function", 
        "Cellular Component": "cellular_component"
    }
    
    # If query is provided, search via OLS API
    if query:
        try:
            url = "https://www.ebi.ac.uk/ols4/api/search"
            params = {
                "q": query,
                "ontology": "go",
                "rows": 50
            }
            if category and category in namespace_map:
                params["fq"] = f"ontology_name:go AND type:class AND namespace:\"{namespace_map[category]}\""
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            for doc in data.get("response", {}).get("docs", []):
                go_id = doc.get("obo_id", "")
                if not go_id.startswith("GO:"):
                    continue
                
                term_category = "Biological Process"
                doc_ns = doc.get("namespace", "")
                for cat, ns in namespace_map.items():
                    if ns == doc_ns:
                        term_category = cat
                        break
                
                # Skip if category filter doesn't match
                if category and term_category != category:
                    continue
                
                results.append({
                    "id": go_id,
                    "name": doc.get("label", ""),
                    "definition": doc.get("description", [""])[0] if doc.get("description") else "",
                    "category": term_category
                })
            
            # Sort alphabetically by name
            results.sort(key=lambda x: x["name"].lower())
            return results
            
        except Exception as e:
            logger.error(f"Error searching GO terms: {e}")
            return []
    
    # If no query and category specified, fetch popular terms for that category
    if category and not query:
        results = _get_popular_go_terms(category)
        # Sort alphabetically by name
        results.sort(key=lambda x: x["name"].lower())
        return results
    
    # Return empty list if no filters
    return []


def _get_popular_go_terms(category: str) -> List[Dict]:
    """Get popular/high-level GO terms for a category."""
    popular_terms = {
        "Biological Process": [
            {"id": "GO:0006281", "name": "DNA repair", "definition": "The process of restoring DNA after damage"},
            {"id": "GO:0006974", "name": "cellular response to DNA damage stimulus", "definition": "Any process that results in a change in state or activity of a cell"},
            {"id": "GO:0006260", "name": "DNA replication", "definition": "The cellular metabolic process in which a cell duplicates DNA"},
            {"id": "GO:0006351", "name": "transcription, DNA-templated", "definition": "The cellular synthesis of RNA on a template of DNA"},
            {"id": "GO:0006412", "name": "translation", "definition": "The cellular metabolic process in which a protein is formed"},
            {"id": "GO:0006915", "name": "apoptotic process", "definition": "A programmed cell death process"},
            {"id": "GO:0007049", "name": "cell cycle", "definition": "The progression of biochemical phases in a cell"},
            {"id": "GO:0006955", "name": "immune response", "definition": "Any immune system process functioning in response to stimulus"},
            {"id": "GO:0007165", "name": "signal transduction", "definition": "The cellular process conveying a signal to trigger change"},
            {"id": "GO:0008152", "name": "metabolic process", "definition": "The chemical reactions and pathways transforming substances"},
        ],
        "Molecular Function": [
            {"id": "GO:0003674", "name": "molecular_function", "definition": "The elemental activities of a gene product"},
            {"id": "GO:0003677", "name": "DNA binding", "definition": "Any molecular function involving selective DNA interaction"},
            {"id": "GO:0003700", "name": "DNA-binding transcription factor activity", "definition": "A protein interacting with a specific DNA sequence"},
            {"id": "GO:0003723", "name": "RNA binding", "definition": "Interacting selectively with an RNA molecule"},
            {"id": "GO:0003824", "name": "catalytic activity", "definition": "Catalysis of a biochemical reaction at physiological temperatures"},
            {"id": "GO:0004871", "name": "signal transducer activity", "definition": "A molecular function accepting and transmitting a signal"},
            {"id": "GO:0004872", "name": "receptor activity", "definition": "Receiving a signal to initiate a change in cell activity"},
            {"id": "GO:0005215", "name": "transporter activity", "definition": "Enables directed movement of substances"},
            {"id": "GO:0005515", "name": "protein binding", "definition": "Interacting selectively with any protein"},
            {"id": "GO:0016787", "name": "hydrolase activity", "definition": "Catalysis of the hydrolysis of various bonds"},
        ],
        "Cellular Component": [
            {"id": "GO:0005575", "name": "cellular_component", "definition": "A location in or near a cell"},
            {"id": "GO:0005576", "name": "extracellular region", "definition": "The space external to the outermost structure of a cell"},
            {"id": "GO:0005622", "name": "intracellular", "definition": "The living contents of a cell"},
            {"id": "GO:0005634", "name": "nucleus", "definition": "A membrane-bounded organelle of eukaryotic cells"},
            {"id": "GO:0005737", "name": "cytoplasm", "definition": "All cell contents excluding plasma membrane and nucleus"},
            {"id": "GO:0005739", "name": "mitochondrion", "definition": "A semiautonomous, self-replicating organelle"},
            {"id": "GO:0005783", "name": "endoplasmic reticulum", "definition": "The irregular network of unit membranes"},
            {"id": "GO:0005794", "name": "Golgi apparatus", "definition": "A membrane-bound cytoplasmic organelle"},
            {"id": "GO:0005829", "name": "cytosol", "definition": "The part of cytoplasm without organelles"},
            {"id": "GO:0005886", "name": "plasma membrane", "definition": "The membrane surrounding and separating the cell"},
        ]
    }
    
    terms = popular_terms.get(category, [])
    return [{**term, "category": category} for term in terms]


def get_kingdoms() -> List[Dict]:
    """Get list of available kingdoms (without counts)."""
    return [
        {
            "name": kingdom,
            "icon": data["icon"],
            "description": data["description"]
        }
        for kingdom, data in KINGDOMS.items()
    ]


def get_go_categories() -> List[Dict]:
    """Get list of GO categories (without counts)."""
    return [
        {
            "name": category,
            "icon": data["icon"],
            "description": data["description"]
        }
        for category, data in GO_CATEGORIES.items()
    ]
