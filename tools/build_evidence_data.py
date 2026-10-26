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
    evidence-data/7955.json     zebrafish - ZFIN mutant phenotypes; genes without one fall back to the mouse ortholog (hint)
    evidence-data/7227.json     fly     - FlyBase allele lethality phenotypes; same fallback
    evidence-data/6239.json     worm    - WormBase allele and RNAi lethal / sterile phenotypes; same fallback

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
import math
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
#   xenopus  the same as rat, but the organism is marked "distant" in index.json: the mouse ortholog is only an
#           indication there, never a measurement, and the verdict says so
#   yeast   {"v": "L"|"S"|"V", "n": [..], "x": 1, "src": "S", "pm": [..]}
#   zebrafish, fly, worm   a mouse-style direct record {"v", "n", "s", "x", "src": "Z"|"F"|"W", "pm"} (n counts mutant
#           lines: fish lines, alleles, alleles + RNAi tests), plus "f": 1 infertility seen, and for worms "k": 1 when
#           the lethal calls all come from RNAi knockdown. A gene without a measurement of its own keeps the
#           {"o", "m"} mouse-ortholog hint, and the organism stays marked "distant" for those genes.
# --------------------------------------------------------------------------------------------------

ZFIN_DOWNLOADS = "https://zfin.org/downloads/"
FLYBASE_FILES = "https://s3ftp.flybase.org/releases/current/precomputed_files/"
WORMBASE_ONTOLOGY = "https://downloads.wormbase.org/releases/current-production-release/ONTOLOGY/"


def latest_in_listing(index_url, pattern, key=None):
    """The newest file in a directory listing whose name matches `pattern` (one group: the release); FlyBase and WormBase
    put the release into the file names, so the address changes with every release."""
    response = requests.get(index_url, timeout=60)
    response.raise_for_status()
    names = {m.group(0): m.group(1) for m in re.finditer(pattern, response.text)}
    if not names:
        raise requests.RequestException(f"No file like {pattern} in {index_url}")
    return index_url + max(names, key=lambda n: (key or str)(names[n]))


NCBI_GENE = "https://ftp.ncbi.nlm.nih.gov/gene/DATA/"
NCBI_GENE_INFO = {
    "9606": "Mammalia/Homo_sapiens", "10090": "Mammalia/Mus_musculus", "10116": "Mammalia/Rattus_norvegicus",
    "7227": "Invertebrates/Drosophila_melanogaster", "6239": "Invertebrates/Caenorhabditis_elegans",
    "7955": "Non-mammalian_vertebrates/Danio_rerio", "8364": "Non-mammalian_vertebrates/Xenopus_tropicalis",
    "559292": "Fungi/Saccharomyces_cerevisiae",
}

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
        "what": "systematic knockout viability and phenotyping screen", "license": "CC BY 4.0",
        "files": {
            "impc_viability.csv.gz": "https://ftp.ebi.ac.uk/pub/databases/impc/all-data-releases/latest/results/viability.csv.gz",
            "impc_g2p.csv.gz": "https://ftp.ebi.ac.uk/pub/databases/impc/all-data-releases/latest/results/genotype-phenotype-assertions-ALL.csv.gz",
        },
    },
    "alliance": {
        "name": "Alliance of Genome Resources", "url": "https://www.alliancegenome.org/downloads",
        "what": "orthologs between human, mouse, rat, zebrafish, fly, worm and yeast",
        "license": "CC0 1.0 for most data, CC BY 4.0 for some",
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
        "license": "no restrictions on use (Ensembl disclaimer)",
        "files": {},          # downloaded per chromosome by download_paralogs()
    },
    "ncbi": {
        "name": "NCBI Gene (gene2pubmed)", "url": "https://ftp.ncbi.nlm.nih.gov/gene/DATA/",
        "what": "the PubMed articles linked to each gene", "license": "no restrictions (NCBI data usage policy)",
        "optional": True,
        "files": {"ncbi_gene2pubmed.gz": NCBI_GENE + "gene2pubmed.gz",
                  **{f"ncbi_gene_info_{taxid}.gz": f"{NCBI_GENE}GENE_INFO/{path}.gene_info.gz" for taxid, path in NCBI_GENE_INFO.items()}},
    },
    "sgd": {
        "name": "Saccharomyces Genome Database (SGD)", "url": "https://www.yeastgenome.org/",
        "what": "yeast deletion phenotypes (viable / inviable)", "license": "CC BY 4.0",
        "files": {"sgd_phenotype.tab": "https://downloads.yeastgenome.org/curation/literature/phenotype_data.tab"},
    },
    "zfin": {
        "name": "Zebrafish Information Network (ZFIN)", "url": "https://zfin.org/downloads",
        "what": "zebrafish mutant phenotypes", "license": "CC BY 4.0", "optional": True,
        "files": {
            "zfin_phenotype.txt": ZFIN_DOWNLOADS + "phenoGeneCleanData_fish.txt",
            "zfin_fish_components.txt": ZFIN_DOWNLOADS + "fish_components_fish.txt",
            "zfin_features.txt": ZFIN_DOWNLOADS + "features-affected-genes.txt",
            "zfin_stages.txt": ZFIN_DOWNLOADS + "stage_ontology.txt",
            "zfin_pubmed.txt": ZFIN_DOWNLOADS + "pub_to_pubmed_id_translation.txt",
        },
    },
    "flybase": {
        "name": "FlyBase", "url": "https://s3ftp.flybase.org/releases/current/precomputed_files/",
        "what": "Drosophila allele phenotypes (lethality, viability, sterility)", "license": "CC BY 4.0", "optional": True,
        "files": {
            "flybase_genotype_phenotype.tsv.gz": lambda: latest_in_listing(
                FLYBASE_FILES + "alleles/", r"genotype_phenotype_data_fb_(\d{4}_\d{2})\.tsv\.gz"),
            "flybase_alleles.tsv.gz": lambda: latest_in_listing(
                FLYBASE_FILES + "alleles/", r"dmel_classical_and_insertion_allele_descriptions_fb_(\d{4}_\d{2})\.tsv\.gz"),
            "flybase_references.tsv.gz": lambda: latest_in_listing(
                FLYBASE_FILES + "references/", r"fbrf_pmid_pmcid_doi_fb_(\d{4}_\d{2})\.tsv\.gz"),
        },
    },
    "wormbase": {
        "name": "WormBase", "url": "https://downloads.wormbase.org/releases/current-production-release/ONTOLOGY/",
        "what": "C. elegans allele and RNAi phenotypes (lethal, sterile)", "license": "CC0 (public domain)", "optional": True,
        "files": {
            "wormbase_phenotype_association.wb.gz": lambda: latest_in_listing(
                WORMBASE_ONTOLOGY, r"phenotype_association\.(WS\d+)\.wb\.gz", key=lambda v: int(v[2:])),
            "wormbase_phenotype_ontology.obo.gz": lambda: latest_in_listing(
                WORMBASE_ONTOLOGY, r"phenotype_ontology\.(WS\d+)\.obo\.gz", key=lambda v: int(v[2:])),
            "alliance_phenotype_wb.json.gz": "https://fms.alliancegenome.org/download/PHENOTYPE_WB.json.gz",
        },
    },
}

