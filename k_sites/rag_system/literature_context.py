"""
RAG-Based Phenotype Prediction System for K-Sites

This module predicts knockout phenotypes by mining and semantically analyzing scientific literature.
Implements comprehensive RAG capabilities with PubMed/PMC integration, semantic embeddings,
adaptive retrieval, and phenotype extraction/classification.
"""

import logging
import os
import requests
import time
from typing import Dict, List, Optional, Tuple, Set
from pathlib import Path
import re
from dataclasses import dataclass, field
from enum import Enum
import json
from collections import defaultdict

# Optional imports for RAG functionality
try:
    from sentence_transformers import SentenceTransformer
    import faiss
    import numpy as np
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False
    logging.warning("RAG libraries not available. Install sentence-transformers, faiss-cpu, numpy for full functionality.")

# Set up logging
logger = logging.getLogger(__name__)

# Minimum cosine similarity (0-1) between a query and an abstract for the abstract to count as
# relevant. Short queries against abstracts rarely exceed 0.5 with MiniLM (the median is about
# 0.25), so the previous cut-off of 0.6 on 1/(1+d^2) -- which equals a cosine of 0.67 -- kept
# nothing and the prediction was always UNKNOWN.
DEFAULT_RELEVANCE_THRESHOLD = 0.30

# "synthetic lethal", "non-lethal" and "sublethal" do not say the gene itself is lethal when deleted
_NOT_LETHAL_PHRASES = re.compile(r"(?:synthetic[\s-]+lethal(?:ity)?|non-?lethal|sub-?lethal)", re.IGNORECASE)
_NOT_LETHAL_PREFIX = re.compile(r"(?:synthetic[\s-]+|non-?|sub-?)$", re.IGNORECASE)

# A sentence is evidence about deleting a gene when it names the gene AND describes losing it.
# Counting every "lethal" in 20 abstracts would call almost any gene lethal.
_LOSS_OF_FUNCTION = re.compile(
    r"knock-?out|knock-?down|\bko\b|\bnull\b|[-\u2212]/[-\u2212]|deficien|deletion|deleted|\bablat|disrupt"
    r"|loss[\s-]of|\black(?:s|ing|ed)?\b|inactivat|homozygous|mutant|essential",
    re.IGNORECASE,
)
_DRUG_CONTEXT = re.compile(
    r"inhibitor|inhibition|inhibiting|\bparpi?\b|olaparib|talazoparib|niraparib|rucaparib|trapping|therap|clinical|resistan",
    re.IGNORECASE,
)
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])")


# Define phenotype severity categories
class PhenotypeSeverity(Enum):
    LETHAL = "LETHAL"
    SEVERE = "SEVERE"
    MODERATE = "MODERATE"
    MILD = "MILD"
    UNKNOWN = "UNKNOWN"

