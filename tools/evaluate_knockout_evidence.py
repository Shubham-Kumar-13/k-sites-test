#!/usr/bin/env python3
"""
How far can the measured knockout evidence be trusted?  Writes the numbers behind VALIDATION.md.

    python tools/build_evidence_data.py --out .cache/evidence-out        # the data files
    python tools/evaluate_knockout_evidence.py                           # prints the report
    python tools/evaluate_knockout_evidence.py --out VALIDATION.md       # writes it
    python tools/evaluate_knockout_evidence.py --predictor 60            # also tests the keyword predictor (needs the network)

What is checked
  1. Published knockouts: genes whose outcome was read from the original paper (tests/fixtures/benchmark/paper_truth.json).
  2. Two independent sources: the MGI literature curation against the IMPC screen, gene by gene.
  3. Mouse against human cells: are genes that kill the mouse embryo also essential in human cell lines (DepMap)?
  4. Coverage: how many genes have a measured result at all.
  5. (optional) The keyword-based phenotype predictor, which is only used where nothing was measured, against the
     measured outcome of a random sample of genes.
"""

import argparse
import collections
import csv
import gzip
import importlib.util
import json
import math
import random
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from k_sites.knockout_evidence import EvidenceProvider, assess_gene       # noqa: E402
from k_sites.workflow.safety_recommender import get_safety_recommendation  # noqa: E402

TRUTH = ROOT / "tests" / "fixtures" / "benchmark" / "paper_truth.json"
FLAGGED = ("AVOID", "HIGH_CONCERN")


INTRO = """# Validation of the measured knockout evidence

K-Sites rates a gene from what has been *measured* when the gene is lost. This page checks how far those measurements
can be trusted, how well the estimate for genes without a measurement works, and how informative the pleiotropy score is.
The numbers below are
produced by `tools/evaluate_knockout_evidence.py`; they describe the data version named below and are refreshed with it.
"""

OUTRO = """## What these checks do not show

- **They do not prove that a knockout will work in your hands.** A measurement says what happened in the published mice, yeast
  or cell lines; strain, allele, cell type, culture conditions and the way the gene is removed all matter.
- **The two mouse sources are not fully independent.** IMPC alleles are often knockout-first or deletion alleles that can be
  hypomorphic, while literature nulls are often classical alleles; where they disagree the report shows both and rates the
  gene at least HIGH_CONCERN if any line was lethal.
- **Absence of a lethality annotation is weak evidence of viability.** K-Sites therefore counts a knockout as viable only when
  the null animals were examined as young or adult animals (or declared normal); genes with only embryonic findings stay
  "not verified".
- **Cell-line essentiality comes from cancer cell lines** (DepMap 24Q4). Primary cells, stem cells and other cell types can differ.
- **Zebrafish, fly and worm are measured only for the genes their community databases cover.** ZFIN, FlyBase and WormBase
  curate mutants that were studied for a reason, so the covered genes are biased towards interesting phenotypes (and, for
  zebrafish, towards recent CRISPR mutants); fish with morpholinos, transgenes or heterozygous genotypes are left out. WormBase
  does not say which alleles are null, so a gene is called viable only when two or more alleles are reported not lethal, and a
  lethal call that rests on RNAi alone is marked as such. Genes without a measurement of their own, Xenopus, and every plant
  or other organism have no measured data; for zebrafish, fly, worm and Xenopus the knockout of the mouse ortholog is shown as
  a hint, never as a measurement. Arabidopsis has no openly licensed machine-readable knockout resource that could be used.

## How to reproduce

```bash
python tools/build_evidence_data.py --out .cache/evidence-out        # builds the data files (downloads the sources once)
python tools/evaluate_knockout_evidence.py --out VALIDATION.md       # re-runs sections 1-5 and 7
python tools/evaluate_knockout_evidence.py --predictor 60            # adds section 6 (needs the network, about 20 minutes)
python -m pytest tests/test_paper_truth.py                            # the published-knockout check as a unit test
```

The published-knockout list is `tests/fixtures/benchmark/paper_truth.json`; every entry cites the paper whose abstract was read.
"""


