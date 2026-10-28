#!/usr/bin/env python3
"""
Build a kegg_code -> NCBI taxid mapping for the browser-mode organism picker.

KEGG's own organism list endpoint no longer reliably returns taxonomy ids, so this script
uses the NCBI Taxonomy dump (names.dmp) to look up the scientific names found in KEGG's
br08601 organism hierarchy.

The output is committed to the repo as tools/data/kegg_code_to_taxid.json so the regular
build_kegg_data.py run does not need to download the large taxonomy dump.

    python tools/build_kegg_taxid_mapping.py --taxdump taxdump.tar.gz --out tools/data/kegg_code_to_taxid.json

The taxonomy dump can be downloaded from:
    https://ftp.ncbi.nlm.nih.gov/pub/taxology/taxdump.tar.gz
"""

import argparse
import gzip
import json
import re
import sys
import tarfile
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Add parent directory so we can import the hardcoded ORGANISMS mapping
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_kegg_data import ORGANISMS

BRITE = "https://www.genome.jp/kegg-bin/download_htext?htext=br08601.keg&format=htext"

# Manual fixes for KEGG organisms whose names differ from the current NCBI Taxonomy entry.
# These are typically species that have been reclassified since KEGG created the code.
MANUAL_TAXID_OVERRIDES = {
    "baf": "29518",    # Borrelia afzelii -> Borreliella afzelii
    "bafz": "29518",   # Borrelia afzelii -> Borreliella afzelii
    "req": "43767",    # Rhodococcus equi -> Prescottella equi
    "pck": "1235990",  # Candidatus Pantoea carbekii US
    "fil": "1608628",  # Candidatus Filomicrobium marinum W
    "fiy": "1608628",  # Candidatus Filomicrobium marinum Y
    "laa": "34021",    # Candidatus Liberibacter asiaticus gxpsy
    "lat": "34021",    # Candidatus Liberibacter asiaticus Ishi-1
    "ncf": "1178",     # Nostoc cf. commune -> Nostoc commune
}


def session():
    s = requests.Session()
    retry = Retry(total=4, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers["User-Agent"] = "K-Sites data builder (https://github.com/Shubham-Kumar-13/k-sites-test)"
    return s


def parse_kegg_codes(htext: str) -> dict:
    """Parse br08601.keg into {kegg_code: scientific_name}."""
    codes = {}
    levels = {}
    for line in htext.splitlines():
        if not line or line[0] not in "ABCDE" or line.startswith("+"):
            continue
        letter, content = line[0], line[1:].strip()
        if not content:
            continue
        if letter != "E":
            level = "ABCDE".index(letter)
            levels[level] = re.sub(r"\s*\(\d+\)\s*$", "", content)
            for deeper in [k for k in levels if k > level]:
                del levels[deeper]
            continue
        match = re.match(r"^(\S+)\s+(.+)$", content)
        if not match:
            continue
        code, label = match.groups()
        # scientific name is before the parenthesized common name
        name = label.split("(")[0].strip()
        codes[code] = name
    return codes


def build_name_to_taxid(taxdump_path: Path) -> tuple:
    """Read names.dmp from the NCBI taxdump and return ({scientific_name_lower: taxid}, {synonym_lower: taxid})."""
    scientific = {}
    synonyms = {}
    opened = tarfile.open(taxdump_path, "r:gz")
    names_member = opened.getmember("names.dmp")
    with opened.extractfile(names_member) as handle:
        # names.dmp is not gzipped inside the tar; it is a plain text file
        for line in handle:
            text = line.decode("utf-8", errors="replace").rstrip("\n")
            # Each line ends with "\t|"; strip it before splitting on "\t|\t"
            if text.endswith("\t|"):
                text = text[:-2]
            parts = text.split("\t|\t")
            if len(parts) < 4:
                continue
            taxid = parts[0].strip()
            name = parts[1].strip()
            name_class = parts[3].strip()
            if not taxid or not name:
                continue
            key = name.lower()
            if name_class == "scientific name":
                scientific[key] = taxid
            elif name_class in ("synonym", "equivalent name"):
                # do not overwrite a scientific name with a synonym
                synonyms.setdefault(key, taxid)
    return scientific, synonyms


def _esearch_taxid(http, name: str, field: str = "", quoted: bool = True) -> str:
    """Return the first taxid for a name in NCBI Taxonomy, or ''."""
    if field:
        term = f'"{name}"[{field}]' if quoted else f'{name}[{field}]'
    else:
        term = f'"{name}"' if quoted else name
    response = http.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params={"db": "taxonomy", "term": term, "retmode": "json"},
        timeout=30,
    )
    response.raise_for_status()
    ids = response.json().get("esearchresult", {}).get("idlist", [])
    return ids[0] if ids else ""