# Stages of death, earliest first. W (before weaning) and U (age not stated) say the least.
STAGES = {"E": "embryonic / prenatal", "P": "perinatal / neonatal", "J": "after birth, before adulthood",
          "L": "larval, pupal or juvenile stage", "A": "adult", "W": "before weaning", "U": "age not stated"}
STAGE_ORDER = "EPJLAWU"

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
# Species whose own knockouts are measured here only for some genes (MODEL_ORGANISMS), or not at all: for the genes
# without a measurement the mouse ortholog is the only (indirect) hint
DISTANT = {"7955": "Danio rerio", "7227": "Drosophila melanogaster", "6239": "Caenorhabditis elegans",
           "8364": "Xenopus tropicalis", "8355": "Xenopus laevis"}
MODEL_ORGANISMS = ("7955", "7227", "6239")
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
        """`url` may be a function that finds the address (FlyBase and WormBase change it with every release); it is only
        called when the file has to be downloaded."""
        path = self.cache / name
        if self.refresh or not path.exists() or path.stat().st_size == 0:
            if callable(url):
                url = self.resolve(url)
            print(f"  downloading {name}", flush=True)
            part = path.with_name(path.name + ".part")           # a cut-off download is never taken for a finished one
            for attempt in range(4):
                try:
                    with requests.get(url, stream=True, timeout=180) as response:
                        response.raise_for_status()
                        with open(part, "wb") as handle:
                            for chunk in response.iter_content(1 << 20):
                                handle.write(chunk)
                    part.replace(path)
                    break
                except requests.RequestException:
                    if attempt == 3:
                        raise
                    time.sleep(3 * (attempt + 1))
        self.log[name] = {"url": url if isinstance(url, str) else "cached", "bytes": path.stat().st_size}
        return path

    @staticmethod
    def resolve(finder):
        for attempt in range(4):
            try:
                return finder()
            except requests.RequestException:
                if attempt == 3:
                    raise
                time.sleep(3 * (attempt + 1))


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
        # the most cited first; among equals the oldest paper, so that the same sources always give the same file
        record["pm"] = [int(p) for p, _ in sorted(gene.pmids.items(), key=lambda item: (-item[1], int(item[0])))[:3]]
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
# zebrafish, fly and worm: knockouts measured by their own community databases
#
# All three work like mouse: every mutant (or RNAi test) that loses one gene is called LETHAL, SUBVIABLE or VIABLE, the
# calls are counted per gene, and the earliest stage of death and the PubMed ids behind the call are kept.
# --------------------------------------------------------------------------------------------------

def tally_calls(calls, stages, pmids, source, extra=None):
    """
    calls: list of 'L' / 'S' / 'V', one per mutant line; stages: {'L': set, 'S': set}; pmids: Counter. -> compact record or None.
    The call is the most frequent one; among equals the more severe. Same rule as the mouse records.
    """
    counts = {"L": 0, "S": 0, "V": 0}
    for call in calls:
        counts[call] += 1
    if not any(counts.values()):
        return None
    severity = {"L": 2, "S": 1, "V": 0}
    call = max(counts, key=lambda c: (counts[c], severity[c]))
    record = {"v": call, "n": [counts["L"], counts["S"], counts["V"]]}
    if call in ("L", "S"):
        stage = earliest_stage(stages[call] or stages["L"] or stages["S"])
        if stage:
            record["s"] = stage
    if sum(1 for c in counts.values() if c) > 1:
        record["x"] = 1
    record["src"] = source
    if pmids:
        record["pm"] = [int(p) for p, _ in sorted(pmids.items(), key=lambda item: (-item[1], int(item[0])))[:3]]
    record.update(extra or {})
    return record


# ---- zebrafish (ZFIN) ----------------------------------------------------------------------------

ZFIN_WHOLE_ORGANISM = "ZFA:0001094"
ZFIN_DEAD = {"PATO:0001422", "PATO:0000718"}              # dead, lethal (sensu genetics)
ZFIN_REDUCED = {"PATO:0001770", "PATO:0000169"}           # semi-viable, viability (recorded as abnormal)
ZFIN_UNKNOWN_STAGE = "ZDB-STAGE-050211-1"
ZFIN_NULL_EFFECTS = {"premature stop", "frameshift", "splice site"}
ZFIN_NOT_LOSS = {"TRANSLOC", "UNSPECIFIED"}
ZFIN_HATCHED_HOURS = 72               # hatching ends at 72 hours
ZFIN_JUVENILE_HOURS = 30 * 24         # larval stages end at 30 days
ZFIN_ADULT_HOURS = 90 * 24


def zfin_stage_letter(stage_id, stages):
    """The stage a ZFIN stage id belongs to: E embryo (up to hatching), L larva / juvenile, A adult, U not stated."""
    if stage_id == ZFIN_UNKNOWN_STAGE or stage_id not in stages:
        return "U"
    begin = stages[stage_id][0]
    return "E" if begin < ZFIN_HATCHED_HOURS else "L" if begin < ZFIN_ADULT_HOURS else "A"


