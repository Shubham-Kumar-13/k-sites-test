#!/usr/bin/env python3
"""
Build the measured knockout-evidence data files used by K-Sites.

K-Sites used to guess how harmful a knockout is from keywords in abstracts. This tool collects what has
actually been measured and writes it as small JSON files that the website (and the Python package) look up
gene by gene:

    evidence-data/index.json    sources, versions, licences, and the lists the compact records refer to
    evidence-data/10090.json    mouse   - knockout viability and phenotypes (MGI literature curation + IMPC screen)
    evidence-data/9606.json     human   - mouse-ortholog knockout, DepMap cell-line essentiality, gnomAD constraint,
                                          GTEx expression specificity
    evidence-data/10116.json    rat     - mouse-ortholog knockout
    evidence-data/559292.json   yeast   - SGD deletion phenotypes (viable / inviable)

Each file maps an upper-case gene symbol to a short record (see EVIDENCE_FORMAT below).

    python tools/build_evidence_data.py --out site/evidence-data

The sources are downloaded once into --cache (default .cache/evidence-sources) and reused. The DepMap table
comes from tools/data/depmap_24q4_summary.tsv.gz (made by tools/summarize_depmap.py).
"""

import argparse
import collections
import concurrent.futures
import csv
import gzip
import io
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = ROOT / ".cache" / "evidence-sources"
DEPMAP_SUMMARY = ROOT / "tools" / "data" / "depmap_24q4_summary.tsv.gz"
FORMAT_VERSION = 1

# --------------------------------------------------------------------------------------------------
# What the compact records contain
#
#   mouse   {"v": "L"|"S"|"V",   knockout call: lethal, subviable (reduced numbers), viable
#            "s": "E"|"P"|"J"|"W"|"U",   earliest stage of death (L and S only)
#            "n": [lethal, subviable, viable],   how many null genotypes / colonies gave each result
#            "x": 1,             the reports disagree (some lethal/subviable, some viable)
#            "r": 1,             reduced lifespan reported in viable knockouts
#            "f": 1,             infertility reported
#            "sys": [..],        indexes of the organ systems with a reported abnormal phenotype
#            "src": "MI",        M = MGI literature curation, I = IMPC screen
#            "id": "MGI:...",    MGI gene id
#            "pm": [..]}         up to three PubMed ids behind the call
#   human   {"o": [mouse symbol, relation], "m": <mouse record>,
#            "p": [[symbol, % identity], ...],   closest paralogs (they may take over the gene's work); also on mouse records
#            "c": [flag, % of cell lines dependent],   flag: C common essential, N non-essential control, "" neither
#            "l": LOEUF,        gnomAD loss-of-function observed/expected upper bound (low = intolerant)
#            "t": [tau, tissues expressed, [top tissue indexes]]}
#   rat     {"o": [mouse symbol, relation], "m": <mouse record>}
#   zebrafish, fly, worm, xenopus   the same as rat, but the organism is marked "distant" in index.json: the mouse
#           ortholog is only an indication there, never a measurement, and the verdict says so
#   yeast   {"v": "L"|"S"|"V", "n": [..], "x": 1, "src": "S", "pm": [..]}
# --------------------------------------------------------------------------------------------------

SOURCES = {
    "mgi": {
        "name": "Mouse Genome Informatics (MGI)", "url": "https://www.informatics.jax.org/downloads/reports/",
        "what": "knockout phenotypes curated from the literature", "license": "CC BY 4.0",
        "files": {
            "MGI_GenePheno.rpt": "https://www.informatics.jax.org/downloads/reports/MGI_GenePheno.rpt",
            "MGI_PhenotypicAllele.rpt": "https://www.informatics.jax.org/downloads/reports/MGI_PhenotypicAllele.rpt",
            "MPheno_OBO.ontology": "https://www.informatics.jax.org/downloads/reports/MPheno_OBO.ontology",
        },
    },
    "impc": {
        "name": "International Mouse Phenotyping Consortium (IMPC)",
        "url": "https://ftp.ebi.ac.uk/pub/databases/impc/all-data-releases/latest/results/",
        "what": "systematic knockout viability and phenotyping screen",
        "files": {
            "impc_viability.csv.gz": "https://ftp.ebi.ac.uk/pub/databases/impc/all-data-releases/latest/results/viability.csv.gz",
            "impc_g2p.csv.gz": "https://ftp.ebi.ac.uk/pub/databases/impc/all-data-releases/latest/results/genotype-phenotype-assertions-ALL.csv.gz",
        },
    },
    "alliance": {
        "name": "Alliance of Genome Resources", "url": "https://www.alliancegenome.org/downloads",
        "what": "orthologs between human, mouse, rat, zebrafish, fly, worm and yeast",
        "files": {"alliance_orthology.tsv.gz": "https://fms.alliancegenome.org/download/ORTHOLOGY-ALLIANCE_COMBINED.tsv.gz"},
    },
    "hgnc": {
        "name": "HGNC (HUGO Gene Nomenclature Committee)", "url": "https://www.genenames.org/download/",
        "what": "approved human gene symbols and their older names", "license": "CC0",
        "files": {"hgnc.tsv": "https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt"},
    },
    "depmap": {
        "name": "DepMap 24Q4 Public (Broad Institute)", "url": "https://doi.org/10.6084/m9.figshare.27993248",
        "what": "CRISPR knockout screens in 1,178 human cancer cell lines", "license": "CC BY 4.0", "files": {},
    },
    "gnomad": {
        "name": "gnomAD v4.1 constraint", "url": "https://gnomad.broadinstitute.org/downloads#v4-constraint",
        "what": "how rarely loss-of-function variants are seen in people",
        "files": {"gnomad_constraint.tsv": "https://storage.googleapis.com/gcp-public-data--gnomad/release/4.1/constraint/gnomad.v4.1.constraint_metrics.tsv"},
    },
    "gtex": {
        "name": "GTEx v8", "url": "https://gtexportal.org/home/downloads/adult-gtex/bulk_tissue_expression",
        "what": "gene expression in 54 human tissues",
        "files": {"gtex_median_tpm.gct.gz": "https://storage.googleapis.com/adult-gtex/bulk-gex/v8/rna-seq/GTEx_Analysis_2017-06-05_v8_RNASeQCv1.1.9_gene_median_tpm.gct.gz"},
    },
    "ensembl": {
        "name": "Ensembl Compara (via BioMart)", "url": "https://www.ensembl.org/biomart/",
        "what": "paralogs: genes of the same species descended from the same ancestor gene",
        "files": {},          # downloaded per chromosome by download_paralogs()
    },
    "sgd": {
        "name": "Saccharomyces Genome Database (SGD)", "url": "https://www.yeastgenome.org/",
        "what": "yeast deletion phenotypes (viable / inviable)",
        "files": {"sgd_phenotype.tab": "https://downloads.yeastgenome.org/curation/literature/phenotype_data.tab"},
    },
}

