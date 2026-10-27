"""
A short known-answer test for a fresh copy of K-Sites: the verdicts of 16 well-known genes, built from the local evidence data.

    python tools/smoke_test.py [--data .cache/evidence-out]

It prints one line per gene (OK or DIFFERENT). The answers were recorded on 2026-10-27 from the data built that day. A different
answer after a rebuild can mean the databases changed (MGI and IMPC are updated regularly), so one or two DIFFERENT lines after a
fresh build are worth a look, not an alarm; many of them mean the copy is broken.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from k_sites.knockout_evidence import EvidenceProvider, assess_gene          # noqa: E402
from k_sites.knockout_evidence.provider import DirectorySource              # noqa: E402
from k_sites.workflow.safety_recommender import get_safety_recommendation   # noqa: E402

# (taxid, gene, context, expected level, what it shows)
CASES = [
    ("9606", "PSMA1", "cells", "AVOID", "proteasome subunit, essential in every cell line"),
    ("9606", "RPL11", "cells", "AVOID", "ribosomal protein, essential in every cell line"),
    ("9606", "GAPDH", "cells", "AVOID", "glycolysis, essential in cell lines"),
    ("9606", "TP53", "cells", "SAFE", "not needed by cells, knockout mice are viable"),
    ("9606", "KRT5", "cells", "SAFE", "skin keratin, not needed by cultured cells"),
    ("9606", "MDM2", "cells", "MODERATE_CONCERN", "essential in only some cell lines (about 40%)"),
    ("9606", "PNKP", "cells", "MODERATE_CONCERN", "essential in only some cell lines (about 41%)"),
    ("9606", "OR7A10", "cells", "MODERATE_CONCERN", "olfactory receptor: DepMap says essential, but it is probably a copy-number artefact"),
    ("10090", "RPL12", "organism", "AVOID", "ribosomal protein, knockout mice die as embryos"),
    ("10090", "ATR", "organism", "AVOID", "checkpoint kinase, embryonic lethal"),
    ("10090", "KRT5", "organism", "AVOID", "skin keratin, newborn mice die"),
    ("10090", "RPL32", "organism", "CAUTION", "IMPC says viable but human cells need it, so it is not called safe"),
    ("10090", "CDK2", "organism", "CAUTION", "viable in mice but essential in many human cell lines"),
    ("10090", "RPL19", "organism", "HIGH_CONCERN", "no mouse result: an estimate of lethality from the human gene"),
    ("559292", "RPL3", "organism", "AVOID", "yeast ribosomal protein, the deletion is inviable"),
    ("559292", "ACT1", "organism", "AVOID", "yeast actin, the deletion is inviable"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=str(ROOT / ".cache" / "evidence-out"), help="Folder with the built evidence files")
    args = parser.parse_args()
    if not (Path(args.data) / "index.json").exists():
        print(f"No evidence data in {args.data}. Build it first (see DEPLOYMENT.md, 'Building it yourself').")
        return 2
    provider = EvidenceProvider(DirectorySource(args.data))
    different = 0
    for taxid, symbol, context, expected, note in CASES:
        evidence = assess_gene(provider, taxid, symbol, context)
        got = get_safety_recommendation(symbol, 2.0, knockout_evidence=evidence).safety_level.value
        mark = "OK       " if got == expected else "DIFFERENT"
        different += got != expected
        print(f"{mark} {symbol:7} taxid {taxid:7} {context:8} expected {expected:17} got {got:17} {note}")
    print(f"\n{len(CASES) - different} of {len(CASES)} as recorded.")
    return 0 if different <= 2 else 1


if __name__ == "__main__":
    sys.exit(main())