def parse_zfin_stages(lines):
    """{stage id: (begin hour, end hour)} from stage_ontology.txt."""
    stages = {}
    for line in lines:
        f = line.rstrip("\r\n").split("\t")
        if len(f) >= 5:
            try:
                stages[f[0]] = (float(f[3]), float(f[4]))
            except ValueError:
                continue
    return stages


def parse_zfin_features(lines):
    """{allele id: 'null' | 'other' | None}: 'null' = deletion or an allele with a stop, frameshift or splice-site effect;
    None = not a loss of the gene (translocation, unspecified)."""
    result = {}
    for line in lines:
        f = line.rstrip("\r\n").split("\t")
        if len(f) < 8:
            continue
        effects = {part.strip() for field in f[8:] for part in field.split(",")}
        if f[7] in ZFIN_NOT_LOSS:
            result[f[0]] = None
        elif f[7] in ("DELETION", "DEFICIENCY") or effects & ZFIN_NULL_EFFECTS:
            result[f[0]] = "null"
        else:
            result[f[0]] = "other"
    return result


ZFIN_HOMOZYGOUS = re.compile(r"<sup>([^<>/]+)/([^<>/]+)</sup>")


def parse_zfin_fish(lines, features):
    """
    {fish id: (gene id, 'null' | 'other')} for fish that are a clean homozygous mutant of exactly one gene: no knockdown
    reagent (morpholino, CRISPR injection), no transgene, one gene, the same allele on both chromosomes.
    """
    parts = collections.defaultdict(lambda: {"name": "", "genes": set(), "alleles": set(), "other": False})
    for line in lines:
        f = line.rstrip("\r\n").split("\t")
        if len(f) < 6:
            continue
        fish = parts[f[0]]
        fish["name"] = f[1]
        if f[2]:
            fish["genes"].add(f[2])
        if f[4]:
            fish["alleles"].add(f[4])
        if (len(f) > 6 and f[6]) or (len(f) > 8 and f[8]):          # a transgene or a knockdown reagent
            fish["other"] = True
    result = {}
    for fish_id, fish in parts.items():
        match = ZFIN_HOMOZYGOUS.search(fish["name"])
        if fish["other"] or len(fish["genes"]) != 1 or not fish["alleles"] or not match or match.group(1) != match.group(2):
            continue
        kinds = [features.get(a, "other") for a in fish["alleles"]]
        if None in kinds:
            continue
        result[fish_id] = (next(iter(fish["genes"])), "null" if all(k == "null" for k in kinds) else "other")
    return result


def build_zebrafish(phenotype_lines, fish, stages, pubmed):
    """{SYMBOL: record} from ZFIN phenotypes of clean homozygous mutants (see parse_zfin_fish)."""
    state = {}
    symbols = {}
    for line in phenotype_lines:
        f = line.rstrip("\r\n").split("\t")
        if len(f) < 24 or f[18] not in fish or fish[f[18]][0] != f[2]:
            continue
        item = state.setdefault(f[18], {"L": [], "S": [], "late": False, "pubs": {"L": [], "S": [], "V": []}})
        symbols[f[2]] = f[1]
        stage = zfin_stage_letter(f[20], stages)
        if f[7] == ZFIN_WHOLE_ORGANISM and f[11] == "abnormal" and f[9] in ZFIN_DEAD:
            item["L"].append(stage)
            item["pubs"]["L"].append(f[23])
        elif f[7] == ZFIN_WHOLE_ORGANISM and f[11] == "abnormal" and f[9] in ZFIN_REDUCED:
            item["S"].append(stage)
            item["pubs"]["S"].append(f[23])
        elif f[20] in stages and stages[f[20]][0] >= ZFIN_JUVENILE_HOURS:
            item["late"] = True                      # a phenotype was scored in a living juvenile or adult
            item["pubs"]["V"].append(f[23])
    per_gene = collections.defaultdict(lambda: {"calls": [], "stages": {"L": set(), "S": set()}, "pubs": collections.Counter()})
    for fish_id, item in state.items():
        gene, kind = fish[fish_id]
        if item["L"]:
            call = "L"
        elif item["S"]:
            call = "S"
        elif item["late"] and kind == "null":
            call = "V"
        else:
            continue
        entry = per_gene[gene]
        entry["calls"].append(call)
        if call in entry["stages"]:
            entry["stages"][call].update(item[call])
        for pub in item["pubs"][call]:
            if pub in pubmed:
                entry["pubs"][pubmed[pub]] += 1
    records = {}
    for gene, entry in per_gene.items():
        record = tally_calls(entry["calls"], entry["stages"], entry["pubs"], "Z")
        if record:
            records[symbols[gene].upper()] = record
    return records


# ---- fly (FlyBase) ---------------------------------------------------------------------------------

FLY_COMPLETE_LETHAL_PREFIX = "lethal"
FLY_PARTIAL_LETHAL_PREFIX = "partially lethal"
FLY_VIABLE, FLY_STERILE = "FBcv:0000349", {"FBcv:0000364", "FBcv:0000366", "FBcv:0000370"}
FLY_EXCLUDED_QUALIFIERS = ("dominant", "maternal effect", "paternal effect", "clone", "sensitive", "temperature", "conditional")
FLY_NOT_LOSS_CLASSES = ("gain of function", "neomorphic", "antimorphic", "hypermorphic", "wild-type")
FLY_CONDITIONAL_CLASSES = ("heat sensitive", "cold sensitive", "temperature conditional")


def fly_allele_kind(classes, has_insertion):
    """'null' (amorphic / loss of function), 'hypo' (hypomorphic), 'insertion' (a transposon insertion in the gene, class
    not stated) or None (gain of function, conditional or otherwise not a plain loss of the gene)."""
    text = classes.lower()
    if any(word in text for word in FLY_NOT_LOSS_CLASSES + FLY_CONDITIONAL_CLASSES):
        return None
    if "amorphic" in text or "loss of function" in text:
        return "null"
    if "hypomorphic" in text:
        return "hypo"
    return "insertion" if has_insertion else None