# Stages of death, earliest first. W (before weaning) and U (age not stated) say the least.
STAGES = {"E": "embryonic / prenatal", "P": "perinatal / neonatal", "J": "after birth, before adulthood",
          "W": "before weaning", "U": "age not stated"}
STAGE_ORDER = "EPJWU"

# MP (Mammalian Phenotype Ontology) terms the lethality logic hangs on
MP_PRENATAL, MP_EMBRYONIC, MP_PERINATAL, MP_POSTNATAL, MP_WEANING = "MP:0002080", "MP:0008762", "MP:0002081", "MP:0002082", "MP:0008569"
MP_PREWEANING, MP_SURVIVAL, MP_PREMATURE_DEATH, MP_TUMOR_SURVIVAL = "MP:0010770", "MP:0010769", "MP:0002083", "MP:0014235"
MP_LETHALITY_COMPLETE, MP_LETHALITY_INCOMPLETE, MP_DECREASED_SURVIVOR = "MP:0011400", "MP:0010831", "MP:0008770"
MP_INFERTILITY, MP_NO_ABNORMAL = "MP:0001924", "MP:0002169"
MP_ROOT = "MP:0000001"
NOT_A_SYSTEM = {"mortality/aging", "normal phenotype", "no phenotypic analysis"}
# Findings in these systems are measured on living young or adult animals. A null genotype with such a finding (or "no
# abnormal phenotype detected") is evidence of viability; a genotype with only embryonic or morphological findings
# (limbs, craniofacial, skeleton, heart, ...) is not, because those are also recorded in embryos that die later.
ADULT_EVIDENCE_SYSTEMS = {
    "behavior/neurological phenotype", "hematopoietic system phenotype", "immune system phenotype",
    "homeostasis/metabolism phenotype", "reproductive system phenotype", "neoplasm", "pigmentation phenotype",
    "hearing/vestibular/ear phenotype", "taste/olfaction phenotype", "adipose tissue phenotype",
    "growth/size/body region phenotype", "integument phenotype", "muscle phenotype",
}

TARGETS = {"9606": "Homo sapiens", "10090": "Mus musculus", "10116": "Rattus norvegicus"}
# Species without their own knockout data here: the mouse ortholog is the only (indirect) hint
DISTANT = {"7955": "Danio rerio", "7227": "Drosophila melanogaster", "6239": "Caenorhabditis elegans",
           "8364": "Xenopus tropicalis", "8355": "Xenopus laevis"}
NCBI_TAXON = {"9606": "human", "10090": "mouse", "10116": "rat", "7955": "zebrafish", "7227": "fly",
              "6239": "worm", "559292": "yeast", "8364": "xenopus tropicalis", "8355": "xenopus laevis"}


# --------------------------------------------------------------------------------------------------
# downloading
# --------------------------------------------------------------------------------------------------

class Downloader:
    def __init__(self, cache, refresh=False):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.refresh = refresh
        self.log = {}

    def fetch(self, name, url):
        path = self.cache / name
        if self.refresh or not path.exists() or path.stat().st_size == 0:
            print(f"  downloading {name}", flush=True)
            for attempt in range(4):
                try:
                    with requests.get(url, stream=True, timeout=180) as response:
                        response.raise_for_status()
                        with open(path, "wb") as handle:
                            for chunk in response.iter_content(1 << 20):
                                handle.write(chunk)
                    break
                except requests.RequestException:
                    if attempt == 3:
                        raise
                    time.sleep(3 * (attempt + 1))
        self.log[name] = {"url": url, "bytes": path.stat().st_size}
        return path


def open_text(path):
    path = Path(path)
    if path.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", newline="")
    return open(path, encoding="utf-8", newline="")


# --------------------------------------------------------------------------------------------------
# the Mammalian Phenotype ontology
# --------------------------------------------------------------------------------------------------

class MPOntology:
    """The parts of the Mammalian Phenotype Ontology needed to read lethality and organ systems."""

    def __init__(self, lines):
        self.names, self.parents, self.alt, self.obsolete = {}, collections.defaultdict(list), {}, set()
        current = None
        for raw in lines:
            line = raw.rstrip("\r\n")
            if line == "[Term]":
                current = None
                continue
            if line.startswith("[") and line.endswith("]"):
                current = None
                continue
            if line.startswith("id: "):
                current = line[4:].strip()
                self.names[current] = ""
            elif current is None:
                continue
            elif line.startswith("name: "):
                self.names[current] = line[6:].strip()
            elif line.startswith("is_a: "):
                self.parents[current].append(line[6:].split("!")[0].strip())
            elif line.startswith("alt_id: "):
                self.alt[line[8:].strip()] = current
            elif line.startswith("is_obsolete: true"):
                self.obsolete.add(current)
        self.children = collections.defaultdict(list)
        for term, parents in self.parents.items():
            for parent in parents:
                self.children[parent].append(term)
        self._desc, self._ancestors = {}, {}

    def canonical(self, term):
        return self.alt.get(term, term)

    def descendants(self, root):
        """The term and everything below it."""
        if root not in self._desc:
            seen, stack = {root}, [root]
            while stack:
                for child in self.children.get(stack.pop(), ()):
                    if child not in seen:
                        seen.add(child)
                        stack.append(child)
            self._desc[root] = frozenset(seen)
        return self._desc[root]

    def ancestors(self, term):
        if term not in self._ancestors:
            seen, stack = {term}, [term]
            while stack:
                for parent in self.parents.get(stack.pop(), ()):
                    if parent not in seen:
                        seen.add(parent)
                        stack.append(parent)
            self._ancestors[term] = frozenset(seen)
        return self._ancestors[term]

    def systems(self):
        """Top-level organ systems: {term id: name}, without the survival / normal / not-analysed branches."""
        return {t: self.names[t] for t in self.children.get(MP_ROOT, ()) if self.names.get(t) not in NOT_A_SYSTEM
                and t not in self.obsolete}