class RiskLevel(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"

@dataclass
class PhenotypePrediction:
    severity: PhenotypeSeverity
    risk_level: RiskLevel
    confidence_score: float
    predicted_phenotypes: List[str]
    supporting_evidence: List[Dict]
    lethality_stage: Optional[str] = None
    confidence_reasoning: str = ""
    compensatory_mechanisms: List[str] = field(default_factory=list)

@dataclass
class LiteratureRecord:
    pmid: str
    pmcid: Optional[str]
    title: str
    abstract: str
    full_text: Optional[str]
    authors: List[str]
    journal: str
    publication_date: str
    doi: Optional[str]
    keywords: List[str]
    evidence_quality: str = "unknown"  # high, medium, low, unknown

class LiteratureMiner:
    """
    Handles literature mining from PubMed and PMC Open Access.
    Implements real-time PubMed integration with NCBI Entrez API.
    """
    
    def __init__(self):
        self.email = os.getenv('NCBI_EMAIL', 'kkokay07@gmail.com')
        self.api_key = os.getenv('NCBI_API_KEY', '')
        self.base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        self.pmc_base_url = "https://www.ncbi.nlm.nih.gov/pmc/articles/"
        self.oai_base_url = "https://www.ncbi.nlm.nih.gov/pmc/oai/oai.cgi"
        
    def _make_request(self, endpoint: str, params: Dict, timeout: int = 30) -> Optional[Dict]:
        """Make a request to NCBI E-Utilities with rate limiting."""
        try:
            if self.api_key:
                params["api_key"] = self.api_key
            
            response = requests.get(self.base_url + endpoint, params=params, timeout=timeout)
            response.raise_for_status()
            
            # Rate limiting - NCBI allows 3 requests/second without API key, 10/second with
            time.sleep(0.2 if self.api_key else 0.35)
            
            return response
        except Exception as e:
            logger.error(f"Error in NCBI request: {str(e)}")
            return None
    
    def search_pubmed(self, gene_symbol: str, search_type: str = "comprehensive", 
                     retmax: int = 100) -> List[LiteratureRecord]:
        """
        Search PubMed for literature related to a gene.
        
        Args:
            gene_symbol: Gene symbol to search for
            search_type: Type of search ("comprehensive", "knockout", "phenotype", 
                        "viability", "crispr", "compensatory")
            retmax: Maximum number of results to return
            
        Returns:
            List of LiteratureRecord objects
        """
        # Smart query construction based on search type
        query_templates = {
            "knockout": f"{gene_symbol}[Gene] AND (knockout[Title/Abstract] OR knockout[MeSH Terms] OR 'gene knockout'[Title/Abstract] OR deletion[Title/Abstract])",
            "phenotype": f"{gene_symbol}[Gene] AND (phenotype[Title/Abstract] OR phenotypic[Title/Abstract] OR 'mutant phenotype'[Title/Abstract] OR morphological[Title/Abstract])",
            "viability": f"{gene_symbol}[Gene] AND (viability[Title/Abstract] OR viable[Title/Abstract] OR lethal[Title/Abstract] OR lethality[Title/Abstract] OR survival[Title/Abstract] OR 'embryonic lethal'[Title/Abstract])",
            "crispr": f"{gene_symbol}[Gene] AND (CRISPR[Title/Abstract] OR 'guide RNA'[Title/Abstract] OR gRNA[Title/Abstract] OR 'gene editing'[Title/Abstract])",
            "compensatory": f"{gene_symbol}[Gene] AND (compensatory[Title/Abstract] OR compensation[Title/Abstract] OR 'redundant gene'[Title/Abstract] OR paralog[Title/Abstract] OR 'genetic buffering'[Title/Abstract])",
            "mouse_knockout": f"{gene_symbol}[Gene] AND (mice[MeSH Terms] OR mouse[Title/Abstract] OR murine[Title/Abstract]) AND (knockout[Title/Abstract] OR 'null mutation'[Title/Abstract] OR deficient[Title/Abstract] OR targeted[Title/Abstract]) AND (lethal[Title/Abstract] OR lethality[Title/Abstract] OR viable[Title/Abstract] OR embryonic[Title/Abstract] OR survival[Title/Abstract])",
            "comprehensive": f"{gene_symbol}[Gene] AND (knockout[Title/Abstract] OR phenotype[Title/Abstract] OR mutant[Title/Abstract] OR viability[Title/Abstract] OR CRISPR[Title/Abstract])"
        }
        
        query = query_templates.get(search_type, query_templates["comprehensive"])
        
        # Step 1: Search for PMIDs
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmax": retmax,
            "retmode": "json",
            "sort": "relevance",
            "email": self.email
        }
        
        response = self._make_request("esearch.fcgi", search_params)
        if not response:
            return []
        
        try:
            search_results = response.json()
            id_list = search_results.get("esearchresult", {}).get("idlist", [])
        except:
            logger.error("Failed to parse PubMed search response")
            return []
        
        if not id_list:
            logger.info(f"No publications found for gene {gene_symbol} with search type {search_type}")
            return []
        
        # Step 2: Fetch detailed records
        return self._fetch_pubmed_details(id_list[:min(50, retmax)])
    
    def _fetch_pubmed_details(self, pmid_list: List[str]) -> List[LiteratureRecord]:
        """Fetch detailed PubMed records including abstracts."""
        if not pmid_list:
            return []
        
        fetch_params = {
            "db": "pubmed",
            "id": ",".join(pmid_list),
            "retmode": "xml",
            "email": self.email
        }
        
        response = self._make_request("efetch.fcgi", fetch_params, timeout=60)
        if not response:
            return []
        
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.content)
            
            records = []
            for article in root.findall('.//PubmedArticle'):
                record = self._parse_pubmed_article(article)
                if record:
                    records.append(record)
            
            return records
        except Exception as e:
            logger.error(f"Error parsing PubMed XML: {str(e)}")
            return []
    
    def _parse_pubmed_article(self, article) -> Optional[LiteratureRecord]:
        """Parse a PubMed XML article into a LiteratureRecord."""
        try:
            import xml.etree.ElementTree as ET
            
            # Get PMID
            pmid_elem = article.find('.//PMID')
            pmid = pmid_elem.text if pmid_elem is not None else ""
            
            # Get PMC ID if available
            pmcid = None
            for article_id in article.findall('.//ArticleId'):
                if article_id.get('IdType') == 'pmc':
                    pmcid = article_id.text
                    break
            
            # Get title
            title_elem = article.find('.//ArticleTitle')
            title = "".join(title_elem.itertext()) if title_elem is not None else ""
            
            # Get abstract
            abstract_texts = []
            for abstract in article.findall('.//Abstract/AbstractText'):
                abstract_text = "".join(abstract.itertext())
                if abstract_text.strip():
                    abstract_texts.append(abstract_text)
            abstract = " ".join(abstract_texts)
            
            # Get authors
            authors = []
            for author in article.findall('.//Author'):
                last_name = author.find('LastName')
                fore_name = author.find('ForeName')
                if last_name is not None and last_name.text:
                    name = last_name.text
                    if fore_name is not None and fore_name.text:
                        name = fore_name.text + " " + name
                    authors.append(name)
            
            # Get journal
            journal_elem = article.find('.//Journal/Title')
            journal = journal_elem.text if journal_elem is not None else ""
            
            # Get publication date
            pub_date = ""
            year_elem = article.find('.//PubDate/Year')
            if year_elem is not None and year_elem.text:
                pub_date = year_elem.text
            
            # Get DOI
            doi = None
            for article_id in article.findall('.//ArticleId'):
                if article_id.get('IdType') == 'doi':
                    doi = article_id.text
                    break
            
            # Get keywords
            keywords = []
            for keyword in article.findall('.//Keyword'):
                if keyword.text:
                    keywords.append(keyword.text)
            
            return LiteratureRecord(
                pmid=pmid,
                pmcid=pmcid,
                title=title,
                abstract=abstract,
                full_text=None,  # Will be fetched separately if PMC ID available
                authors=authors,
                journal=journal,
                publication_date=pub_date,
                doi=doi,
                keywords=keywords
            )
        except Exception as e:
            logger.error(f"Error parsing article: {str(e)}")
            return None
    
    def fetch_pmc_fulltext(self, pmcid: str) -> Optional[str]:
        """
        Fetch full text from PMC Open Access.
        
        Args:
            pmcid: PMC ID (e.g., "PMC1234567")
            
        Returns:
            Full text content or None if unavailable
        """
        if not pmcid:
            return None
        
        # Remove "PMC" prefix if present
        pmcid_clean = pmcid.replace("PMC", "")
        
        try:
            # Try to fetch via OAI API
            params = {
                "verb": "GetRecord",
                "identifier": f"oai:pubmedcentral.nih.gov:{pmcid_clean}",
                "metadataPrefix": "pmc"
            }
            
            response = requests.get(self.oai_base_url, params=params, timeout=30)
            response.raise_for_status()
            
            # Parse XML to extract full text
            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.content)
            
            # Extract body text
            body_texts = []
            for elem in root.iter():
                if elem.tag.endswith('body') or elem.tag.endswith('p'):
                    if elem.text:
                        body_texts.append(elem.text)
            
            if body_texts:
                return "\n".join(body_texts)
            
            return None
        except Exception as e:
            logger.error(f"Error fetching PMC full text for {pmcid}: {str(e)}")
            return None
    
    def batch_search_genes(self, gene_symbols: List[str], search_types: Optional[List[str]] = None) -> Dict[str, List[LiteratureRecord]]:
        """
        Perform batch processing of multiple genes with multiple search strategies.
        
        Args:
            gene_symbols: List of gene symbols to search
            search_types: List of search types to perform (default: all types)
            
        Returns:
            Dictionary mapping gene symbols to their publication lists
        """
        if search_types is None:
            search_types = ["knockout", "phenotype", "viability", "crispr", "compensatory", "comprehensive"]
        
        results = {}
        
        for gene_symbol in gene_symbols:
            logger.info(f"Batch searching literature for gene: {gene_symbol}")
            
            gene_publications = []
            seen_pmids = set()
            
            for search_type in search_types:
                pubs = self.search_pubmed(gene_symbol, search_type, retmax=50)
                
                for pub in pubs:
                    if pub.pmid not in seen_pmids:
                        seen_pmids.add(pub.pmid)
                        gene_publications.append(pub)
                        
                        # Try to fetch full text if PMC ID available
                        if pub.pmcid:
                            full_text = self.fetch_pmc_fulltext(pub.pmcid)
                            if full_text:
                                pub.full_text = full_text
                                pub.evidence_quality = "high"  # Full text available
            
            results[gene_symbol] = gene_publications
            logger.info(f"Found {len(gene_publications)} unique publications for {gene_symbol}")
        
        return results


