#!/usr/bin/env python3
"""
Record a fixture for the phenotype-prediction parity test (JavaScript vs Python).

Runs the Python RAG phenotype predictor for a few genes on live PubMed data, recording every
NCBI answer and the prediction. tests/js/rag.test.mjs replays the answers through the browser
engine (with the MiniLM model) and compares.

    python tools/record_rag_fixture.py --genes POLB XRCC1 SMUG1
"""

import argparse
import gzip
import json
import logging
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "tests" / "fixtures" / "js_parity"


def cache_key(url, params):
    items = sorted((k, str(v)) for k, v in (params or {}).items() if v is not None)
    query = "&".join(f"{k}={v}" for k, v in items)
    return f"{url}?{query}" if query else url


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--genes", nargs="+", default=["POLB", "XRCC1", "SMUG1"])
    parser.add_argument("--from-recording", action="store_true",
                        help="Do not call PubMed: replay the saved answers and only recompute the Python result")
    args = parser.parse_args()

    logging.disable(logging.CRITICAL)
    recording = {}
    real_get = requests.get

    if args.from_recording:
        with gzip.open(FIXTURES / "rag_recording.json.gz", "rt", encoding="utf-8") as handle:
            saved = json.load(handle)

        class Saved:
            def __init__(self, entry):
                self.status_code, self.text = entry["status"], entry["text"]
                self.content = entry["text"].encode("utf-8")

            def json(self):
                return json.loads(self.text)

            def raise_for_status(self):
                pass

        def recording_get(url, **kwargs):
            return Saved(saved[cache_key(url, kwargs.get("params"))])
    else:
        def recording_get(url, **kwargs):
            response = real_get(url, **kwargs)
            recording[cache_key(url, kwargs.get("params"))] = {"status": response.status_code, "text": response.text}
            return response

    requests.get = recording_get

    from k_sites.rag_system.literature_context import RAGPhenotypePredictor

    predictor = RAGPhenotypePredictor()
    results = {}
    for gene in args.genes:
        prediction = predictor.predict_phenotype(gene, "9606")
        results[gene] = {
            "severity": prediction.severity.value,
            "risk_level": prediction.risk_level.value,
            "confidence_score": prediction.confidence_score,
            "predicted_phenotypes": sorted(prediction.predicted_phenotypes),
            "compensatory_mechanisms": sorted(prediction.compensatory_mechanisms),
            "lethality_stage": prediction.lethality_stage,
            "evidence_pmids": sorted(e["pmid"] for e in prediction.supporting_evidence),
            "similarity": {e["pmid"]: e["similarity_score"] for e in prediction.supporting_evidence},
        }
        print(f"{gene}: {prediction.severity.value} / {prediction.risk_level.value}, "
              f"confidence {prediction.confidence_score:.2f}, {len(prediction.supporting_evidence)} documents")

    FIXTURES.mkdir(parents=True, exist_ok=True)
    if not args.from_recording:
        with gzip.open(FIXTURES / "rag_recording.json.gz", "wt", encoding="utf-8") as handle:
            json.dump(recording, handle, separators=(",", ":"))
    (FIXTURES / "rag_python_result.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print("Replayed the saved NCBI answers" if args.from_recording else f"Recorded {len(recording)} NCBI responses")


if __name__ == "__main__":
    main()