class SurvivalTerms:
    """Which MP terms mean lethality (and at what stage), premature death, infertility or an embryo-only finding."""

    def __init__(self, mp):
        self.mp = mp
        for term in (MP_PRENATAL, MP_PERINATAL, MP_POSTNATAL, MP_PREWEANING, MP_SURVIVAL, MP_PREMATURE_DEATH, MP_INFERTILITY):
            if term not in mp.names:
                raise ValueError(f"The ontology has no term {term}; the lethality rules need updating")
        embryonic = mp.descendants(MP_PRENATAL) | mp.descendants(MP_EMBRYONIC)
        perinatal = mp.descendants(MP_PERINATAL)
        postnatal = mp.descendants(MP_POSTNATAL) | mp.descendants(MP_WEANING)
        universe = (mp.descendants(MP_PREWEANING) | postnatal
                    | {MP_LETHALITY_COMPLETE, MP_LETHALITY_INCOMPLETE, MP_DECREASED_SURVIVOR})
        partial_terms = {MP_LETHALITY_INCOMPLETE, MP_DECREASED_SURVIVOR} | {
            t for t in universe if "incomplete penetrance" in mp.names.get(t, "")}
        self.lethal = {}
        for term in universe:
            if term not in mp.names or term in mp.obsolete:
                continue
            stage = "E" if term in embryonic else "P" if term in perinatal else "J" if term in postnatal \
                else "W" if term in mp.descendants(MP_PREWEANING) else "U"
            self.lethal[term] = (stage, term in partial_terms)
        self.premature_death = mp.descendants(MP_PREMATURE_DEATH) - mp.descendants(MP_TUMOR_SURVIVAL)
        self.infertility = mp.descendants(MP_INFERTILITY)
        self.system_names = mp.systems()
        self.adult_systems = {t for t, name in self.system_names.items() if name in ADULT_EVIDENCE_SYSTEMS}
        self._system_cache = {}

    def systems_of(self, term):
        if term not in self._system_cache:
            self._system_cache[term] = frozenset(self.mp.ancestors(term) & self.system_names.keys())
        return self._system_cache[term]


def earliest_stage(stages):
    for stage in STAGE_ORDER:
        if stage in stages:
            return stage
    return None


# --------------------------------------------------------------------------------------------------
# MGI: alleles and genotypes
# --------------------------------------------------------------------------------------------------

def parse_alleles(lines):
    """{allele id: {symbol, type, attrs, marker, marker_symbol}} from MGI_PhenotypicAllele.rpt."""
    alleles = {}
    for line in lines:
        if line.startswith("#") or not line.strip():
            continue
        f = line.rstrip("\r\n").split("\t")
        if len(f) < 8:
            continue
        alleles[f[0]] = {"symbol": f[1], "type": f[3], "attrs": {a.strip() for a in f[4].split("|") if a.strip()},
                         "marker": f[6], "marker_symbol": f[7]}
    return alleles


def allele_class(allele):
    """
    'ko'   null / knockout allele
    'hypo' hypomorph
    'trap' gene trap
    None   anything else (floxed, reporter-only, point mutants, transgenes, ...), which says nothing about loss of the gene.
    """
    if not allele or not allele["marker"] or allele["type"] == "Transgenic":
        return None
    if "Null/knockout" in allele["attrs"]:
        return "ko"
    if "Hypomorph" in allele["attrs"]:
        return "hypo"
    if allele["type"] == "Gene trapped":
        return "trap"
    return None


def split_composition(text):
    """'A<x>/B<y>' -> ('A<x>', 'B<y>'), splitting at the single '/' outside <...>; None if there is not exactly one."""
    depth, cut = 0, None
    for index, char in enumerate(text):
        if char == "<":
            depth += 1
        elif char == ">":
            depth = max(0, depth - 1)
        elif char == "/" and depth == 0:
            if cut is not None:
                return None
            cut = index
    return None if cut is None else (text[:cut], text[cut + 1:])


def zygosity(composition):
    """'hom', 'hemi' (X-linked, /Y), 'compound' (two different alleles) or None (heterozygous, wild type, or unclear)."""
    parts = split_composition(composition.strip())
    if not parts:
        return None
    left, right = parts
    if right == "Y":
        return "hemi"
    if left == right:
        return "hom"
    if "<+>" in left or "<+>" in right or left in ("+", "") or right in ("+", ""):
        return None
    return "compound"


@dataclass
class Genotype:
    gid: str
    composition: str
    alleles: list
    marker: str = ""
    background: str = ""
    mps: set = field(default_factory=set)
    pmids: dict = field(default_factory=lambda: collections.defaultdict(set))   # mp term -> pubmed ids


def read_genotypes(lines, ontology):
    """Group the rows of MGI_GenePheno.rpt (single-gene genotypes) by genotype."""
    genotypes = {}
    for line in lines:
        f = line.rstrip("\r\n").split("\t")
        if len(f) < 8:
            continue
        composition, _, allele_ids, background, mp, pmids, marker, gid = f[:8]
        genotype = genotypes.get(gid)
        if genotype is None:
            genotype = genotypes[gid] = Genotype(gid, composition, [a for a in allele_ids.split("|") if a],
                                                 marker.split("|")[0], background)
        mp = ontology.canonical(mp)
        genotype.mps.add(mp)
        for pmid in re.split(r"[|,]", pmids):
            if pmid.strip().isdigit():
                genotype.pmids[mp].add(pmid.strip())
    return genotypes


@dataclass
class GeneCalls:
    """What all the null genotypes of one gene say."""
    counts: dict = field(default_factory=lambda: {"L": 0, "S": 0, "V": 0})
    stages: dict = field(default_factory=lambda: {"L": set(), "S": set()})
    pmids: collections.Counter = field(default_factory=collections.Counter)
    systems: set = field(default_factory=set)
    sources: set = field(default_factory=set)
    reduced_lifespan: bool = False
    infertile: bool = False
    marker: str = ""
    symbol: str = ""