class DiversityAwareVectorStore:
    """
    Vector store for semantic search using FAISS with diversity weighting.
    Implements adaptive retrieval with relevance thresholding and diversity weighting.
    """
    
    def __init__(self, model_name: str = 'all-MiniLM-L6-v2'):
        if not RAG_AVAILABLE:
            logger.warning("Vector store unavailable due to missing dependencies")
            self.model = None
            self.index = None
            self.documents = []
            self.embeddings = None
        else:
            try:
                self.model = SentenceTransformer(model_name)
                logger.info(f"Loaded sentence transformer model: {model_name}")
            except Exception as e:
                logger.error(f"Could not load sentence transformer model: {e}")
                self.model = None
            
            self.index = None
            self.documents = []
            self.embeddings = None
    
    def add_documents(self, documents: List[LiteratureRecord]):
        """Add documents to the vector store."""
        if not RAG_AVAILABLE or self.model is None:
            logger.warning("Cannot add documents: RAG libraries not available")
            return
        
        if not documents:
            return
        
        # Prepare text for embedding
        texts = []
        for doc in documents:
            text = f"{doc.title}. {doc.abstract}"
            if doc.full_text:
                text += f" {doc.full_text[:2000]}"  # Add first 2000 chars of full text
            texts.append(text)
        
        # Generate embeddings
        embeddings = np.asarray(self.model.encode(texts, show_progress_bar=False), dtype="float32")
        embeddings = embeddings / np.maximum(np.linalg.norm(embeddings, axis=1, keepdims=True), 1e-12)
        
        # Create FAISS index if doesn't exist
        if self.index is None:
            dimension = embeddings.shape[1]
            self.index = faiss.IndexFlatL2(dimension)
            self.embeddings = embeddings
        else:
            self.embeddings = np.vstack([self.embeddings, embeddings])
        
        # Add to index
        self.index.add(embeddings.astype('float32'))
        self.documents.extend(documents)
        
        logger.info(f"Added {len(documents)} documents to vector store (total: {len(self.documents)})")
    
    def search(self, query: str, k: int = 10, relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
               diversity_weight: float = 0.3, context_aware: bool = True) -> List[Tuple[LiteratureRecord, float]]:
        """
        Perform semantic search with adaptive retrieval and diversity weighting.
        
        Args:
            query: Search query
            k: Number of results to return (will be adapted based on diversity)
            relevance_threshold: Minimum cosine similarity (0-1) between the query and a document
            diversity_weight: Weight for diversity vs relevance (0-1, higher = more diversity)
            context_aware: Whether to adapt k based on query context
            
        Returns:
            List of tuples (document, adjusted_score)
        """
        if not RAG_AVAILABLE or self.model is None or self.index is None:
            logger.warning("Cannot perform search: RAG libraries not available or index empty")
            return []
        
        # Context-aware k selection
        if context_aware:
            k = self._adapt_k_for_context(query, k)
        
        # Generate query embedding
        query_embedding = np.asarray(self.model.encode([query]), dtype="float32")
        query_embedding = query_embedding / np.maximum(np.linalg.norm(query_embedding, axis=1, keepdims=True), 1e-12)
        
        # Search for more results than needed for diversity reranking
        search_k = min(k * 3, len(self.documents))
        
        # Perform similarity search
        distances, indices = self.index.search(query_embedding.astype('float32'), search_k)
        
        # FAISS returns squared L2 distances. For unit-length vectors d^2 = 2 - 2*cos, so the
        # cosine similarity is 1 - d^2 / 2.
        similarities = 1.0 - distances[0] / 2.0
        
        # Filter by relevance threshold
        candidates = []
        for idx, sim in zip(indices[0], similarities):
            if idx < len(self.documents) and sim >= relevance_threshold:
                candidates.append((self.documents[idx], float(sim), idx))
        
        if not candidates:
            return []
        
        # Apply diversity weighting using Maximal Marginal Relevance (MMR)
        if diversity_weight > 0 and len(candidates) > k:
            selected = self._maximal_marginal_relevance(candidates, k, diversity_weight)
        else:
            selected = candidates[:k]
        
        logger.info(f"Retrieved {len(selected)} diverse documents for query: {query[:50]}...")
        return [(doc, score) for doc, score, _ in selected]
    
    def _adapt_k_for_context(self, query: str, base_k: int) -> int:
        """
        Adapt the number of retrieved documents based on query context.
        
        Viability/compensatory queries may need more documents for comprehensive analysis.
        Specific gene queries can use fewer documents.
        """
        query_lower = query.lower()
        
        # High-context queries that need more evidence
        high_context_terms = ['viability', 'lethal', 'compensatory', 'compensation', 
                             'phenotype', 'knockout', 'essential']
        
        # Count context terms
        context_score = sum(1 for term in high_context_terms if term in query_lower)
        
        if context_score >= 2:
            return min(base_k * 2, 20)  # Double the results for complex queries
        elif context_score == 1:
            return min(int(base_k * 1.5), 15)
        else:
            return base_k
    
    def _maximal_marginal_relevance(self, candidates: List[Tuple], k: int, 
                                    lambda_param: float) -> List[Tuple]:
        """
        Apply Maximal Marginal Relevance for diversity-weighted retrieval.
        
        MMR = lambda * Relevance - (1 - lambda) * max_similarity_to_selected
        
        Args:
            candidates: List of (document, score, idx) tuples
            k: Number of documents to select
            lambda_param: Trade-off between relevance and diversity (0-1)
            
        Returns:
            Selected documents with diversity weighting
        """
        if not RAG_AVAILABLE or self.embeddings is None:
            return candidates[:k]
        
        selected = []
        remaining = list(candidates)
        
        while len(selected) < k and remaining:
            if not selected:
                # Select highest relevance first
                best = max(remaining, key=lambda x: x[1])
                selected.append(best)
                remaining.remove(best)
            else:
                # Calculate MMR scores
                selected_indices = [idx for _, _, idx in selected]
                selected_embeddings = self.embeddings[selected_indices]
                
                mmr_scores = []
                for doc, rel_score, idx in remaining:
                    # Calculate max similarity to already selected documents
                    emb = self.embeddings[idx].reshape(1, -1)
                    sims = np.dot(selected_embeddings, emb.T).flatten()
                    max_sim = np.max(sims) if len(sims) > 0 else 0
                    
                    # MMR score
                    mmr_score = lambda_param * rel_score - (1 - lambda_param) * max_sim
                    mmr_scores.append((mmr_score, (doc, rel_score, idx)))
                
                # Select highest MMR score
                best = max(mmr_scores, key=lambda x: x[0])[1]
                selected.append(best)
                remaining.remove(best)
        
        return selected
    
    def clear(self):
        """Clear all documents from the vector store."""
        self.index = None
        self.documents = []
        self.embeddings = None
        logger.info("Vector store cleared")


