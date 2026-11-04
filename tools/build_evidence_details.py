#!/usr/bin/env python3
"""Build a traceable pilot of Arabidopsis evidence without changing the scoring database."""

import argparse
import collections
import csv
import gzip
import json
import re
from datetime import date
from pathlib import Path

import requests

from build_evidence_data import THALEMINE_LIST_CALLS, fetch_thalemine_list

CALL = {"L": "LETHAL", "V": "VIABLE"}
AGI_LOCUS = re.compile(r"^AT(?:[1-5]|C|M)G\d{5}$")
MULTI_GENE = re.compile(
    r"(?:\b(?:double|triple|quadruple|quintuple|multiple)\b[^.!?;]*\b(?:mutants?|knockouts?|knock-outs?)\b|\bdouble homozygous\b)",
    re.I,
)
NEGATED_LETHAL = re.compile(
    r"\b(?:not|never|no)\b[^.!?;]*\blethal\b|\bdoes not\b[^.!?;]*\blethal\b|\b(?:caused|attributed) by\b[^.!?;]*\blocus\b",
    re.I,
)
LETHAL = [
    re.compile(r"\b(?:embryo|embryonic|seedling|gametophyte)[ -]lethal\b", re.I),
    re.compile(r"\blethal in the homozygous state\b", re.I),
    re.compile(r"\bhomozygous (?:mutants?|plants|progeny) (?:are|is) (?:embryo |seedling )?lethal\b", re.I),
    re.compile(r"\bhomozygotes are (?:embryo |seedling )?lethal\b", re.I),
    re.compile(r"\bconditional(?:ly)? lethal\b", re.I),
]
VIABLE = [
    re.compile(r"^no (?:visible|obvious) phenotype[.!?]?$", re.I),
    re.compile(r"^viable and fertile under described growth conditions[.!?]?$", re.I),
    re.compile(r"\bno visible whole plant phenotypic effect\b", re.I),
    re.compile(r"\bdoes not have any obvious aberrant phenotypes?\b", re.I),
    re.compile(r"\bhomozygous viable\b", re.I),
    re.compile(r"\bviable homozygotes\b", re.I),
]


def sentences(text):
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|;\s*", text or "") if part.strip()]


def classify_tair_sentence(sentence):
    lower = sentence.lower()
    if MULTI_GENE.search(sentence) or NEGATED_LETHAL.search(sentence) or "background line" in lower:
        return None
    lethal = any(pattern.search(sentence) for pattern in LETHAL)
    viable = any(pattern.search(sentence) for pattern in VIABLE)
    if lethal == viable:
        return None
    call = "LETHAL" if lethal else "VIABLE"
    qualifiers = []
    if any(word in lower for word in ("conditional", "unless", "restored", "supplied with", "under ", "when exposed",
                                      "fluctuating light", "rescued", "grafted")):
        qualifiers.append("conditional")
    if "incomplete penetrance" in lower:
        qualifiers.append("incomplete_penetrance")
    zygosity = "homozygous" if "homozyg" in lower else "not_reported"
    knockout = any(word in lower for word in ("knockout", "knock-out", "t-dna", "null allele"))
    return {
        "call": call,
        "experiment_type": "knockout" if knockout else "mutant_not_otherwise_specified",
        "zygosity": zygosity,
        "evidence_level": "direct" if knockout and zygosity == "homozygous" else "qualified",
        "qualifiers": qualifiers,
    }


def select_tair_genes(genes, gene_limit):
    if gene_limit is None:
        return sorted(genes)

    def profile(gene):
        calls = {record["call"] for record in genes[gene]}
        return next(iter(calls)) if len(calls) == 1 else "CONFLICTING"

    groups = {"LETHAL": [], "VIABLE": [], "CONFLICTING": []}
    for gene in sorted(genes):
        groups[profile(gene)].append(gene)
    selected = []
    for gene in ("AT1G01040", "AT1G02660", "AT1G02880"):
        if gene in genes and len(selected) < gene_limit:
            selected.append(gene)
            groups[profile(gene)].remove(gene)
    while len(selected) < gene_limit and any(groups.values()):
        for group in ("LETHAL", "VIABLE", "CONFLICTING"):
            if groups[group] and len(selected) < gene_limit:
                selected.append(groups[group].pop(0))
    return sorted(selected)


def parse_tair(rows, gene_limit=100):
    genes = collections.defaultdict(list)
    seen = {}
    for row in rows:
        locus = (row.get("LOCUS_NAME") or "").strip().upper()
        if not AGI_LOCUS.fullmatch(locus):
            continue
        germplasm = (row.get("GERMPLASM_NAME") or "").strip()
        if not germplasm or any(character in germplasm for character in (" ", "/", ",", ";", "+")):
            continue
        references = [value for value in (row.get("PUBMED_ID") or "").split() if value.isdigit()]
        for sentence in sentences(row.get("PHENOTYPE")):
            finding = classify_tair_sentence(sentence)
            if finding is None:
                continue
            key = (locus, germplasm, sentence)
            if key in seen:
                existing = seen[key]
                existing["references"] = sorted(set(existing["references"]) | set(references))
                continue
            record = {
                "source": "tair",
                "source_record_id": germplasm,
                "phenotype": sentence,
                "references": references,
                **finding,
            }
            genes[locus].append(record)
            seen[key] = record
    owners = collections.defaultdict(set)
    for gene, records in genes.items():
        for record in records:
            owners[(record["source_record_id"], record["phenotype"])].add(gene)
    ambiguous = {key for key, loci in owners.items() if len(loci) > 1}
    unambiguous = {
        gene: [record for record in records if (record["source_record_id"], record["phenotype"]) not in ambiguous]
        for gene, records in genes.items()
    }
    unambiguous = {gene: records for gene, records in unambiguous.items() if records}
    return {gene: unambiguous[gene] for gene in select_tair_genes(unambiguous, gene_limit)}