def evaluate_genotype(genotype, alleles, survival):
    """
    One null genotype -> ('L'|'S'|'V', stage, pubmed ids, systems, lifespan flag, infertility flag), or None when the genotype
    is not a clean loss of the gene or says nothing about survival.

    Lethality counts whenever any loss-of-function allele (null, hypomorph, gene trap) is lethal: if a partial loss is lethal,
    the full loss is too. Viability counts only when every allele is a null.
    """
    kind = zygosity(genotype.composition)
    if kind is None:
        return None
    classes = [allele_class(alleles.get(a)) for a in genotype.alleles]
    if not classes or any(c is None for c in classes):
        return None
    if kind == "compound" and len(classes) < 2:
        return None
    null = all(c == "ko" for c in classes)

    lethal = {t: survival.lethal[t] for t in genotype.mps if t in survival.lethal}
    complete = [stage for stage, partial in lethal.values() if not partial]
    partial = [stage for stage, partial in lethal.values() if partial]
    systems = set()
    for mp in genotype.mps:
        systems |= survival.systems_of(mp)
    if complete:
        call, stage, source_terms = "L", earliest_stage(complete), [t for t, (s, p) in lethal.items() if not p]
    elif partial:
        call, stage, source_terms = "S", earliest_stage(partial), [t for t, (s, p) in lethal.items() if p]
    else:
        # viable: the null mice were examined as young or adult animals (or declared normal), not just as embryos
        if not null or not (systems & survival.adult_systems or MP_NO_ABNORMAL in genotype.mps):
            return None
        call, stage, source_terms = "V", None, list(genotype.mps)
    pmids = set()
    for term in source_terms:
        pmids |= genotype.pmids.get(term, set())
    return (call, stage, pmids, systems,
            bool(genotype.mps & survival.premature_death), bool(genotype.mps & survival.infertility))


def calls_from_mgi(genotypes, alleles, survival):
    """{MGI gene id: GeneCalls} from the MGI literature curation."""
    genes = {}
    for genotype in genotypes.values():
        result = evaluate_genotype(genotype, alleles, survival)
        if result is None:
            continue
        call, stage, pmids, systems, premature, infertile = result
        marker = genotype.marker
        if not marker:
            continue
        gene = genes.setdefault(marker, GeneCalls(marker=marker))
        gene.counts[call] += 1
        if stage and call in gene.stages:
            gene.stages[call].add(stage)
        gene.pmids.update(pmids)
        gene.systems |= systems
        gene.sources.add("M")
        if call == "V" and premature:
            gene.reduced_lifespan = True
        gene.infertile = gene.infertile or infertile
    return genes


# --------------------------------------------------------------------------------------------------
# IMPC
# --------------------------------------------------------------------------------------------------

IMPC_CALLS = {"viable": "V", "lethal": "L", "subviable": "S"}


def add_impc(genes, viability_rows, g2p_rows, alleles, survival):
    """Add the IMPC viability screen (and its significant phenotypes) to the per-gene calls."""
    lethal_stage = collections.defaultdict(set)
    for row in g2p_rows:
        if row.get("zygosity") not in ("homozygote", "hemizygote"):
            continue
        marker = row.get("marker_accession_id", "")
        term = row.get("mp_term_id", "")
        allele = alleles.get(row.get("allele_accession_id", ""))
        if allele is not None and allele_class(allele) is None:
            continue
        gene = genes.setdefault(marker, GeneCalls(marker=marker))
        gene.symbol = gene.symbol or row.get("marker_symbol", "")
        gene.systems |= survival.systems_of(term)
        gene.sources.add("I")
        if term in survival.lethal:
            lethal_stage[marker].add(survival.lethal[term][0])
        if term in survival.premature_death:
            gene.reduced_lifespan = True
        if term in survival.infertility:
            gene.infertile = True

    colonies = set()
    for row in viability_rows:
        call = IMPC_CALLS.get(row.get("Viability Phenotype HOMs/HEMIs", "").strip().lower())
        if call is None or row.get("Zygosity") not in ("homozygote", "hemizygote"):
            continue
        marker = row["Gene Accession Id"]
        allele = alleles.get(row.get("Allele Accession Id", ""))
        if allele is not None and allele_class(allele) is None:
            continue                       # e.g. a floxed allele that is still functional
        key = (marker, row.get("Colony Id"), row.get("Allele Accession Id"))
        if key in colonies:
            continue
        colonies.add(key)
        gene = genes.setdefault(marker, GeneCalls(marker=marker))
        gene.symbol = gene.symbol or row["Gene Symbol"]
        gene.counts[call] += 1
        gene.sources.add("I")
        if call in gene.stages:
            gene.stages[call].add("W")      # the screen scores survival to weaning
    for marker, stages in lethal_stage.items():
        gene = genes[marker]
        definite = stages & set("EPJ")
        for call in ("L", "S"):
            if gene.stages[call] == {"W"} and definite:
                gene.stages[call] = definite
    return genes


def mouse_record(gene, systems_index):
    """GeneCalls -> the compact record, or None when there is nothing to say about viability."""
    counts = gene.counts
    if not any(counts.values()):
        return None
    severity = {"L": 2, "S": 1, "V": 0}
    call = max(counts, key=lambda c: (counts[c], severity[c]))
    record = {"v": call, "n": [counts["L"], counts["S"], counts["V"]]}
    if call in ("L", "S"):
        stage = earliest_stage(gene.stages[call] or gene.stages["L"] or gene.stages["S"])
        if stage:
            record["s"] = stage
    if sum(1 for c in counts.values() if c) > 1:
        record["x"] = 1
    if gene.reduced_lifespan:
        record["r"] = 1
    if gene.infertile:
        record["f"] = 1
    if gene.systems:
        record["sys"] = sorted(systems_index[s] for s in gene.systems if s in systems_index)
    record["src"] = "".join(c for c in "MI" if c in gene.sources)
    if gene.marker:
        record["id"] = gene.marker
    if gene.pmids:
        record["pm"] = [int(p) for p, _ in gene.pmids.most_common(3)]
    return record


