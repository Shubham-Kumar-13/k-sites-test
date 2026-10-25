#!/usr/bin/env python3
"""
Record a fixture for the JavaScript/Python parity test.

Runs the real Python pipeline on live data for a few genes, recording every HTTP response it
receives and the result it produces. The JavaScript engine is later run offline against the
same responses (tests/js/parity.test.mjs) and must reach the same scores.

    python tools/record_parity_fixture.py --go-term GO:0006284 --organism 9606 --genes 6

Writes tests/fixtures/js_parity/recording.json.gz and python_result.json.
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
    """Same key the JavaScript HttpClient uses: url plus the sorted, stringified parameters."""
    items = sorted((k, str(v)) for k, v in (params or {}).items() if v is not None)
    query = "&".join(f"{k}={v}" for k, v in items)
    return f"{url}?{query}" if query else url


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--go-term", default="GO:0006284")
    parser.add_argument("--organism", default="9606")
    parser.add_argument("--evidence", default="experimental")
    parser.add_argument("--genes", type=int, default=6, help="Only analyse the first N genes of the GO term")
    parser.add_argument("--max-pleiotropy", type=int, default=10)
    args = parser.parse_args()

    logging.disable(logging.CRITICAL)
    recording = {}

    import k_sites.data_retrieval.go_gene_mapper as mapper
    import k_sites.data_retrieval.multi_database_client as multi
    from k_sites.workflow import pipeline

    def recorder(real):
        def wrapper(url, **kwargs):
            response = real(url, **kwargs)
            recording[cache_key(url, kwargs.get("params"))] = {"status": response.status_code, "text": response.text}
            return response
        return wrapper

    real_requests_get = requests.get

    def requests_get(url, **kwargs):
        response = real_requests_get(url, **kwargs)
        recording[cache_key(url, kwargs.get("params"))] = {"status": response.status_code, "text": response.text}
        return response

    # the GO-term lookup has an on-disk cache; bypass it so the request is really made and recorded
    mapper._go_gene_cache.clear()
    mapper._load_cache = lambda: None
    mapper._save_cache = lambda: None

    mapper.http_get = recorder(mapper.http_get)
    multi.http_get = recorder(multi.http_get)
    requests.get = requests_get

    # analyse only the first few genes of the GO term, but keep the real coverage report
    real_with_coverage = mapper.get_genes_for_go_term_with_coverage

    def limited(*a, **kw):
        genes, coverage = real_with_coverage(*a, **kw)
        return genes[: args.genes], coverage

    mapper.get_genes_for_go_term_with_coverage = limited

    result = pipeline.run_k_sites_pipeline(
        go_term=args.go_term, organism=args.organism, max_pleiotropy=args.max_pleiotropy,
        evidence_filter=args.evidence, predict_phenotypes=False,
    )

    # keep only what is comparable and stable
    result["metadata"].pop("timestamp", None)
    result["metadata"].pop("execution_duration", None)
    for gene in result["genes"]:
        gene.pop("safety_recommendation_object", None)
    for key in ("most_specific_gene", "least_specific_gene"):
        result["statistics"][key] = (result["statistics"][key] or {}).get("symbol")

    FIXTURES.mkdir(parents=True, exist_ok=True)
    with gzip.open(FIXTURES / "recording.json.gz", "wt", encoding="utf-8") as handle:
        json.dump(recording, handle, separators=(",", ":"))
    meta = {"go_term": args.go_term, "organism": args.organism, "evidence_filter": args.evidence,
            "genes": args.genes, "max_pleiotropy": args.max_pleiotropy}
    (FIXTURES / "python_result.json").write_text(
        json.dumps({"input": meta, "result": result}, indent=1, default=str), encoding="utf-8")

    size = (FIXTURES / "recording.json.gz").stat().st_size
    print(f"Recorded {len(recording)} responses ({size / 1024:.0f} KB gzipped) and {len(result['genes'])} gene results")


if __name__ == "__main__":
    main()