def load_builder():
    spec = importlib.util.spec_from_file_location("build_evidence_data", ROOT / "tools" / "build_evidence_data.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_evidence_data"] = module
    spec.loader.exec_module(module)
    return module


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def pct(part, whole):
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


# --------------------------------------------------------------------------------------------------------------------
def paper_check(provider):
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))["genes"]
    rows, lethal_ok, viable_ok = [], 0, 0
    species = {"10090": "mouse", "7955": "zebrafish", "7227": "fly", "6239": "worm"}
    for entry in truth:
        taxid = entry.get("taxid", "10090")
        evidence = assess_gene(provider, taxid, entry["gene"])
        verdict = get_safety_recommendation(entry["gene"], 3.0, knockout_evidence=evidence)
        flagged = verdict.safety_level.value in FLAGGED
        organism = evidence["organism"]
        ok = flagged if entry["expected"] == "lethal" else not (verdict.safety_level.value == "AVOID")
        lethal_ok += ok and entry["expected"] == "lethal"
        viable_ok += ok and entry["expected"] == "viable"
        stage = organism["stage_text"] if organism["stage"] and organism["stage"] != "U" else ""
        counts = organism["counts"]
        other_lines = [f"{counts[key]} {key}" for key in ("lethal", "subviable") if counts[key]]
        mixed = f"; {', '.join(other_lines)} of {sum(counts.values())} lines" if organism["call"] == "VIABLE" and other_lines else ""
        rows.append([species[taxid], entry["gene"], entry["expected"], f"{organism['call'].lower()}" + (f" ({stage})" if stage else "") + mixed,
                     verdict.safety_level.value, "yes" if ok else "**NO**",
                     f"[{entry['citation']}](https://doi.org/{entry['doi']})"])
    n_lethal = sum(1 for e in truth if e["expected"] == "lethal")
    n_viable = len(truth) - n_lethal
    by_species = ", ".join(f"{sum(1 for e in truth if e.get('taxid', '10090') == t)} {name}" for t, name in species.items())
    text = [f"Genes whose knockout outcome was read from the original paper: {n_lethal} lethal, {n_viable} viable ({by_species}).", "",
            table(["Organism", "Gene", "Paper says", "Data says", "Verdict", "Agrees", "Paper"], rows), "",
            f"- Lethal knockouts flagged (AVOID or HIGH_CONCERN): **{lethal_ok} of {n_lethal}**",
            f"- Viable knockouts not rated AVOID: **{viable_ok} of {n_viable}**"]
    return "\n".join(text)