def build_mouse(files):
    """Returns ({symbol upper: record}, {MGI id: symbol}, info dict) from the downloaded MGI and IMPC files."""
    print("Mouse: reading the ontology and alleles", flush=True)
    with open_text(files["MPheno_OBO.ontology"]) as handle:
        ontology = MPOntology(handle)
    survival = SurvivalTerms(ontology)
    with open_text(files["MGI_PhenotypicAllele.rpt"]) as handle:
        alleles = parse_alleles(handle)
    print(f"  {len(survival.lethal)} lethality terms, {len(survival.system_names)} organ systems, {len(alleles)} alleles")
    print("Mouse: reading MGI genotypes", flush=True)
    with open_text(files["MGI_GenePheno.rpt"]) as handle:
        genotypes = read_genotypes(handle, ontology)
    genes = calls_from_mgi(genotypes, alleles, survival)
    mgi_genes = len(genes)
    print(f"  {len(genotypes)} genotypes -> {mgi_genes} genes with a viability call")
    print("Mouse: adding the IMPC screen", flush=True)
    with open_text(files["impc_viability.csv.gz"]) as via, open_text(files["impc_g2p.csv.gz"]) as g2p:
        add_impc(genes, csv.DictReader(via), csv.DictReader(g2p), alleles, survival)

    marker_symbol = {}
    for allele in alleles.values():
        if allele["marker"] and allele["marker_symbol"]:
            marker_symbol[allele["marker"]] = allele["marker_symbol"]
    systems_names = sorted(set(survival.system_names.values()))
    systems_index = {term: systems_names.index(name) for term, name in survival.system_names.items()}
    records, by_id = {}, {}
    for marker, gene in genes.items():
        symbol = marker_symbol.get(marker) or gene.symbol
        record = mouse_record(gene, systems_index)
        if symbol and record:
            records[symbol.upper()] = record
            by_id[marker] = symbol
    print(f"  {len(records)} mouse genes with measured knockout viability")
    return records, by_id, {"systems": systems_names, "mgi_genes": mgi_genes, "genes": len(records)}


# --------------------------------------------------------------------------------------------------
# orthologs (Alliance)
# --------------------------------------------------------------------------------------------------

def parse_orthology(lines, wanted=None):
    """
    Pairs from the Alliance orthology table as dicts {a, b, a_sym, b_sym, a_tax, b_tax, best, best_rev, algorithms}.
    ``wanted`` is an optional set of taxon pairs (frozensets of taxon ids) to keep.
    """
    pairs = []
    header = None
    for line in lines:
        if line.startswith("#") or not line.strip():
            continue
        f = line.rstrip("\r\n").split("\t")
        if header is None:
            header = f
            continue
        if len(f) < 13:
            continue
        a_tax, b_tax = f[2].replace("NCBITaxon:", ""), f[6].replace("NCBITaxon:", "")
        if wanted is not None and frozenset((a_tax, b_tax)) not in wanted:
            continue
        pairs.append({"a": f[0], "a_sym": f[1], "a_tax": a_tax, "b": f[4], "b_sym": f[5], "b_tax": b_tax,
                      "best": f[11] == "Yes", "best_rev": f[12] == "Yes", "algorithms": int(f[9] or 0)})
    return pairs


def orthologs_to_mouse(pairs, tax):
    """
    {gene id in species `tax`: (mouse gene id, mouse symbol, relation, gene symbol)} using unambiguous orthologs only.
    relation: '1:1', 'n:1' (several genes share one mouse ortholog) or 'best' (several candidates, one clear best pair).
    """
    candidates = collections.defaultdict(list)
    reverse = collections.defaultdict(set)
    symbols = {}
    for p in pairs:
        if p["a_tax"] == tax and p["b_tax"] == "10090":
            gene, mouse, gene_sym, mouse_sym = p["a"], p["b"], p["a_sym"], p["b_sym"]
            best = p["best"] and p["best_rev"]
        elif p["b_tax"] == tax and p["a_tax"] == "10090":
            gene, mouse, gene_sym, mouse_sym = p["b"], p["a"], p["b_sym"], p["a_sym"]
            best = p["best"] and p["best_rev"]
        else:
            continue
        candidates[gene].append((mouse, mouse_sym, best))
        reverse[mouse].add(gene)
        symbols[gene] = gene_sym
    result = {}
    for gene, options in candidates.items():
        unique = {m: (s, b) for m, s, b in options}
        if len(unique) == 1:
            mouse, (mouse_sym, _) = next(iter(unique.items()))
            result[gene] = (mouse, mouse_sym, "1:1" if len(reverse[mouse]) == 1 else "n:1", symbols[gene])
        else:
            best = [(m, s) for m, (s, b) in unique.items() if b]
            if len(best) == 1:
                result[gene] = (best[0][0], best[0][1], "best", symbols[gene])
    return result


# --------------------------------------------------------------------------------------------------
# human layers
# --------------------------------------------------------------------------------------------------

def hgnc_aliases(path):
    """{old name or alias: current symbol} for names that point to exactly one approved gene."""
    owners = collections.defaultdict(set)
    approved = set()
    with open_text(path) as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("status") != "Approved":
                continue
            approved.add(row["symbol"])
            for column in ("prev_symbol", "alias_symbol"):
                for name in (row.get(column) or "").split("|"):
                    name = name.strip().strip('"')
                    if name:
                        owners[name].add(row["symbol"])
    return {name: next(iter(symbols)) for name, symbols in owners.items() if len(symbols) == 1 and name not in approved}


def read_depmap(path):
    """{entrez: (symbol, lines screened, lines dependent, common essential, non-essential control)}."""
    rows = {}
    with open_text(path) as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            rows[row["entrez"]] = (row["symbol"], int(row["lines_screened"]), int(row["lines_dependent"]),
                                   row["common_essential"] == "1", row["nonessential_control"] == "1")
    return rows


def read_gnomad(path):
    """{ensembl gene id: LOEUF} for the MANE-select transcript of each gene (LOEUF = lof.oe_ci.upper)."""
    result = {}
    with open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            gene_id = row.get("gene_id", "")
            if not gene_id.startswith("ENSG") or row.get("mane_select") != "true":
                continue
            try:
                result[gene_id] = round(float(row["lof.oe_ci.upper"]), 3)
            except (ValueError, KeyError):
                continue
    return result