def parse_fly_alleles(lines):
    """{allele id: (gene id, gene symbol, kind)} from the FlyBase classical and insertion allele descriptions."""
    alleles = {}
    for line in lines:
        if line.startswith("#") or not line.strip():
            continue
        f = line.rstrip("\r\n").split("\t")
        if len(f) < 7 or not f[3].startswith("FBgn"):
            continue
        kind = fly_allele_kind(f[4], bool(f[6]))
        if kind:
            alleles[f[1]] = (f[3], f[2], kind)
    return alleles


def fly_stage_letter(name):
    text = name.lower()
    if "embryonic" in text:
        return "E"
    if "adult" in text and "pharate" not in text:
        return "A"
    if any(word in text for word in ("larva", "instar", "pupa", "p-stage", "pharate")):
        return "L"
    return "U"


def parse_fly_references(lines):
    """{FBrf id: pubmed id} from fbrf_pmid_pmcid_doi."""
    result = {}
    for line in lines:
        f = line.rstrip("\r\n").split("\t")
        if len(f) >= 2 and f[0].startswith("FBrf") and f[1].isdigit():
            result[f[0]] = f[1]
    return result


def build_fly(phenotype_lines, alleles, pubmed):
    """{SYMBOL: record} from FlyBase phenotypes of single-allele genotypes (null, hypomorphic or insertion alleles)."""
    state = {}
    for line in phenotype_lines:
        if line.startswith("#") or not line.strip():
            continue
        f = line.rstrip("\r\n").split("\t")
        if len(f) < 7 or f[1] not in alleles:
            continue
        if any(word in f[4].lower() for word in FLY_EXCLUDED_QUALIFIERS):
            continue
        name, term = f[2], f[3]
        item = state.setdefault(f[1], {"L": [], "S": [], "V": [], "sterile": False})
        refs = item.setdefault("refs", {"L": [], "S": [], "V": []})
        if name.startswith(FLY_PARTIAL_LETHAL_PREFIX) or name == "semi-lethal":
            item["S"].append(fly_stage_letter(name))
            refs["S"].append(f[6])
        elif name.startswith(FLY_COMPLETE_LETHAL_PREFIX) and term.startswith("FBcv:"):
            item["L"].append(fly_stage_letter(name))
            refs["L"].append(f[6])
        elif term == FLY_VIABLE:
            item["V"].append("V")
            refs["V"].append(f[6])
        elif term in FLY_STERILE:
            item["sterile"] = True
    per_gene = collections.defaultdict(lambda: {"calls": [], "stages": {"L": set(), "S": set()}, "pubs": collections.Counter(),
                                                "sterile": False, "symbol": ""})
    for allele_id, item in state.items():
        gene, symbol, kind = alleles[allele_id]
        # lethality of any loss-of-function allele counts (a partial loss that kills, the full loss kills too);
        # viability only counts for a null allele
        if item["L"]:
            call = "L"
        elif item["S"]:
            call = "S"
        elif item["V"] and kind == "null":
            call = "V"
        else:
            continue
        entry = per_gene[gene]
        entry["symbol"] = symbol
        entry["calls"].append(call)
        if call in entry["stages"]:
            entry["stages"][call].update(item[call])
        for ref in item["refs"][call]:
            if ref in pubmed:
                entry["pubs"][pubmed[ref]] += 1
        entry["sterile"] = entry["sterile"] or item["sterile"]
    records = {}
    for gene, entry in per_gene.items():
        record = tally_calls(entry["calls"], entry["stages"], entry["pubs"], "F", {"f": 1} if entry["sterile"] else None)
        if record:
            records[entry["symbol"].upper()] = record
    return records


# ---- worm (WormBase) -------------------------------------------------------------------------------

WORM_LETHAL, WORM_EMBRYONIC, WORM_LARVAL, WORM_ADULT, WORM_STERILE = (
    "WBPhenotype:0000062", "WBPhenotype:0000050", "WBPhenotype:0000054", "WBPhenotype:0000060", "WBPhenotype:0000688")
WORM_MIN_VIABLE_ALLELES = 2


def parse_worm_papers(data):
    """{WBPaper id: pubmed id} from the Alliance WormBase phenotype file (parsed JSON)."""
    papers = {}
    for record in data.get("data", []):
        evidence = record.get("evidence", {})
        paper = evidence.get("crossReference", {}).get("id", "")
        pmid = evidence.get("publicationId", "")
        if paper.startswith("WB:WBPaper") and pmid.startswith("PMID:"):
            papers[paper[3:]] = pmid[5:]
    return papers


