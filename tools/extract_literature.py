#!/usr/bin/env python3
"""
Read the PubMed abstracts of genes that have no measured knockout result and write down what they report (build time only).

An AI model (Kimi, through its OpenAI-style API) reads the abstracts of the papers linked to a gene and answers one question per
paper: did the knockout / loss of the gene kill the animals or cells, make them subviable, or leave them viable? Every answer must
carry a quote, and the quote must appear word for word in the abstract, otherwise the answer is thrown away. That one rule is what
stops the model from inventing results.

The API key is read from the environment (KIMI_API_KEY or MOONSHOT_API_KEY) and is never written to a file, a log or the website.

    # 1. how accurate is it? Test on mouse genes whose outcome is already known from MGI/IMPC (needs the key, costs a little)
    python tools/extract_literature.py pilot --data .cache/evidence-out --genes 100

    # 2. only when the pilot is good enough: extract for genes with no result
    python tools/extract_literature.py extract --data .cache/evidence-out --taxid 10090 --genes 500 --out .cache/literature/10090.json

Optional environment variables: KIMI_BASE_URL (default https://api.moonshot.ai/v1), KIMI_MODEL, NCBI_API_KEY (more PubMed requests per second).
"""

import argparse
import collections
import gzip
import json
import os
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "literature"
SOURCES = ROOT / ".cache" / "evidence-sources"

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
DEFAULT_BASE_URL = "https://api.moonshot.ai/v1"
DEFAULT_MODEL = "kimi-k3.1-pro"
OUTCOMES = ("lethal", "subviable", "viable", "not_reported")
PAPERS_PER_GENE = 8                       # the papers read for one gene (the most recent ones that mention a knockout)
KNOCKOUT_WORDS = re.compile(r"knock-?out|null mutant|null allele|deletion mutant|loss[- ]of[- ]function|-/-|homozygous|"
                            r"mutant|deficient|inactivation|CRISPR|disrupt", re.IGNORECASE)

SYSTEM = (
    "You read one scientific abstract about the gene {gene} ({organism}) and report what it says happens when the gene is "
    "knocked out, deleted or mutated to lose its function (not overexpression, not a drug). Answer with JSON only: "
    '{{"outcome": "lethal" | "subviable" | "viable" | "not_reported", "stage": "<when the animals or cells die, or empty>", '
    '"quote": "<one sentence copied word for word from the abstract that supports the outcome, or empty>"}}. '
    'Use "lethal" only when the abstract states that homozygous knockout animals / cells die or cannot be obtained, '
    '"subviable" when fewer survive than expected, "viable" when they survive, and "not_reported" in every other case, '
    "including when the abstract is about a different gene or a heterozygous or conditional knockout only. "
    "Never guess: when the abstract does not say, answer not_reported."
)


# ----------------------------------------------------------------------------------------------------------------------
# PubMed
# ----------------------------------------------------------------------------------------------------------------------

def parse_abstracts(xml_text):
    """{pmid: 'title. abstract'} from a PubMed efetch XML answer (articles without an abstract are left out)."""
    found = {}
    for article in ET.fromstring(xml_text).iter("PubmedArticle"):
        pmid = article.findtext(".//PMID")
        title = "".join(article.find(".//ArticleTitle").itertext()) if article.find(".//ArticleTitle") is not None else ""
        parts = ["".join(node.itertext()) for node in article.iterfind(".//Abstract/AbstractText")]
        if pmid and parts:
            found[pmid] = f"{title.strip()} {' '.join(p.strip() for p in parts)}".strip()
    return found


class PubMed:
    """Fetches abstracts in batches and keeps every abstract it has seen on disk."""

    def __init__(self, cache=CACHE, session=None, sleep=time.sleep):
        self.path = Path(cache) / "abstracts.json"
        self.session = session or requests
        self.sleep = sleep
        self.delay = 0.11 if os.environ.get("NCBI_API_KEY") else 0.35
        self.store = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def get(self, pmids):
        wanted = [p for p in dict.fromkeys(str(p) for p in pmids) if p not in self.store]
        for start in range(0, len(wanted), 150):
            batch = wanted[start:start + 150]
            params = {"db": "pubmed", "id": ",".join(batch), "retmode": "xml"}
            if os.environ.get("NCBI_API_KEY"):
                params["api_key"] = os.environ["NCBI_API_KEY"]
            response = self.session.get(EUTILS, params=params, timeout=120)
            response.raise_for_status()
            found = parse_abstracts(response.content)
            for pmid in batch:
                self.store[pmid] = found.get(pmid, "")        # "" = no abstract, remembered so it is not asked again
            self.sleep(self.delay)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.store), encoding="utf-8")
        return {str(p): self.store.get(str(p), "") for p in pmids}