def read_gtex(path):
    """
    ({ensembl id without version: (tau, tissues expressed, [top tissue indexes])}, tissue names).
    tau (0 = same everywhere, 1 = one tissue only) is computed from the median TPM of each tissue; genes whose highest
    median is below 1 TPM have no tau.
    """
    result = {}
    with open_text(path) as handle:
        handle.readline()
        handle.readline()
        header = handle.readline().rstrip("\r\n").split("\t")
        tissues = header[2:]
        for line in handle:
            f = line.rstrip("\r\n").split("\t")
            values = [float(x) for x in f[2:]]
            top = max(values)
            if top < 1:
                result[f[0].split(".")[0]] = (None, 0, [])
                continue
            tau = sum(1 - v / top for v in values) / (len(values) - 1)
            order = sorted(range(len(values)), key=lambda i: -values[i])
            result[f[0].split(".")[0]] = (round(tau, 2), sum(1 for v in values if v >= 1),
                                          [i for i in order[:3] if values[i] >= 0.5 * top])
    return result, tissues


def slim(mouse_record):
    """The mouse record as carried on a human or rat gene: without the mouse's own paralogs and expression."""
    return {key: value for key, value in mouse_record.items() if key not in ("p", "t")}


def build_human(sources, mouse_records, mouse_by_id, pairs, depmap_path, paralog_path=None):
    print("Human: reading gene names, DepMap, gnomAD and GTEx", flush=True)
    genes = {}
    with open_text(sources["hgnc.tsv"]) as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("status") == "Approved":
                genes[row["hgnc_id"]] = {"symbol": row["symbol"], "entrez": row.get("entrez_id", ""),
                                         "ensembl": row.get("ensembl_gene_id", ""),
                                         "coding": row.get("locus_group") == "protein-coding gene"}
    aliases = hgnc_aliases(sources["hgnc.tsv"])
    by_entrez = {g["entrez"]: g["symbol"] for g in genes.values() if g["entrez"]}
    by_ensembl = {g["ensembl"]: g["symbol"] for g in genes.values() if g["ensembl"]}
    approved = {g["symbol"] for g in genes.values()}

    def resolve(symbol, entrez=None, ensembl=None):
        if entrez and entrez in by_entrez:
            return by_entrez[entrez]
        if ensembl and ensembl in by_ensembl:
            return by_ensembl[ensembl]
        if symbol in approved:
            return symbol
        return aliases.get(symbol)

    records = collections.defaultdict(dict)
    mapping = orthologs_to_mouse(pairs, "9606")
    for hgnc_id, (mouse_id, mouse_symbol, relation, _) in mapping.items():
        gene = genes.get(hgnc_id)
        mouse = mouse_records.get(mouse_symbol.upper())
        if gene and mouse:
            records[gene["symbol"]]["o"] = [mouse_symbol, relation]
            records[gene["symbol"]]["m"] = slim(mouse)

    depmap = read_depmap(depmap_path)
    for entrez, (symbol, screened, dependent, common, nonessential) in depmap.items():
        target = resolve(symbol, entrez=entrez)
        if target:
            flag = "C" if common else "N" if nonessential else ""
            records[target]["c"] = [flag, round(100 * dependent / screened, 1) if screened else None, screened]

    for ensembl, loeuf in read_gnomad(sources["gnomad_constraint.tsv"]).items():
        target = by_ensembl.get(ensembl)
        if target:
            records[target]["l"] = loeuf

    gtex, tissues = read_gtex(sources["gtex_median_tpm.gct.gz"])
    for ensembl, (tau, expressed, top) in gtex.items():
        target = by_ensembl.get(ensembl)
        if target:
            records[target]["t"] = [tau, expressed, top]
    out = {symbol.upper(): rec for symbol, rec in records.items()}
    if paralog_path:
        coding = {g["symbol"].upper() for g in genes.values() if g["coding"]}
        with open_text(paralog_path) as handle:
            for gene, paralogs in parse_paralogs(handle, allowed_genes=coding, allowed_paralogs=coding).items():
                if gene in out:
                    out[gene]["p"] = paralogs
        print(f"  {sum(1 for r in out.values() if 'p' in r)} human genes with a close paralog")
    alias_out = {name.upper(): symbol for name, symbol in aliases.items() if symbol in records}
    print(f"  {len(out)} human genes, {len(alias_out)} older names")
    return out, alias_out, tissues


# --------------------------------------------------------------------------------------------------
# other species
# --------------------------------------------------------------------------------------------------

def build_inferred(pairs, tax, mouse_records, by_id):
    """Species whose knockouts are read from the mouse ortholog: {symbol upper: {"o": [...], "m": record}}."""
    records = {}
    for gene_id, (mouse_id, mouse_symbol, relation, symbol) in orthologs_to_mouse(pairs, tax).items():
        mouse = mouse_records.get(mouse_symbol.upper())
        if mouse:
            records[symbol.upper()] = {"o": [mouse_symbol, relation], "m": slim(mouse)}
    return records


YEAST_EXPERIMENTS = {"systematic mutation set", "classical genetics"}


def build_yeast(lines):
    """
    SGD null-mutant phenotypes: a gene whose deletion is 'inviable' under normal growth is essential.
    Rows recorded under a special condition or chemical (for example lethal only at 37 C) or in a special set-up
    (homozygous diploid, double mutants) are ignored, because they do not describe a plain deletion.
    """
    counts = collections.defaultdict(lambda: {"L": 0, "V": 0})
    pmids = collections.defaultdict(collections.Counter)
    names = {}
    for line in lines:
        f = line.rstrip("\r\n").split("\t")
        if len(f) < 12 or f[6] != "null" or f[5] not in YEAST_EXPERIMENTS or f[10].strip() or f[11].strip():
            continue
        phenotype = f[9].strip()
        if phenotype in ("inviable", "viable"):
            systematic, standard = f[0], f[2]
            key = systematic
            names[systematic] = standard
            counts[key]["L" if phenotype == "inviable" else "V"] += 1
            if phenotype == "inviable":
                for ref in f[4].split("|"):
                    if ref.startswith("PMID:"):
                        pmids[key][ref[5:]] += 1
    records = {}
    for systematic, c in counts.items():
        call = "L" if c["L"] and c["L"] >= c["V"] else "V"
        record = {"v": call, "n": [c["L"], 0, c["V"]], "src": "S"}
        if call == "L":
            record["s"] = "U"
        if c["L"] and c["V"]:
            record["x"] = 1
        if pmids[systematic]:
            record["pm"] = [int(p) for p, _ in pmids[systematic].most_common(3)]
        for key in {systematic, names.get(systematic) or systematic}:
            records[key.upper()] = record
    return records