def build_worm(lines, ontology, papers):
    """
    ({SYMBOL: record}, {sequence name: SYMBOL}) from the WormBase phenotype associations of alleles and RNAi experiments.

    LETHAL: some allele or RNAi experiment gave a lethal phenotype (WBPhenotype 'lethal' or anything below it).
    VIABLE: at least WORM_MIN_VIABLE_ALLELES alleles were tested and reported 'not lethal' with no lethal result at all.
    The file does not say which alleles are null, so a few weak alleles cannot make a gene viable.
    An all-RNAi lethal call is marked "k": it is a knockdown, not a mutant.
    """
    lethal = ontology.descendants(WORM_LETHAL)
    stage_of = {}
    for term in lethal:
        stage_of[term] = ("E" if term in ontology.descendants(WORM_EMBRYONIC) else
                          "L" if term in ontology.descendants(WORM_LARVAL) else
                          "A" if term in ontology.descendants(WORM_ADULT) else "U")
    sterile = ontology.descendants(WORM_STERILE)
    genes = {}
    sequence_names = {}
    for line in lines:
        if line.startswith("!") or not line.strip():
            continue
        f = line.rstrip("\r\n").split("\t")
        if len(f) < 11 or f[0] != "WB":
            continue
        term, negated = f[4], f[3].strip().upper() == "NOT"
        if term not in lethal and term not in sterile:
            continue
        gene = genes.setdefault(f[1], {"symbol": f[2], "experiments": {}})
        if f[10]:
            sequence_names[f[10].upper()] = f[2]
        for experiment in (x for x in f[7].split("|") if x.startswith(("WB:WBVar", "WB:WBRNAi"))):
            item = gene["experiments"].setdefault(experiment, {"lethal": set(), "notlethal": False, "sterile": False, "refs": []})
            if term in lethal and not negated:
                item["lethal"].add(stage_of[term])
                item["refs"].append(f[5].replace("WB_REF:", ""))
            elif term == WORM_LETHAL and negated:
                item["notlethal"] = True
                item["refs"].append(f[5].replace("WB_REF:", ""))
            elif term in sterile and not negated:
                item["sterile"] = True
    records = {}
    aliases = {}
    for gene in genes.values():
        calls, stages, pubs, infertile, rnai_only = [], {"L": set(), "S": set()}, collections.Counter(), False, True
        viable_alleles = []
        for experiment, item in gene["experiments"].items():
            if item["lethal"]:
                calls.append("L")
                stages["L"] |= item["lethal"]
                rnai_only = rnai_only and experiment.startswith("WB:WBRNAi")
                refs = item["refs"]
            elif item["notlethal"] and experiment.startswith("WB:WBVar"):
                viable_alleles.append(experiment)
                refs = item["refs"]
            else:
                refs = []
            for ref in refs:
                if ref in papers:
                    pubs[papers[ref]] += 1
            infertile = infertile or (item["sterile"] and experiment.startswith("WB:WBVar"))
        if len(viable_alleles) >= WORM_MIN_VIABLE_ALLELES:
            calls += ["V"] * len(viable_alleles)
        extra = {"f": 1} if infertile else {}
        if calls and "L" in calls and rnai_only:
            extra["k"] = 1
        record = tally_calls(calls, stages, pubs, "W", extra)
        if record:
            records[gene["symbol"].upper()] = record
    for name, symbol in sequence_names.items():
        if symbol.upper() in records and name != symbol.upper():
            aliases[name] = symbol
    return records, aliases


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
# an estimate of lethality for genes that have no knockout result
# --------------------------------------------------------------------------------------------------
# Most genes were never knocked out in a mouse. For those the measurements of their human ortholog (how many cancer cell
# lines need it, how rarely people carry loss-of-function variants, where it is expressed, whether a close paralog
# exists) are used in a small logistic regression that was fitted on the mouse genes whose outcome is known. The fit is
# tested on genes it has not seen (5-fold cross-validation); the result goes into index.json and VALIDATION.md.
# It is an estimate, labelled as such everywhere, and never makes a verdict better than CAUTION.

LETHALITY_FEATURES = ["depmap_percent", "depmap_missing", "common_essential", "loeuf", "loeuf_missing", "tau",
                      "tissues", "paralog"]
LETHAL_LIKELY, LETHAL_POSSIBLE = 0.5, 0.3       # probability bands used in the report and the verdict
MIN_TRAINING_GENES = 500                        # fewer known knockouts than this: no estimate is made


def lethality_features(record):
    """The feature vector of a human gene record, or None when it has no cell-line, constraint or expression data."""
    cells, loeuf, tissue = record.get("c"), record.get("l"), record.get("t")
    has_cells = bool(cells) and cells[1] is not None
    if not (has_cells or loeuf is not None or tissue):
        return None
    return [
        (cells[1] / 100.0) if has_cells else 0.0,
        0.0 if has_cells else 1.0,
        1.0 if cells and cells[0] == "C" else 0.0,
        min(float(loeuf), 2.0) if loeuf is not None else 1.0,
        0.0 if loeuf is not None else 1.0,
        float(tissue[0]) if tissue and tissue[0] is not None else 0.5,
        (tissue[1] / 54.0) if tissue and tissue[1] is not None else 0.5,
        1.0 if record.get("p") else 0.0,
    ]


def _solve(matrix, vector):
    """Solves matrix x = vector by Gaussian elimination with partial pivoting (the matrices are 9 x 9)."""
    n = len(vector)
    a = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda r: abs(a[r][column]))
        a[column], a[pivot] = a[pivot], a[column]
        for row in range(column + 1, n):
            factor = a[row][column] / a[column][column]
            for k in range(column, n + 1):
                a[row][k] -= factor * a[column][k]
    x = [0.0] * n
    for row in range(n - 1, -1, -1):
        x[row] = (a[row][n] - sum(a[row][k] * x[k] for k in range(row + 1, n))) / a[row][row]
    return x


def _sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def fit_lethality_model(rows, l2=1.0, max_iterations=30):
    """Logistic regression (Newton's method, ridge penalty). rows: [(1 lethal | 0 viable, feature vector)]."""
    k = len(rows[0][1])
    means = [sum(x[i] for _, x in rows) / len(rows) for i in range(k)]
    sds = [math.sqrt(sum((x[i] - means[i]) ** 2 for _, x in rows) / len(rows)) or 1.0 for i in range(k)]
    data = [(y, [1.0] + [(x[i] - means[i]) / sds[i] for i in range(k)]) for y, x in rows]
    weights = [0.0] * (k + 1)
    for _ in range(max_iterations):
        gradient = [0.0] * (k + 1)
        hessian = [[0.0] * (k + 1) for _ in range(k + 1)]
        for y, z in data:
            p = _sigmoid(sum(w * v for w, v in zip(weights, z)))
            error, weight = p - y, p * (1.0 - p)
            for i in range(k + 1):
                gradient[i] += error * z[i]
                row = hessian[i]
                scaled = weight * z[i]
                for j in range(i, k + 1):
                    row[j] += scaled * z[j]
        for i in range(k + 1):
            for j in range(i):
                hessian[i][j] = hessian[j][i]
            if i:
                gradient[i] += l2 * weights[i]
                hessian[i][i] += l2
        step = _solve(hessian, gradient)
        weights = [w - s for w, s in zip(weights, step)]
        if max(abs(s) for s in step) < 1e-8:
            break
    return {"means": means, "sds": sds, "weights": weights}


def lethality_probability(model, features):
    z = model["weights"][0] + sum(w * (v - m) / s for w, v, m, s in
                                  zip(model["weights"][1:], features, model["means"], model["sds"]))
    return _sigmoid(z)


def rank_auc(labels, scores):
    """Area under the ROC curve (probability that a lethal gene scores above a viable one; ties count half)."""
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        for position in range(i, j + 1):
            ranks[order[position]] = (i + j) / 2.0 + 1.0
        i = j + 1
    positives = [r for r, y in zip(ranks, labels) if y]
    negatives = len(labels) - len(positives)
    if not positives or not negatives:
        return 0.5
    return (sum(positives) - len(positives) * (len(positives) + 1) / 2.0) / (len(positives) * negatives)


