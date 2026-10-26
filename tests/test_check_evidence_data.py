"""The independent check of tools/check_evidence_data.py: essential genes of DEG against an organism's own lethal calls."""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_evidence_data", ROOT / "tools" / "check_evidence_data.py")
check = importlib.util.module_from_spec(spec)
sys.modules["check_evidence_data"] = check
spec.loader.exec_module(check)


def write(folder, genes):
    (folder / "559292.json").write_text(json.dumps({"genes": genes, "aliases": {}}), encoding="utf-8")
    return {"organisms": {"559292": {"name": "Saccharomyces cerevisiae S288C", "file": "559292.json"}}}


class TestIndependentCheck:
    def test_lethal_calls_are_compared_with_the_essential_genes_and_with_every_gene(self, tmp_path):
        genes = {
            "ACT1": {"v": "L", "n": [1, 0, 0]}, "TFC3": {"v": "L", "n": [1, 0, 0]},
            "RAD52": {"v": "V", "n": [0, 0, 1]}, "AAA1": {"v": "V", "n": [0, 0, 1]},
            "BBB1": {"v": "V", "n": [0, 0, 1]}, "CCC1": {"v": "V", "n": [0, 0, 1]},
        }
        index = write(tmp_path, genes)

        found = check.independent_check(tmp_path, index, {"559292": {"ACT1", "TFC3", "RAD52", "NOTINDATA"}})

        assert found["559292"] == {"source": "DEG", "essential_genes": 3, "essential_called_lethal": 67, "all_called_lethal": 33}

    def test_an_organism_without_a_file_or_a_result_is_left_out(self, tmp_path):
        index = write(tmp_path, {"AAA1": {"v": "V", "n": [0, 0, 1]}})

        assert check.independent_check(tmp_path, index, {"559292": {"ZZZ9"}, "7227": {"N"}}) == {}

    def test_the_deg_sets_of_the_four_organisms_are_known(self):
        assert {taxid for taxid, _ in check.DEG_SETS.values()} == {"559292", "6239", "7955", "7227"}
