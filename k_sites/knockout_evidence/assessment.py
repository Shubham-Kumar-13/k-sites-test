"""
What is known, from measurements, about losing one gene.

``assess_gene`` looks a gene up in the evidence files and returns a plain dictionary (safe to store as JSON) with up to
four parts:

    organism    the knockout of the whole organism: lethal / subviable / viable, at which stage, in how many lines
                (direct for mouse, yeast, zebrafish, fly and worm; read from the mouse ortholog for human and rat, and
                for the genes of zebrafish, fly and worm that have no measurement of their own)
    cells       how often losing the gene kills a human cancer cell line (DepMap CRISPR screens)
    constraint  how rarely loss-of-function variants are seen in people (gnomAD)
    expression  how many human tissues express the gene, and which most (GTEx)

    paralogs    the closest paralogs, which may take over the gene's work and hide the effect of a knockout (Ensembl)
    conservation  in how many of the five model species (human, mouse, rat, fly, worm) the gene or an ortholog exists
                (Alliance of Genome Resources orthologs)
    literature  how many PubMed articles NCBI Gene links to the gene
    estimate    only for a gene without a knockout result: the chance that its knockout is lethal in mice, estimated from
                the measurements of its human ortholog (a model tested on genes whose outcome is known). It is labelled
                as an estimate and never counts as a measurement.

Every part carries ``call`` / ``text`` and the sources behind it. Nothing is made up: a gene without a record gets
``UNKNOWN`` and the safety verdict says so.
"""

import math
from typing import Any, Dict, List, Optional

from .provider import EvidenceProvider

# Cut-offs on the percentage of human cancer cell lines in which losing the gene is lethal (DepMap dependency >= 0.5)
CELL_ESSENTIAL_PERCENT = 50
CELL_SELECTIVE_PERCENT = 10
# Cut-offs on LOEUF (upper bound of observed/expected loss-of-function variants): lower = less tolerated
LOEUF_HIGHLY_CONSTRAINED = 0.35
LOEUF_CONSTRAINED = 0.6
# Cut-offs on the tissue-specificity index tau of GTEx median expression
TAU_RESTRICTED = 0.8
TAU_ENRICHED = 0.5
# A paralog this similar (percent identity) is close enough to take over the gene's work
CLOSE_PARALOG_IDENTITY = 40

SPECIES_NOUN = {"10090": "mice", "10116": "rats", "9606": "humans", "559292": "yeast", "7955": "zebrafish", "7227": "flies",
                "6239": "worms"}
SOURCE_OF_LETTER = {"M": "mgi", "I": "impc", "S": "sgd", "Z": "zfin", "F": "flybase", "W": "wormbase"}
# what the counts of knockout lines are counts of, (one, many)
LINE_NOUN = {"7955": ("mutant line", "mutant lines"), "7227": ("allele", "alleles"), "6239": ("allele or RNAi test", "alleles or RNAi tests")}
CALL_OF_LETTER = {"L": "LETHAL", "S": "SUBVIABLE", "V": "VIABLE"}
# the model species of the conservation score, in the order of the bits in a record's "cv" number
CONSERVATION_SPECIES = ["human", "mouse", "rat", "fly", "worm"]
# the bands of the lethality estimate (the cut-offs are in index.json, written by the data builder)
ESTIMATE_LIKELY, ESTIMATE_POSSIBLE = 0.5, 0.3
ESTIMATE_LABELS = {"likely": "likely lethal", "possible": "possibly lethal", "unlikely": "unlikely to be lethal"}


def resolve_context(taxid, context: str = "auto") -> str:
    """'cells' (cultured cells) or 'organism' (whole animal / plant / yeast). 'auto': cells for human, organism otherwise."""
    if context in ("cells", "organism"):
        return context
    return "cells" if str(taxid) == "9606" else "organism"


def _lines(count: int, total: int, taxid: str = "") -> str:
    one, many = LINE_NOUN.get(taxid, ("knockout line", "knockout lines"))
    return f"{count} of {total} {one if total == 1 else many}"