def train_lethality_model(human):
    """Fit on the human genes whose one-to-one mouse ortholog was knocked out (lethal or viable) and test by 5-fold
    cross-validation. Returns the model with its accuracy figures in "tested"."""
    rows = []
    for symbol in sorted(human):
        record = human[symbol]
        mouse = record.get("m")
        if not mouse or record["o"][1] != "1:1" or mouse.get("v") not in ("L", "V"):
            continue
        features = lethality_features(record)
        if features:
            rows.append((1 if mouse["v"] == "L" else 0, features))
    if len(rows) < MIN_TRAINING_GENES:
        return None
    folds = 5
    held_out = []
    for fold in range(folds):
        train = [row for i, row in enumerate(rows) if i % folds != fold]
        model = fit_lethality_model(train)
        held_out += [(y, lethality_probability(model, x)) for i, (y, x) in enumerate(rows) if i % folds == fold]
    labels, scores = [y for y, _ in held_out], [p for _, p in held_out]
    lethal, viable = sum(labels), len(labels) - sum(labels)
    bands = {}
    for name, low, high in (("likely", LETHAL_LIKELY, 1.01), ("possible", LETHAL_POSSIBLE, LETHAL_LIKELY), ("unlikely", -1.0, LETHAL_POSSIBLE)):
        inside = [y for y, p in held_out if low <= p < high]
        bands[name] = {"genes": len(inside), "lethal_share": round(sum(inside) / len(inside), 3) if inside else None}
    flagged = [(y, p) for y, p in held_out if p >= LETHAL_POSSIBLE]
    model = fit_lethality_model(rows)
    model["tested"] = {
        "genes": len(rows), "lethal": lethal, "viable": viable, "auc": round(rank_auc(labels, scores), 3),
        "bands": bands,
        "lethal_found_at_possible": round(sum(y for y, _ in flagged) / lethal, 3),
        "viable_flagged_at_possible": round(sum(1 - y for y, _ in flagged) / viable, 3),
    }
    return model


def add_lethality_estimates(human, human_aliases, mouse_records, mouse_paralogs, pairs):
    """Give the genes without a mouse knockout result an estimate: record["pl"] = [probability, the other gene].
    On a human gene "the other gene" is its mouse ortholog; on a mouse gene (a new stub record) it is the human ortholog.
    Only one-to-one orthologs get one. Returns the model, or None when there are too few genes to fit it."""
    model = train_lethality_model(human)
    if model is None:
        return None
    given = 0
    for _, (_, mouse_symbol, relation, human_symbol) in sorted(orthologs_to_mouse(pairs, "9606").items(), key=lambda kv: kv[1][3]):
        if relation != "1:1" or mouse_symbol.upper() in mouse_records:
            continue
        key = human_symbol.upper()
        record = human.get(key) or human.get(human_aliases.get(key, "").upper())
        if record is None or "m" in record:
            continue
        features = lethality_features(record)
        if not features:
            continue
        probability = round(lethality_probability(model, features), 2)
        record["pl"] = [probability, mouse_symbol]
        stub = {"pl": [probability, human_symbol]}
        if record.get("t"):
            stub["t"] = record["t"]
        if mouse_symbol.upper() in mouse_paralogs:
            stub["p"] = mouse_paralogs[mouse_symbol.upper()]
        mouse_records[mouse_symbol.upper()] = stub
        given += 1
    print(f"  lethality estimate for {given} genes without a mouse knockout (cross-validated AUC {model['tested']['auc']})")
    return model



# --------------------------------------------------------------------------------------------------
# conservation and literature, read from the databases instead of searched for by gene name
# --------------------------------------------------------------------------------------------------
# Conservation: in how many of the five model species (human, mouse, rat, fly, worm) does the gene, or an ortholog of it,
# exist? The old way asked a database for the same gene symbol in each species, which misses every ortholog that has a
# different name (PCNA is mus209 in the fly) and can match an unrelated gene with the same name.
# Literature: how many PubMed articles NCBI Gene links to the gene (gene2pubmed), not a text search of the symbol.

CONSERVATION_SPECIES = ("9606", "10090", "10116", "7227", "6239")        # bit 0 = human ... bit 4 = worm
MIN_ALGORITHMS = 3          # an ortholog call counts when this many algorithms agree, or two do and it is the best pair both ways


def read_conservation(lines, taxa):
    """One pass over the Alliance orthology table. Returns ({gene id: taxon ids of the model species with an ortholog},
    {(taxon id, SYMBOL): gene id}) for the genes of the species in `taxa`."""
    species = set(CONSERVATION_SPECIES)
    orthologs = collections.defaultdict(set)
    ids = {}
    header = False
    for line in lines:
        if line.startswith("#") or not line.strip():
            continue
        f = line.rstrip("\r\n").split("\t")
        if not header:
            header = True
            continue
        if len(f) < 13:
            continue
        a_tax, b_tax = f[2].replace("NCBITaxon:", ""), f[6].replace("NCBITaxon:", "")
        if not ((a_tax in species and b_tax in taxa) or (b_tax in species and a_tax in taxa)):
            continue
        ids[(a_tax, f[1].upper())] = f[0]
        ids[(b_tax, f[5].upper())] = f[4]
        matched = int(f[9] or 0)
        if matched >= MIN_ALGORITHMS or (matched >= 2 and f[11] == "Yes" and f[12] == "Yes"):
            orthologs[f[0]].add(b_tax)
            orthologs[f[4]].add(a_tax)
    return orthologs, ids


def conservation_bits(taxid, symbol, orthologs, ids):
    """Which model species carry the gene (or an ortholog) as a number: bit i is CONSERVATION_SPECIES[i]. None when the
    gene is not in the orthology table under that symbol."""
    gene = ids.get((taxid, symbol.upper()))
    if gene is None:
        return None
    found = set(orthologs.get(gene, ()))
    if taxid in CONSERVATION_SPECIES:
        found.add(taxid)
    return sum(1 << i for i, species in enumerate(CONSERVATION_SPECIES) if species in found)


