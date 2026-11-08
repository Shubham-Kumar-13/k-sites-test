"""
Hosted-LLM phenotype predictor for the K-Sites backend.

This is an optional predictor: when the user supplies an API key for one of the
supported providers, the backend sends PubMed abstracts to that provider and asks
it to classify the likely knockout phenotype. The key is stored only for the
duration of the analysis job and is cleared afterwards.
"""

import json
import logging
import re
from typing import Dict, List, Optional

import requests

from k_sites.rag_system.literature_context import (
    LiteratureMiner,
    PhenotypePrediction,
    PhenotypeSeverity,
    RiskLevel,
)

logger = logging.getLogger(__name__)

MAX_PAPERS = 6
MAX_ABSTRACT_LENGTH = 2500
MAX_TOKENS = 1024
REQUEST_TIMEOUT = 60

LLM_PROVIDERS: Dict[str, Dict] = {
    "openai": {
        "name": "OpenAI",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4o-mini",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
        "build_body": lambda model, messages: {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_object"},
        },
        "extract_content": lambda data: data["choices"][0]["message"]["content"],
    },
    "anthropic": {
        "name": "Anthropic",
        "api_url": "https://api.anthropic.com/v1/messages",
        "default_model": "claude-3-5-sonnet-20241022",
        "headers": lambda key: {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        "build_body": lambda model, messages: {
            "model": model,
            "system": next((m["content"] for m in messages if m["role"] == "system"), ""),
            "messages": [m for m in messages if m["role"] != "system"],
            "temperature": 0.1,
            "max_tokens": MAX_TOKENS,
        },
        "extract_content": lambda data: data["content"][0]["text"],
    },
    "kimi": {
        "name": "Kimi (Moonshot)",
        "api_url": "https://api.moonshot.ai/v1/chat/completions",
        "default_model": "kimi-k2-0905-preview",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
        "build_body": lambda model, messages: {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_object"},
        },
        "extract_content": lambda data: data["choices"][0]["message"]["content"],
    },
    "qwen": {
        "name": "Qwen (Alibaba)",
        "api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "default_model": "qwen-plus",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
        "build_body": lambda model, messages: {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_object"},
        },
        "extract_content": lambda data: data["choices"][0]["message"]["content"],
    },
    "deepseek": {
        "name": "DeepSeek",
        "api_url": "https://api.deepseek.com/v1/chat/completions",
        "default_model": "deepseek-chat",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
        "build_body": lambda model, messages: {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_object"},
        },
        "extract_content": lambda data: data["choices"][0]["message"]["content"],
    },
    "grok": {
        "name": "Grok (xAI)",
        "api_url": "https://api.x.ai/v1/chat/completions",
        "default_model": "grok-2-latest",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
        "build_body": lambda model, messages: {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_object"},
        },
        "extract_content": lambda data: data["choices"][0]["message"]["content"],
    },
}

VALID_SEVERITY = {s.value for s in PhenotypeSeverity}
VALID_RISK = {r.value for r in RiskLevel}
RISK_FOR_SEVERITY = {
    PhenotypeSeverity.LETHAL.value: RiskLevel.CRITICAL.value,
    PhenotypeSeverity.SEVERE.value: RiskLevel.HIGH.value,
    PhenotypeSeverity.MODERATE.value: RiskLevel.MEDIUM.value,
    PhenotypeSeverity.MILD.value: RiskLevel.LOW.value,
    PhenotypeSeverity.UNKNOWN.value: RiskLevel.UNKNOWN.value,
}


def _unknown_prediction(reason: str) -> PhenotypePrediction:
    return PhenotypePrediction(
        severity=PhenotypeSeverity.UNKNOWN,
        risk_level=RiskLevel.UNKNOWN,
        confidence_score=0.1,
        predicted_phenotypes=[],
        supporting_evidence=[],
        lethality_stage=None,
        compensatory_mechanisms=[],
        confidence_reasoning=reason or "No literature-based prediction could be made",
    )


def _normalize_prediction(raw: Dict, selected_publications: List[Dict]) -> PhenotypePrediction:
    severity_value = raw.get("severity", "UNKNOWN")
    severity = PhenotypeSeverity[severity_value] if severity_value in VALID_SEVERITY else PhenotypeSeverity.UNKNOWN

    risk_value = raw.get("risk_level")
    if risk_value in VALID_RISK:
        risk_level = RiskLevel[risk_value]
    else:
        risk_level = RiskLevel[RISK_FOR_SEVERITY.get(severity_value, RiskLevel.UNKNOWN.value)]

    confidence = raw.get("confidence_score", 0.5)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.5

    supporting_evidence = raw.get("supporting_evidence") or [
        {
            "pmid": pub.get("pmid"),
            "title": pub.get("title"),
            "publication_date": pub.get("publication_date"),
            "journal": pub.get("journal"),
            "evidence_quality": "high",
        }
        for pub in selected_publications
    ]

    return PhenotypePrediction(
        severity=severity,
        risk_level=risk_level,
        confidence_score=confidence,
        predicted_phenotypes=raw.get("predicted_phenotypes") or [],
        supporting_evidence=supporting_evidence,
        lethality_stage=raw.get("lethality_stage") or None,
        compensatory_mechanisms=raw.get("compensatory_mechanisms") or [],
        confidence_reasoning=raw.get("reasoning") or "Phenotype inferred from PubMed abstracts by a hosted language model",
    )


def _build_prompt(symbol: str, taxid: str, aliases: List[str], publications: List[Dict]) -> str:
    alias_text = f"Aliases used in papers: {', '.join(aliases)}." if aliases else ""
    abstract_list = []
    for i, pub in enumerate(publications, start=1):
        title = pub.get("title") or "Untitled"
        abstract = (pub.get("abstract") or "")[:MAX_ABSTRACT_LENGTH]
        abstract_list.append(f"[{i}] Title: {title}\nAbstract: {abstract}")

    return f"""You are a biomedical literature analyst. A researcher wants to know the likely phenotype of knocking out the gene {symbol} (NCBI TaxID {taxid}). {alias_text}

Read the PubMed abstracts below. Focus only on sentences that describe the effect of knocking out, deleting, mutating, or inactivating {symbol}. Ignore drug-inhibition studies, synthetic lethality with other genes, and papers where {symbol} is only mentioned in passing.

Return exactly one JSON object with this structure:
{{
  "severity": "LETHAL" | "SEVERE" | "MODERATE" | "MILD" | "UNKNOWN",
  "risk_level": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN",
  "confidence_score": 0.0 to 1.0,
  "predicted_phenotypes": ["short phenotype term", ...],
  "lethality_stage": "Embryonic" | "Perinatal" | "Postnatal" | "Larval" | "Neonatal" | null,
  "compensatory_mechanisms": ["term", ...],
  "reasoning": "one-sentence explanation"
}}

Severity guide:
- LETHAL: knockout causes death, non-viability, or complete lethality.
- SEVERE: major developmental or physiological defects, but not universally lethal.
- MODERATE: partial defects or reduced fitness.
- MILD: subtle or no observable phenotype.
- UNKNOWN: the abstracts do not clearly describe the knockout effect.

Risk mapping: LETHAL→CRITICAL, SEVERE→HIGH, MODERATE→MEDIUM, MILD→LOW, UNKNOWN→UNKNOWN.
Confidence score: higher when multiple independent papers agree and the evidence is direct.

Abstracts:
{"\n\n".join(abstract_list)}"""


def _extract_json_object(text: str) -> Dict:
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError("Response did not contain a JSON object")
    return json.loads(match.group(0))


def _call_llm(provider_id: str, prompt: str, api_key: str, model: Optional[str] = None) -> Dict:
    provider = LLM_PROVIDERS.get(provider_id)
    if not provider:
        raise ValueError(f"Unknown LLM provider: {provider_id}")

    messages = [
        {"role": "system", "content": "You return only valid JSON."},
        {"role": "user", "content": prompt},
    ]

    response = requests.post(
        provider["api_url"],
        headers={"Content-Type": "application/json", **provider["headers"](api_key)},
        json=provider["build_body"](model or provider["default_model"], messages),
        timeout=REQUEST_TIMEOUT,
    )

    text = response.text
    if not response.ok:
        raise ValueError(f"{provider['name']} API returned HTTP {response.status_code}: {text[:200]}")

    data = response.json()
    content = provider["extract_content"](data)
    if not content or not content.strip():
        raise ValueError(f"{provider['name']} response had no content")

    return _extract_json_object(content)


class LlmPhenotypePredictor:
    """Predict knockout phenotypes by sending PubMed abstracts to a hosted LLM."""

    def __init__(self, provider: str, api_key: str, model: Optional[str] = None):
        if provider not in LLM_PROVIDERS:
            raise ValueError(f"Unsupported LLM provider: {provider}")
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.literature_miner = LiteratureMiner()

    def predict_phenotype(
        self,
        gene_symbol: str,
        organism_taxid: str = "9606",
        include_compensatory: bool = True,
        aliases: Optional[List[str]] = None,
    ) -> PhenotypePrediction:
        logger.info(f"LLM phenotype prediction for {gene_symbol} using provider {self.provider}")

        search_types = ["knockout", "phenotype", "viability", "mouse_knockout"]
        if include_compensatory:
            search_types.append("compensatory")

        seen = set()
        publications = []
        for search_type in search_types:
            try:
                pubs = self.literature_miner.search_pubmed(gene_symbol, search_type, retmax=20)
                for pub in pubs:
                    if pub.pmid not in seen:
                        seen.add(pub.pmid)
                        publications.append(pub)
            except Exception as e:
                logger.warning(f"LLM predictor PubMed search failed for {gene_symbol} ({search_type}): {e}")

        if not publications:
            return _unknown_prediction(f"No PubMed papers found for {gene_symbol}")

        selected = publications[:MAX_PAPERS]
        selected_dicts = [
            {
                "pmid": pub.pmid,
                "title": pub.title,
                "abstract": pub.abstract,
                "publication_date": pub.publication_date,
                "journal": pub.journal,
            }
            for pub in selected
        ]

        prompt = _build_prompt(gene_symbol, organism_taxid, aliases or [], selected_dicts)
        raw = _call_llm(self.provider, prompt, self.api_key, self.model)
        return _normalize_prediction(raw, selected_dicts)