def _organism_part(index: dict, taxid: str, record: Optional[dict]) -> Dict[str, Any]:
    part: Dict[str, Any] = {
        "call": "UNKNOWN", "basis": "none", "distant": False, "stage": None, "stage_text": None,
        "counts": {"lethal": 0, "subviable": 0, "viable": 0}, "mixed": False, "sources": [], "species": None,
        "ortholog": None, "mgi_id": None, "references": [], "systems": [], "reduced_lifespan": False,
        "infertile": False, "rnai_only": False, "human_essential_percent": None,
        "text": "No measured knockout data for this gene",
    }
    if not record:
        return part
    if "v" in record:
        base, basis = record, "direct"
        part["species"] = index.get("organisms", {}).get(taxid, {}).get("name")
        species_key = taxid
    elif "m" in record:
        base, basis = record["m"], "ortholog"
        part["ortholog"] = {"symbol": record["o"][0], "relation": record["o"][1]}
        part["distant"] = bool(index.get("organisms", {}).get(taxid, {}).get("distant"))
        part["species"], species_key = "Mus musculus", "10090"
    else:
        return part

    lethal, subviable, viable = base["n"]
    part["counts"] = {"lethal": lethal, "subviable": subviable, "viable": viable}
    part["call"] = CALL_OF_LETTER[base["v"]]
    part["basis"] = basis
    part["mixed"] = bool(base.get("x"))
    part["stage"] = base.get("s")
    part["stage_text"] = index.get("stages", {}).get(part["stage"]) if part["stage"] else None
    letters = base.get("src", "")
    part["sources"] = [SOURCE_OF_LETTER[c] for c in letters if c in SOURCE_OF_LETTER]
    if basis == "ortholog":
        part["sources"].append("alliance")
    part["mgi_id"] = base.get("id")
    part["references"] = list(base.get("pm", []))
    names = index.get("systems", [])
    part["systems"] = [names[i] for i in base.get("sys", []) if i < len(names)]
    part["reduced_lifespan"] = bool(base.get("r"))
    part["infertile"] = bool(base.get("f"))
    part["rnai_only"] = bool(base.get("k"))
    part["human_essential_percent"] = base.get("hc")

    noun = SPECIES_NOUN.get(species_key, "the model organism")
    if basis == "direct":
        where = noun
    elif part["distant"]:
        where = f"{noun} (mouse ortholog {part['ortholog']['symbol']}, {part['ortholog']['relation']}; a distant relative, so only an indication)"
    else:
        where = f"{noun} (mouse ortholog {part['ortholog']['symbol']}, {part['ortholog']['relation']})"
    stage = f" ({part['stage_text']})" if part["stage"] and part["stage"] != "U" else ""
    counts = part["counts"]
    total = lethal + subviable + viable
    if species_key == "559292":
        subject, lethal_word, viable_word = "Deletion", "inviable", "viable"
    else:
        subject, lethal_word, viable_word = "Knockout", "lethal", "viable"
    lines_taxid = taxid if basis == "direct" else ""
    if part["call"] == "LETHAL":
        text = f"{subject} is {lethal_word}{stage} in {where}: {_lines(lethal, total, lines_taxid)}"
    elif part["call"] == "SUBVIABLE":
        detail = "; ".join(x for x in (part["stage_text"] if part["stage"] != "U" else None,
                                       "fewer homozygotes than expected") if x)
        text = f"{subject} is subviable ({detail}) in {where}: {_lines(subviable, total, lines_taxid)}"
    else:
        text = f"{subject} is {viable_word} in {where}: {_lines(viable, total, lines_taxid)}"
    if part["rnai_only"] and part["call"] == "LETHAL":
        text += "; every lethal result comes from RNAi knockdown, none from a mutant"
    if part["mixed"]:
        others = [f"{n} {word}" for n, word, call in ((lethal, "lethal", "LETHAL"), (subviable, "subviable", "SUBVIABLE"),
                                                       (viable, "viable", "VIABLE")) if n and call != part["call"]]
        text += f"; {', '.join(others)} in other lines (strain or allele dependent)"
    part["text"] = text
    return part