class PhenotypeExtractor:
    """
    Extracts and classifies phenotypes from literature.
    Implements NLP pattern matching for phenotype terms with severity classification.
    """
    
    def __init__(self):
        # Comprehensive phenotype patterns organized by category
        self.phenotype_patterns = {
            "lethality": [
                r"\blethal\b", r"\blethality\b", r"embryonic\s+lethal", 
                r"perinatal\s+lethal", r"postnatal\s+lethal", r"prenatal\s+lethal",
                r"early\s+lethal", r"late\s+lethal", r"neonatal\s+lethal",
                r"\bdeath\b", r"\bmortality\b", r"\bsurvival\b",
                r"non-viable", r"inviable", r"sterile", r"\bsterility\b"
            ],
            "development": [
                r"growth\s+defect", r"developmental\s+defect", r"morphogenetic\s+defect",
                r"abnormal\s+development", r"malformation", r"\bdysplasia\b",
                r"congenital\s+defect", r"birth\s+defect", r"teratogenic",
                r"growth\s+retardation", r"developmental\s+delay", r"organogenesis\s+defect"
            ],
            "behavior": [
                r"behavioral\s+defect", r"locomotion\s+defect", r"motor\s+defect",
                r"movement\s+defect", r"coordination\s+defect", r"locomotor\s+defect",
                r"activity\s+defect", r"behavioral\s+abnormality", r"neurological\s+defect"
            ],
            "physiology": [
                r"metabolic\s+defect", r"cardiac\s+defect", r"cardiovascular\s+defect",
                r"respiratory\s+defect", r"neurological\s+defect", r"cognitive\s+defect",
                r"immune\s+defect", r"reproductive\s+defect", r"sensory\s+defect",
                r"vision\s+defect", r"hearing\s+defect", r"digestive\s+defect"
            ]
        }
        
        # Severity classification patterns
        self.severity_indicators = {
            PhenotypeSeverity.LETHAL: [
                r"\blethal\b", r"\blethality\b", r"embryonic\s+lethal", 
                r"perinatal\s+lethal", r"postnatal\s+lethal", r"early\s+lethal",
                r"100%\s+lethal", r"complete\s+lethality", r"fully\s+lethal",
                r"non-viable", r"inviable",
                r"\bdie[sd]?\b", r"(?:embryonic|perinatal|postnatal|neonatal|early|premature)\s+(?:death|mortality|demise)",
                r"fail(?:s|ed)?\s+to\s+survive"
            ],
            PhenotypeSeverity.SEVERE: [
                r"\bsevere\b", r"\bsevere\s+defect\b", r"major\s+defect", 
                r"profound\s+impairment", r"significant\s+defect", r"substantial\s+defect",
                r"extreme\s+phenotype", r"drastic\s+effect", r"dramatic\s+change"
            ],
            PhenotypeSeverity.MODERATE: [
                r"\bmoderate\b", r"\bintermediate\b", r"reduced\s+fitness", 
                r"partial\s+defect", r"mild\s+defect", r"minor\s+impairment",
                r"suboptimal", r"compromised"
            ],
            PhenotypeSeverity.MILD: [
                r"\bmild\b", r"\bsubtle\b", r"\bminor\b", r"\bslight\b", 
                r"\bsmall\s+change\b", r"\bminimal\b", r"\bweak\s+phenotype\b",
                r"(?<!non-)(?<!not\s)\bviable\b", r"\bfertile\b", r"normal\s+(?:development|lifespan|viability)",
                r"no\s+(?:obvious|overt|apparent|detectable|gross)\s+(?:phenotype|abnormalit)", r"\btolerated\b"
            ]
        }
        
        # Compensatory mechanism patterns
        self.compensatory_patterns = [
            r"compensat(?:e|ion|ory)", r"redundancy", r"redundant\s+gene",
            r"genetic\s+buffering", r"paralog", r"paralogous",
            r"backup\s+gene", r"functional\s+redundancy", r"gene\s+duplication",
            r"homeostatic\s+mechanism", r"feedback\s+mechanism"
        ]
    
    @staticmethod
    def gene_evidence_sentences(text: str, gene_symbol: str, require_loss: bool = True,
                                aliases: Optional[List[str]] = None) -> List[str]:
        """
        Sentences that mention the gene (by symbol or by an alias such as its protein name) and,
        unless require_loss is False, describe losing it (knockout, null, deficient, deletion, -/- ...).
        """
        if not text or not gene_symbol:
            return []
        names = [gene_symbol] + [a.strip() for a in (aliases or []) if a and len(a.strip()) >= 8]
        alternatives = "|".join(re.escape(n) for n in names)
        mention = re.compile(r"(?<![A-Za-z0-9])(?:" + alternatives + r")(?![A-Za-z0-9])", re.IGNORECASE)
        sentences = []
        for sentence in _SENTENCE_BREAK.split(text):
            if not mention.search(sentence):
                continue
            if require_loss and (not _LOSS_OF_FUNCTION.search(sentence) or _DRUG_CONTEXT.search(sentence)):
                continue
            sentences.append(sentence.strip())
        return sentences

    def extract_phenotypes_from_text(self, text: str) -> List[Dict]:
        """
        Extract phenotype terms from text using pattern matching.
        
        Args:
            text: Text to extract phenotypes from
            
        Returns:
            List of extracted phenotypes with details
        """
        if not text:
            return []
        
        phenotypes = []
        text_lower = text.lower()
        
        # Check for each phenotype category
        for category, patterns in self.phenotype_patterns.items():
            for pattern in patterns:
                for match in re.finditer(pattern, text_lower, re.IGNORECASE):
                    if "lethal" in match.group() and _NOT_LETHAL_PREFIX.search(text_lower[max(0, match.start() - 12):match.start()]):
                        continue  # "synthetic lethal", "non-lethal", "sublethal"
                    context_start = max(0, match.start() - 100)
                    context_end = min(len(text), match.end() + 100)

                    phenotype = {
                        "category": category,
                        "term": match.group(),
                        "position": match.span(),
                        "context": text[context_start:context_end].strip(),
                        "evidence_quality": "high" if len(text) > 500 else "medium"
                    }
                    phenotypes.append(phenotype)
        
        return phenotypes
    
    def extract_compensatory_mechanisms(self, text: str) -> List[Dict]:
        """Extract compensatory mechanism mentions from text."""
        if not text:
            return []
        
        mechanisms = []
        text_lower = text.lower()
        
        for pattern in self.compensatory_patterns:
            for match in re.finditer(pattern, text_lower, re.IGNORECASE):
                context_start = max(0, match.start() - 150)
                context_end = min(len(text), match.end() + 150)
                
                mechanisms.append({
                    "term": match.group(),
                    "context": text[context_start:context_end].strip(),
                    "confidence": "high" if "compensat" in match.group() else "medium"
                })
        
        return mechanisms
    
    def classify_severity(self, phenotypes: List[Dict], text: str = "") -> Tuple[PhenotypeSeverity, str]:
        """
        Classify the overall severity based on extracted phenotypes and text.
        
        Returns:
            Tuple of (severity, reasoning)
        """
        if not phenotypes and not text:
            return PhenotypeSeverity.UNKNOWN, "No phenotype data available"
        
        combined_text = _NOT_LETHAL_PHRASES.sub(" ", text.lower())
        for pheno in phenotypes:
            combined_text += " " + pheno.get("term", "").lower()
        
        # Count severity indicators
        severity_counts = {severity: 0 for severity in PhenotypeSeverity}
        
        for severity, patterns in self.severity_indicators.items():
            for pattern in patterns:
                matches = re.findall(pattern, combined_text, re.IGNORECASE)
                severity_counts[severity] += len(matches)
        
        # Determine overall severity (highest severity with at least one match)
        if severity_counts[PhenotypeSeverity.LETHAL] > 0:
            return PhenotypeSeverity.LETHAL, f"Lethality terms detected ({severity_counts[PhenotypeSeverity.LETHAL]} instances)"
        elif severity_counts[PhenotypeSeverity.SEVERE] > 0:
            return PhenotypeSeverity.SEVERE, f"Severe phenotype terms detected ({severity_counts[PhenotypeSeverity.SEVERE]} instances)"
        elif severity_counts[PhenotypeSeverity.MODERATE] > 0:
            return PhenotypeSeverity.MODERATE, f"Moderate phenotype terms detected ({severity_counts[PhenotypeSeverity.MODERATE]} instances)"
        elif severity_counts[PhenotypeSeverity.MILD] > 0:
            return PhenotypeSeverity.MILD, f"Mild phenotype terms detected ({severity_counts[PhenotypeSeverity.MILD]} instances)"
        else:
            return PhenotypeSeverity.UNKNOWN, "No clear severity indicators found in literature"
    
    def detect_lethality_stage(self, text: str) -> Optional[str]:
        """
        Detect the stage of lethality if present.
        
        Returns:
            Stage of lethality or None
        """
        if not text:
            return None
        
        text_lower = text.lower()
        
        stages = [
            (r"embryonic\s+lethal|embryo\s+lethal|prenatal\s+lethal|e\d+\.\d", "Embryonic"),
            (r"perinatal\s+lethal|perinatal\s+death|birth\s+lethal", "Perinatal"),
            (r"postnatal\s+lethal|adult\s+lethal|juvenile\s+lethal|p\d+\.\d", "Postnatal"),
            (r"larval\s+(?:stage\s+)?(?:lethal|death)|l\d+\s+lethal", "Larval"),
            (r"neonatal\s+lethal|newborn\s+lethal", "Neonatal")
        ]
        
        for pattern, stage in stages:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return stage
        
        return None
    
    def calculate_confidence_score(self, publications: List[LiteratureRecord], 
                                   phenotypes: List[Dict], 
                                   has_full_text: bool) -> Tuple[float, str]:
        """
        Calculate confidence score based on:
        - Publication count and quality
        - Evidence clarity (full text vs abstract only)
        - Consistency of findings
        
        Returns:
            Tuple of (confidence_score, reasoning)
        """
        if not publications:
            return 0.1, "No publication evidence available"
        
        # Base score from publication count
        pub_count = len(publications)
        if pub_count >= 20:
            pub_score = 0.4
        elif pub_count >= 10:
            pub_score = 0.3
        elif pub_count >= 5:
            pub_score = 0.2
        else:
            pub_score = 0.1
        
        # Evidence quality bonus
        high_quality_pubs = sum(1 for pub in publications if pub.evidence_quality == "high")
        evidence_score = min(0.3, high_quality_pubs * 0.1)
        
        # Full text bonus
        full_text_score = 0.2 if has_full_text else 0.0
        
        # Phenotype extraction bonus
        phenotype_score = min(0.2, len(phenotypes) * 0.05)
        
        # Calculate total
        total_score = pub_score + evidence_score + full_text_score + phenotype_score
        
        # Cap at 1.0
        total_score = min(1.0, total_score)
        
        reasoning = (
            f"Confidence based on {pub_count} publications "
            f"({high_quality_pubs} with full text), "
            f"{len(phenotypes)} phenotype terms extracted. "
            f"Evidence quality: {'High' if total_score > 0.7 else 'Medium' if total_score > 0.4 else 'Low'}."
        )
        
        return total_score, reasoning


