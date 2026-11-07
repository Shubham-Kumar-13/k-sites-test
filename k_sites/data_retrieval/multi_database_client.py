"""
Multi-Database Integration Client for K-Sites

Queries GO.org, UniProt, and KEGG SIMULTANEOUSLY for comprehensive gene data.
This is a CRITICAL component for non-pleiotropic gene identification.
"""

import logging
import os
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import json

from k_sites.data_retrieval.http import get_session, http_get

# Set up logging
logger = logging.getLogger(__name__)

# API Rate limiting
RATE_LIMIT_DELAY = 0.34  # ~3 requests per second

# NCBI E-Utilities credentials (required by NCBI, allows higher rate limit with API key)
NCBI_EMAIL = os.getenv("NCBI_EMAIL") or os.getenv("K_SITES_NCBI_EMAIL") or ""
NCBI_API_KEY = os.getenv("NCBI_API_KEY") or os.getenv("K_SITES_NCBI_API_KEY") or ""
NCBI_DELAY = 0.11 if NCBI_API_KEY else 0.34  # 10/sec with key, 3/sec without


class LookupFailure(Exception):
    """Raised when a database could not be queried (as opposed to returning no data)."""


# Higher number = stronger evidence when the same GO term is seen several times.
EVIDENCE_PRIORITY = {"experimental": 4, "computational": 3, "curatorial": 2, "IEA": 1, "unknown": 0}


