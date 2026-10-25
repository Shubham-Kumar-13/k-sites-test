"""
The measured knockout evidence as report columns, and the lists of genes left out of a report.

The same columns are written to the CSV, Excel and HTML reports (webapp/static/js/engine/report.js writes the same
ones in the browser).
"""

from typing import Any, Dict, List, Optional

EVIDENCE_HEADERS = [
    "Evidence_Basis", "Knockout_Context", "Organism_Knockout", "Organism_Knockout_Stage", "Organism_Knockout_Lines",
    "Organism_Knockout_Basis", "Organism_Knockout_Sources", "Organism_Phenotype_Systems", "Cell_Essentiality",
    "Cell_Lines_Dependent_Percent", "LOEUF", "Expression_Tau", "Expression_Pattern", "Close_Paralogs",
    "Knockout_References", "Knockout_Evidence",
]

EXCLUDED_HEADERS = ["Gene_Symbol", "Gene_Description", "Reason", "Detail", "Pleiotropy_Score", "Composite_Score",
                    "Organism_Knockout", "Organism_Knockout_Stage", "Cell_Essentiality", "Knockout_Evidence"]

BASIS_LABELS = {
    "measured": "Measured", "ortholog": "Measured in the mouse ortholog", "distant": "Mouse ortholog only (distant relative)",
    "predicted": "Predicted from the literature", "none": "Not verified",
}


def source_names(evidence: Optional[Dict[str, Any]]) -> List[str]:
    return [s["name"] for s in (evidence or {}).get("sources", [])]


def _basis(evidence: Dict[str, Any]) -> str:
    organism = evidence["organism"]
    if organism["basis"] == "direct":
        return "direct"
    if organism["basis"] == "ortholog":
        return f"ortholog {organism['ortholog']['symbol']} ({organism['ortholog']['relation']})"
    return ""


def evidence_summary(evidence: Optional[Dict[str, Any]]) -> str:
    """One line with everything measured: the organism result, then the cell-line result."""
    if not evidence:
        return ""
    parts = []
    if evidence["organism"]["call"] != "UNKNOWN":
        parts.append(evidence["organism"]["text"])
    if evidence["cells"]["call"] != "UNKNOWN":
        parts.append(evidence["cells"]["text"])
    return " | ".join(parts)


def evidence_cells(gene: Dict[str, Any]) -> List[Any]:
    """The values for EVIDENCE_HEADERS of one gene (empty cells where nothing was measured)."""
    safety = gene.get("safety_recommendation") or {}
    evidence = gene.get("knockout_evidence")
    values = {header: "" for header in EVIDENCE_HEADERS}
    values["Evidence_Basis"] = safety.get("evidence_basis", "")
    if evidence:
        organism, cells = evidence["organism"], evidence["cells"]
        known = organism["call"] != "UNKNOWN"
        counts = organism["counts"]
        constraint, expression, paralogs = evidence.get("constraint"), evidence.get("expression"), evidence.get("paralogs")
        values["Knockout_Context"] = evidence["context"]
        if known:
            values["Organism_Knockout"] = organism["call"]
            if organism["stage"] != "U" and organism["stage_text"]:
                values["Organism_Knockout_Stage"] = organism["stage_text"]
            values["Organism_Knockout_Lines"] = f"{counts['lethal']} lethal, {counts['subviable']} subviable, {counts['viable']} viable"
            values["Organism_Knockout_Basis"] = _basis(evidence)
            values["Organism_Knockout_Sources"] = "; ".join(s["name"] for s in evidence["sources"] if s["id"] in organism["sources"])
            values["Organism_Phenotype_Systems"] = "; ".join(organism["systems"])
            values["Knockout_References"] = "; ".join(f"PMID:{p}" for p in organism["references"])
        if cells["call"] != "UNKNOWN":
            values["Cell_Essentiality"] = cells["call"]
            values["Cell_Lines_Dependent_Percent"] = cells["percent"]
        if constraint:
            values["LOEUF"] = constraint["loeuf"]
        if expression:
            if expression["tau"] is not None:
                values["Expression_Tau"] = expression["tau"]
            values["Expression_Pattern"] = expression["label"]
        if paralogs:
            values["Close_Paralogs"] = "; ".join(f"{g['symbol']} ({g['identity']}%)" for g in paralogs["genes"])
        values["Knockout_Evidence"] = evidence_summary(evidence)
    return [values[header] for header in EVIDENCE_HEADERS]


def excluded_cells(entry: Dict[str, Any]) -> List[Any]:
    """The values for EXCLUDED_HEADERS of one gene that is not shown in the report."""
    evidence = entry.get("knockout_evidence")
    organism = (evidence or {}).get("organism") or {}
    cells = (evidence or {}).get("cells") or {}
    known = organism.get("call", "UNKNOWN") != "UNKNOWN"
    return [
        entry.get("symbol", ""), entry.get("description", ""), entry.get("reason", ""), entry.get("detail", ""),
        entry.get("pleiotropy_score", ""), entry.get("composite_score", ""),
        organism["call"] if known else "",
        organism["stage_text"] if known and organism.get("stage") not in (None, "U") and organism.get("stage_text") else "",
        cells["call"] if cells.get("call", "UNKNOWN") != "UNKNOWN" else "",
        evidence_summary(evidence),
    ]