class RAGPhenotypePredictor:
    """
    Main class for RAG-based phenotype prediction.
    Orchestrates literature mining, vector search, and phenotype extraction.
    """
    
    def __init__(self):
        self.literature_miner = LiteratureMiner()
        self.vector_store = DiversityAwareVectorStore()
        self.phenotype_extractor = PhenotypeExtractor()
        self.logger = logging.getLogger(__name__)
    
    def predict_phenotype(self, gene_symbol: str, organism_taxid: str = "9606",
                         include_compensatory: bool = True,
                         aliases: Optional[List[str]] = None) -> PhenotypePrediction:
        """
        Predict knockout phenotype for a gene using RAG.
        
        Args:
            gene_symbol: Gene symbol to predict phenotype for
            organism_taxid: NCBI Taxonomy ID for the organism
            include_compensatory: Whether to search for compensatory mechanisms
            aliases: Other names used for the gene in papers (e.g. its protein name)

        Returns:
            PhenotypePrediction object with results
        """
        self.logger.info(f"Predicting phenotype for gene {gene_symbol} in organism {organism_taxid}")
        
        # Step 1: Mine literature with multiple search strategies
        search_types = ["knockout", "phenotype", "viability", "mouse_knockout"]
        if include_compensatory:
            search_types.append("compensatory")
        
        publications = []
        for search_type in search_types:
            pubs = self.literature_miner.search_pubmed(gene_symbol, search_type, retmax=30)
            publications.extend(pubs)
        
        # Deduplicate publications
        seen_pmids = set()
        unique_publications = []
        for pub in publications:
            if pub.pmid not in seen_pmids:
                seen_pmids.add(pub.pmid)
                unique_publications.append(pub)
        
        if not unique_publications:
            self.logger.warning(f"No literature found for gene {gene_symbol}")
            return PhenotypePrediction(
                severity=PhenotypeSeverity.UNKNOWN,
                risk_level=RiskLevel.UNKNOWN,
                confidence_score=0.1,
                predicted_phenotypes=[],
                supporting_evidence=[],
                compensatory_mechanisms=[],
                confidence_reasoning="No literature found for this gene"
            )
        
        self.logger.info(f"Retrieved {len(unique_publications)} unique publications for {gene_symbol}")
        
        # Step 2: Add to vector store for semantic search
        self.vector_store.clear()
        self.vector_store.add_documents(unique_publications)
        
        # Step 3: Perform specialized queries
        queries = self._construct_specialized_queries(gene_symbol, include_compensatory)
        
        all_relevant_docs = []
        for query in queries:
            # Use adaptive retrieval with diversity weighting
            relevant_docs = self.vector_store.search(
                query, 
                k=5, 
                relevance_threshold=DEFAULT_RELEVANCE_THRESHOLD,
                diversity_weight=0.3,
                context_aware=True
            )
            all_relevant_docs.extend(relevant_docs)
        
        # Deduplicate
        seen_docs = set()
        unique_docs = []
        for doc, score in all_relevant_docs:
            if doc.pmid not in seen_docs:
                seen_docs.add(doc.pmid)
                unique_docs.append((doc, score))
        
        # Step 4: Extract phenotypes and compensatory mechanisms
        all_phenotypes = []
        all_compensatory = []
        supporting_evidence = []
        evidence_texts = []
        has_full_text = False
        
        for doc, score in unique_docs:
            # Combine all available text
            text_parts = [doc.title, doc.abstract]
            if doc.full_text:
                text_parts.append(doc.full_text)
                has_full_text = True
            
            text_content = " ".join(filter(None, text_parts))

            # Only sentences about losing THIS gene count as evidence
            evidence_text = " ".join(self.phenotype_extractor.gene_evidence_sentences(text_content, gene_symbol, aliases=aliases))
            gene_text = " ".join(self.phenotype_extractor.gene_evidence_sentences(text_content, gene_symbol, require_loss=False, aliases=aliases))
            evidence_texts.append(evidence_text)

            # Extract phenotypes
            phenotypes = self.phenotype_extractor.extract_phenotypes_from_text(evidence_text)
            all_phenotypes.extend(phenotypes)

            # Extract compensatory mechanisms
            compensatory = self.phenotype_extractor.extract_compensatory_mechanisms(gene_text)
            all_compensatory.extend(compensatory)
            
            # Add supporting evidence
            evidence = {
                "pmid": doc.pmid,
                "pmcid": doc.pmcid,
                "title": doc.title,
                "similarity_score": score,
                "phenotypes_extracted": [p["term"] for p in phenotypes],
                "evidence_quality": doc.evidence_quality,
                "publication_date": doc.publication_date,
                "journal": doc.journal
            }
            supporting_evidence.append(evidence)
        
        # Step 5: Classify severity
        combined_text = " ".join(evidence_texts)
        severity, severity_reasoning = self.phenotype_extractor.classify_severity(
            all_phenotypes, combined_text
        )
        if not combined_text.strip():
            severity_reasoning = (f"None of the {len(unique_publications)} retrieved papers has a sentence "
                                  f"describing the effect of losing {gene_symbol}")
        
        # Step 6: Determine risk level
        risk_mapping = {
            PhenotypeSeverity.LETHAL: RiskLevel.CRITICAL,
            PhenotypeSeverity.SEVERE: RiskLevel.HIGH,
            PhenotypeSeverity.MODERATE: RiskLevel.MEDIUM,
            PhenotypeSeverity.MILD: RiskLevel.LOW,
            PhenotypeSeverity.UNKNOWN: RiskLevel.UNKNOWN
        }
        risk_level = risk_mapping.get(severity, RiskLevel.UNKNOWN)
        
        # Step 7: Detect lethality stage if applicable
        lethality_stage = None
        if severity == PhenotypeSeverity.LETHAL:
            lethality_stage = self.phenotype_extractor.detect_lethality_stage(combined_text)
        
        # Step 8: Calculate confidence score
        confidence_score, confidence_reasoning = self.phenotype_extractor.calculate_confidence_score(
            unique_publications,
            all_phenotypes,
            has_full_text
        )
        
        # Step 9: Compile compensatory mechanisms
        compensatory_mechanisms = list(set([m["term"] for m in all_compensatory]))
        
        # Create prediction result
        prediction = PhenotypePrediction(
            severity=severity,
            risk_level=risk_level,
            confidence_score=confidence_score,
            predicted_phenotypes=list(set([p["term"] for p in all_phenotypes])),
            supporting_evidence=supporting_evidence,
            lethality_stage=lethality_stage,
            compensatory_mechanisms=compensatory_mechanisms,
            confidence_reasoning=confidence_reasoning + " " + severity_reasoning
        )
        
        self.logger.info(
            f"Predicted phenotype for {gene_symbol}: "
            f"severity={severity.value}, risk={risk_level.value}, "
            f"confidence={confidence_score:.2f}, "
            f"compensatory={len(compensatory_mechanisms)}"
        )
        
        return prediction
    
    def _construct_specialized_queries(self, gene_symbol: str, include_compensatory: bool) -> List[str]:
        """Construct specialized queries for phenotype prediction."""
        queries = [
            f"{gene_symbol} knockout phenotype",
            f"{gene_symbol} mutant viability",
            f"{gene_symbol} gene deletion effect",
            f"Is {gene_symbol} essential for survival?",
        ]
        
        if include_compensatory:
            queries.extend([
                f"{gene_symbol} compensatory mechanism",
                f"{gene_symbol} genetic redundancy",
                f"{gene_symbol} paralog compensation"
            ])
        
        return queries
    
    def batch_predict_phenotypes(self, gene_list: List[str], organism_taxid: str = "9606",
                                 include_compensatory: bool = True) -> Dict[str, PhenotypePrediction]:
        """
        Predict phenotypes for multiple genes.
        
        Args:
            gene_list: List of gene symbols
            organism_taxid: NCBI Taxonomy ID for the organism
            include_compensatory: Whether to search for compensatory mechanisms
            
        Returns:
            Dictionary mapping gene symbols to predictions
        """
        results = {}
        
        for gene_symbol in gene_list:
            try:
                prediction = self.predict_phenotype(gene_symbol, organism_taxid, include_compensatory)
                results[gene_symbol] = prediction
            except Exception as e:
                self.logger.error(f"Error predicting phenotype for {gene_symbol}: {str(e)}")
                results[gene_symbol] = PhenotypePrediction(
                    severity=PhenotypeSeverity.UNKNOWN,
                    risk_level=RiskLevel.UNKNOWN,
                    confidence_score=0.0,
                    predicted_phenotypes=[],
                    supporting_evidence=[],
                    compensatory_mechanisms=[],
                    confidence_reasoning=f"Prediction failed: {str(e)}"
                )
        
        return results


# Convenience functions for easy access
def predict_gene_phenotype(gene_symbol: str, organism_taxid: str = "9606",
                          include_compensatory: bool = True) -> PhenotypePrediction:
    """Convenience function to predict phenotype for a single gene."""
    predictor = RAGPhenotypePredictor()
    return predictor.predict_phenotype(gene_symbol, organism_taxid, include_compensatory)

def batch_predict_gene_phenotypes(gene_list: List[str], organism_taxid: str = "9606",
                                  include_compensatory: bool = True) -> Dict[str, PhenotypePrediction]:
    """Convenience function to predict phenotypes for multiple genes."""
    predictor = RAGPhenotypePredictor()
    return predictor.batch_predict_phenotypes(gene_list, organism_taxid, include_compensatory)
