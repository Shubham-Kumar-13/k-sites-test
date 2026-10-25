#!/usr/bin/env python3
"""
Shrink tests/fixtures/js_parity/rag_recording.json.gz.

The recorded PubMed answers are full records; the phenotype prediction only reads the PMID, title,
abstract, authors, journal, year, keywords and article ids. Everything else (MeSH terms, references,
grants, chemicals, ...) is removed, so the file is small enough to keep in the repository.
"""

import gzip
import json
import xml.etree.ElementTree as ET
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "js_parity" / "rag_recording.json.gz"
DROP = {
    "MeshHeadingList", "ReferenceList", "CommentsCorrectionsList", "GrantList", "ChemicalList",
    "PublicationTypeList", "DataBankList", "SupplMeshList", "GeneSymbolList", "History",
    "ELocationID", "Affiliation", "AffiliationInfo", "Language", "ArticleDate", "PubMedPubDate",
}


def trim_record(text):
    root = ET.fromstring(text)
    for parent in root.iter():
        for child in list(parent):
            if child.tag in DROP:
                parent.remove(child)
    return ET.tostring(root, encoding="unicode")


def main():
    with gzip.open(PATH, "rt", encoding="utf-8") as handle:
        recording = json.load(handle)
    before = sum(len(v["text"]) for v in recording.values())
    for key, entry in recording.items():
        if "efetch" in key and entry["status"] == 200 and entry["text"].lstrip().startswith("<"):
            entry["text"] = trim_record(entry["text"])
    after = sum(len(v["text"]) for v in recording.values())
    with gzip.open(PATH, "wt", encoding="utf-8", compresslevel=9) as handle:
        json.dump(recording, handle, separators=(",", ":"))
    print(f"{before / 1e6:.1f} MB -> {after / 1e6:.1f} MB of text; file is now {PATH.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
