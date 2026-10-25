#!/usr/bin/env python3
"""
Summarise the DepMap CRISPR knockout screens into one small table (tools/data/depmap_24q4_summary.tsv.gz).

The full gene-dependency matrix is 420 MB, so it is summarised once and the result is kept in the
repository; tools/build_evidence_data.py reads the summary. Per gene it records
  - how many cancer cell lines were screened,
  - the percentage of those lines in which losing the gene is lethal (dependency probability >= 0.5),
  - whether DepMap lists the gene as a common essential / as a non-essential control.

DepMap 24Q4 Public (Broad Institute; CC BY 4.0), mirrored on figshare: https://doi.org/10.6084/m9.figshare.27993248

    python tools/summarize_depmap.py                       # downloads the files and writes the summary
    python tools/summarize_depmap.py --cache some/folder   # keep the downloads there
"""

import argparse
import csv
import gzip
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "data" / "depmap_24q4_summary.tsv.gz"

FILES = {
    "CRISPRGeneDependency.csv": "https://ndownloader.figshare.com/files/51064631",
    "CRISPRInferredCommonEssentials.csv": "https://ndownloader.figshare.com/files/51064916",
    "AchillesNonessentialControls.csv": "https://ndownloader.figshare.com/files/51063566",
}
DEPENDENT = 0.5            # DepMap's own cut-off for "this gene is a dependency in this cell line"
GENE_COLUMN = re.compile(r"^(?P<symbol>.+?) \((?P<entrez>\d+)\)$")


def download(url, path):
    if path.exists() and path.stat().st_size > 0:
        return path
    print(f"Downloading {url}")
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with open(path, "wb") as handle:
            for chunk in response.iter_content(1 << 20):
                handle.write(chunk)
    return path


def read_gene_list(path):
    """Gene names of a one-column DepMap list ("AARS1 (16)") as {entrez: symbol}."""
    genes = {}
    with open(path, encoding="utf-8") as handle:
        next(handle)  # header
        for line in handle:
            match = GENE_COLUMN.match(line.strip().strip('"'))
            if match:
                genes[match["entrez"]] = match["symbol"]
    return genes


def summarize_dependency(path):
    """{entrez: (symbol, lines screened, lines dependent)} from the model x gene probability matrix."""
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        columns = []
        for index, name in enumerate(header[1:], start=1):
            match = GENE_COLUMN.match(name)
            if match:
                columns.append((index, match["symbol"], match["entrez"]))
        screened = [0] * len(header)
        dependent = [0] * len(header)
        for row in reader:
            for index, _, _ in columns:
                value = row[index]
                if value:
                    screened[index] += 1
                    if float(value) >= DEPENDENT:
                        dependent[index] += 1
    return {entrez: (symbol, screened[index], dependent[index]) for index, symbol, entrez in columns}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache", default=str(ROOT / ".cache" / "depmap"), help="Folder for the downloaded files")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    paths = {name: download(url, cache / name) for name, url in FILES.items()}

    common = read_gene_list(paths["CRISPRInferredCommonEssentials.csv"])
    nonessential = read_gene_list(paths["AchillesNonessentialControls.csv"])
    summary = summarize_dependency(paths["CRISPRGeneDependency.csv"])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["symbol", "entrez", "lines_screened", "lines_dependent", "common_essential", "nonessential_control"])
        for entrez, (symbol, screened, dependent) in sorted(summary.items(), key=lambda item: item[1][0]):
            writer.writerow([symbol, entrez, screened, dependent, int(entrez in common), int(entrez in nonessential)])
    print(f"Wrote {len(summary)} genes to {out} "
          f"({len(common)} common essentials, {len(nonessential)} non-essential controls)")


if __name__ == "__main__":
    sys.exit(main())