# --------------------------------------------------------------------------------------------------------------------
def source_concordance(cache):
    bed = load_builder()
    needed = ["MPheno_OBO.ontology", "MGI_PhenotypicAllele.rpt", "MGI_GenePheno.rpt", "impc_viability.csv.gz", "impc_g2p.csv.gz"]
    if any(not (cache / n).exists() for n in needed):
        return "*Skipped: the raw source files are not in the cache (run tools/build_evidence_data.py first).*"
    with bed.open_text(cache / needed[0]) as handle:
        ontology = bed.MPOntology(handle)
    survival = bed.SurvivalTerms(ontology)
    with bed.open_text(cache / needed[1]) as handle:
        alleles = bed.parse_alleles(handle)
    with bed.open_text(cache / needed[2]) as handle:
        genotypes = bed.read_genotypes(handle, ontology)
    mgi = bed.calls_from_mgi(genotypes, alleles, survival)
    impc = {}
    with bed.open_text(cache / needed[3]) as via, bed.open_text(cache / needed[4]) as g2p:
        bed.add_impc(impc, csv.DictReader(via), csv.DictReader(g2p), alleles, survival)

    def call(gene):
        counts = gene.counts
        if not any(counts.values()):
            return None
        return max(counts, key=lambda c: (counts[c], {"L": 2, "S": 1, "V": 0}[c]))

    both = [m for m in mgi if m in impc and call(mgi[m]) and call(impc[m]) and any(impc[m].counts.values())]
    cross = collections.Counter((call(mgi[m]), call(impc[m])) for m in both)
    names = {"L": "lethal", "S": "subviable", "V": "viable"}
    rows = [[f"MGI: {names[a]}"] + [cross[(a, b)] for b in "LSV"] for a in "LSV"]
    agree = sum(cross[(a, a)] for a in "LSV")
    # a gene counts as flagged when any of its knockout lines was lethal (the verdict flags such genes at least as HIGH_CONCERN)
    impc_lethal = [m for m in both if call(impc[m]) == "L"]
    flagged = sum(1 for m in impc_lethal if mgi[m].counts["L"] or mgi[m].counts["S"])
    impc_viable = [m for m in both if call(impc[m]) == "V"]
    wrongly = sum(1 for m in impc_viable if mgi[m].counts["L"] and call(mgi[m]) == "L")
    text = [f"Genes with a call from both the MGI literature curation and the IMPC screen: **{len(both):,}**.", "",
            table(["", "IMPC: lethal", "IMPC: subviable", "IMPC: viable"], rows), "",
            f"- The two sources give the same call for **{pct(agree, len(both))}** of these genes.",
            f"- Of the {len(impc_lethal):,} genes that the IMPC screen found lethal, MGI records a lethal or subviable knockout for "
            f"**{pct(flagged, len(impc_lethal))}** (a lethal gene is therefore rarely rated safe).",
            f"- Of the {len(impc_viable):,} genes the IMPC screen found viable, MGI calls **{pct(wrongly, len(impc_viable))}** lethal "
            "(often a classical null allele that the screen's allele did not reproduce)."]
    return "\n".join(text)


# --------------------------------------------------------------------------------------------------------------------
def odds_ratio(a, b, c, d):
    """Odds ratio and a 95% interval (Woolf) for the 2x2 table [[a, b], [c, d]] (+0.5 for empty cells)."""
    a, b, c, d = (x + 0.5 for x in (a, b, c, d))
    ratio = (a * d) / (b * c)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    return ratio, math.exp(math.log(ratio) - 1.96 * se), math.exp(math.log(ratio) + 1.96 * se)


def mouse_vs_cells(data):
    genes = json.loads((data / "9606.json").read_text(encoding="utf-8"))["genes"]
    cells = collections.Counter()
    for record in genes.values():
        mouse, cell = record.get("m"), record.get("c")
        if not mouse or not cell or cell[1] is None or record["o"][1] != "1:1":
            continue
        essential = cell[0] == "C" or cell[1] >= 50
        cells[(mouse["v"] == "L", essential)] += 1
    a, b, c, d = cells[(True, True)], cells[(True, False)], cells[(False, True)], cells[(False, False)]
    ratio, low, high = odds_ratio(a, b, c, d)
    total = a + b + c + d
    text = [f"Human genes with a one-to-one mouse ortholog and a DepMap result: **{total:,}**.", "",
            table(["", "essential in most human cell lines", "not essential in most human cell lines"],
                  [["lethal in the mouse knockout", a, b], ["viable or subviable in the mouse knockout", c, d]]), "",
            f"- {pct(a, a + c)} of the genes that are essential in most cell lines are lethal in the mouse; "
            f"{pct(b, a + b)} of the mouse-lethal genes are *not* essential in cell lines (they are needed for development, not for every cell).",
            f"- Odds ratio {ratio:.1f} (95% interval {low:.1f} to {high:.1f}): the two independent measurements agree far more often than chance, "
            "and they are different enough that both are shown."]
    return "\n".join(text)