def read_gene_info(lines):
    """From an NCBI gene_info file: ({SYMBOL: Entrez gene id} for the official symbol, the nomenclature symbol and the locus
    tag, {SYNONYM: official symbol} for the older names that point to one gene only). Databases and papers still use the
    older names (the mouse gene Trp53bp1 is called Tp53bp1 in GO), so they are kept as aliases."""
    primary, secondary, synonyms, clashes = {}, {}, {}, set()
    for line in lines:
        if line.startswith("#"):
            continue
        f = line.rstrip("\r\n").split("\t")
        if len(f) < 11:
            continue
        if f[2] and f[2] != "-":
            primary.setdefault(f[2].upper(), f[1])                # an official symbol always beats another gene's tag
        for name in (f[10], f[3]):
            if name and name != "-":
                secondary.setdefault(name.upper(), f[1])
        for synonym in f[4].split("|"):
            key = synonym.strip().upper()
            if key and key != "-":
                if key in synonyms and synonyms[key] != f[2]:
                    clashes.add(key)
                synonyms[key] = f[2]
    ids = {**secondary, **primary}
    return ids, {key: symbol for key, symbol in synonyms.items() if key not in clashes and key not in ids}


def read_gene2pubmed(lines, taxa):
    """{Entrez gene id: number of PubMed articles linked to it} for the genes of the species in `taxa`."""
    counts = collections.Counter()
    for line in lines:
        if line.startswith("#"):
            continue
        f = line.split("\t", 2)
        if len(f) == 3 and f[0] in taxa:
            counts[f[1]] += 1
    return counts


def add_gene_facts(organism_files, orthologs, ids, literature):
    """Put the conservation (record["cv"]) and the literature count (record["lc"]) on every gene that has them, and
    the older names of the genes as aliases. `literature`: {taxon id: (symbol -> gene id, gene id -> articles,
    older name -> symbol)} or empty."""
    for taxid, data in organism_files.items():
        # genes known by several names (yeast: RPS3 and YNL178W) share one record; each name gets its own copy
        data["genes"] = {key: dict(record) for key, record in data["genes"].items()}
        symbols, counts, synonyms = literature.get(taxid, ({}, {}, {}))
        for synonym, symbol in synonyms.items():
            if symbol.upper() in data["genes"] and synonym not in data["genes"] and synonym not in data["aliases"]:
                data["aliases"][synonym] = symbol
        for symbol, record in data["genes"].items():
            if orthologs is not None:
                bits = conservation_bits(taxid, symbol, orthologs, ids)
                if bits is not None:
                    record["cv"] = bits
            gene = symbols.get(symbol)
            if gene is not None:
                record["lc"] = counts.get(gene, 0)


# --------------------------------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------------------------------

def write_json(path, data):
    path.write_text(json.dumps(data, separators=(",", ":"), sort_keys=True), encoding="utf-8")


def count_measured(genes, own_only=False):
    """Genes with a measured knockout result of their own or of their mouse ortholog (v, m), or a cell-line screen (c),
    as opposed to genes that only have constraint or expression data. `own_only`: not counting the mouse-ortholog hints
    (for the organisms that have measurements of their own)."""
    keys = ("v", "c") if own_only else ("v", "m", "c")
    return sum(1 for record in genes.values() if any(key in record for key in keys))


def drop_empty_organisms(organism_files, index_organisms, out=None):
    """Leave out an organism for which the sources hold no gene at all (the Alliance lists no Xenopus laevis
    orthologs), so the site says "no measured data for this organism" instead of showing an empty layer.
    A file left in `out` by an earlier build is removed too."""
    for taxid in [taxid for taxid, data in organism_files.items() if not data["genes"]]:
        print(f"  NOTE: no genes found for {index_organisms[taxid]['name']} ({taxid}); it gets no data file", flush=True)
        del organism_files[taxid], index_organisms[taxid]
        if out is not None:
            (Path(out) / f"{taxid}.json").unlink(missing_ok=True)


MODEL_ORGANISM_FILES = {
    "7955": ["zfin_stages.txt", "zfin_features.txt", "zfin_fish_components.txt", "zfin_pubmed.txt", "zfin_phenotype.txt"],
    "7227": ["flybase_alleles.tsv.gz", "flybase_references.tsv.gz", "flybase_genotype_phenotype.tsv.gz"],
    "6239": ["wormbase_phenotype_ontology.obo.gz", "alliance_phenotype_wb.json.gz", "wormbase_phenotype_association.wb.gz"],
}


def build_model_organisms(files, taxids):
    """{taxid: (direct records {SYMBOL: record}, aliases)} for zebrafish, fly and worm from their own databases.
    An organism whose source files could not be downloaded is left out (it keeps the mouse-ortholog hint)."""
    result = {}
    for taxid in list(taxids):
        if any(name not in files for name in MODEL_ORGANISM_FILES[taxid]):
            print(f"  WARNING: the files for {DISTANT[taxid]} are missing; no measurements of its own in this build", flush=True)
            taxids = [t for t in taxids if t != taxid]
    if "7955" in taxids:
        print("Zebrafish: reading ZFIN", flush=True)
        with open_text(files["zfin_stages.txt"]) as handle:
            stages = parse_zfin_stages(handle)
        with open_text(files["zfin_features.txt"]) as handle:
            features = parse_zfin_features(handle)
        with open_text(files["zfin_fish_components.txt"]) as handle:
            fish = parse_zfin_fish(handle, features)
        with open_text(files["zfin_pubmed.txt"]) as handle:
            pubmed = {f[0]: f[1] for f in (line.rstrip("\r\n").split("\t") for line in handle) if len(f) >= 2 and f[1].isdigit()}
        with open_text(files["zfin_phenotype.txt"]) as handle:
            result["7955"] = (build_zebrafish(handle, fish, stages, pubmed), {})
        print(f"  {len(fish)} clean homozygous fish lines -> {len(result['7955'][0])} genes with a call")
    if "7227" in taxids:
        print("Fly: reading FlyBase", flush=True)
        with open_text(files["flybase_alleles.tsv.gz"]) as handle:
            alleles = parse_fly_alleles(handle)
        with open_text(files["flybase_references.tsv.gz"]) as handle:
            pubmed = parse_fly_references(handle)
        with open_text(files["flybase_genotype_phenotype.tsv.gz"]) as handle:
            result["7227"] = (build_fly(handle, alleles, pubmed), {})
        print(f"  {len(alleles)} usable alleles -> {len(result['7227'][0])} genes with a call")
    if "6239" in taxids:
        print("Worm: reading WormBase", flush=True)
        with open_text(files["wormbase_phenotype_ontology.obo.gz"]) as handle:
            ontology = MPOntology(handle)
        with gzip.open(files["alliance_phenotype_wb.json.gz"], "rt", encoding="utf-8") as handle:
            papers = parse_worm_papers(json.load(handle))
        with open_text(files["wormbase_phenotype_association.wb.gz"]) as handle:
            result["6239"] = build_worm(handle, ontology, papers)
        print(f"  {len(result['6239'][0])} genes with a call")
    return result