def _cells_part(record: Optional[dict]) -> Dict[str, Any]:
    part: Dict[str, Any] = {"call": "UNKNOWN", "percent": None, "lines": None, "common_essential": False,
                            "source": "depmap", "text": "No human cell-line screen data for this gene"}
    if not record or "c" not in record:
        return part
    flag, percent, lines = record["c"]
    part["percent"], part["lines"] = percent, lines
    part["common_essential"] = flag == "C"
    if percent is None:
        return part
    if flag == "C" or percent >= CELL_ESSENTIAL_PERCENT:
        part["call"] = "ESSENTIAL"
        suffix = "; DepMap common essential" if flag == "C" else ""
        part["text"] = f"Essential in {percent:g}% of {lines:,} human cancer cell lines{suffix}"
    elif flag == "N" or percent < CELL_SELECTIVE_PERCENT:
        part["call"] = "NON_ESSENTIAL"
        part["text"] = f"Rarely essential: needed in {percent:g}% of {lines:,} human cancer cell lines"
    else:
        part["call"] = "SELECTIVE"
        part["text"] = f"Essential in {percent:g}% of {lines:,} human cancer cell lines; check that your cell type is not one of them"
    return part


def _conservation_part(record: Optional[dict]) -> Optional[Dict[str, Any]]:
    """In how many of the model species the gene (or an ortholog) exists, or None when the gene is not in the orthology table."""
    if not record or "cv" not in record:
        return None
    found = [name for i, name in enumerate(CONSERVATION_SPECIES) if record["cv"] >> i & 1]
    return {"score": len(found) / len(CONSERVATION_SPECIES), "found_in": found,
            "text": f"Present in {len(found)} of {len(CONSERVATION_SPECIES)} model species ({', '.join(found)})"}


def _literature_part(record: Optional[dict]) -> Optional[Dict[str, Any]]:
    """The number of PubMed articles that NCBI Gene links to the gene, or None when it is not known."""
    if not record or "lc" not in record:
        return None
    return {"count": record["lc"]}


def _percent(fraction: float) -> int:
    return int(math.floor(fraction * 100 + 0.5))