# --------------------------------------------------------------------------------------------------------------------
def coverage(data, hgnc):
    index = json.loads((data / "index.json").read_text(encoding="utf-8"))
    mouse = json.loads((data / "10090.json").read_text(encoding="utf-8"))["genes"]
    human = json.loads((data / "9606.json").read_text(encoding="utf-8"))["genes"]
    mouse = {symbol: r for symbol, r in mouse.items() if "v" in r}          # the others only carry a lethality estimate
    calls = collections.Counter(r["v"] for r in mouse.values())
    rows = [["Mouse knockout (MGI and IMPC)", f"{len(mouse):,}", f"{calls['L']:,} lethal, {calls['S']:,} subviable, {calls['V']:,} viable"]]
    protein_coding = None
    if hgnc.exists():
        with open(hgnc, encoding="utf-8") as handle:
            protein_coding = {row["symbol"].upper() for row in csv.DictReader(handle, delimiter="\t")
                              if row["status"] == "Approved" and row["locus_group"] == "protein-coding gene"}
    if protein_coding:
        with_mouse = sum(1 for s in protein_coding if "m" in human.get(s, {}))
        with_cells = sum(1 for s in protein_coding if "c" in human.get(s, {}))
        with_any = sum(1 for s in protein_coding if "m" in human.get(s, {}) or "c" in human.get(s, {}))
        rows += [["Human protein-coding genes with a mouse-ortholog knockout", f"{with_mouse:,} of {len(protein_coding):,}", pct(with_mouse, len(protein_coding))],
                 ["Human protein-coding genes with a DepMap cell-line result", f"{with_cells:,} of {len(protein_coding):,}", pct(with_cells, len(protein_coding))],
                 ["Human protein-coding genes with at least one of the two", f"{with_any:,} of {len(protein_coding):,}", pct(with_any, len(protein_coding))]]
    for taxid, info in index["organisms"].items():
        if taxid in ("10090", "9606"):
            continue
        detail = ""
        if info.get("distant") and "knockout" in info["layers"]:
            genes = json.loads((data / info["file"]).read_text(encoding="utf-8"))["genes"]
            own = collections.Counter(r["v"] for r in genes.values() if "v" in r)
            detail = f"measured: {own['L']:,} lethal, {own['S']:,} subviable, {own['V']:,} viable; the other genes carry the mouse-ortholog hint"
        rows.append([f"{info['name']} ({', '.join(info['layers'])})", f"{info['genes']:,}", detail])
    return table(["Data", "Genes", "Detail"], rows) + f"\n\nData version {index['built']}."



# --------------------------------------------------------------------------------------------------------------------
def estimate_check(data):
    """How well does the lethality estimate for genes without a knockout result work (it is tested on genes whose outcome is known)?"""
    index = json.loads((data / "index.json").read_text(encoding="utf-8"))
    model = index.get("lethality_model")
    if not model:
        return "*Skipped: this data build has no lethality estimate.*"
    tested = model["tested"]
    mouse = json.loads((data / "10090.json").read_text(encoding="utf-8"))["genes"]
    human = json.loads((data / "9606.json").read_text(encoding="utf-8"))["genes"]
    mouse_bands = collections.Counter(
        "likely" if r["pl"][0] >= model["likely"] else "possible" if r["pl"][0] >= model["possible"] else "unlikely"
        for r in mouse.values() if "pl" in r and "v" not in r)
    names = {"likely": f"likely lethal (estimate {model['likely']:g} or higher)",
             "possible": f"possibly lethal ({model['possible']:g} to {model['likely']:g})",
             "unlikely": f"unlikely to be lethal (under {model['possible']:g})"}
    rows = [[names[band], f"{tested['bands'][band]['genes']:,}",
             f"{100 * tested['bands'][band]['lethal_share']:.1f}%" if tested["bands"][band]["lethal_share"] is not None else "",
             f"{mouse_bands[band]:,}"] for band in ("likely", "possible", "unlikely")]
    return "\n".join([
        f"Most genes were never knocked out in a mouse. For them K-Sites estimates the chance that the knockout is lethal from the "
        f"measurements of the human ortholog (share of cancer cell lines that need the gene, how rarely people carry loss-of-function "
        f"variants, tissue expression, close paralogs). The model was fitted on **{tested['genes']:,}** mouse genes with a known outcome "
        f"({tested['lethal']:,} lethal, {tested['viable']:,} viable) and tested on genes it had not seen (5-fold cross-validation).", "",
        f"- Area under the ROC curve: **{tested['auc']:.3f}** (0.5 is a coin flip, 1.0 is perfect).",
        f"- Flagging the genes estimated at {model['possible']:g} or higher finds **{100 * tested['lethal_found_at_possible']:.1f}%** of the lethal genes "
        f"and wrongly flags **{100 * tested['viable_flagged_at_possible']:.1f}%** of the viable ones. "
        "For comparison, the keyword prediction in section 6 found 23% and wrongly flagged 13%.", "",
        table(["Estimated band", "Tested genes", "Of these, lethal in the mouse", "Mouse genes without a knockout result in this band"], rows), "",
        f"- Human genes with an estimate (no mouse knockout result): {sum(1 for r in human.values() if 'pl' in r):,}.",
        "- The genes that were tested in mice are not a random sample: researchers knock out genes they already suspect to matter, so the lethal "
        "share among never-tested genes is probably lower than the shares above. The estimate is shown as an estimate, never rates a gene better "
        "than CAUTION, and a measurement always replaces it."])


