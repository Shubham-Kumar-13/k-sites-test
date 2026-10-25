#!/usr/bin/env python3
"""
Measure how well the phenotype prediction agrees with well-known mouse knockout outcomes.

Runs the predictor on live PubMed data for genes whose knockout is known to be lethal
(embryonic/perinatal/neonatal) or viable, and reports how many it gets right. Run it after
changing the phenotype logic:

    python tools/evaluate_phenotype_prediction.py
    python tools/evaluate_phenotype_prediction.py --save tests/fixtures/js_parity   # also record for the JS test

The truth list is general knowledge of published mouse knockouts (MGI). "Viable" includes genes
whose knockout mice have tumours or milder defects but are born and survive.
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

LETHAL = ["XRCC1", "POLB", "LIG3", "LIG4", "RAD51", "BRCA1", "APEX1", "FEN1", "ATR", "XRCC4", "TDG"]
VIABLE = ["OGG1", "UNG", "PARP1", "TP53", "MSH2", "MUTYH", "SMUG1", "NEIL1", "MPG", "NTHL1", "XPA", "XPC"]


def cache_key(url, params):
    items = sorted((k, str(v)) for k, v in (params or {}).items() if v is not None)
    query = "&".join(f"{k}={v}" for k, v in items)
    return f"{url}?{query}" if query else url


def protein_name(symbol):
    """The reviewed UniProt entry's recommended protein name, like the pipeline's gene description."""
    try:
        r = requests.get("https://rest.uniprot.org/uniprotkb/search", params={
            "query": f"gene_exact:{symbol} AND organism_id:9606 AND reviewed:true",
            "format": "json", "fields": "protein_name", "size": 1}, timeout=30)
        entry = r.json()["results"][0]
        return entry["proteinDescription"]["recommendedName"]["fullName"]["value"]
    except Exception:
        return ""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--save", help="Folder to save the NCBI answers and predictions for the JavaScript test")
    parser.add_argument("--genes", nargs="*", help="Evaluate only these genes")
    parser.add_argument("--from-recording", metavar="FOLDER", help="Replay saved NCBI answers from this folder instead of calling PubMed")
    args = parser.parse_args()

    logging.disable(logging.CRITICAL)
    recording = {}
    real_get = requests.get
    saved_aliases = {}

    if args.from_recording:
        folder = Path(args.from_recording)
        with gzip.open(folder / "rag_recording.json.gz", "rt", encoding="utf-8") as handle:
            saved = json.load(handle)
        saved_aliases = {g: v.get("alias", "") for g, v in json.loads((folder / "rag_python_result.json").read_text(encoding="utf-8")).items()}

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

    from k_sites.rag_system.literature_context import RAGPhenotypePredictor
    predictor = RAGPhenotypePredictor()

    truth = {g: "lethal" for g in LETHAL} | {g: "viable" for g in VIABLE}
    if args.genes:
        truth = {g: truth.get(g, "?") for g in args.genes}

    rows = []
    aliases = {g: saved_aliases.get(g, "") for g in truth} if args.from_recording else {g: protein_name(g) for g in truth}
    requests.get = recording_get
    for gene, expected in truth.items():
        prediction = predictor.predict_phenotype(gene, "9606", aliases=[aliases[gene]] if aliases[gene] else [])
        called_lethal = prediction.severity.value == "LETHAL"
        correct = (called_lethal if expected == "lethal" else not called_lethal) if expected != "?" else None
        rows.append((gene, expected, prediction, correct))
        mark = {True: "ok ", False: "WRONG", None: "   "}[correct]
        print(f"{mark:5s} {gene:7s} truth={expected:6s} predicted={prediction.severity.value:8s} "
              f"risk={prediction.risk_level.value:8s} conf={prediction.confidence_score:.2f} "
              f"stage={prediction.lethality_stage}", flush=True)
    requests.get = real_get

    scored = [r for r in rows if r[3] is not None]
    lethal = [r for r in scored if r[1] == "lethal"]
    viable = [r for r in scored if r[1] == "viable"]
    print()
    print(f"Lethal knockouts called LETHAL (sensitivity): {sum(r[3] for r in lethal)}/{len(lethal)}")
    print(f"Viable knockouts NOT called lethal (specificity): {sum(r[3] for r in viable)}/{len(viable)}")
    print(f"Overall: {sum(r[3] for r in scored)}/{len(scored)} correct")

    if args.save and not args.from_recording:
        folder = Path(args.save)
        folder.mkdir(parents=True, exist_ok=True)
        with gzip.open(folder / "rag_recording.json.gz", "wt", encoding="utf-8") as handle:
            json.dump(recording, handle, separators=(",", ":"))
        out = {}
        for gene, expected, p, _ in rows:
            out[gene] = {
                "alias": aliases[gene],
                "severity": p.severity.value, "risk_level": p.risk_level.value,
                "confidence_score": p.confidence_score,
                "predicted_phenotypes": sorted(p.predicted_phenotypes),
                "compensatory_mechanisms": sorted(p.compensatory_mechanisms),
                "lethality_stage": p.lethality_stage,
                "evidence_pmids": sorted(e["pmid"] for e in p.supporting_evidence),
            }
        (folder / "rag_python_result.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        print(f"Saved {len(recording)} NCBI answers and {len(out)} predictions to {folder}")


if __name__ == "__main__":
    main()
