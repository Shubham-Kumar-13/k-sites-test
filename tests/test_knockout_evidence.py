"""
Measured knockout evidence: reading the data files, assessing a gene, and the safety verdicts that follow from it.

The fixtures in tests/fixtures/evidence are a small copy of the real data files (tools/record_evidence_fixture.py).
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from k_sites.knockout_evidence import EvidenceProvider, EvidenceUnavailable, assess_gene, resolve_context
from k_sites.knockout_evidence.provider import DirectorySource, UrlSource
from k_sites.workflow.safety_recommender import get_safety_recommendation

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "evidence"


@pytest.fixture(scope="module")
def provider():
    return EvidenceProvider.from_directory(FIXTURES)


def verdict(provider, taxid, symbol, pleiotropy, context="auto"):
    evidence = assess_gene(provider, taxid, symbol, context)
    return get_safety_recommendation(symbol, pleiotropy, knockout_evidence=evidence), evidence


class TestProvider:
    def test_genes_are_found_by_symbol_in_any_case_and_by_old_name(self, provider):
        human = provider.organism("9606")

        assert human.lookup("tdg") is human.lookup("TDG") is not None
        assert human.lookup("AARS") is human.lookup("AARS1")          # AARS is the old name of AARS1
        assert human.lookup("NOSUCHGENE") is None
        assert human.lookup("") is None

    def test_organisms_without_files_have_no_evidence(self, provider):
        assert provider.organism("3702") is None
        assert provider.organism("4932") is provider.organism("559292")      # both taxon ids of baker's yeast

    def test_a_different_file_format_is_refused(self, tmp_path):
        (tmp_path / "index.json").write_text(json.dumps({"format": 99, "organisms": {}}), encoding="utf-8")

        with pytest.raises(EvidenceUnavailable, match="format 99"):
            EvidenceProvider.from_directory(tmp_path).index

    def test_a_missing_folder_is_reported(self, tmp_path):
        with pytest.raises(EvidenceUnavailable):
            EvidenceProvider.from_directory(tmp_path / "nothing").index


class TestDownload:
    def session(self, files, fail=False):
        session = MagicMock()

        def get(url, timeout=None):
            if fail:
                raise requests.ConnectionError("offline")
            name = url.rsplit("/", 1)[1]
            response = MagicMock()
            response.json.return_value = files[name]
            return response
        session.get.side_effect = get
        return session

    def files(self):
        return {name: json.loads((FIXTURES / name).read_text(encoding="utf-8")) for name in ("index.json", "10090.json")}

    def test_files_are_saved_per_release_and_reused_when_offline(self, tmp_path):
        online = UrlSource("https://example.org/evidence-data", tmp_path, session=self.session(self.files()))
        assert EvidenceProvider(online).organism("10090").lookup("Tdg")["v"] == "L"

        offline = UrlSource("https://example.org/evidence-data", tmp_path, session=self.session({}, fail=True))
        again = EvidenceProvider(offline)
        assert again.index["built"] == online._release
        assert again.organism("10090").lookup("Tdg")["v"] == "L"            # from the saved copy

    def test_nothing_saved_and_no_network_is_an_error(self, tmp_path):
        source = UrlSource("https://example.org/evidence-data", tmp_path, session=self.session({}, fail=True))

        with pytest.raises(EvidenceUnavailable):
            EvidenceProvider(source).index

    def test_old_releases_are_removed(self, tmp_path):
        (tmp_path / "2020-01-01").mkdir()
        (tmp_path / "2020-01-01" / "index.json").write_text("{}", encoding="utf-8")

        EvidenceProvider(UrlSource("https://example.org/x", tmp_path, session=self.session(self.files()))).index

        assert not (tmp_path / "2020-01-01").exists()


class TestAssessment:
    def test_context_follows_the_organism_unless_chosen(self):
        assert resolve_context("9606") == "cells"
        assert resolve_context("10090") == "organism"
        assert resolve_context("9606", "organism") == "organism"
        assert resolve_context("10090", "cells") == "cells"

    def test_a_lethal_mouse_gene_reads_as_lethal_with_stage_and_references(self, provider):
        organism = assess_gene(provider, "10090", "Tdg")["organism"]

        assert organism["call"] == "LETHAL" and organism["basis"] == "direct"
        assert organism["stage"] == "E" and organism["stage_text"] == "embryonic / prenatal"
        assert organism["counts"] == {"lethal": 3, "subviable": 0, "viable": 0}
        assert 21278727 in organism["references"] and organism["mgi_id"] == "MGI:108247"
        assert organism["sources"] == ["mgi"]
        assert organism["text"] == "Knockout is lethal (embryonic / prenatal) in mice: 3 of 3 knockout lines"

    def test_human_genes_use_the_mouse_ortholog_and_the_cell_screens(self, provider):
        evidence = assess_gene(provider, "9606", "TDG")

        assert evidence["context"] == "cells"
        assert evidence["organism"]["basis"] == "ortholog"
        assert evidence["organism"]["ortholog"] == {"symbol": "Tdg", "relation": "1:1"}
        assert evidence["organism"]["sources"] == ["mgi", "alliance"]
        assert evidence["cells"]["call"] == "NON_ESSENTIAL" and evidence["cells"]["percent"] == 3.7
        assert evidence["cells"]["lines"] == 1178
        assert evidence["constraint"]["label"] == "not constrained"
        assert evidence["expression"]["label"] == "tissue-enriched"
        assert evidence["has_measured"]
        assert {s["id"] for s in evidence["sources"]} == {"mgi", "alliance", "depmap", "gnomad", "gtex"}

    def test_cell_essentiality_classes(self, provider):
        assert assess_gene(provider, "9606", "PCNA")["cells"]["call"] == "ESSENTIAL"        # common essential
        assert assess_gene(provider, "9606", "XRCC1")["cells"]["call"] == "SELECTIVE"       # essential in 16% of lines
        assert assess_gene(provider, "9606", "OGG1")["cells"]["call"] == "NON_ESSENTIAL"

    def test_mixed_reports_are_described_not_hidden(self, provider):
        organism = assess_gene(provider, "10090", "Sirt6")["organism"]

        assert organism["call"] == "VIABLE" and organism["mixed"]
        assert "1 lethal, 1 subviable in other lines" in organism["text"]

    def test_yeast_deletions(self, provider):
        assert assess_gene(provider, "559292", "ACT1")["organism"]["text"] == "Deletion is inviable in yeast: 2 of 2 knockout lines"
        assert assess_gene(provider, "559292", "RAD52")["organism"]["call"] == "VIABLE"
        assert assess_gene(provider, "559292", "YML032C")["found"]            # the systematic name works too

    def test_unknown_genes_and_organisms_say_so(self, provider):
        missing = assess_gene(provider, "9606", "NOSUCHGENE")
        assert missing["covered"] and not missing["found"] and not missing["has_measured"]
        assert missing["organism"]["call"] == "UNKNOWN" and missing["cells"]["call"] == "UNKNOWN"

        uncovered = assess_gene(provider, "3702", "tdg")
        assert not uncovered["covered"] and uncovered["organism"]["call"] == "UNKNOWN"

    def test_without_a_provider_nothing_is_claimed(self):
        evidence = assess_gene(None, "9606", "TDG")

        assert not evidence["covered"] and not evidence["has_measured"]


class TestVerdicts:
    @pytest.mark.parametrize("taxid,symbol,pleiotropy,context,level,primary", [
        # whole organism: lethal knockouts are to be avoided, viable ones are fine
        ("10090", "Tdg", 7.0, "auto", "AVOID", "Conditional Knockout (Cre-Lox)"),
        ("10090", "Polb", 10.0, "auto", "AVOID", "Conditional Knockout (Cre-Lox)"),
        ("10090", "Smug1", 2.6, "auto", "SAFE", "Standard Knockout"),
        ("10090", "Fam168a", 0.0, "auto", "SAFE", "Standard Knockout"),
        # viable but with many annotated roles, a reported shorter life, or conflicting reports: validate first
        ("10090", "Ogg1", 10.0, "auto", "CAUTION", "Standard KO with Validation"),
        ("10090", "Ung", 8.3, "auto", "CAUTION", "Standard KO with Validation"),
        ("10090", "Xpa", 10.0, "auto", "CAUTION", "Standard KO with Validation"),
        # lethal in at least one knockout line although most lines are viable
        ("10090", "Sirt6", 10.0, "auto", "HIGH_CONCERN", "Conditional Knockout (Cre-Lox)"),
        # cultured human cells: DepMap decides
        ("9606", "PCNA", 10.0, "auto", "AVOID", "CRISPR Interference (CRISPRi)"),
        ("9606", "POLE", 10.0, "auto", "AVOID", "CRISPR Interference (CRISPRi)"),
        ("9606", "XRCC1", 9.3, "auto", "CAUTION", "Standard KO with Validation"),
        ("9606", "TDG", 7.0, "auto", "CAUTION", "Standard KO with Validation"),
        ("9606", "SMUG1", 2.6, "auto", "SAFE", "Standard Knockout"),
        ("9606", "NEIL2", 0.0, "auto", "SAFE", "Standard Knockout"),
        # the same human gene as a whole organism follows the mouse ortholog
        ("9606", "TDG", 7.0, "organism", "AVOID", "Conditional Knockout (Cre-Lox)"),
        # yeast
        ("559292", "ACT1", 6.0, "auto", "AVOID", "Conditional Knockout (Cre-Lox)"),
        ("559292", "RAD52", 2.0, "auto", "SAFE", "Standard Knockout"),
    ])
    def test_verdict_follows_the_measurement(self, provider, taxid, symbol, pleiotropy, context, level, primary):
        recommendation, _ = verdict(provider, taxid, symbol, pleiotropy, context)

        assert recommendation.safety_level.value == level
        assert recommendation.primary_recommendation.value == primary

    def test_a_lethal_gene_is_never_called_safe_however_specific_it_looks(self, provider):
        recommendation, _ = verdict(provider, "10090", "Tdg", 0.0)      # a pleiotropy score of 0 would have meant SAFE

        assert recommendation.safety_level.value == "AVOID"
        assert recommendation.evidence_basis == "measured"
        assert recommendation.justification[0].startswith("Knockout is lethal (embryonic / prenatal) in mice")
        assert any("cannot be kept" in c for c in recommendation.concerns)
        assert any("Death occurs embryonic / prenatal" in c for c in recommendation.experimental_considerations)
        assert recommendation.confidence_score == 0.9

    def test_the_mouse_result_is_still_shown_for_cell_work(self, provider):
        recommendation, _ = verdict(provider, "9606", "POLB", 10.0)

        assert recommendation.safety_level.value == "CAUTION"            # not essential in cell lines
        assert any("lethal (perinatal / neonatal) in mice" in line for line in recommendation.justification)
        assert any("whole-animal knockout cannot be made" in c for c in recommendation.concerns)

    def test_ortholog_results_are_marked_and_less_certain(self, provider):
        recommendation, evidence = verdict(provider, "10116", "Polb", 10.0)

        assert recommendation.evidence_basis == "ortholog"
        assert recommendation.safety_level.value == "AVOID"
        assert recommendation.confidence_score == 0.75 and evidence["organism"]["ortholog"]["relation"] == "1:1"

    def test_with_no_measurement_the_verdict_is_never_better_than_caution(self, provider):
        recommendation, evidence = verdict(provider, "9606", "NOSUCHGENE", 0.5)

        assert not evidence["has_measured"]
        assert recommendation.safety_level.value == "CAUTION"
        assert recommendation.primary_recommendation.value == "Standard KO with Validation"
        assert recommendation.evidence_basis == "none"
        assert "unverified" in recommendation.justification[0]
        assert any("has not been measured" in c for c in recommendation.concerns)

    def test_an_unmeasured_gene_the_old_rules_rated_worse_still_says_it_was_not_measured(self, provider):
        recommendation, evidence = verdict(provider, "9606", "NOSUCHGENE", 9.0)

        assert not evidence["has_measured"]
        assert recommendation.safety_level.value != "SAFE"
        assert recommendation.justification[0].startswith("No measured knockout data for this gene")
        assert recommendation.concerns[0].startswith("Lethality has not been measured")
        assert "No major concerns identified" not in recommendation.concerns

    def test_an_organism_without_data_is_also_capped(self, provider):
        recommendation, _ = verdict(provider, "3702", "tdg", 0.5)

        assert recommendation.safety_level.value == "CAUTION"

    def test_without_evidence_the_old_rules_apply_unchanged(self):
        recommendation = get_safety_recommendation("X", 1.0)

        assert recommendation.safety_level.value == "SAFE" and recommendation.evidence_basis == "none"

    def test_highly_constrained_genes_are_flagged_but_not_downgraded(self, provider):
        recommendation, evidence = verdict(provider, "9606", "DDB1", 5.0, "organism")

        assert evidence["constraint"]["label"] == "highly constrained"
        assert any("Highly constrained in people" in line for line in recommendation.justification)

    def test_golden_cases_still_hold(self, provider):
        golden = [json.loads(line.rstrip(",")) for line in (FIXTURES / "golden.json").read_text(encoding="utf-8").splitlines()
                  if line.startswith("{")]
        assert len(golden) > 100
        for case in golden:
            evidence = assess_gene(provider, case["taxid"], case["symbol"], case["context"])
            assert evidence == case["evidence"], case["symbol"]


# ---------------------------------------------------------------------------------------------------------------------
# paralogs, tissue-restricted expression and distant relatives, with a small hand-made data set


class TestCellsWithoutACellLineResult:
    """No DepMap result: a viable mouse ortholog does not show that cells can do without the gene."""

    def provider(self, record):
        index = {"format": 1, "built": "2026-01-01", "stages": {}, "systems": [],
                 "organisms": {"9606": {"name": "Homo sapiens", "file": "9606.json", "layers": []}}, "sources": []}
        return EvidenceProvider(DictSource({"index.json": index, "9606.json": {"genes": {"RPS26": record}, "aliases": {}}}))

    def test_a_viable_mouse_ortholog_is_never_enough_for_safe_in_cells(self):
        record = {"o": ["Rps26", "n:1"], "m": {"v": "V", "n": [0, 0, 2]}}
        evidence = assess_gene(self.provider(record), "9606", "RPS26", "cells")

        recommendation = get_safety_recommendation("RPS26", 2.0, knockout_evidence=evidence)

        assert evidence["cells"]["call"] == "UNKNOWN" and evidence["organism"]["call"] == "VIABLE"
        assert recommendation.safety_level.value == "CAUTION"
        assert any("cells were not screened" in c for c in recommendation.concerns)
        assert any("not a one-to-one match" in c for c in recommendation.concerns)


class TestLethalityEstimate:
    """Genes without a knockout result get an estimate from their human ortholog; it is never a measurement."""

    def test_a_mouse_gene_without_a_knockout_gets_an_estimate_from_its_human_ortholog(self, provider):
        recommendation, evidence = verdict(provider, "10090", "Pole", 10.0)

        estimate = evidence["estimate"]
        assert evidence["organism"]["call"] == "UNKNOWN" and not evidence["has_measured"]
        assert estimate["band"] == "likely" and estimate["from_human_ortholog"] and estimate["other_symbol"] == "POLE"
        assert "Estimated" in estimate["text"] and "not a measurement" in estimate["text"]
        assert estimate["percent"] <= 99                                          # never shown as certain
        assert recommendation.evidence_basis == "estimate"
        assert recommendation.safety_level.value == "HIGH_CONCERN"
        assert recommendation.primary_recommendation.value == "Conditional Knockout (Cre-Lox)"
        assert recommendation.justification[0] == estimate["text"]
        assert any("Lethality has not been measured" in c for c in recommendation.concerns)

    def test_a_human_gene_whose_mouse_ortholog_was_never_knocked_out_gets_one_too(self, provider):
        # where the cell lines call the gene essential they decide a whole-organism verdict; otherwise the estimate does
        symbol = next(s for s, r in provider.organism("9606").genes.items() if "pl" in r and "m" not in r
                      and assess_gene(provider, "9606", s, "organism")["cells"]["call"] != "ESSENTIAL")
        recommendation, evidence = verdict(provider, "9606", symbol, 6.0, context="organism")

        assert not evidence["estimate"]["from_human_ortholog"] and evidence["estimate"]["other_symbol"]
        assert recommendation.evidence_basis == "estimate"
        assert recommendation.safety_level.value in ("HIGH_CONCERN", "MODERATE_CONCERN", "CAUTION")

    def test_where_the_cell_lines_call_the_gene_essential_they_decide_a_whole_organism_verdict(self, provider):
        recommendation, evidence = verdict(provider, "9606", "POLE", 10.0, context="organism")

        assert evidence["cells"]["call"] == "ESSENTIAL" and evidence["estimate"]["band"] == "likely"
        assert recommendation.evidence_basis == "measured" and recommendation.safety_level.value == "HIGH_CONCERN"

    def test_the_bands_follow_the_probability_and_nothing_is_ever_safe(self, provider):
        seen = {}
        for symbol, record in provider.organism("10090").genes.items():
            if "pl" in record and "v" not in record:
                recommendation, evidence = verdict(provider, "10090", symbol, 1.0)
                band = evidence["estimate"]["band"]
                probability = record["pl"][0]
                assert band == ("likely" if probability >= 0.5 else "possible" if probability >= 0.3 else "unlikely")
                assert recommendation.safety_level.value == {"likely": "HIGH_CONCERN", "possible": "MODERATE_CONCERN",
                                                             "unlikely": "CAUTION"}[band]
                seen[band] = seen.get(band, 0) + 1
        assert set(seen) == {"likely", "possible", "unlikely"}

    def test_a_measured_gene_has_no_estimate_and_the_estimate_never_overrides_a_measurement(self, provider):
        recommendation, evidence = verdict(provider, "10090", "Tdg", 7.0)

        assert evidence["estimate"] is None and recommendation.evidence_basis == "measured"
        assert recommendation.safety_level.value == "AVOID"

    def test_cells_are_judged_by_the_cell_lines_not_by_the_estimate(self, provider):
        recommendation, evidence = verdict(provider, "9606", "RPA3", 9.0)             # human: cultured cells

        assert evidence["cells"]["call"] == "ESSENTIAL" and recommendation.evidence_basis == "measured"

    def test_the_estimate_adds_its_sources(self, provider):
        _, evidence = verdict(provider, "10090", "Pole", 10.0)

        assert {"mgi", "impc", "depmap", "gnomad", "gtex"} <= {s["id"] for s in evidence["sources"]}


class TestConservationAndLiterature:
    def provider(self, human):
        index = {"format": 1, "built": "2026-01-01", "organisms": {"9606": {"name": "Homo sapiens", "file": "9606.json", "layers": []}},
                 "sources": []}
        return EvidenceProvider(DictSource({"index.json": index, "9606.json": {"genes": human, "aliases": {}}}))

    def test_conservation_counts_the_model_species_that_carry_the_gene(self):
        provider = self.provider({"PCNA": {"cv": 0b11011, "lc": 6361}, "TINY": {"cv": 0b00001, "lc": 0}, "NOCV": {}})

        pcna = assess_gene(provider, "9606", "PCNA")
        tiny = assess_gene(provider, "9606", "TINY")

        assert pcna["conservation"]["score"] == 0.8
        assert pcna["conservation"]["found_in"] == ["human", "mouse", "fly", "worm"]
        assert pcna["conservation"]["text"] == "Present in 4 of 5 model species (human, mouse, fly, worm)"
        assert tiny["conservation"]["score"] == 0.2 and tiny["literature"]["count"] == 0
        assert pcna["literature"]["count"] == 6361

    def test_a_gene_without_the_facts_has_none(self):
        provider = self.provider({"NOCV": {}})

        evidence = assess_gene(provider, "9606", "NOCV")
        unknown = assess_gene(provider, "9606", "NOSUCHGENE")

        assert evidence["conservation"] is None and evidence["literature"] is None
        assert unknown["conservation"] is None and unknown["literature"] is None

    def test_the_fixture_genes_carry_them_in_the_same_way(self, provider):
        for symbol, record in provider.organism("9606").genes.items():
            evidence = assess_gene(provider, "9606", symbol)
            if "cv" in record:
                assert evidence["conservation"]["score"] == bin(record["cv"]).count("1") / 5
            if "lc" in record:
                assert evidence["literature"]["count"] == record["lc"]


class DictSource:
    def __init__(self, files):
        self.files = files

    def read(self, name):
        return self.files[name]


def tiny_provider():
    mouse_viable = {"v": "V", "n": [0, 0, 3], "src": "M"}
    mouse_lethal = {"v": "L", "n": [2, 0, 0], "s": "E", "src": "M", "id": "MGI:1", "pm": [111]}
    index = {
        "format": 1, "built": "2026-01-01", "stages": {"E": "embryonic / prenatal", "U": "age not stated"},
        "systems": [], "tissues": ["Liver", "Brain", "Heart"],
        "sources": [{"id": s, "name": s.upper(), "url": f"https://example.org/{s}", "what": ""}
                    for s in ("mgi", "impc", "alliance", "depmap", "gnomad", "gtex", "ensembl")],
        "organisms": {
            "9606": {"name": "Homo sapiens", "file": "9606.json", "layers": []},
            "10090": {"name": "Mus musculus", "file": "10090.json", "layers": []},
            "7227": {"name": "Drosophila melanogaster", "file": "7227.json", "layers": [], "distant": True},
        },
    }
    human = {
        # viable in the mouse, not essential in cells, with two close paralogs and one distant one
        "TWIN1": {"o": ["Twin1", "1:1"], "m": mouse_viable, "c": ["", 1.0, 1178], "p": [["TWIN2", 62], ["TWIN3", 44], ["OTHER", 33]]},
        # lethal in the mouse, expressed mainly in the liver
        "LIVER1": {"o": ["Liver1", "1:1"], "m": mouse_lethal, "t": [0.9, 3, [0]]},
        "BROAD1": {"o": ["Broad1", "1:1"], "m": mouse_lethal, "t": [0.2, 3, [0, 1]]},
    }
    fly = {"LETHALFLY": {"o": ["Liver1", "1:1"], "m": mouse_lethal},
           "VIABLEFLY": {"o": ["Twin1", "1:1"], "m": mouse_viable}}
    files = {"index.json": index, "9606.json": {"genes": human, "aliases": {}},
             "10090.json": {"genes": {"TWIN1": {**mouse_viable, "p": [["TWIN2", 70]]}}, "aliases": {}},
             "7227.json": {"genes": fly, "aliases": {}}}
    return EvidenceProvider(DictSource(files))


class TestParalogsExpressionAndDistantRelatives:
    provider = tiny_provider()

    def test_close_paralogs_are_listed_and_warned_about(self):
        evidence = assess_gene(self.provider, "9606", "TWIN1")
        recommendation = get_safety_recommendation("TWIN1", 1.0, knockout_evidence=evidence)

        assert [g["symbol"] for g in evidence["paralogs"]["genes"]] == ["TWIN2", "TWIN3", "OTHER"]
        assert evidence["paralogs"]["close"] == ["TWIN2", "TWIN3"]            # 40% identity or more
        assert evidence["paralogs"]["text"] == "Closest paralogs: TWIN2 (62% identical), TWIN3 (44% identical), OTHER (33% identical)"
        assert recommendation.safety_level.value == "SAFE"                      # a paralog is advice, not a risk
        assert any("close paralogs TWIN2, TWIN3 may take over its work" in c for c in recommendation.concerns)
        assert "ensembl" in [s["id"] for s in evidence["sources"]]

    def test_a_single_close_paralog_is_worded_in_the_singular(self):
        evidence = assess_gene(self.provider, "10090", "Twin1")
        recommendation = get_safety_recommendation("Twin1", 1.0, knockout_evidence=evidence)

        assert any("The close paralog TWIN2 may take over its work" in c for c in recommendation.concerns)

    def test_a_tissue_restricted_lethal_gene_gets_a_tissue_specific_suggestion(self):
        narrow = get_safety_recommendation("LIVER1", 1.0, knockout_evidence=assess_gene(self.provider, "9606", "LIVER1", "organism"))
        broad = get_safety_recommendation("BROAD1", 1.0, knockout_evidence=assess_gene(self.provider, "9606", "BROAD1", "organism"))

        assert any("concentrated in Liver" in m and "tissue-specific conditional knockout" in m for m in narrow.mitigation_strategies)
        assert not any("concentrated in" in m for m in broad.mitigation_strategies)

    def test_expression_of_a_mouse_gene_is_marked_as_coming_from_the_human_ortholog(self):
        files = self.provider.source.files
        files["10090.json"]["genes"]["TWIN1"]["t"] = [0.7, 3, [1]]
        evidence = assess_gene(EvidenceProvider(DictSource(files)), "10090", "Twin1")

        assert evidence["expression"]["text"].endswith("(in the human ortholog)")
        del files["10090.json"]["genes"]["TWIN1"]["t"]

    def test_a_distant_relative_gets_a_hint_never_a_measurement(self):
        evidence = assess_gene(self.provider, "7227", "LETHALFLY")
        recommendation = get_safety_recommendation("LETHALFLY", 1.0, knockout_evidence=evidence)

        assert evidence["organism"]["distant"] and evidence["organism"]["call"] == "LETHAL"
        assert not evidence["has_measured"]                                     # so a phenotype prediction would still run
        assert "a distant relative, so only an indication" in evidence["organism"]["text"]
        assert recommendation.evidence_basis == "distant"
        assert recommendation.safety_level.value == "MODERATE_CONCERN"
        assert recommendation.primary_recommendation.value == "Heterozygous Knockout"
        assert recommendation.justification[0].startswith("No measured knockout data for this gene")
        assert recommendation.justification[1] == evidence["organism"]["text"]
        assert "has not been tested" in recommendation.concerns[0]
        assert recommendation.concerns[1].startswith("Lethality has not been measured")

    def test_a_viable_mouse_ortholog_does_not_make_a_distant_gene_safe(self):
        evidence = assess_gene(self.provider, "7227", "VIABLEFLY")
        recommendation = get_safety_recommendation("VIABLEFLY", 0.5, knockout_evidence=evidence)

        assert recommendation.evidence_basis == "distant"
        assert recommendation.safety_level.value == "CAUTION"
        assert recommendation.justification[0].startswith("No measured knockout data for this gene")