def read_gene_links(taxid, symbols, sources=SOURCES):
    """{SYMBOL: [pmids, newest first]} for the given symbols, from NCBI gene_info and gene2pubmed."""
    ids = {}
    with gzip.open(Path(sources) / f"ncbi_gene_info_{taxid}.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            f = line.split("\t")
            if len(f) > 2 and f[2].strip().upper() in symbols:
                ids.setdefault(f[1], f[2].strip().upper())
    links = collections.defaultdict(set)
    with gzip.open(Path(sources) / "ncbi_gene2pubmed.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            f = line.split("\t")
            if len(f) > 2 and f[0] == str(taxid) and f[1] in ids:
                links[ids[f[1]]].add(f[2].strip())
    return {symbol: sorted(pmids, key=int, reverse=True) for symbol, pmids in links.items()}


# ----------------------------------------------------------------------------------------------------------------------
# the model
# ----------------------------------------------------------------------------------------------------------------------

def normalise(text):
    return re.sub(r"\s+", " ", text or "").strip().lower()


def check_answer(raw, abstract):
    """The model's JSON answer checked against the abstract: {'outcome', 'stage', 'quote'} or None when it cannot be trusted."""
    try:
        answer = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(answer, dict) or answer.get("outcome") not in OUTCOMES:
        return None
    if answer["outcome"] == "not_reported":
        return {"outcome": "not_reported", "stage": "", "quote": ""}
    quote = (answer.get("quote") or "").strip()
    if len(quote) < 20 or normalise(quote) not in normalise(abstract):
        return None            # a result without a word-for-word quote is thrown away: that is what stops invented results
    return {"outcome": answer["outcome"], "stage": str(answer.get("stage") or "")[:80], "quote": quote}


class Kimi:
    """The chat API of Kimi (OpenAI style). The key comes from the environment only."""

    def __init__(self, session=None, environ=None):
        env = os.environ if environ is None else environ
        self.key = env.get("KIMI_API_KEY") or env.get("MOONSHOT_API_KEY")
        if not self.key:
            raise SystemExit("Set the KIMI_API_KEY environment variable first (the key is never stored by this tool).")
        self.base = (env.get("KIMI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model = env.get("KIMI_MODEL") or DEFAULT_MODEL
        self.session = session or requests
        self.calls = 0

    def ask(self, gene, organism, abstract):
        body = {"model": self.model, "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": SYSTEM.format(gene=gene, organism=organism)},
                             {"role": "user", "content": abstract[:6000]}]}
        for attempt in range(4):
            response = self.session.post(f"{self.base}/chat/completions", json=body, timeout=180,
                                         headers={"Authorization": f"Bearer {self.key}"})
            if response.status_code in (429, 500, 502, 503):
                time.sleep(5 * (attempt + 1))
                continue
            response.raise_for_status()
            self.calls += 1
            return response.json()["choices"][0]["message"]["content"]
        raise requests.RequestException("the Kimi API did not answer")


def read_gene(llm, pubmed, gene, organism, pmids, papers=PAPERS_PER_GENE):
    """What the papers say about one gene: {'outcome', 'quote', 'pmid', 'papers'} or None when no paper reports a result."""
    abstracts = pubmed.get(pmids[:papers * 6])
    relevant = [(p, abstracts[p]) for p in map(str, pmids[:papers * 6]) if abstracts.get(p) and KNOCKOUT_WORDS.search(abstracts[p])]
    votes = []
    for pmid, abstract in relevant[:papers]:
        answer = check_answer(llm.ask(gene, organism, abstract), abstract)
        if answer and answer["outcome"] != "not_reported":
            votes.append({**answer, "pmid": pmid})
    if not votes:
        return None
    counts = collections.Counter(v["outcome"] for v in votes)
    # a lethal report wins over a viable one only when it is the most common answer; ties go to the more cautious outcome
    order = {"lethal": 0, "subviable": 1, "viable": 2}
    best = sorted(counts, key=lambda o: (-counts[o], order[o]))[0]
    pick = next(v for v in votes if v["outcome"] == best)
    return {"outcome": best, "quote": pick["quote"], "pmid": pick["pmid"], "papers": len(votes),
            "agree": counts[best], "mixed": len(counts) > 1}


# ----------------------------------------------------------------------------------------------------------------------
# commands
# ----------------------------------------------------------------------------------------------------------------------

LETTER = {"lethal": "L", "subviable": "S", "viable": "V"}


def pilot(args):
    """Accuracy of the reading on mouse genes with a known outcome (MGI/IMPC). The abstracts are the only thing the model sees."""
    genes = json.loads((Path(args.data) / "10090.json").read_text(encoding="utf-8"))["genes"]
    known = {s: r["v"] for s, r in genes.items() if r.get("v") and not r.get("x") and r["v"] in "LV"}
    sample = sorted(known)
    random.Random(7).shuffle(sample)          # the same sample every time
    links = read_gene_links("10090", set(sample))
    llm, pubmed = Kimi(), PubMed(args.cache)
    rows = []
    for symbol in sample:
        if len(rows) >= args.genes:
            break
        if symbol not in links:
            continue
        result = read_gene(llm, pubmed, symbol, "Mus musculus", links[symbol])
        rows.append((symbol, known[symbol], LETTER.get(result["outcome"]) if result else None, result))
        print(f"  {symbol:12s} known {known[symbol]}  read {rows[-1][2]}", flush=True)
    answered = [r for r in rows if r[2]]
    right = [r for r in answered if r[1] == r[2] or (r[1] == "L" and r[2] == "S")]
    called_lethal = [r for r in answered if r[2] == "L"]
    lethal_known = [r for r in rows if r[1] == "L"]
    print(f"\nGenes tried {len(rows)}; the abstracts gave an answer for {len(answered)} ({100 * len(answered) / max(1, len(rows)):.0f}%).")
    print(f"Of the answers, {len(right)} agree with MGI/IMPC ({100 * len(right) / max(1, len(answered)):.0f}%).")
    print(f"Called lethal: {len(called_lethal)}, of which truly lethal {sum(1 for r in called_lethal if r[1] == 'L')} "
          f"({100 * sum(1 for r in called_lethal if r[1] == 'L') / max(1, len(called_lethal)):.0f}% precision); "
          f"found {sum(1 for r in lethal_known if r[2] in ('L', 'S'))} of {len(lethal_known)} lethal genes.")
    Path(args.cache).mkdir(parents=True, exist_ok=True)
    (Path(args.cache) / "pilot.json").write_text(json.dumps([{"gene": s, "known": k, "read": r, "result": x} for s, k, r, x in rows],
                                                              indent=1), encoding="utf-8")
    print(f"Calls to the model: {llm.calls}. Details: {Path(args.cache) / 'pilot.json'}")


def extract(args):
    """Outcomes for genes of one organism that have no measured result; resumes from the output file."""
    data = Path(args.data)
    genes = json.loads((data / f"{args.taxid}.json").read_text(encoding="utf-8"))["genes"]
    todo = sorted(s for s, r in genes.items() if "v" not in r and "m" not in r and r.get("lc", 0) >= 1)
    links = read_gene_links(args.taxid, set(todo))
    out = Path(args.out)
    done = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    llm, pubmed = Kimi(), PubMed(args.cache)
    organism = args.organism or args.taxid
    tried = 0
    for symbol in todo:
        if tried >= args.genes:
            break
        if symbol in done or symbol not in links:
            continue
        tried += 1
        done[symbol] = read_gene(llm, pubmed, symbol, organism, links[symbol]) or {"outcome": "not_reported"}
        if tried % 20 == 0:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(done, indent=1, sort_keys=True), encoding="utf-8")
            print(f"  {tried} genes read", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(done, indent=1, sort_keys=True), encoding="utf-8")
    useful = sum(1 for r in done.values() if r["outcome"] != "not_reported")
    print(f"{len(done)} genes in {out}, {useful} with a reported outcome. Calls to the model: {llm.calls}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, function in (("pilot", pilot), ("extract", extract)):
        p = sub.add_parser(name)
        p.add_argument("--data", default=str(ROOT / ".cache" / "evidence-out"), help="Folder with the built evidence files")
        p.add_argument("--cache", default=str(CACHE), help="Where abstracts and results are kept")
        p.add_argument("--genes", type=int, default=100, help="How many genes to read")
        p.set_defaults(function=function)
    sub.choices["extract"].add_argument("--taxid", required=True)
    sub.choices["extract"].add_argument("--organism", help="Name given to the model, for example 'Mus musculus'")
    sub.choices["extract"].add_argument("--out", required=True)
    args = parser.parse_args()
    args.function(args)


if __name__ == "__main__":
    main()