def build_thalemine_details(http):
    genes = collections.defaultdict(list)
    for list_name, call in THALEMINE_LIST_CALLS.items():
        text = fetch_thalemine_list(list_name, http)
        for line in text.strip().splitlines():
            parts = line.strip().split("\t")
            if len(parts) < 2:
                continue
            symbol, identifier = parts[0].strip().upper(), parts[1].strip()
            gene = identifier or symbol
            if not AGI_LOCUS.fullmatch(gene):
                continue
            genes[gene].append({
                "source": "thalemine",
                "source_record_id": list_name,
                "experiment_type": "curated_loss_of_function",
                "zygosity": "not_reported",
                "evidence_level": "curated",
                "call": CALL[call],
                "phenotype": f"Curated loss-of-function category: {list_name}",
                "qualifiers": ["phenotype_category"],
                "references": [],
            })
    return genes


def merge_gene_records(*sources):
    merged = collections.defaultdict(list)
    for source in sources:
        for gene, records in source.items():
            merged[gene].extend(records)
    result = {}
    for gene, records in merged.items():
        records.sort(key=lambda record: (record["source"], record["source_record_id"], record["phenotype"]))
        counts = collections.Counter(record["call"] for record in records)
        calls = sorted(counts)
        result[gene] = {
            "call": calls[0] if len(calls) == 1 else "CONFLICTING",
            "conflicting": len(calls) > 1,
            "counts": {"lethal": counts["LETHAL"], "viable": counts["VIABLE"]},
            "sources": sorted({record["source"] for record in records}),
            "records": records,
        }
    return result


def validate_details(data):
    genes = data.get("genes", {})
    if not genes:
        raise ValueError("The detailed evidence pilot is empty")
    owners = collections.defaultdict(set)
    for gene, record in genes.items():
        if not AGI_LOCUS.fullmatch(gene):
            raise ValueError(f"Invalid Arabidopsis locus: {gene}")
        if not record["records"]:
            raise ValueError(f"No evidence records for {gene}")
        calls = {finding["call"] for finding in record["records"]}
        expected = next(iter(calls)) if len(calls) == 1 else "CONFLICTING"
        if record["call"] != expected or record["conflicting"] != (len(calls) > 1):
            raise ValueError(f"Incorrect conflict summary for {gene}")
        seen = set()
        for finding in record["records"]:
            if finding["call"] not in ("LETHAL", "VIABLE"):
                raise ValueError(f"Invalid call for {gene}")
            if finding["evidence_level"] not in ("direct", "qualified", "curated"):
                raise ValueError(f"Invalid evidence level for {gene}")
            if MULTI_GENE.search(finding["phenotype"]):
                raise ValueError(f"Multi-gene evidence assigned to {gene}")
            if NEGATED_LETHAL.search(finding["phenotype"]):
                raise ValueError(f"Negated lethal evidence assigned to {gene}")
            if finding["source"] == "tair" and any(character in finding["source_record_id"] for character in (" ", "/", ",", ";", "+")):
                raise ValueError(f"Multi-gene germplasm assigned to {gene}")
            key = (finding["source"], finding["source_record_id"], finding["phenotype"])
            if key in seen:
                raise ValueError(f"Duplicate evidence record for {gene}")
            seen.add(key)
            if finding["source"] == "tair":
                owners[(finding["source_record_id"], finding["phenotype"])].add(gene)
    ambiguous = {key: loci for key, loci in owners.items() if len(loci) > 1}
    if ambiguous:
        raise ValueError(f"Cross-locus evidence ambiguity: {next(iter(ambiguous))}")
    return True


def build(out, tair_path, gene_limit=100):
    http = requests.Session()
    http.headers["User-Agent"] = "K-Sites detailed evidence pilot builder"
    with gzip.open(tair_path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
        tair = parse_tair(csv.DictReader(handle, delimiter="\t"), gene_limit)
    thalemine = build_thalemine_details(http)
    data = {
        "format": 1,
        "built": date.today().isoformat(),
        "organism": {"taxid": "3702", "name": "Arabidopsis thaliana"},
        "pilot": {
            "tair_gene_limit": gene_limit,
            "tair_genes": len(tair),
            "scope": ("100-gene audit pilot" if gene_limit is not None else "All TAIR rows passing strict evidence rules")
                      + "; incomplete biological coverage, not a replacement for the scoring database",
        },
        "genes": merge_gene_records(thalemine, tair),
    }
    validate_details(data)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tair", default=".cache/evidence-sources/tair_phenotype.txt.gz")
    parser.add_argument("--out", default="webapp/results/evidence-details/3702.json")
    parser.add_argument("--tair-gene-limit", type=int, default=100)
    parser.add_argument("--all-tair", action="store_true", help="Include every TAIR row passing the strict evidence rules")
    args = parser.parse_args()
    data = build(args.out, args.tair, None if args.all_tair else args.tair_gene_limit)
    print(f"Wrote {args.out}: {len(data['genes'])} genes, including {data['pilot']['tair_genes']} TAIR genes")


if __name__ == "__main__":
    main()
