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


class TestRecordIntegrity:
    def test_direct_records_need_valid_counts_an_approved_source_and_conflict_flags(self):
        genes = {
            "GOOD": {"v": "L", "n": [1, 0, 0], "src": "Z"},
            "WRONG-SOURCE": {"v": "L", "n": [1, 0, 0], "src": "ZMP"},
            "UNMARKED-CONFLICT": {"v": "L", "n": [1, 0, 1], "src": "Z"},
            "WRONG-CALL": {"v": "V", "n": [1, 0, 0], "src": "Z"},
            "BAD\nKEY": {"v": "V", "n": [0, 0, 1], "src": "Z"},
            "BAD-COUNTS": {"v": "V", "n": [0, 0, 0], "src": "Z"},
        }

        problems, examples = check.record_violations("7955", genes)

        assert problems == {
            "unapproved direct-evidence source": 1,
            "conflicting evidence is not marked": 1,
            "verdict does not follow evidence counts": 1,
            "invalid gene key": 1,
            "invalid evidence counts": 1,
        }
        assert "GOOD" not in examples.values()

    def test_an_unregistered_organism_cannot_have_a_direct_knockout_verdict(self):
        problems, _ = check.record_violations("9913", {"BTA": {"v": "V", "n": [0, 0, 1], "src": "O"}})

        assert problems["unapproved direct-evidence source"] == 1

    def test_cell_line_records_require_the_engine_schema_and_a_known_source(self):
        genes = {
            "DEPMAP": {"c": ["C", 99.0, 1178]},
            "SCORE": {"c": ["", 75.0, 318], "cs": "project_score"},
            "SHORT": {"c": ["", 75.0]},
            "NO-LINES": {"c": ["", 75.0, None]},
            "WRONG-SOURCE": {"c": ["", 75.0, 318], "cs": "unknown"},
        }

        problems, examples = check.record_violations("9606", genes)

        assert problems == {"invalid cell-line record": 3}
        assert set(examples.values()) <= {"SHORT", "NO-LINES", "WRONG-SOURCE"}