# --------------------------------------------------------------------------------------------------------------------
def pleiotropy_check(data, cache):
    """Does the pleiotropy score (from the number of GO biological-process terms) track what is measured when a mouse gene is knocked out?"""
    from k_sites.gene_analysis.pleiotropy_scorer import calculate_pleiotropy_score
    gaf = cache / "mgi.gaf.gz"
    if not gaf.exists():
        import requests
        response = requests.get("http://current.geneontology.org/annotations/mgi.gaf.gz", timeout=300)
        response.raise_for_status()
        gaf.write_bytes(response.content)
    bed = load_builder()
    experimental = {"EXP", "IDA", "IPI", "IMP", "IGI", "IEP", "HTP", "HDA", "HMP", "HGI", "HEP"}
    terms = {"all evidence": collections.defaultdict(set), "experimental evidence only": collections.defaultdict(set)}
    with gzip.open(gaf, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("!"):
                continue
            f = line.rstrip("\n").split("\t")
            if len(f) < 15 or f[8] != "P" or "NOT" in f[3]:
                continue
            terms["all evidence"][f[2].upper()].add(f[4])
            if f[6] in experimental:
                terms["experimental evidence only"][f[2].upper()].add(f[4])
    mouse = json.loads((data / "10090.json").read_text(encoding="utf-8"))["genes"]

    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2.0
            i = j + 1
        return out

    def spearman(a, b):
        ra, rb = ranks(a), ranks(b)
        n = len(a)
        ma, mb = sum(ra) / n, sum(rb) / n
        cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
        return cov / math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))

    lines = []
    for label, source in terms.items():
        rows = []
        for symbol, record in mouse.items():
            n = len(source.get(symbol, ()))
            if n and "v" in record:
                rows.append((calculate_pleiotropy_score(n), len(record.get("sys", [])), record["v"]))
        labelled = [(p, 1 if v == "L" else 0) for p, _, v in rows if v in ("L", "V")]
        auc = bed.rank_auc([y for _, y in labelled], [p for p, _ in labelled])
        bands = []
        for low, high in ((0, 0.01), (0.01, 3), (3, 6), (6, 9), (9, 10.01)):
            inside = [(s, v) for p, s, v in rows if low <= p < high and v in ("L", "V")]
            if inside:
                bands.append([f"{low:g} to {min(high, 10):g}", f"{len(inside):,}", pct(sum(1 for _, v in inside if v == "L"), len(inside)),
                              f"{sum(s for s, _ in inside) / len(inside):.1f}"])
        lines += [f"**{label}**: {len(rows):,} mouse genes with GO biological-process terms and a measured knockout.", "",
                  f"- Rank correlation between the pleiotropy score and the number of organ systems with a knockout phenotype: "
                  f"**{spearman([p for p, _, _ in rows], [s for _, s, _ in rows]):.2f}**.",
                  f"- Area under the ROC curve for telling lethal from viable knockouts: **{auc:.2f}** ({len(labelled):,} genes).", "",
                  table(["Pleiotropy score", "Genes", "Lethal knockouts", "Mean organ systems affected"], bands), ""]
    lines += ["The score rises with both measures, so it carries real signal, but it is modest: it is a count of annotated roles and "
              "genes that are heavily studied have more annotations. Treat it as a hint about broad effects, not as a replacement for "
              "the knockout measurement."]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------------------------------