def query_ncbi_taxonomy(http, names: list) -> dict:
    """Query NCBI Taxonomy via eutils for names that were not found in names.dmp."""
    found = {}
    for name in names:
        try:
            taxid = (
                _esearch_taxid(http, name, "Scientific Name")
                or _esearch_taxid(http, name, "Scientific Name", quoted=False)
                or _esearch_taxid(http, name, "All Names")
                or _esearch_taxid(http, name, "All Names", quoted=False)
                or _esearch_taxid(http, name, "")
            )
            if taxid:
                found[name] = taxid
        except Exception:
            pass
        time.sleep(0.35)  # stay under NCBI's ~3 requests/second limit for keyless use
    return found


def _lookup_name(name: str, scientific: dict, synonyms: dict) -> str:
    """Look up a single name; prefer scientific names, then synonyms."""
    key = name.lower()
    return scientific.get(key) or synonyms.get(key)


def build_mapping(codes: dict, scientific: dict, synonyms: dict, http) -> dict:
    """Map kegg_code -> taxid using scientific name lookup with strain-level fallbacks."""
    mapping = {}
    missing_names = []
    for code, name in codes.items():
        taxid = _lookup_name(name, scientific, synonyms)
        words = name.split()

        # Fallback 1: manual overrides for renamed/reclassified species
        if not taxid and code in MANUAL_TAXID_OVERRIDES:
            taxid = MANUAL_TAXID_OVERRIDES[code]

        # Fallback 2: hardcoded model-organism mapping (covers strain synonyms)
        if not taxid and code in ORGANISMS:
            taxid = ORGANISMS[code][0]

        # Fallback 3: genus + species for strain names like "Escherichia coli K-12 MG1655"
        if not taxid and len(words) >= 2:
            taxid = _lookup_name(f"{words[0]} {words[1]}", scientific, synonyms)

        # Fallback 4: genus + species + subsp. + subspecies, e.g. "Oryza sativa japonica"
        if not taxid and len(words) >= 3:
            taxid = _lookup_name(f"{words[0]} {words[1]} subsp. {words[2]}", scientific, synonyms)

        if taxid:
            mapping[code] = taxid
        else:
            missing_names.append(name)

    # Fallback 5: ask NCBI Taxonomy directly for the few remaining names
    if missing_names:
        print(f"Querying NCBI Taxonomy for {len(missing_names)} remaining names...")
        ncbi_found = query_ncbi_taxonomy(http, missing_names)
        for code, name in codes.items():
            if code not in mapping and name in ncbi_found:
                mapping[code] = ncbi_found[name]

    return mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--taxdump", required=True, help="Path to taxdump.tar.gz from NCBI")
    parser.add_argument("--out", default="tools/data/kegg_code_to_taxid.json", help="Output JSON file")
    parser.add_argument("--brite", help="Path to a local br08601.keg file (default: download from KEGG)")
    args = parser.parse_args()

    taxdump_path = Path(args.taxdump)
    if not taxdump_path.exists():
        sys.exit(f"Taxdump not found: {taxdump_path}")

    http = session()
    if args.brite:
        htext = Path(args.brite).read_text(encoding="utf-8")
    else:
        response = http.get(BRITE, timeout=120)
        response.raise_for_status()
        htext = response.text

    codes = parse_kegg_codes(htext)
    print(f"Found {len(codes)} organism codes in KEGG hierarchy")

    print("Reading NCBI names.dmp (this may take a minute)...")
    scientific, synonyms = build_name_to_taxid(taxdump_path)
    print(f"Loaded {len(scientific)} scientific names and {len(synonyms)} synonyms from NCBI Taxonomy")

    mapping = build_mapping(codes, scientific, synonyms, http)
    missing = set(codes.keys()) - set(mapping.keys())
    print(f"Mapped {len(mapping)} organisms ({len(missing)} without a taxid)")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(mapping, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