# --------------------------------------------------------------------------------------------------
# paralogs (Ensembl BioMart)
# --------------------------------------------------------------------------------------------------

BIOMART_URL = "https://www.ensembl.org/biomart/martservice"
BIOMART_QUERY = ('<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE Query><Query virtualSchemaName="default" formatter="TSV" '
                 'header="1" uniqueRows="1" count="" datasetConfigVersion="0.6"><Dataset name="{dataset}" interface="default">'
                 '<Filter name="chromosome_name" value="{chromosome}"/><Filter name="biotype" value="protein_coding"/>'
                 '<Attribute name="external_gene_name"/>'
                 '<Attribute name="{prefix}_paralog_associated_gene_name"/><Attribute name="{prefix}_paralog_perc_id"/>'
                 '<Attribute name="{prefix}_paralog_subtype"/></Dataset></Query>')
PARALOG_SPECIES = {
    "human": ("hsapiens_gene_ensembl", "hsapiens", [str(i) for i in range(1, 23)] + ["X", "Y"]),
    "mouse": ("mmusculus_gene_ensembl", "mmusculus", [str(i) for i in range(1, 20)] + ["X", "Y"]),
}
# Paralogs that split before the vertebrates are too distant to take over each other's work
OLD_ANCESTORS = {"Opisthokonta", "Bilateria", "Chordata", ""}
MIN_PARALOG_IDENTITY = 30.0
PARALOGS_PER_GENE = 3


def keep_paralog_row(fields):
    """True for a (gene, paralog, identity, ancestor) row worth keeping: a different gene, similar enough, not ancient."""
    if len(fields) < 4 or not fields[0] or not fields[1] or fields[0] == fields[1]:
        return False
    try:
        identity = float(fields[2])
    except ValueError:
        return False
    return identity >= MIN_PARALOG_IDENTITY and fields[3] not in OLD_ANCESTORS


def fetch_biomart_chromosome(dataset, prefix, chromosome, attempts=8):
    """One BioMart query. BioMart sometimes answers with a 'Service unavailable' page, so this retries with longer pauses."""
    query = BIOMART_QUERY.format(dataset=dataset, prefix=prefix, chromosome=chromosome)
    for attempt in range(attempts):
        try:
            response = requests.get(BIOMART_URL, params={"query": query}, timeout=600)
            response.raise_for_status()
            if "Gene name" in response.text.split("\n", 1)[0]:
                return response.text
            problem = response.text[:120].replace("\n", " ")
        except requests.RequestException as error:
            problem = str(error)
        if attempt == attempts - 1:
            raise requests.RequestException(f"BioMart did not answer for chromosome {chromosome}: {problem}")
        time.sleep(min(20 * (attempt + 1), 90))


def download_paralogs(species, cache, refresh=False, workers=3):
    """
    The close paralogs of every protein-coding gene of a species, one BioMart query per chromosome (three at a time),
    filtered while downloading. Each chromosome is kept in its own small file, so a download that was interrupted
    resumes where it stopped.
    """
    cache = Path(cache)
    path = cache / f"{species}_paralogs.tsv"
    if path.exists() and path.stat().st_size and not refresh:
        return path
    dataset, prefix, chromosomes = PARALOG_SPECIES[species]
    print(f"  downloading the {species} paralogs ({len(chromosomes)} chromosomes)", flush=True)
    folder = cache / f"{species}_paralogs_by_chromosome"
    folder.mkdir(parents=True, exist_ok=True)

    def fetch(chromosome):
        part = folder / f"chr{chromosome}.tsv"
        if refresh or not part.exists():
            text = fetch_biomart_chromosome(dataset, prefix, chromosome)
            kept = [fields for fields in (line.split("\t") for line in text.splitlines()[1:]) if keep_paralog_row(fields)]
            part.write_text("\n".join("\t".join(fields[:4]) for fields in kept) + "\n", encoding="utf-8")
        return part

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        parts = list(pool.map(fetch, chromosomes))
    rows = ["gene\tparalog\tidentity\tancestor"]
    for part in parts:
        rows += [line for line in part.read_text(encoding="utf-8").splitlines() if line]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def parse_paralogs(lines, allowed_genes=None, allowed_paralogs=None):
    """
    {GENE: [[PARALOG, identity %], ...]} with the closest PARALOGS_PER_GENE paralogs of each gene.
    ``allowed_*`` (sets of upper-case symbols) keep out pseudogenes and RNA genes.
    """
    found = collections.defaultdict(dict)
    for line in lines:
        fields = line.rstrip("\r\n").split("\t")
        if fields[0] == "gene" or not keep_paralog_row(fields):
            continue
        gene, paralog = fields[0].upper(), fields[1].upper()
        if allowed_genes is not None and gene not in allowed_genes:
            continue
        if allowed_paralogs is not None and paralog not in allowed_paralogs:
            continue
        found[gene][paralog] = max(found[gene].get(paralog, 0.0), float(fields[2]))
    return {gene: [[paralog, round(identity)] for paralog, identity in
                   sorted(candidates.items(), key=lambda item: (-item[1], item[0]))[:PARALOGS_PER_GENE]]
            for gene, candidates in found.items()}


# --------------------------------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------------------------------

def write_json(path, data):
    path.write_text(json.dumps(data, separators=(",", ":"), sort_keys=True), encoding="utf-8")


def count_measured(genes):
    """Genes with a measured knockout result of their own or of their mouse ortholog (v, m), or a cell-line screen (c),
    as opposed to genes that only have constraint or expression data."""
    return sum(1 for record in genes.values() if any(key in record for key in ("v", "m", "c")))