def predictor_check(data, sample_size, seed=7):
    """Run the keyword-based phenotype predictor on genes whose knockout outcome is measured, and compare."""
    from k_sites.rag_system.literature_context import RAGPhenotypePredictor, PhenotypeSeverity
    mouse = json.loads((data / "10090.json").read_text(encoding="utf-8"))["genes"]
    mouse = {symbol: r for symbol, r in mouse.items() if "v" in r}
    rng = random.Random(seed)
    lethal = sorted(s for s, r in mouse.items() if r["v"] == "L" and not r.get("x") and r["n"][0] >= 2)
    viable = sorted(s for s, r in mouse.items() if r["v"] == "V" and not r.get("x") and r["n"][2] >= 2)
    half = sample_size // 2
    sample = [(s, "L") for s in rng.sample(lethal, half)] + [(s, "V") for s in rng.sample(viable, half)]
    predictor = RAGPhenotypePredictor()
    outcomes = collections.Counter()
    for symbol, truth in sample:
        try:
            severity = predictor.predict_phenotype(symbol.capitalize(), "10090").severity
        except Exception:
            severity = PhenotypeSeverity.UNKNOWN
        predicted_lethal = severity == PhenotypeSeverity.LETHAL
        outcomes[(truth, "lethal" if predicted_lethal else "unknown" if severity == PhenotypeSeverity.UNKNOWN else "not lethal")] += 1
        print(f"  {symbol:10} truth={truth} predicted={severity.value}", flush=True)
    rows = [["measured lethal"] + [outcomes[("L", k)] for k in ("lethal", "not lethal", "unknown")],
            ["measured viable"] + [outcomes[("V", k)] for k in ("lethal", "not lethal", "unknown")]]
    return "\n".join([
        f"Random sample of {len(sample)} mouse genes with a clear measured outcome (seed {seed}).", "",
        table(["", "predicted lethal", "predicted not lethal", "no prediction"], rows), "",
        f"- Sensitivity: {pct(outcomes[('L', 'lethal')], half)} of the lethal genes were predicted lethal.",
        f"- False alarms: {pct(outcomes[('V', 'lethal')], half)} of the viable genes were predicted lethal.",
        f"- No prediction at all: {pct(outcomes[('L', 'unknown')] + outcomes[('V', 'unknown')], len(sample))} of the genes."])