def _estimate_part(index: dict, taxid: str, record: Optional[dict], organism: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The lethality estimate of a gene that has no knockout result (see the module notes), or None."""
    if not record or "pl" not in record or organism["call"] != "UNKNOWN":
        return None
    probability, other = record["pl"]
    model = index.get("lethality_model") or {}
    likely, possible = model.get("likely", ESTIMATE_LIKELY), model.get("possible", ESTIMATE_POSSIBLE)
    band = "likely" if probability >= likely else "possible" if probability >= possible else "unlikely"
    percent = max(1, min(99, _percent(probability)))      # an estimate is never shown as certain
    from_human = taxid != "9606"
    if from_human:
        source = f"the cell-line, population and expression data of its human ortholog {other}"
    else:
        source = f"its own cell-line, population and expression data (its mouse ortholog {other} has no knockout result)"
    text = (f"No measured knockout result. Estimated {percent}% chance that a knockout is lethal in mice "
            f"({ESTIMATE_LABELS[band]}), from {source}.")
    share = ((model.get("tested") or {}).get("bands") or {}).get(band, {}).get("lethal_share")
    if share is not None and model.get("auc") is not None:
        text += f" Among tested mouse genes with such an estimate {_percent(share)}% were lethal (AUC {model['auc']:g})."
    text += " This is an estimate, not a measurement."
    return {"probability": probability, "percent": percent, "band": band, "label": ESTIMATE_LABELS[band],
            "other_symbol": other, "from_human_ortholog": from_human, "text": text}


def _constraint_part(record: Optional[dict]) -> Optional[Dict[str, Any]]:
    if not record or "l" not in record:
        return None
    loeuf = record["l"]
    label = ("highly constrained" if loeuf < LOEUF_HIGHLY_CONSTRAINED
             else "constrained" if loeuf < LOEUF_CONSTRAINED else "not constrained")
    return {"loeuf": loeuf, "label": label,
            "text": f"Loss-of-function variants are {'rare' if loeuf < LOEUF_CONSTRAINED else 'tolerated'} in people "
                    f"(gnomAD LOEUF {loeuf:g}, {label})"}


def _expression_part(index: dict, record: Optional[dict]) -> Optional[Dict[str, Any]]:
    if not record or "t" not in record:
        return None
    tau, expressed, top = record["t"]
    tissues = index.get("tissues", [])
    names = [tissues[i] for i in top if i < len(tissues)]
    if tau is None:
        return {"tau": None, "label": "barely expressed", "tissues_expressed": expressed, "top_tissues": [],
                "text": "Barely expressed (under 1 TPM in every GTEx tissue)"}
    label = "tissue-specific" if tau >= TAU_RESTRICTED else "tissue-enriched" if tau >= TAU_ENRICHED else "broadly expressed"
    where = f"; highest in {', '.join(names)}" if names else ""
    return {"tau": tau, "label": label, "tissues_expressed": expressed, "top_tissues": names,
            "text": f"{label.capitalize()}: expressed in {expressed} of {len(tissues) or 54} tissues (tau {tau:.2f}){where}"}


def _paralogs_part(record: Optional[dict]) -> Optional[Dict[str, Any]]:
    if not record or not record.get("p"):
        return None
    genes = [{"symbol": symbol, "identity": identity} for symbol, identity in record["p"]]
    close = [g["symbol"] for g in genes if g["identity"] >= CLOSE_PARALOG_IDENTITY]
    listing = ", ".join(f"{g['symbol']} ({g['identity']}% identical)" for g in genes)
    return {"genes": genes, "close": close, "text": f"Closest paralogs: {listing}"}


def _sources_used(index: dict, organism: dict, cells: dict, constraint, expression, paralogs=None, estimate=None) -> List[dict]:
    wanted = list(organism["sources"])
    if estimate:
        wanted += ["mgi", "impc", "depmap", "gnomad", "gtex"]
    if cells["call"] != "UNKNOWN":
        wanted.append("depmap")
    if constraint:
        wanted.append("gnomad")
    if expression:
        wanted.append("gtex")
    if paralogs:
        wanted.append("ensembl")
    by_id = {s["id"]: s for s in index.get("sources", [])}
    return [{"id": w, "name": by_id[w]["name"], "url": by_id[w]["url"]} for w in dict.fromkeys(wanted) if w in by_id]


def assess_gene(provider: Optional[EvidenceProvider], taxid, symbol: str, context: str = "auto") -> Dict[str, Any]:
    """Everything measured about losing ``symbol`` in the organism ``taxid`` (see the module notes)."""
    taxid = str(taxid)
    resolved = resolve_context(taxid, context)
    result: Dict[str, Any] = {
        "symbol": symbol, "taxid": taxid, "context": resolved, "covered": False, "found": False,
        "organism": _organism_part({}, taxid, None), "cells": _cells_part(None), "constraint": None,
        "expression": None, "paralogs": None, "estimate": None, "conservation": None, "literature": None,
        "has_measured": False, "sources": [], "data_version": None,
    }
    if provider is None:
        return result
    index = provider.index
    result["data_version"] = index.get("built")
    organism = provider.organism(taxid)
    if organism is None:
        return result
    result["covered"] = True
    record = organism.lookup(symbol)
    if record is None:
        return result
    result["found"] = True
    result["organism"] = _organism_part(index, organism.taxid, record)
    result["cells"] = _cells_part(record)
    result["constraint"] = _constraint_part(record)
    result["expression"] = _expression_part(index, record)
    if result["expression"] and organism.taxid != "9606":
        result["expression"]["text"] += " (in the human ortholog)"
    result["paralogs"] = _paralogs_part(record)
    result["estimate"] = _estimate_part(index, organism.taxid, record, result["organism"])
    result["conservation"] = _conservation_part(record)
    result["literature"] = _literature_part(record)
    # a distant relative's mouse ortholog is a hint, not a measurement
    result["has_measured"] = ((result["organism"]["call"] != "UNKNOWN" and not result["organism"]["distant"])
                              or result["cells"]["call"] != "UNKNOWN")
    result["sources"] = _sources_used(index, result["organism"], result["cells"], result["constraint"], result["expression"],
                                      result["paralogs"], result["estimate"])
    return result