def drop_empty_organisms(organism_files, index_organisms, out=None):
    """Leave out an organism for which the sources hold no gene at all (the Alliance lists no Xenopus laevis
    orthologs), so the site says "no measured data for this organism" instead of showing an empty layer.
    A file left in `out` by an earlier build is removed too."""
    for taxid in [taxid for taxid, data in organism_files.items() if not data["genes"]]:
        print(f"  NOTE: no genes found for {index_organisms[taxid]['name']} ({taxid}); it gets no data file", flush=True)
        del organism_files[taxid], index_organisms[taxid]
        if out is not None:
            (Path(out) / f"{taxid}.json").unlink(missing_ok=True)


def build_all(out, cache, refresh=False, depmap_path=DEPMAP_SUMMARY, organisms=("mouse", "human", "rat", "yeast", "distant"),
              paralogs=True):
    out, downloader = Path(out), Downloader(cache, refresh)
    out.mkdir(parents=True, exist_ok=True)
    print("Downloading the sources", flush=True)
    files = {}
    for source in SOURCES.values():
        for name, url in source["files"].items():
            files[name] = downloader.fetch(name, url)
    wanted = {frozenset(("9606", "10090")), frozenset(("10116", "10090"))}
    wanted |= {frozenset((taxid, "10090")) for taxid in DISTANT}
    pairs = parse_orthology(open_text(files["alliance_orthology.tsv.gz"]), wanted=wanted)

    mouse_records, by_id, info = build_mouse(files)
    paralog_files = {}
    if paralogs:
        try:
            for species in ("human", "mouse"):
                paralog_files[species] = download_paralogs(species, downloader.cache, refresh)
        except requests.RequestException as error:
            print(f"  WARNING: the paralogs could not be downloaded ({error}); the data are built without them", flush=True)
            paralog_files.clear()
    if paralog_files:
        mouse_genes = {p["a_sym"].upper() for p in pairs if p["a_tax"] == "10090"} | \
                      {p["b_sym"].upper() for p in pairs if p["b_tax"] == "10090"} | set(mouse_records)
        with open_text(paralog_files["mouse"]) as handle:
            for gene, found in parse_paralogs(handle, allowed_genes=mouse_genes, allowed_paralogs=mouse_genes).items():
                if gene in mouse_records:
                    mouse_records[gene]["p"] = found
        print(f"  {sum(1 for r in mouse_records.values() if 'p' in r)} mouse genes with a close paralog")
    organism_files, index_organisms = {}, {}
    if "mouse" in organisms:
        organism_files["10090"] = {"genes": mouse_records, "aliases": {}}
        index_organisms["10090"] = {"name": "Mus musculus", "layers": ["knockout", "expression"] + (["paralogs"] if paralog_files else [])}
    index = {"format": FORMAT_VERSION, "built": date.today().isoformat(), "stages": STAGES,
             "systems": info["systems"], "organisms": index_organisms}
    if "human" in organisms:
        human, aliases, tissues = build_human(files, mouse_records, by_id, pairs, depmap_path, paralog_files.get("human"))
        organism_files["9606"] = {"genes": human, "aliases": aliases}
        index_organisms["9606"] = {"name": "Homo sapiens",
                                   "layers": ["ortholog-knockout", "cell-essentiality", "constraint", "expression"]
                                   + (["paralogs"] if paralog_files else [])}
        index["tissues"] = tissues
        # mouse genes: where the human ortholog is expressed (a hint for a tissue-specific knockout)
        for _, (_, mouse_symbol, relation, human_symbol) in orthologs_to_mouse(pairs, "9606").items():
            mouse_record_ = mouse_records.get(mouse_symbol.upper())
            expression = human.get(human_symbol.upper(), {}).get("t")
            if relation == "1:1" and mouse_record_ is not None and expression:
                mouse_record_["t"] = expression
    if "rat" in organisms:
        organism_files["10116"] = {"genes": build_inferred(pairs, "10116", mouse_records, by_id), "aliases": {}}
        index_organisms["10116"] = {"name": "Rattus norvegicus", "layers": ["ortholog-knockout"]}
    if "distant" in organisms:
        for taxid, name in DISTANT.items():
            organism_files[taxid] = {"genes": build_inferred(pairs, taxid, mouse_records, by_id), "aliases": {}}
            index_organisms[taxid] = {"name": name, "layers": ["ortholog-knockout"], "distant": True}
    if "yeast" in organisms:
        with open_text(files["sgd_phenotype.tab"]) as handle:
            organism_files["559292"] = {"genes": build_yeast(handle), "aliases": {}}
        index_organisms["559292"] = {"name": "Saccharomyces cerevisiae S288C", "layers": ["knockout"]}

    drop_empty_organisms(organism_files, index_organisms, out)
    for taxid, data in organism_files.items():
        index_organisms[taxid]["genes"] = len(data["genes"])
        index_organisms[taxid]["measured"] = count_measured(data["genes"])
        index_organisms[taxid]["file"] = f"{taxid}.json"
        write_json(out / f"{taxid}.json", data)
    index["sources"] = [
        {"id": key, "name": s["name"], "url": s["url"], "what": s["what"], "license": s.get("license", "")}
        for key, s in SOURCES.items()]
    write_json(out / "index.json", index)
    sizes = {p.name: p.stat().st_size for p in out.glob("*.json")}
    print("Wrote", ", ".join(f"{n} ({s / 1e6:.2f} MB)" for n, s in sorted(sizes.items())))
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="site/evidence-data", help="Output folder")
    parser.add_argument("--cache", default=str(DEFAULT_CACHE), help="Folder for the downloaded sources")
    parser.add_argument("--refresh", action="store_true", help="Download the sources again")
    parser.add_argument("--depmap-summary", default=str(DEPMAP_SUMMARY))
    parser.add_argument("--organisms", nargs="*", default=["mouse", "human", "rat", "yeast", "distant"])
    parser.add_argument("--no-paralogs", action="store_true", help="Skip the paralog download (about 5 minutes)")
    args = parser.parse_args()
    if not Path(args.depmap_summary).exists():
        sys.exit(f"{args.depmap_summary} is missing; run tools/summarize_depmap.py first")
    build_all(args.out, args.cache, args.refresh, args.depmap_summary, tuple(args.organisms), not args.no_paralogs)


if __name__ == "__main__":
    main()