def build_all(out, cache, refresh=False, depmap_path=DEPMAP_SUMMARY, organisms=("mouse", "human", "rat", "yeast", "distant"),
              paralogs=True):
    out, downloader = Path(out), Downloader(cache, refresh)
    out.mkdir(parents=True, exist_ok=True)
    print("Downloading the sources", flush=True)
    files = {}
    build_warnings = []             # what could not be read in this build; written to index.json so the site's builds are auditable
    for source in SOURCES.values():
        for name, url in source["files"].items():
            try:
                files[name] = downloader.fetch(name, url)
            except requests.RequestException as error:
                if not source.get("optional"):
                    raise
                # a community database that cannot be reached (or answers a script with a bot check) must not stop the
                # whole build: its organism then keeps the mouse-ortholog hint
                print(f"  WARNING: {name} could not be downloaded ({error}); {source['name']} is left out of this build", flush=True)
                build_warnings.append(f"{name} could not be downloaded ({type(error).__name__}: {str(error)[:200]}); {source['name']} is left out")
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
            build_warnings.append(f"the paralogs could not be downloaded ({type(error).__name__}: {str(error)[:200]})")
            paralog_files.clear()
    mouse_paralogs = {}
    if paralog_files:
        mouse_genes = {p["a_sym"].upper() for p in pairs if p["a_tax"] == "10090"} | \
                      {p["b_sym"].upper() for p in pairs if p["b_tax"] == "10090"} | set(mouse_records)
        with open_text(paralog_files["mouse"]) as handle:
            mouse_paralogs = parse_paralogs(handle, allowed_genes=mouse_genes, allowed_paralogs=mouse_genes)
        for gene, found in mouse_paralogs.items():
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
        human_aliases = aliases
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
        own = build_model_organisms(files, MODEL_ORGANISMS) if "distant" in organisms else {}
        for taxid, name in DISTANT.items():
            genes, aliases = build_inferred(pairs, taxid, mouse_records, by_id), {}
            layers = ["ortholog-knockout"]
            if taxid in own:
                for symbol, record in own[taxid][0].items():
                    genes.setdefault(symbol, {}).update(record)       # a measurement of its own beside the mouse hint
                aliases = own[taxid][1]
                layers = ["knockout", "ortholog-knockout"]
            organism_files[taxid] = {"genes": genes, "aliases": aliases}
            index_organisms[taxid] = {"name": name, "layers": layers, "distant": True}
    if "yeast" in organisms:
        with open_text(files["sgd_phenotype.tab"]) as handle:
            organism_files["559292"] = {"genes": build_yeast(handle), "aliases": {}}
        index_organisms["559292"] = {"name": "Saccharomyces cerevisiae S288C", "layers": ["knockout"]}

    if "mouse" in organisms and "human" in organisms:
        model = add_lethality_estimates(human, human_aliases, mouse_records, mouse_paralogs, pairs)
        if model:
            index["lethality_model"] = {
                "features": LETHALITY_FEATURES, "likely": LETHAL_LIKELY, "possible": LETHAL_POSSIBLE,
                "auc": round(model["tested"]["auc"], 2), "tested": model["tested"],
                "weights": [round(w, 4) for w in model["weights"]],
            }
            for taxid in ("10090", "9606"):
                index_organisms[taxid]["layers"].append("lethality-estimate")

    taxa = set(organism_files)
    orthologs = ids = None
    if taxa:
        print("Conservation: reading the orthologs of the model species", flush=True)
        orthologs, ids = read_conservation(open_text(files["alliance_orthology.tsv.gz"]), taxa | set(CONSERVATION_SPECIES))
    literature = {}
    counts = collections.Counter()
    if "ncbi_gene2pubmed.gz" in files:
        print("Literature: counting the PubMed articles of each gene", flush=True)
        counts = read_gene2pubmed(open_text(files["ncbi_gene2pubmed.gz"]), taxa)
    for taxid in taxa:
        name = f"ncbi_gene_info_{taxid}.gz"
        if name in files:
            with open_text(files[name]) as handle:
                symbols, synonyms = read_gene_info(handle)
            literature[taxid] = (symbols, counts, synonyms)
    add_gene_facts(organism_files, orthologs, ids, literature)
    print(f"  conservation for {sum(1 for d in organism_files.values() for r in d['genes'].values() if 'cv' in r):,} genes, "
          f"literature counts for {sum(1 for d in organism_files.values() for r in d['genes'].values() if 'lc' in r):,} genes")

    drop_empty_organisms(organism_files, index_organisms, out)
    for taxid, data in organism_files.items():
        index_organisms[taxid]["genes"] = len(data["genes"])
        index_organisms[taxid]["measured"] = count_measured(data["genes"], own_only="knockout" in index_organisms[taxid]["layers"]
                                                            and taxid in MODEL_ORGANISMS)
        index_organisms[taxid]["file"] = f"{taxid}.json"
        write_json(out / f"{taxid}.json", data)
    index["sources"] = [
        {"id": key, "name": s["name"], "url": s["url"], "what": s["what"], "license": s.get("license", "")}
        for key, s in SOURCES.items() if not s["files"] or all(name in files for name in s["files"])]
    if build_warnings:
        index["build_warnings"] = build_warnings
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