class MultiDatabaseClient:
    """
    Client for querying GO.org, UniProt, and KEGG simultaneously.

    Each ``_query_*`` method returns data when the lookup worked (including "gene not
    found") and raises ``LookupFailure`` when the database itself could not be queried.
    """

    # Evidence code classifications - EXPLICIT as per requirements
    EXPERIMENTAL_EVIDENCE_CODES = {
        "IDA",  # Inferred from Direct Assay
        "IMP",  # Inferred from Mutant Phenotype
        "IGI",  # Inferred from Genetic Interaction
        "IPI",  # Inferred from Physical Interaction
        "IEP",  # Inferred from Expression Pattern
        "EXP",  # Inferred from Experiment
        "HTP",  # High Throughput experimental
        "HDA",  # High Throughput Direct Assay
        "HMP",  # High Throughput Mutant Phenotype
        "HGI",  # High Throughput Genetic Interaction
        "HEP",  # High Throughput Expression Pattern
    }

    COMPUTATIONAL_EVIDENCE_CODES = {
        "ISS",  # Inferred from Sequence or Structural Similarity
        "ISO",  # Inferred from Sequence Orthology
        "ISA",  # Inferred from Sequence Alignment
        "ISM",  # Inferred from Sequence Model
        "IGC",  # Inferred from Genomic Context
        "IBA",  # Inferred from Biological aspect of Ancestor
        "IBD",  # Inferred from Biological aspect of Descendant
        "IKR",  # Inferred from Key Residues
        "IRD",  # Inferred from Rapid Divergence
        "RCA",  # Reviewed Computational Analysis
    }

    # IEA is specifically called out as computational PREDICTION (not evidence)
    IEA_CODE = {"IEA"}  # Inferred from Electronic Annotation

    CURATORIAL_CODES = {
        "TAS",  # Traceable Author Statement
        "NAS",  # Non-traceable Author Statement
        "IC",   # Inferred by Curator
        "ND",   # No biological Data available
    }

    # Model organisms for cross-species validation (human, mouse, fly, worm)
    MODEL_ORGANISMS = {
        "9606": "Homo sapiens",      # Human
        "10090": "Mus musculus",     # Mouse
        "7227": "Drosophila melanogaster",  # Fly
        "6239": "Caenorhabditis elegans",   # Worm
    }

    QUICKGO_URL = "https://www.ebi.ac.uk/QuickGO/services/annotation/search"
    QUICKGO_PAGE_SIZE = 200  # QuickGO rejects larger pages with HTTP 400
    UNIPROT_URL = "https://rest.uniprot.org/uniprotkb/search"
    MYGENE_URL = "https://mygene.info/v3/query"
    NCBI_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    NCBI_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    def __init__(self):
        self.session = get_session()

    def query_all_databases_simultaneously(
        self,
        gene_symbol: str,
        taxid: str,
        databases: Optional[List[str]] = None
    ) -> Dict[str, any]:
        """
        Query the selected databases simultaneously for a gene.

        Args:
            gene_symbol: Gene symbol (e.g., "BRCA1")
            taxid: NCBI Taxonomy ID
            databases: List of database ids to query (e.g., ['quickgo', 'uniprot']).
                QuickGO is always included. When None, all available databases are used.

        Returns:
            Comprehensive gene data from the selected databases. ``query_status`` says per
            database whether the lookup worked; ``data_issues`` lists human-readable
            problems (failed lookups, unresolved gene).
        """
        logger.info(f"Querying databases for {gene_symbol} in {taxid}: {databases or 'all'}")

        selected = set(databases or [])
        if not selected:
            selected = {"quickgo", "uniprot", "mygene", "ncbi"}
        selected.add("quickgo")

        results = {
            "gene_symbol": gene_symbol,
            "taxid": taxid,
            "go_data": {},
            "uniprot_data": {},
            "mygene_data": {},
            "ncbi_data": {},
            "combined_bp_terms": [],
            "combined_evidence": {},
            "query_status": {},
            "data_issues": []
        }

        query_map = {
            "quickgo": ("go", self._query_quickgo),
            "uniprot": ("uniprot", self._query_uniprot),
            "mygene": ("mygene", self._query_mygene),
            "ncbi": ("ncbi", self._query_ncbi_gene),
        }
        active = {name: func for db_id, (name, func) in query_map.items() if db_id in selected}

        with ThreadPoolExecutor(max_workers=max(1, len(active))) as executor:
            futures = {
                executor.submit(func, gene_symbol, taxid): name
                for name, func in active.items()
            }

            for future in as_completed(futures):
                db_name = futures[future]
                try:
                    data = future.result()
                    results[f"{db_name}_data"] = data
                    results["query_status"][db_name] = "success"
                except Exception as e:
                    logger.warning(f"Failed to query {db_name} for {gene_symbol}: {e}")
                    results["query_status"][db_name] = f"failed: {str(e)}"
                    results["data_issues"].append(f"{db_name} lookup failed: {e}")

        # Combine and deduplicate BP terms from the selected sources
        results["combined_bp_terms"] = self._combine_bp_terms(results)
        results["combined_evidence"] = self._combine_evidence(results)

        return results

    def _query_quickgo(self, gene_symbol: str, taxid: str) -> Dict:
        """Query QuickGO (GO.org) for the Biological Process annotations of a gene."""
        logger.debug(f"Querying QuickGO for {gene_symbol}")

        uniprot_id = self._resolve_gene_to_uniprot(gene_symbol, taxid)
        if not uniprot_id:
            return {"found": False, "uniprot_id": None, "annotations": [], "bp_terms": [],
                    "bp_term_count": 0, "total_annotations": 0}

        raw_results = self._fetch_quickgo_bp_annotations(uniprot_id)

        annotations = []
        for result in raw_results:
            qualifier = str(result.get("qualifier", "")).upper().split("|")
            if "NOT" in qualifier:
                continue  # a NOT annotation says the gene is NOT involved in the process

            evidence_code = result.get("goEvidence", "")
            annotations.append({
                "go_id": result.get("goId", ""),
                "go_name": result.get("goName") or "",
                "aspect": result.get("goAspect", "biological_process"),
                "evidence_codes": [evidence_code] if evidence_code else [],
                "evidence_type": self._classify_evidence([evidence_code]),
                "source": "QuickGO"
            })

        return {
            "found": True,
            "uniprot_id": uniprot_id,
            "total_annotations": len(annotations),
            "bp_term_count": len({a["go_id"] for a in annotations}),
            "annotations": annotations,
            "bp_terms": annotations  # request is already limited to Biological Process
        }

    def _fetch_quickgo_bp_annotations(self, uniprot_id: str) -> List[Dict]:
        """Fetch every Biological Process annotation for a UniProt accession (paginated)."""
        collected: List[Dict] = []
        page = 1

        while True:
            params = {
                "geneProductId": uniprot_id,
                "aspect": "biological_process",
                "limit": self.QUICKGO_PAGE_SIZE,
                "page": page,
                "includeFields": "goName",
            }
            time.sleep(RATE_LIMIT_DELAY)
            try:
                response = http_get(self.QUICKGO_URL, params=params)
            except Exception as e:
                raise LookupFailure(f"QuickGO request failed: {e}")

            if response.status_code != 200:
                raise LookupFailure(f"QuickGO returned HTTP {response.status_code}: {response.text[:200]}")

            data = response.json()
            results = data.get("results", [])
            collected.extend(results)

            total_hits = data.get("numberOfHits", len(collected))
            if not results or len(collected) >= total_hits or page >= 50:
                break
            page += 1

        return collected

    def _query_uniprot(self, gene_symbol: str, taxid: str) -> Dict:
        """Query UniProt for gene/protein data."""
        logger.debug(f"Querying UniProt for {gene_symbol}")

        params = {
            "query": f"gene:{gene_symbol} AND organism_id:{taxid}",
            "format": "json",
            "fields": "accession,id,gene_names,protein_name,go_p,go_f,go_c,organism_name",
            "size": 10
        }

        time.sleep(RATE_LIMIT_DELAY)
        try:
            response = http_get(self.UNIPROT_URL, params=params)
        except Exception as e:
            raise LookupFailure(f"UniProt request failed: {e}")

        if response.status_code != 200:
            raise LookupFailure(f"UniProt returned HTTP {response.status_code}: {response.text[:200]}")

        data = response.json()

        entries = []
        bp_terms = []

        for result in data.get("results", []):
            accession = result.get("primaryAccession", "")
            go_annotations = []

            for go in result.get("uniProtKBCrossReferences", []):
                if go.get("database") != "GO":
                    continue
                go_id = go.get("id", "")
                properties = {p["key"]: p["value"] for p in go.get("properties", [])}
                go_term = properties.get("GoTerm", "")
                evidence = properties.get("GoEvidenceType", "")  # e.g. "IDA:UniProtKB"

                aspect = "unknown"
                if go_term.startswith("P:"):
                    aspect = "P"
                    bp_terms.append({
                        "go_id": go_id,
                        "go_name": go_term[2:],
                        "aspect": "biological_process",
                        "evidence_codes": [self._normalize_code(evidence)],
                        "evidence_type": self._classify_evidence([evidence]),
                        "source": "UniProt"
                    })
                elif go_term.startswith("F:"):
                    aspect = "F"
                elif go_term.startswith("C:"):
                    aspect = "C"

                go_annotations.append({
                    "go_id": go_id,
                    "go_term": go_term,
                    "aspect": aspect,
                    "evidence": evidence
                })

            entries.append({
                "accession": accession,
                "go_annotations": go_annotations
            })

        return {
            "found": bool(entries),
            "total_entries": len(entries),
            "bp_term_count": len({t["go_id"] for t in bp_terms}),
            "entries": entries,
            "bp_terms": bp_terms
        }

    def _query_mygene(self, gene_symbol: str, taxid: str) -> Dict:
        """Query MyGene.info for GO Biological Process annotations."""
        logger.debug(f"Querying MyGene.info for {gene_symbol}")

        params = {
            "q": f"symbol:{gene_symbol}",
            "species": taxid,
            "fields": "go",
            "size": 1,
        }

        time.sleep(RATE_LIMIT_DELAY)
        try:
            response = http_get(self.MYGENE_URL, params=params)
        except Exception as e:
            raise LookupFailure(f"MyGene.info request failed: {e}")

        if response.status_code != 200:
            raise LookupFailure(f"MyGene.info returned HTTP {response.status_code}: {response.text[:200]}")

        data = response.json()
        hits = data.get("hits", [])
        bp_terms = []

        for hit in hits:
            go = hit.get("go", {})
            bp = go.get("BP", [])
            if isinstance(bp, dict):
                bp = [bp]
            for term in bp:
                go_id = term.get("id", "")
                if not go_id:
                    continue
                evidence = term.get("evidence", "")
                bp_terms.append({
                    "go_id": go_id,
                    "go_name": term.get("term", ""),
                    "aspect": "biological_process",
                    "evidence_codes": [self._normalize_code(evidence)] if evidence else [],
                    "evidence_type": self._classify_evidence([evidence]),
                    "source": "MyGene.info",
                })

        return {
            "found": bool(bp_terms),
            "total_entries": len(hits),
            "bp_term_count": len({t["go_id"] for t in bp_terms}),
            "bp_terms": bp_terms,
        }

    def _query_ncbi_gene(self, gene_symbol: str, taxid: str) -> Dict:
        """Query NCBI Gene (Entrez) for GO Biological Process annotations."""
        logger.debug(f"Querying NCBI Gene for {gene_symbol}")

        params = {
            "db": "gene",
            "term": f"{gene_symbol}[Gene Name] AND {taxid}[Taxonomy ID]",
            "retmode": "json",
            "retmax": 1,
        }
        if NCBI_EMAIL:
            params["email"] = NCBI_EMAIL
        if NCBI_API_KEY:
            params["api_key"] = NCBI_API_KEY

        time.sleep(NCBI_DELAY)
        try:
            response = http_get(self.NCBI_ESEARCH_URL, params=params)
        except Exception as e:
            raise LookupFailure(f"NCBI esearch request failed: {e}")

        if response.status_code != 200:
            raise LookupFailure(f"NCBI esearch returned HTTP {response.status_code}: {response.text[:200]}")

        data = response.json()
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return {"found": False, "bp_term_count": 0, "bp_terms": []}

        gene_id = ids[0]
        params = {
            "db": "gene",
            "id": gene_id,
            "retmode": "xml",
        }
        if NCBI_EMAIL:
            params["email"] = NCBI_EMAIL
        if NCBI_API_KEY:
            params["api_key"] = NCBI_API_KEY

        time.sleep(NCBI_DELAY)
        try:
            response = http_get(self.NCBI_EFETCH_URL, params=params)
        except Exception as e:
            raise LookupFailure(f"NCBI efetch request failed: {e}")

        if response.status_code != 200:
            raise LookupFailure(f"NCBI efetch returned HTTP {response.status_code}: {response.text[:200]}")

        bp_terms = []
        try:
            root = ET.fromstring(response.text)
            for commentary in root.iter("Gene-commentary"):
                heading = (commentary.findtext("Gene-commentary_heading") or "").strip()
                if heading.lower() != "geneontology":
                    continue
                for section in commentary.findall(".//Gene-commentary"):
                    label = (section.findtext("Gene-commentary_label") or "").strip()
                    if label.lower() != "process":
                        continue
                    for entry in section.findall(".//Gene-commentary"):
                        go_id = None
                        go_name = None
                        evidence = None
                        for object_id in entry.findall(".//Object-id_id"):
                            value = (object_id.text or "").strip()
                            if value.isdigit():
                                go_id = f"GO:{int(value):07d}"
                                break
                        for anchor in entry.findall(".//Other-source_anchor"):
                            value = (anchor.text or "").strip()
                            if value:
                                go_name = value
                                break
                        for post_text in entry.findall(".//Other-source_post-text"):
                            value = (post_text.text or "").strip()
                            if value.lower().startswith("evidence:"):
                                evidence = value.split(":", 1)[1].strip()
                                break
                        if go_id:
                            bp_terms.append({
                                "go_id": go_id,
                                "go_name": go_name or "",
                                "aspect": "biological_process",
                                "evidence_codes": [self._normalize_code(evidence)] if evidence else [],
                                "evidence_type": self._classify_evidence([evidence]),
                                "source": "NCBI Gene",
                            })
        except ET.ParseError as e:
            raise LookupFailure(f"NCBI Gene XML parse failed: {e}")

        return {
            "found": bool(bp_terms),
            "gene_id": gene_id,
            "bp_term_count": len({t["go_id"] for t in bp_terms}),
            "bp_terms": bp_terms,
        }

    def _resolve_gene_to_uniprot(self, gene_symbol: str, taxid: str) -> Optional[str]:
        """
        Resolve gene symbol to a UniProt accession.

        Returns None when UniProt has no such gene; raises ``LookupFailure`` when UniProt
        could not be queried.
        """
        params = {
            "query": f"gene:{gene_symbol} AND organism_id:{taxid} AND reviewed:true",
            "format": "json",
            "fields": "accession",
            "size": 1
        }

        time.sleep(RATE_LIMIT_DELAY)
        try:
            response = http_get(self.UNIPROT_URL, params=params)
        except Exception as e:
            raise LookupFailure(f"UniProt request failed: {e}")

        if response.status_code != 200:
            raise LookupFailure(f"UniProt returned HTTP {response.status_code}")

        results = response.json().get("results", [])
        return results[0].get("primaryAccession") if results else None

    @staticmethod
    def _normalize_code(code) -> str:
        """Reduce 'IDA:UniProtKB' or 'ida' to the bare GO evidence code 'IDA'."""
        if not code:
            return ""
        return str(code).split(":")[0].strip().upper()

    def _classify_evidence(self, evidence_codes) -> str:
        """
        Classify evidence codes into experimental, computational, or IEA.

        CRITICAL: IDA, IMP, IGI must be classified as EXPERIMENTAL.
        IEA must be classified as computational PREDICTION.
        """
        if isinstance(evidence_codes, str):
            evidence_codes = [evidence_codes]
        codes = {self._normalize_code(c) for c in (evidence_codes or []) if c}
        codes.discard("")
        if not codes:
            return "unknown"

        # Check for experimental evidence FIRST (highest priority)
        if codes & self.EXPERIMENTAL_EVIDENCE_CODES:
            return "experimental"

        # Check for computational analysis (not IEA)
        if codes & self.COMPUTATIONAL_EVIDENCE_CODES:
            return "computational"

        # Check for curatorial evidence
        if codes & self.CURATORIAL_CODES:
            return "curatorial"

        # IEA (electronic annotation - lowest quality)
        if codes & self.IEA_CODE:
            return "IEA"

        return "unknown"

    def _combine_bp_terms(self, results: Dict) -> List[Dict]:
        """
        Combine and deduplicate BP terms from all sources.

        When a term is seen more than once, the strongest evidence type wins.
        """
        merged: Dict[str, Dict] = {}

        for source_key in ("go_data", "uniprot_data", "mygene_data", "ncbi_data"):
            for term in results.get(source_key, {}).get("bp_terms", []):
                go_id = term.get("go_id", "")
                if not go_id:
                    continue
                evidence_type = term.get("evidence_type", "unknown")
                existing = merged.get(go_id)
                if existing is None:
                    merged[go_id] = dict(term)
                elif EVIDENCE_PRIORITY.get(evidence_type, 0) > EVIDENCE_PRIORITY.get(existing.get("evidence_type", "unknown"), 0):
                    existing["evidence_type"] = evidence_type
                    existing["evidence_codes"] = term.get("evidence_codes", existing.get("evidence_codes", []))
                    if not existing.get("go_name"):
                        existing["go_name"] = term.get("go_name", "")

        return list(merged.values())

    def _combine_evidence(self, results: Dict) -> Dict:
        """Count the combined BP terms by their strongest evidence type."""
        evidence_counts = {
            "experimental": 0,
            "computational": 0,
            "IEA": 0,
            "curatorial": 0,
            "unknown": 0
        }

        for term in results.get("combined_bp_terms", []):
            evidence_type = term.get("evidence_type", "unknown")
            evidence_counts[evidence_type] = evidence_counts.get(evidence_type, 0) + 1

        return evidence_counts


# Singleton instance
_multi_db_client = None


def get_multi_database_client() -> MultiDatabaseClient:
    """Get the singleton multi-database client."""
    global _multi_db_client
    if _multi_db_client is None:
        _multi_db_client = MultiDatabaseClient()
    return _multi_db_client


def query_gene_from_all_databases(gene_symbol: str, taxid: str, databases: Optional[List[str]] = None) -> Dict:
    """
    Query the selected databases simultaneously for a gene.

    This is the main entry point for multi-database integration.
    """
    client = get_multi_database_client()
    return client.query_all_databases_simultaneously(gene_symbol, taxid, databases)