# --------------------------------------------------------------------------------------------------------------------
def cross_organism_check(data, cache):
    """
    One test for every organism: the human core-essential genes (CEGv2) and non-essential genes (NEGv1) are mapped to each
    organism through the best one-to-one orthologs (Alliance), and the share of them that the organism's own knockout data
    call lethal is compared. A good source calls most core-essential orthologs lethal and few non-essential ones.
    """
    gold = ROOT / "tools" / "data" / "gold"
    read = lambda name: {line.split("\t")[0].upper() for number, line in enumerate(open(gold / name, encoding="utf-8")) if number}
    core, non_essential = read("core_essential_CEGv2.tsv"), read("non_essential_NEGv1.tsv")
    taxa = {"10090": "Mouse", "559292": "Yeast", "7955": "Zebrafish", "7227": "Fly", "6239": "Worm"}
    orthologs = collections.defaultdict(lambda: collections.defaultdict(set))
    with gzip.open(cache / "alliance_orthology.tsv.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            f = line.rstrip("\n").split("\t")
            if len(f) < 13 or f[11] != "Yes" or f[12] != "Yes":
                continue
            a, b = f[2].replace("NCBITaxon:", ""), f[6].replace("NCBITaxon:", "")
            if a == "9606" and b in taxa:
                orthologs[b][f[1].upper()].add(f[5].upper())
            elif b == "9606" and a in taxa:
                orthologs[a][f[5].upper()].add(f[1].upper())
    rows = []
    for taxid, name in taxa.items():
        path = Path(data) / f"{taxid}.json"
        if not path.exists():
            continue
        genes = json.loads(path.read_text(encoding="utf-8"))["genes"]

        def share(gold_set):
            measured = lethal = 0
            for human in gold_set:
                for gene in orthologs[taxid].get(human, ()):
                    record = genes.get(gene)
                    if record and "v" in record:
                        measured += 1
                        lethal += record["v"] == "L"
            return measured, lethal

        (n_core, l_core), (n_non, l_non) = share(core), share(non_essential)
        if n_core and n_non:
            rows.append((name, n_core, pct(l_core, n_core), n_non, pct(l_non, n_non),
                         f"{100 * l_core / n_core - 100 * l_non / n_non:.0f}"))
    text = table(["Organism", "Core-essential orthologs with a result", "called lethal", "Non-essential orthologs with a result",
                  "called lethal", "Separation (points)"], rows)
    return text + """

A large separation means the organism's lethal calls tell essential genes from non-essential ones. Mouse (a systematic screen
plus the literature) separates them best. **For fly and worm the separation is small because their databases record lethal
mutants far more often than viable ones**: a gene is in the database mostly because a mutant was found that died. For them a
lethal call is a hint to confirm in the literature, not a measurement of how many genes are essential, and the share of
"non-essential" genes called lethal is inflated by that selection, not necessarily by errors. The site says so before a fly,
worm or zebrafish run."""


# --------------------------------------------------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=str(ROOT / ".cache" / "evidence-out"), help="Folder with the built evidence files")
    parser.add_argument("--cache", default=str(ROOT / ".cache" / "evidence-sources"), help="Folder with the raw source downloads")
    parser.add_argument("--predictor", type=int, default=0, help="Also test the keyword predictor on this many genes (network needed)")
    parser.add_argument("--predictor-from", help="Take section 6 (the old keyword predictor check) from an earlier report file; "
                                                  "its section number in that file is 5")
    parser.add_argument("--out", help="Write the report to this file (default: print)")
    args = parser.parse_args()
    data, cache = Path(args.data), Path(args.cache)
    provider = EvidenceProvider.from_directory(data)

    sections = [
        ("1. Do the data and the verdicts match published knockouts?", paper_check(provider)),
        ("2. Do the two sources agree with each other?", source_concordance(cache)),
        ("3. Do mouse lethality and human cell essentiality agree?", mouse_vs_cells(data)),
        ("4. How many genes are covered?", coverage(data, cache / "hgnc.tsv")),
        ("5. How good is the estimate for genes without a knockout result?", estimate_check(data)),
    ]
    if args.predictor:
        print("Testing the keyword predictor ...", flush=True)
        sections.append(("6. How good is the old keyword prediction?", predictor_check(data, args.predictor)))
    if args.predictor_from and not args.predictor:
        earlier = Path(args.predictor_from).read_text(encoding="utf-8")
        if "## 5." in earlier:
            sections.append(("6. How good is the old keyword prediction?",
                             earlier.split("## 5.", 1)[1].split("\n", 2)[2].split("\n## ", 1)[0].strip()))
    sections.append(("7. Does the pleiotropy score track what is measured?", pleiotropy_check(data, cache)))
    sections.append(("8. Do the knockout results of every organism agree with the human core-essential genes?",
                     cross_organism_check(data, cache)))
    report = [INTRO, f"*Generated {date.today().isoformat()} by `tools/evaluate_knockout_evidence.py`.*", ""]
    for title, body in sections:
        report += [f"## {title}", "", body, ""]
    report += [OUTRO]
    text = "\n".join(report)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
