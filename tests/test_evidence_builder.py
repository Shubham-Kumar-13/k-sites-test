"""
The builder of the measured knockout-evidence files (tools/build_evidence_data.py): how MGI / IMPC records become a
lethal / subviable / viable call, and how the other layers (orthologs, DepMap, gnomAD, GTEx, SGD) are joined.
"""

import gzip
import importlib.util
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bed = load_tool("build_evidence_data")

OBO = """format-version: 1.2

[Term]
id: MP:0000001
name: mammalian phenotype

[Term]
id: MP:0010768
name: mortality/aging
is_a: MP:0000001 ! mammalian phenotype

[Term]
id: MP:0010769
name: abnormal survival
is_a: MP:0010768 ! mortality/aging

[Term]
id: MP:0010770
name: preweaning lethality
is_a: MP:0010769

[Term]
id: MP:0002080
name: prenatal lethality
is_a: MP:0010770

[Term]
id: MP:0008762
name: embryonic lethality
is_a: MP:0002080

[Term]
id: MP:0011092
name: embryonic lethality, complete penetrance
is_a: MP:0008762

[Term]
id: MP:0011102
name: embryonic lethality, incomplete penetrance
is_a: MP:0008762

[Term]
id: MP:0002081
name: perinatal lethality
is_a: MP:0010770

[Term]
id: MP:0002082
name: postnatal lethality
is_a: MP:0010770

[Term]
id: MP:0011100
name: preweaning lethality, complete penetrance
is_a: MP:0010770

[Term]
id: MP:0002083
name: premature death
is_a: MP:0010769

[Term]
id: MP:0002873
name: normal phenotype
is_a: MP:0000001

[Term]
id: MP:0002169
name: no abnormal phenotype detected
is_a: MP:0002873

[Term]
id: MP:0005380
name: embryo phenotype
is_a: MP:0000001

[Term]
id: MP:0001697
name: abnormal embryo size
is_a: MP:0005380

[Term]
id: MP:0005382
name: craniofacial phenotype
is_a: MP:0000001

[Term]
id: MP:0000428
name: abnormal craniofacial morphology
is_a: MP:0005382

[Term]
id: MP:0005385
name: cardiovascular system phenotype
is_a: MP:0000001

[Term]
id: MP:0001544
name: abnormal cardiovascular system physiology
is_a: MP:0005385

[Term]
id: MP:0005378
name: growth/size/body region phenotype
is_a: MP:0000001

[Term]
id: MP:0001262
name: decreased body weight
is_a: MP:0005378

[Term]
id: MP:0005389
name: reproductive system phenotype
is_a: MP:0000001

[Term]
id: MP:0001924
name: infertility
is_a: MP:0005389
alt_id: MP:9999999
"""


@pytest.fixture(scope="module")
def ontology():
    return bed.MPOntology(io.StringIO(OBO))


@pytest.fixture(scope="module")
def survival(ontology):
    return bed.SurvivalTerms(ontology)


def allele(symbol, kind="Targeted", attrs=("Null/knockout",), marker="MGI:1", marker_symbol="Gene"):
    return {"symbol": symbol, "type": kind, "attrs": set(attrs), "marker": marker, "marker_symbol": marker_symbol}


ALLELES = {
    "A:ko": allele("Gene<tm1>"),
    "A:ko2": allele("Gene<tm2>"),
    "A:hypo": allele("Gene<tm3>", attrs=("Hypomorph",)),
    "A:trap": allele("Gene<Gt1>", kind="Gene trapped", attrs=()),
    "A:flox": allele("Gene<tm1c>", attrs=("Conditional ready", "No functional change")),
    "A:tg": allele("Tg(x)", kind="Transgenic", marker=""),
}


def genotype(composition, alleles, mps, pmids=None, gid="G1", marker="MGI:1"):
    g = bed.Genotype(gid, composition, list(alleles), marker)
    g.mps = set(mps)
    for mp, ids in (pmids or {}).items():
        g.pmids[mp] = set(ids)
    return g


class TestGenotypeNotation:
    def test_the_slash_inside_brackets_is_not_a_separator(self):
        assert bed.split_composition("Gene<tm1(Cre/ERT2)>/Gene<tm1(Cre/ERT2)>") == (
            "Gene<tm1(Cre/ERT2)>", "Gene<tm1(Cre/ERT2)>")
        assert bed.split_composition("no separator") is None

    @pytest.mark.parametrize("composition,expected", [
        ("Gene<tm1>/Gene<tm1>", "hom"),
        ("Gene<tm1>/Gene<+>", None),
        ("Gene<+>/Gene<tm1>", None),
        ("Gene<tm1>/Y", "hemi"),
        ("Gene<tm1>/Gene<tm2>", "compound"),
        ("Gene<tm1>", None),
    ])
    def test_zygosity(self, composition, expected):
        assert bed.zygosity(composition) == expected

    def test_allele_classes(self):
        assert bed.allele_class(ALLELES["A:ko"]) == "ko"
        assert bed.allele_class(ALLELES["A:hypo"]) == "hypo"
        assert bed.allele_class(ALLELES["A:trap"]) == "trap"
        assert bed.allele_class(ALLELES["A:flox"]) is None       # a floxed allele still works
        assert bed.allele_class(ALLELES["A:tg"]) is None
        assert bed.allele_class(None) is None


class TestOntology:
    def test_lethality_terms_know_stage_and_penetrance(self, survival):
        assert survival.lethal["MP:0008762"] == ("E", False)
        assert survival.lethal["MP:0011102"] == ("E", True)          # incomplete penetrance -> subviable
        assert survival.lethal["MP:0002081"] == ("P", False)
        assert survival.lethal["MP:0002082"] == ("J", False)
        assert survival.lethal["MP:0011100"] == ("W", False)         # before weaning, stage not stated
        assert "MP:0002083" not in survival.lethal                   # premature death is reduced lifespan, not lethality
        assert "MP:0002083" in survival.premature_death

    def test_organ_systems_leave_out_survival_and_normal(self, survival):
        assert set(survival.system_names.values()) == {
            "embryo phenotype", "craniofacial phenotype", "cardiovascular system phenotype",
            "growth/size/body region phenotype", "reproductive system phenotype"}
        assert {survival.system_names[t] for t in survival.adult_systems} == {
            "growth/size/body region phenotype", "reproductive system phenotype"}
        assert survival.systems_of("MP:0001544") == {"MP:0005385"}

    def test_alternate_ids_resolve(self, ontology):
        assert ontology.canonical("MP:9999999") == "MP:0001924"

    def test_the_earliest_stage_wins(self):
        assert bed.earliest_stage({"J", "E"}) == "E"
        assert bed.earliest_stage({"W", "U"}) == "W"
        assert bed.earliest_stage(set()) is None


class TestGenotypeCalls:
    def evaluate(self, survival, composition, alleles, mps, **kw):
        return bed.evaluate_genotype(genotype(composition, alleles, mps, **kw), ALLELES, survival)

    def test_embryonic_lethality_of_a_homozygous_null(self, survival):
        call, stage, pmids, systems, premature, infertile = self.evaluate(
            survival, "Gene<tm1>/Gene<tm1>", ["A:ko"], ["MP:0011092", "MP:0001697"],
            pmids={"MP:0011092": ["111"], "MP:0001697": ["222"]})

        assert (call, stage) == ("L", "E")
        assert pmids == {"111"}                    # the papers behind the lethality, not every paper
        assert systems == {"MP:0005380"}

    def test_incomplete_penetrance_is_subviable(self, survival):
        assert self.evaluate(survival, "Gene<tm1>/Gene<tm1>", ["A:ko"], ["MP:0011102"])[:2] == ("S", "E")

    def test_complete_lethality_beats_partial(self, survival):
        result = self.evaluate(survival, "Gene<tm1>/Gene<tm1>", ["A:ko"], ["MP:0011102", "MP:0002082"])
        assert result[:2] == ("L", "J")

    def test_adult_phenotypes_mean_viable(self, survival):
        call, stage, pmids, systems, premature, infertile = self.evaluate(
            survival, "Gene<tm1>/Gene<tm1>", ["A:ko"], ["MP:0001262", "MP:0002083", "MP:0001924"])
        assert (call, stage) == ("V", None)
        assert premature and infertile

    def test_no_abnormal_phenotype_means_viable(self, survival):
        assert self.evaluate(survival, "Gene<tm1>/Gene<tm1>", ["A:ko"], ["MP:0002169"])[0] == "V"

    def test_only_embryo_or_morphology_findings_do_not_prove_viability(self, survival):
        # an embryo study can describe the same malformations in animals that die later, so these say nothing about survival
        assert self.evaluate(survival, "Gene<tm1>/Gene<tm1>", ["A:ko"], ["MP:0001697"]) is None
        assert self.evaluate(survival, "Gene<tm1>/Gene<tm1>", ["A:ko"], ["MP:0000428", "MP:0001544"]) is None

    def test_heterozygotes_and_non_loss_alleles_are_ignored(self, survival):
        assert self.evaluate(survival, "Gene<tm1>/Gene<+>", ["A:ko"], ["MP:0008762"]) is None
        assert self.evaluate(survival, "Gene<tm1c>/Gene<tm1c>", ["A:flox"], ["MP:0008762"]) is None

    def test_a_lethal_hypomorph_counts_but_a_viable_one_does_not(self, survival):
        # if a partial loss is lethal, the full loss is lethal; if a partial loss is viable, the full loss may not be
        assert self.evaluate(survival, "Gene<tm3>/Gene<tm3>", ["A:hypo"], ["MP:0008762"])[:2] == ("L", "E")
        assert self.evaluate(survival, "Gene<tm3>/Gene<tm3>", ["A:hypo"], ["MP:0001262"]) is None
        assert self.evaluate(survival, "Gene<Gt1>/Gene<Gt1>", ["A:trap"], ["MP:0001262"]) is None

    def test_two_different_null_alleles_count_as_a_null(self, survival):
        assert self.evaluate(survival, "Gene<tm1>/Gene<tm2>", ["A:ko", "A:ko2"], ["MP:0008762"])[0] == "L"

    def test_hemizygous_x_linked_null(self, survival):
        assert self.evaluate(survival, "Gene<tm1>/Y", ["A:ko"], ["MP:0001262"])[0] == "V"


class TestGeneCalls:
    def genes(self, survival, *genotypes):
        return bed.calls_from_mgi({g.gid: g for g in genotypes}, ALLELES, survival)

    def test_counts_stage_and_references(self, survival):
        genes = self.genes(
            survival,
            genotype("Gene<tm1>/Gene<tm1>", ["A:ko"], ["MP:0011092"], {"MP:0011092": ["10", "11"]}, gid="G1"),
            genotype("Gene<tm1>/Gene<tm1>", ["A:ko"], ["MP:0002081"], {"MP:0002081": ["10"]}, gid="G2"),
            genotype("Gene<tm1>/Gene<tm1>", ["A:ko"], ["MP:0001262"], gid="G3"))
        gene = genes["MGI:1"]

        assert gene.counts == {"L": 2, "S": 0, "V": 1}
        assert gene.stages["L"] == {"E", "P"}
        assert gene.pmids.most_common(1)[0] == ("10", 2)
        record = bed.mouse_record(gene, {"MP:0005380": 0})
        assert record["v"] == "L" and record["s"] == "E" and record["n"] == [2, 0, 1] and record["x"] == 1
        assert record["pm"][0] == 10 and record["id"] == "MGI:1" and record["src"] == "M"

    def test_references_do_not_depend_on_the_order_they_were_seen_in(self):
        records = []
        for order in (["30", "10", "20", "40"], ["40", "20", "10", "30"]):
            gene = bed.GeneCalls(marker="MGI:1")
            gene.counts.update({"V": 1})
            gene.pmids.update(order)
            gene.pmids["20"] += 1                                   # cited twice, so it comes first
            records.append(bed.mouse_record(gene, {}))

        assert records[0]["pm"] == records[1]["pm"] == [20, 10, 30]

    def test_majority_decides_and_a_tie_goes_to_the_more_severe_call(self, survival):
        viable = [genotype("Gene<tm1>/Gene<tm1>", ["A:ko"], ["MP:0001262"], gid=f"V{i}") for i in range(3)]
        lethal = genotype("Gene<tm1>/Gene<tm1>", ["A:ko"], ["MP:0008762"], gid="L1")
        mostly_viable = bed.mouse_record(self.genes(survival, *viable, lethal)["MGI:1"], {})
        assert mostly_viable["v"] == "V" and mostly_viable["x"] == 1 and mostly_viable["n"] == [1, 0, 3]

        tie = bed.mouse_record(self.genes(survival, viable[0], lethal)["MGI:1"], {})
        assert tie["v"] == "L"

    def test_a_gene_with_no_usable_genotype_has_no_record(self):
        assert bed.mouse_record(bed.GeneCalls(), {}) is None


class TestImpc:
    VIABILITY = [
        {"Gene Symbol": "Gene", "Gene Accession Id": "MGI:1", "Allele Accession Id": "A:ko", "Colony Id": "C1",
         "Zygosity": "homozygote", "Viability Phenotype HOMs/HEMIs": "lethal"},
        {"Gene Symbol": "Gene", "Gene Accession Id": "MGI:1", "Allele Accession Id": "A:ko2", "Colony Id": "C2",
         "Zygosity": "homozygote", "Viability Phenotype HOMs/HEMIs": "subviable"},
        {"Gene Symbol": "Gene", "Gene Accession Id": "MGI:1", "Allele Accession Id": "A:ko2", "Colony Id": "C2",
         "Zygosity": "homozygote", "Viability Phenotype HOMs/HEMIs": "subviable"},       # the same colony twice
        {"Gene Symbol": "Gene", "Gene Accession Id": "MGI:1", "Allele Accession Id": "A:flox", "Colony Id": "C3",
         "Zygosity": "homozygote", "Viability Phenotype HOMs/HEMIs": "viable"},          # floxed: says nothing
        {"Gene Symbol": "Other", "Gene Accession Id": "MGI:2", "Allele Accession Id": "MGI:unknown", "Colony Id": "C4",
         "Zygosity": "homozygote", "Viability Phenotype HOMs/HEMIs": "viable"},
    ]

    def test_screen_results_are_counted_once_per_colony(self, survival):
        genes = bed.add_impc({}, self.VIABILITY, [], ALLELES, survival)

        assert genes["MGI:1"].counts == {"L": 1, "S": 1, "V": 0}
        assert genes["MGI:2"].counts["V"] == 1
        assert genes["MGI:1"].sources == {"I"}
        assert genes["MGI:1"].stages["L"] == {"W"}          # the screen scores survival to weaning

    def test_assertions_refine_the_stage_and_add_organ_systems(self, survival):
        g2p = [{"zygosity": "homozygote", "marker_accession_id": "MGI:1", "marker_symbol": "Gene",
                "allele_accession_id": "A:ko", "mp_term_id": "MP:0011092"},
               {"zygosity": "heterozygote", "marker_accession_id": "MGI:1", "marker_symbol": "Gene",
                "allele_accession_id": "A:ko", "mp_term_id": "MP:0001262"},
               {"zygosity": "homozygote", "marker_accession_id": "MGI:1", "marker_symbol": "Gene",
                "allele_accession_id": "A:ko", "mp_term_id": "MP:0001544"}]

        genes = bed.add_impc({}, self.VIABILITY[:1], g2p, ALLELES, survival)

        assert genes["MGI:1"].stages["L"] == {"E"}
        assert genes["MGI:1"].systems == {"MP:0005385"}      # the heterozygous finding is not counted


ORTHOLOGY = """#####
# Orthology
#####
Gene1ID\tGene1Symbol\tGene1SpeciesTaxonID\tGene1SpeciesName\tGene2ID\tGene2Symbol\tGene2SpeciesTaxonID\tGene2SpeciesName\tAlgorithms\tAlgorithmsMatch\tOutOfAlgorithms\tIsBestScore\tIsBestRevScore
HGNC:1\tTDG\tNCBITaxon:9606\tHomo sapiens\tMGI:10\tTdg\tNCBITaxon:10090\tMus musculus\tA|B\t5\t9\tYes\tYes
HGNC:2\tAAA\tNCBITaxon:9606\tHomo sapiens\tMGI:20\tAaa\tNCBITaxon:10090\tMus musculus\tA\t4\t9\tYes\tYes
HGNC:3\tAAB\tNCBITaxon:9606\tHomo sapiens\tMGI:20\tAaa\tNCBITaxon:10090\tMus musculus\tA\t4\t9\tYes\tNo
HGNC:4\tCCC\tNCBITaxon:9606\tHomo sapiens\tMGI:30\tCcc1\tNCBITaxon:10090\tMus musculus\tA\t4\t9\tYes\tYes
HGNC:4\tCCC\tNCBITaxon:9606\tHomo sapiens\tMGI:31\tCcc2\tNCBITaxon:10090\tMus musculus\tA\t3\t9\tNo\tNo
HGNC:5\tDDD\tNCBITaxon:9606\tHomo sapiens\tMGI:40\tDdd1\tNCBITaxon:10090\tMus musculus\tA\t3\t9\tYes\tNo
HGNC:5\tDDD\tNCBITaxon:9606\tHomo sapiens\tMGI:41\tDdd2\tNCBITaxon:10090\tMus musculus\tA\t3\t9\tYes\tNo
MGI:10\tTdg\tNCBITaxon:10090\tMus musculus\tRGD:10\tTdg\tNCBITaxon:10116\tRattus norvegicus\tA\t5\t9\tYes\tYes
MGI:10\tTdg\tNCBITaxon:10090\tMus musculus\tSGD:S1\tTDG1\tNCBITaxon:559292\tSaccharomyces cerevisiae\tA\t5\t9\tYes\tYes
"""


class TestOrthologs:
    def test_unambiguous_orthologs_and_their_relation(self):
        pairs = bed.parse_orthology(io.StringIO(ORTHOLOGY),
                                    wanted={frozenset(("9606", "10090")), frozenset(("10116", "10090"))})
        human = bed.orthologs_to_mouse(pairs, "9606")

        assert human["HGNC:1"] == ("MGI:10", "Tdg", "1:1", "TDG")
        assert human["HGNC:2"][2] == "1:1" and human["HGNC:3"][2] == "n:1"      # AAB is only a weaker match of the mouse gene AAA owns
        assert human["HGNC:4"] == ("MGI:30", "Ccc1", "best", "CCC")             # several candidates, one clear best pair
        assert "HGNC:5" not in human                                            # several candidates, no best pair
        assert bed.orthologs_to_mouse(pairs, "10116")["RGD:10"][0] == "MGI:10"

    def test_only_the_requested_species_pairs_are_read(self):
        pairs = bed.parse_orthology(io.StringIO(ORTHOLOGY), wanted={frozenset(("9606", "10090"))})
        assert all({p["a_tax"], p["b_tax"]} == {"9606", "10090"} for p in pairs)


SGD = "\n".join("\t".join(row) for row in [
    # systematic, type, name, id, reference, experiment, mutant, allele, strain, phenotype, chemical, condition, details
    ["YFL039C", "ORF", "ACT1", "S1", "SGD_REF:1|PMID:111", "systematic mutation set", "null", "act1-D", "S288C", "inviable", "", "", ""],
    ["YFL039C", "ORF", "ACT1", "S1", "SGD_REF:2|PMID:222", "classical genetics", "null", "act1-D", "S288C", "inviable", "", "", ""],
    ["YML032C", "ORF", "RAD52", "S2", "SGD_REF:3|PMID:333", "systematic mutation set", "null", "rad52-D", "S288C", "viable", "", "", ""],
    ["YML032C", "ORF", "RAD52", "S2", "SGD_REF:4|PMID:444", "homozygous diploid", "null", "rad52-D", "S288C", "inviable", "", "37 C", ""],
    ["YML032C", "ORF", "RAD52", "S2", "SGD_REF:5|PMID:555", "classical genetics", "null", "rad52-D", "S288C", "inviable", "", "elevated temperature", ""],
    ["YFL039C", "ORF", "ACT1", "S1", "SGD_REF:6|PMID:666", "classical genetics", "overexpression", "", "S288C", "inviable", "", "", ""],
    ["YAL001C", "ORF", "", "S3", "SGD_REF:7|PMID:777", "systematic mutation set", "null", "d", "S288C", "viable", "", "", ""],
])


class TestYeast:
    def test_only_plain_deletions_count(self):
        records = bed.build_yeast(io.StringIO(SGD))

        assert records["ACT1"]["v"] == "L" and records["ACT1"]["n"] == [2, 0, 0] and records["ACT1"]["pm"][0] in (111, 222)
        assert records["YFL039C"] is records["ACT1"]                              # reachable by either name
        assert records["RAD52"] == {"v": "V", "n": [0, 0, 1], "src": "S"}         # lethal only under special conditions
        assert "YAL001C" in records and records["YAL001C"]["v"] == "V"


class TestLethalityEstimate:
    def test_the_area_under_the_curve(self):
        assert bed.rank_auc([1, 1, 0, 0], [0.9, 0.8, 0.2, 0.1]) == 1.0
        assert bed.rank_auc([1, 1, 0, 0], [0.1, 0.2, 0.8, 0.9]) == 0.0
        assert bed.rank_auc([1, 0, 1, 0], [0.5, 0.5, 0.5, 0.5]) == 0.5            # ties count half

    def test_features_need_some_cell_line_constraint_or_expression_data(self):
        assert bed.lethality_features({"o": ["x", "1:1"]}) is None
        full = bed.lethality_features({"c": ["C", 80.0, 1000], "l": 0.2, "t": [0.4, 40, [1]], "p": [["B", 60]]})
        assert full == [0.8, 0.0, 1.0, 0.2, 0.0, 0.4, 40 / 54.0, 1.0]
        sparse = bed.lethality_features({"l": 5.0})                              # LOEUF is capped, the rest is marked missing
        assert sparse[0] == 0.0 and sparse[1] == 1.0 and sparse[3] == 2.0 and sparse[4] == 0.0

    def test_the_model_learns_a_clear_signal(self):
        import random
        generator = random.Random(4)
        rows = []
        for _ in range(400):
            lethal = generator.random() < 0.4
            percent = generator.uniform(0.5, 1.0) if lethal else generator.uniform(0.0, 0.5)
            rows.append((1 if lethal else 0, [percent, 0.0, 0.0, generator.uniform(0, 2), 0.0, 0.5, 0.5, 0.0]))
        model = bed.fit_lethality_model(rows)

        scores = [bed.lethality_probability(model, x) for _, x in rows]
        assert bed.rank_auc([y for y, _ in rows], scores) > 0.95
        assert all(0.0 <= s <= 1.0 for s in scores)

    def test_estimates_are_given_only_to_unmeasured_one_to_one_orthologs(self, monkeypatch):
        import random
        generator = random.Random(2)
        human, mouse = {}, {}
        pairs_by_id = {}
        for i in range(700):                               # genes with a mouse knockout: the training data
            lethal = generator.random() < 0.4
            pct = generator.uniform(60, 100) if lethal else generator.uniform(0, 30)
            human[f"G{i}"] = {"o": [f"G{i}", "1:1"], "m": {"v": "L" if lethal else "V", "n": [1, 0, 0]},
                              "c": ["", pct, 1000], "l": 0.5, "t": [0.4, 30, []]}
            mouse[f"G{i}".upper()] = {"v": "L"}
            pairs_by_id[f"HGNC:{i}"] = (f"MGI:{i}", f"G{i}", "1:1", f"G{i}")
        human["NEW1"] = {"c": ["C", 95.0, 1000], "l": 0.1, "t": [0.4, 30, []]}                  # never knocked out
        human["NEW2"] = {"c": ["", 1.0, 1000], "l": 1.5, "t": [0.4, 30, []]}
        human["MANY"] = {"c": ["C", 95.0, 1000]}                                                    # not a one-to-one ortholog
        human["NODATA"] = {"o": None}
        pairs_by_id["HGNC:n1"] = ("MGI:n1", "New1", "1:1", "NEW1")
        pairs_by_id["HGNC:n2"] = ("MGI:n2", "New2", "1:1", "NEW2")
        pairs_by_id["HGNC:n3"] = ("MGI:n3", "Many", "n:1", "MANY")
        monkeypatch.setattr(bed, "orthologs_to_mouse", lambda pairs, tax: pairs_by_id)

        model = bed.add_lethality_estimates(human, {}, mouse, {"NEW1": [["NEW1B", 70]]}, [])

        assert model["tested"]["auc"] > 0.9
        assert human["NEW1"]["pl"][1] == "New1" and human["NEW1"]["pl"][0] > 0.5
        assert human["NEW2"]["pl"][0] < 0.3
        assert "pl" not in human["MANY"] and "pl" not in human["G0"]                     # not 1:1, and measured genes are left alone
        stub = mouse["NEW1"]
        assert stub["pl"] == [human["NEW1"]["pl"][0], "NEW1"] and stub["p"] == [["NEW1B", 70]] and "v" not in stub
        assert bed.count_measured(mouse) == 700                                       # a stub is not a measurement

    def test_too_few_genes_give_no_model(self):
        human = {f"G{i}": {"o": ["g", "1:1"], "m": {"v": "L"}, "c": ["", 50.0, 10]} for i in range(20)}

        assert bed.add_lethality_estimates(human, {}, {}, {}, []) is None


class TestGeneFacts:
    HEADER = ("Gene1ID\tGene1Symbol\tGene1SpeciesTaxonID\tGene1SpeciesName\tGene2ID\tGene2Symbol\tGene2SpeciesTaxonID\t"
              "Gene2SpeciesName\tAlgorithms\tAlgorithmsMatch\tOutOfAlgorithms\tIsBestScore\tIsBestRevScore\n")

    @staticmethod
    def row(id1, sym1, tax1, id2, sym2, tax2, matched, best="No", best_rev="No"):
        return f"{id1}\t{sym1}\tNCBITaxon:{tax1}\tx\t{id2}\t{sym2}\tNCBITaxon:{tax2}\ty\tA|B\t{matched}\t9\t{best}\t{best_rev}\n"

    def table(self):
        return io.StringIO(self.HEADER
                           + self.row("HGNC:1", "PCNA", 9606, "MGI:1", "Pcna", 10090, 9, "Yes", "Yes")
                           + self.row("HGNC:1", "PCNA", 9606, "FB:1", "mus209", 7227, 5)
                           + self.row("HGNC:1", "PCNA", 9606, "WB:1", "pcn-1", 6239, 2, "Yes", "Yes")      # two algorithms, best both ways
                           + self.row("HGNC:1", "PCNA", 9606, "RGD:1", "Pcna", 10116, 1, "Yes", "Yes")     # a single algorithm: not enough
                           + self.row("HGNC:2", "SMUG1", 9606, "MGI:2", "Smug1", 10090, 8, "Yes", "Yes")
                           + self.row("HGNC:2", "SMUG1", 9606, "SGD:1", "UNG1", 559292, 2))                 # two algorithms, not the best pair

    def test_which_model_species_carry_an_ortholog(self):
        taxa = {"9606", "10090", "10116", "7227", "6239", "559292"}
        orthologs, ids = bed.read_conservation(self.table(), taxa)

        assert orthologs["HGNC:1"] == {"10090", "7227", "6239"}                   # not rat: one algorithm is too little
        assert orthologs["MGI:1"] == {"9606"} and orthologs["HGNC:2"] == {"10090"}
        assert bed.conservation_bits("9606", "pcna", orthologs, ids) == 0b11011         # human, mouse, fly, worm
        assert bed.conservation_bits("10090", "Pcna", orthologs, ids) == 0b00011        # mouse and human only
        assert bed.conservation_bits("9606", "SMUG1", orthologs, ids) == 0b00011
        assert bed.conservation_bits("559292", "UNG1", orthologs, ids) == 0               # yeast is not one of the five
        assert bed.conservation_bits("9606", "NOSUCHGENE", orthologs, ids) is None

    def test_gene_info_maps_symbols_and_locus_tags_to_gene_ids(self):
        text = ("#tax_id\tGeneID\tSymbol\tLocusTag\tSynonyms\tdbXrefs\tchromosome\tmap_location\tdescription\ttype_of_gene\t"
                "Symbol_from_nomenclature_authority\n"
                "559292\t850\tACT1\tYFL039C\t-\t-\tVI\t-\tactin\tprotein-coding\tACT1\n"
                "9606\t5111\tPCNA\t-\tPOLD\t-\t20\t-\tproliferating cell nuclear antigen\tprotein-coding\tPCNA\n")

        ids, synonyms = bed.read_gene_info(io.StringIO(text))

        assert ids == {"ACT1": "850", "YFL039C": "850", "PCNA": "5111"}
        assert synonyms == {"POLD": "PCNA"}

    def test_an_official_symbol_beats_the_locus_tag_or_nomenclature_symbol_of_another_gene(self):
        text = ("#tax_id\tGeneID\tSymbol\tLocusTag\tSynonyms\tdbXrefs\tchromosome\tmap_location\tdescription\ttype_of_gene\t"
                "Symbol_from_nomenclature_authority\n"
                "559292\t111\tOTHER\tRPS3\t-\t-\tI\t-\td\tprotein-coding\t-\n"           # another gene whose locus tag is RPS3
                "559292\t855543\tRPS3\tYNL178W\t-\t-\tXIV\t-\td\tprotein-coding\tRPS3\n")

        ids, _ = bed.read_gene_info(io.StringIO(text))

        assert ids["RPS3"] == "855543" and ids["OTHER"] == "111" and ids["YNL178W"] == "855543"

    def test_older_names_become_aliases_only_when_they_point_to_one_gene(self):
        text = ("#tax_id\tGeneID\tSymbol\tLocusTag\tSynonyms\tdbXrefs\tchromosome\tmap_location\tdescription\ttype_of_gene\t"
                "Symbol_from_nomenclature_authority\n"
                "10090\t1\tTrp53bp1\t-\tTp53bp1|53BP1\t-\t2\t-\td\tprotein-coding\tTrp53bp1\n"
                "10090\t2\tMre11a\t-\tMre11|SHARED\t-\t9\t-\td\tprotein-coding\tMre11a\n"
                "10090\t3\tOther\t-\tSHARED|Trp53bp1\t-\t1\t-\td\tprotein-coding\tOther\n")

        ids, synonyms = bed.read_gene_info(io.StringIO(text))

        assert synonyms == {"TP53BP1": "Trp53bp1", "53BP1": "Trp53bp1", "MRE11": "Mre11a"}     # SHARED is ambiguous, TRP53BP1 is an official symbol

    def test_aliases_are_added_for_genes_in_the_file_and_never_for_a_name_that_is_a_gene(self):
        files = {"10090": {"genes": {"TRP53BP1": {}, "MRE11A": {}, "TP53BP1": {}}, "aliases": {}}}
        synonyms = {"TP53BP1": "Trp53bp1", "MRE11": "Mre11a", "GONE": "Absent"}

        bed.add_gene_facts(files, None, {}, {"10090": ({}, {}, synonyms)})

        assert files["10090"]["aliases"] == {"MRE11": "Mre11a"}        # TP53BP1 is itself a record; GONE points to no record

    def test_articles_are_counted_per_gene_for_the_wanted_species_only(self):
        text = "#tax_id\tGeneID\tPubMed_ID\n9606\t5111\t101\n9606\t5111\t102\n10090\t18538\t7\n3702\t99\t1\n"

        counts = bed.read_gene2pubmed(io.StringIO(text), {"9606", "10090"})

        assert counts == {"5111": 2, "18538": 1}

    def test_the_facts_are_put_on_the_genes_that_have_them(self):
        orthologs, ids = bed.read_conservation(self.table(), {"9606", "10090", "7227", "6239", "10116"})
        files = {"9606": {"genes": {"PCNA": {}, "SMUG1": {"c": ["", 1.0, 5]}, "NOPE": {}}}, "10090": {"genes": {"PCNA": {}}}}
        literature = {"9606": ({"PCNA": "5111", "SMUG1": "23583"}, {"5111": 2}, {})}

        bed.add_gene_facts(files, orthologs, ids, literature)

        assert files["9606"]["genes"]["PCNA"] == {"cv": 0b11011, "lc": 2}
        assert files["9606"]["genes"]["SMUG1"]["lc"] == 0 and files["9606"]["genes"]["SMUG1"]["cv"] == 0b00011   # a known gene with no articles
        assert files["9606"]["genes"]["NOPE"] == {}                                                           # unknown to both: nothing is invented
        assert files["10090"]["genes"]["PCNA"] == {"cv": 0b00011}                                              # mouse symbols match, no literature file

    def test_two_names_of_one_gene_get_their_own_copy_of_the_record(self):
        shared = {"v": "L"}
        files = {"559292": {"genes": {"RPS3": shared, "YNL178W": shared}, "aliases": {}}}
        literature = {"559292": ({"RPS3": "1", "YNL178W": "2"}, {"1": 5, "2": 7}, {})}

        bed.add_gene_facts(files, None, {}, literature)

        assert files["559292"]["genes"]["RPS3"]["lc"] == 5 and files["559292"]["genes"]["YNL178W"]["lc"] == 7

    def test_a_build_without_the_ncbi_files_has_no_literature(self):
        orthologs, ids = bed.read_conservation(self.table(), {"9606"})
        files = {"9606": {"genes": {"PCNA": {}}}}

        bed.add_gene_facts(files, orthologs, ids, {})

        assert "lc" not in files["9606"]["genes"]["PCNA"] and "cv" in files["9606"]["genes"]["PCNA"]


class TestDownloader:
    class Response:
        def __init__(self, chunks, fail_after=None):
            self.chunks, self.fail_after = chunks, fail_after

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, size):
            for number, chunk in enumerate(self.chunks):
                if self.fail_after is not None and number >= self.fail_after:
                    raise bed.requests.ConnectionError("connection lost")
                yield chunk

    def test_a_download_that_breaks_off_leaves_no_file_behind(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bed.time, "sleep", lambda seconds: None)
        monkeypatch.setattr(bed.requests, "get", lambda *a, **k: self.Response([b"abc", b"def"], fail_after=1))

        with pytest.raises(bed.requests.ConnectionError):
            bed.Downloader(tmp_path).fetch("source.tsv", "https://example.org/source.tsv")

        assert not (tmp_path / "source.tsv").exists()

    def test_a_retry_after_a_broken_download_gives_the_whole_file(self, tmp_path, monkeypatch):
        answers = iter([self.Response([b"abc", b"def"], fail_after=1), self.Response([b"abc", b"def"])])
        monkeypatch.setattr(bed.time, "sleep", lambda seconds: None)
        monkeypatch.setattr(bed.requests, "get", lambda *a, **k: next(answers))

        path = bed.Downloader(tmp_path).fetch("source.tsv", "https://example.org/source.tsv")

        assert path.read_bytes() == b"abcdef" and not list(tmp_path.glob("*.part"))


class TestHumanLayers:
    def test_gnomad_uses_the_mane_select_transcript(self, tmp_path):
        path = tmp_path / "constraint.tsv"
        path.write_text(
            "gene\tgene_id\tmane_select\tlof.oe_ci.upper\n"
            "TDG\tENSG1\ttrue\t0.8112\n"
            "TDG\tENSG1\tfalse\t0.2\n"
            "OLD\t5\ttrue\t0.5\n"
            "NA1\tENSG2\ttrue\tNA\n", encoding="utf-8")

        assert bed.read_gnomad(path) == {"ENSG1": 0.811}

    def test_gtex_tau_and_top_tissues(self, tmp_path):
        path = tmp_path / "gtex.gct.gz"
        rows = ["#1.2", "3\t3", "Name\tDescription\tLiver\tBrain\tHeart",
                "ENSG1.4\tUBIQ\t10\t10\t10",           # same everywhere -> tau 0
                "ENSG2.1\tSPEC\t100\t0\t0",            # one tissue -> tau 1
                "ENSG3.1\tLOW\t0.2\t0\t0.1"]
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write("\n".join(rows) + "\n")

        result, tissues = bed.read_gtex(path)

        assert tissues == ["Liver", "Brain", "Heart"]
        assert result["ENSG1"] == (0.0, 3, [0, 1, 2])
        assert result["ENSG2"] == (1.0, 1, [0])
        assert result["ENSG3"] == (None, 0, [])

    def test_older_gene_names_only_when_they_point_to_one_gene(self, tmp_path):
        path = tmp_path / "hgnc.tsv"
        path.write_text(
            "hgnc_id\tsymbol\tstatus\tprev_symbol\talias_symbol\n"
            "HGNC:1\tAARS1\tApproved\tAARS\t\n"
            "HGNC:2\tONE\tApproved\t\tSHARED|P53LIKE\n"
            "HGNC:3\tTWO\tApproved\t\tSHARED\n"
            "HGNC:4\tGONE\tWithdrawn\tOLDNAME\t\n", encoding="utf-8")

        assert bed.hgnc_aliases(path) == {"AARS": "AARS1", "P53LIKE": "ONE"}


class TestParalogs:
    ROWS = [
        "gene\tparalog\tidentity\tancestor",
        "PARP1\tPARP2\t38.5\tEuteleostomi",
        "PARP1\tPARP3\t31.2\tVertebrata",
        "PARP1\tPARP1\t100\tHomo sapiens",              # itself
        "PARP1\tTNKS\t20.1\tEuteleostomi",               # too different
        "PARP1\tRNU2-1P\t55\tEuteleostomi",              # a pseudogene (removed by the allowed set)
        "PARP1\tOLDGENE\t45\tBilateria",                 # split before the vertebrates
        "PARP1\tPARP2\t35.0\tEuteleostomi",              # the same paralog again: the better score is kept
        "PARP1\tPARP4\t33.0\tEuteleostomi",
        "PARP1\tPARP6\t32.0\tEuteleostomi",
        "LIG1\t\t50\tEuteleostomi",                      # no paralog name
    ]

    def test_which_rows_are_kept(self):
        keep = bed.keep_paralog_row
        assert keep(["A", "B", "45", "Euteleostomi"])
        assert not keep(["A", "A", "45", "Euteleostomi"])
        assert not keep(["A", "B", "25", "Euteleostomi"])
        assert not keep(["A", "B", "45", "Opisthokonta"])
        assert not keep(["A", "", "45", "Euteleostomi"])
        assert not keep(["A", "B", "not a number", "Euteleostomi"])

    def test_the_closest_paralogs_of_each_gene(self):
        found = bed.parse_paralogs(self.ROWS, allowed_paralogs={"PARP2", "PARP3", "PARP4", "PARP6", "TNKS"})

        # the three closest, best first; PARP3 (31%) is the fourth, the pseudogene and the ancient paralog are gone
        assert found["PARP1"] == [["PARP2", 38], ["PARP4", 33], ["PARP6", 32]]
        assert "LIG1" not in found

    def test_genes_can_be_restricted_to_protein_coding_ones(self):
        found = bed.parse_paralogs(self.ROWS, allowed_genes={"LIG1"})

        assert found == {}


class TestOtherSpecies:
    FLY = ("Gene1ID\tGene1Symbol\tGene1SpeciesTaxonID\tGene1SpeciesName\tGene2ID\tGene2Symbol\tGene2SpeciesTaxonID\tGene2SpeciesName\t"
           "Algorithms\tAlgorithmsMatch\tOutOfAlgorithms\tIsBestScore\tIsBestRevScore\n"
           "FB:FBgn1\tdTdg\tNCBITaxon:7227\tDrosophila melanogaster\tMGI:10\tTdg\tNCBITaxon:10090\tMus musculus\tA|B\t5\t9\tYes\tYes\n")

    def test_a_distant_species_carries_the_mouse_record_without_the_mouse_extras(self):
        pairs = bed.parse_orthology(io.StringIO(self.FLY), wanted={frozenset(("7227", "10090"))})
        mouse = {"TDG": {"v": "L", "n": [3, 0, 0], "s": "E", "p": [["OTHER", 50]], "t": [0.5, 3, [0]]}}

        records = bed.build_inferred(pairs, "7227", mouse, {})

        assert records == {"DTDG": {"o": ["Tdg", "1:1"], "m": {"v": "L", "n": [3, 0, 0], "s": "E"}}}
        assert "7955" in bed.DISTANT and "7227" in bed.DISTANT and "6239" in bed.DISTANT

    def test_only_genes_with_a_knockout_result_count_as_measured(self):
        genes = {"A": {"v": "L"}, "B": {"o": ["Tdg", "1:1"], "m": {"v": "V"}}, "C": {"c": ["E", 90.0, 1000]},
                 "D": {"t": [0.5, 3, [0]], "l": 0.3}}          # D has expression and constraint only

        assert bed.count_measured(genes) == 3

    def test_an_organism_without_a_single_gene_gets_no_file(self, capsys, tmp_path):
        files = {"7227": {"genes": {"DTDG": {}}, "aliases": {}}, "8355": {"genes": {}, "aliases": {}}}
        index = {"7227": {"name": "Drosophila melanogaster"}, "8355": {"name": "Xenopus laevis"}}
        (tmp_path / "8355.json").write_text("{}")                      # left over from an earlier build

        bed.drop_empty_organisms(files, index, tmp_path)

        assert list(files) == ["7227"] and list(index) == ["7227"]
        assert not (tmp_path / "8355.json").exists()
        assert "Xenopus laevis" in capsys.readouterr().out


class TestZebrafish:
    STAGES = ["ZDB-STAGE-1\tZFS:1\tZygote\t0.00\t0.75", "ZDB-STAGE-2\tZFS:2\tLarval\t96.00\t120.00",
              "ZDB-STAGE-3\tZFS:3\tAdult\t2160.00\t17520.00", "ZDB-STAGE-050211-1\tZFS:0\tUnknown\t0.00\t17520.00"]
    FEATURES = [
        "ZDB-ALT-1\tSO:1\ta1\tgene1\tZDB-GENE-1\tSO:2\tis allele of\tPOINT_MUTATION\tSO:3\tC\t\t\t\t\t\t\t\t\t\t\t\tpremature stop\tSO:4",
        "ZDB-ALT-2\tSO:1\ta2\tgene1\tZDB-GENE-1\tSO:2\tis allele of\tPOINT_MUTATION\tSO:3\tC\t\t\t\t\t\t\t\t\t\t\t\tmissense\tSO:4",
        "ZDB-ALT-3\tSO:1\ta3\tgene2\tZDB-GENE-2\tSO:2\tis allele of\tDELETION",
        "ZDB-ALT-4\tSO:1\ta4\tgene3\tZDB-GENE-3\tSO:2\tis allele of\tTRANSLOC",
    ]

    def fish_lines(self):
        def line(fish, name, gene, allele, construct="", reagent=""):
            return f"{fish}\t{name}\t{gene}\tsym\t{allele}\tal\t{construct}\t\t{reagent}\t\tZDB-GENO-{fish}\t{name}"
        return [line("F1", "gene1<sup>a1/a1</sup>", "ZDB-GENE-1", "ZDB-ALT-1"),
                line("F2", "gene1<sup>a2/a2</sup>", "ZDB-GENE-1", "ZDB-ALT-2"),
                line("F3", "gene2<sup>a3/a3</sup>", "ZDB-GENE-2", "ZDB-ALT-3"),
                line("F4", "gene1<sup>a1/+</sup>", "ZDB-GENE-1", "ZDB-ALT-1"),                       # heterozygous
                line("F5", "gene1<sup>a1/a1</sup>", "ZDB-GENE-1", "ZDB-ALT-1", construct="ZDB-TG-1"),  # carries a transgene
                line("F6", "gene1<sup>a1/a1</sup> + MO1-gene1", "ZDB-GENE-1", "ZDB-ALT-1", reagent="ZDB-MRPHLNO-1"),
                line("F7", "gene3<sup>a4/a4</sup>", "ZDB-GENE-3", "ZDB-ALT-4")]                      # a translocation

    def test_only_clean_homozygous_mutants_of_one_gene_are_kept(self):
        features = bed.parse_zfin_features(self.FEATURES)

        assert features == {"ZDB-ALT-1": "null", "ZDB-ALT-2": "other", "ZDB-ALT-3": "null", "ZDB-ALT-4": None}
        assert bed.parse_zfin_fish(self.fish_lines(), features) == {
            "F1": ("ZDB-GENE-1", "null"), "F2": ("ZDB-GENE-1", "other"), "F3": ("ZDB-GENE-2", "null")}

    def phenotype(self, fish, gene, symbol, pato, name, tag="abnormal", structure="ZFA:0001094", stage="ZDB-STAGE-2", pub="ZDB-PUB-1"):
        cols = [""] * 25
        cols[0], cols[1], cols[2] = "1", symbol, gene
        cols[7], cols[9], cols[10], cols[11] = structure, pato, name, tag
        cols[18], cols[20], cols[21], cols[23] = fish, stage, stage, pub
        return "\t".join(cols)

    def test_death_viability_and_stage(self):
        stages = bed.parse_zfin_stages(self.STAGES)
        fish = {"F1": ("ZDB-GENE-1", "null"), "F2": ("ZDB-GENE-1", "other"), "F3": ("ZDB-GENE-2", "null")}
        lines = [
            self.phenotype("F1", "ZDB-GENE-1", "gene1", "PATO:0001422", "dead", stage="ZDB-STAGE-2"),
            self.phenotype("F2", "ZDB-GENE-1", "gene1", "PATO:0000718", "lethal (sensu genetics)", stage="ZDB-STAGE-1"),
            # a heart phenotype of a living adult: the null fish survived
            self.phenotype("F3", "ZDB-GENE-2", "gene2", "PATO:0000001", "quality", structure="ZFA:0000114", stage="ZDB-STAGE-3"),
        ]

        records = bed.build_zebrafish(lines, fish, stages, {"ZDB-PUB-1": "123"})

        assert records["GENE1"] == {"v": "L", "n": [2, 0, 0], "s": "E", "src": "Z", "pm": [123]}
        assert records["GENE2"] == {"v": "V", "n": [0, 0, 1], "src": "Z", "pm": [123]}

    def test_a_larval_phenotype_does_not_prove_viability_and_an_unclear_allele_cannot_prove_it(self):
        stages = bed.parse_zfin_stages(self.STAGES)
        fish = {"F1": ("ZDB-GENE-1", "null"), "F2": ("ZDB-GENE-2", "other")}
        lines = [self.phenotype("F1", "ZDB-GENE-1", "gene1", "PATO:1", "q", structure="ZFA:5", stage="ZDB-STAGE-2"),
                 self.phenotype("F2", "ZDB-GENE-2", "gene2", "PATO:1", "q", structure="ZFA:5", stage="ZDB-STAGE-3")]

        assert bed.build_zebrafish(lines, fish, stages, {}) == {}

    def test_the_stage_letters(self):
        stages = bed.parse_zfin_stages(self.STAGES)

        assert [bed.zfin_stage_letter(s, stages) for s in ("ZDB-STAGE-1", "ZDB-STAGE-2", "ZDB-STAGE-3", "ZDB-STAGE-050211-1", "x")] \
            == ["E", "L", "A", "U", "U"]


class TestFly:
    ALLELES = [
        "#Allele\tid\tgene\tgeneid\tclass\tclassid\tinsertion",
        "g1[1]\tFBal1\tg1\tFBgn1\tamorphic allele - genetic evidence\tFBcv:1\t",
        "g1[2]\tFBal2\tg1\tFBgn1\thypomorphic allele - genetic evidence\tFBcv:2\t",
        "g2[1]\tFBal3\tg2\tFBgn2\tamorphic allele - molecular evidence\tFBcv:1\t",
        "g3[D]\tFBal4\tg3\tFBgn3\tgain of function allele\tFBcv:3\t",
        "g4[ts]\tFBal5\tg4\tFBgn4\theat sensitive loss of function allele\tFBcv:4\t",
        "g5[P1]\tFBal6\tg5\tFBgn5\t\t\tFBti1",                      # a transposon insertion, class not stated
        "g6[x]\tFBal7\tg6\tFBgn6\t\t\t",                             # nothing known about the effect
        "Scer\\GAL4[x]\tFBal8\tScer\\GAL4\tnone\tamorphic allele\tFBcv:1\t",
    ]

    def row(self, allele, name, term, qualifiers="", ref="FBrf1"):
        return f"sym\t{allele}\t{name}\t{term}\t{qualifiers}\t\t{ref}"

    def test_which_alleles_describe_a_loss_of_the_gene(self):
        alleles = bed.parse_fly_alleles(self.ALLELES)

        assert alleles == {"FBal1": ("FBgn1", "g1", "null"), "FBal2": ("FBgn1", "g1", "hypo"), "FBal3": ("FBgn2", "g2", "null"),
                           "FBal6": ("FBgn5", "g5", "insertion")}

    def test_lethal_partial_and_viable_calls(self):
        alleles = bed.parse_fly_alleles(self.ALLELES)
        lines = [
            self.row("FBal1", "lethal - all die during embryonic stage", "FBcv:0002033"),
            self.row("FBal2", "lethal - all die before end of larval stage", "FBcv:0002002", ref="FBrf2"),
            self.row("FBal3", "viable", "FBcv:0000349"),
            self.row("FBal6", "partially lethal - majority die", "FBcv:0000352"),
            self.row("FBal4", "lethal", "FBcv:0000351"),                      # not in the allele table
        ]

        records = bed.build_fly(lines, alleles, {"FBrf1": "11", "FBrf2": "12"})

        assert records["G1"] == {"v": "L", "n": [2, 0, 0], "s": "E", "src": "F", "pm": [11, 12]}
        assert records["G2"] == {"v": "V", "n": [0, 0, 1], "src": "F", "pm": [11]}
        assert records["G5"] == {"v": "S", "n": [0, 1, 0], "s": "U", "src": "F", "pm": [11]}
        assert "G3" not in records

    def test_dominant_maternal_and_conditional_findings_are_not_a_knockout(self):
        alleles = bed.parse_fly_alleles(self.ALLELES)
        lines = [self.row("FBal1", "lethal", "FBcv:0000351", "dominant"),
                 self.row("FBal1", "lethal", "FBcv:0000351", "maternal effect|recessive"),
                 self.row("FBal3", "lethal", "FBcv:0000351", "heat sensitive")]

        assert bed.build_fly(lines, alleles, {}) == {}

    def test_viability_needs_a_null_allele_and_sterility_is_noted(self):
        alleles = bed.parse_fly_alleles(self.ALLELES)
        lines = [self.row("FBal2", "viable", "FBcv:0000349"),               # a hypomorph says nothing about the null
                 self.row("FBal3", "viable", "FBcv:0000349"), self.row("FBal3", "female sterile", "FBcv:0000366")]

        records = bed.build_fly(lines, alleles, {})

        assert "G1" not in records
        assert records["G2"]["v"] == "V" and records["G2"]["f"] == 1

    def test_the_stage_of_death(self):
        assert [bed.fly_stage_letter(n) for n in ("lethal - all die during embryonic stage", "lethal - all die before end of larval stage",
                                                  "lethal - all die during pharate adult stage", "lethal - all die during adult stage",
                                                  "lethal")] == ["E", "L", "L", "A", "U"]

    def test_pubmed_ids_of_references(self):
        lines = ["#header", "FBrf1\t123\tPMC1\t10.1/x", "FBrf2\t\t\t", "FBrf3\tnone\t"]

        assert bed.parse_fly_references(lines) == {"FBrf1": "123"}


class TestWorm:
    OBO = ["[Term]", "id: WBPhenotype:0000062", "name: lethal", "", "[Term]", "id: WBPhenotype:0000050", "name: embryonic lethal",
           "is_a: WBPhenotype:0000062 ! lethal", "", "[Term]", "id: WBPhenotype:0000054", "name: larval lethal",
           "is_a: WBPhenotype:0000062 ! lethal", "", "[Term]", "id: WBPhenotype:0000060", "name: adult lethal",
           "is_a: WBPhenotype:0000062 ! lethal", "", "[Term]", "id: WBPhenotype:0000688", "name: sterile", "",
           "[Term]", "id: WBPhenotype:0000001", "name: unrelated"]

    @staticmethod
    def row(gene, symbol, term, experiment, negated="", ref="WBPaper1", sequence="Y1.1"):
        return f"WB\t{gene}\t{symbol}\t{negated}\t{term}\tWB_REF:{ref}\tIMP\tWB:{experiment}\tP\t\t{sequence}\tgene\ttaxon:6239"

    def ontology(self):
        return bed.MPOntology(self.OBO)

    def test_lethal_alleles_and_stage(self):
        lines = ["!gaf-version: 2.0",
                 self.row("WBGene1", "aaa-1", "WBPhenotype:0000050", "WBVar1"),
                 self.row("WBGene1", "aaa-1", "WBPhenotype:0000054", "WBVar2", ref="WBPaper2"),
                 self.row("WBGene1", "aaa-1", "WBPhenotype:0000001", "WBVar3")]            # unrelated phenotype

        records, aliases = bed.build_worm(lines, self.ontology(), {"WBPaper1": "11", "WBPaper2": "12"})

        assert records == {"AAA-1": {"v": "L", "n": [2, 0, 0], "s": "E", "src": "W", "pm": [11, 12]}}
        assert aliases == {"Y1.1": "aaa-1"}

    def test_rnai_only_lethality_is_marked_and_not_counted_as_a_mutant(self):
        lines = [self.row("WBGene1", "aaa-1", "WBPhenotype:0000050", "WBRNAi1"),
                 self.row("WBGene2", "bbb-1", "WBPhenotype:0000050", "WBRNAi2"),
                 self.row("WBGene2", "bbb-1", "WBPhenotype:0000054", "WBVar9")]

        records, _ = bed.build_worm(lines, self.ontology(), {})

        assert records["AAA-1"]["k"] == 1
        assert "k" not in records["BBB-1"]

    def test_a_gene_is_viable_only_when_several_alleles_are_reported_not_lethal(self):
        one = [self.row("WBGene1", "aaa-1", "WBPhenotype:0000062", "WBVar1", negated="NOT")]
        two = one + [self.row("WBGene1", "aaa-1", "WBPhenotype:0000062", "WBVar2", negated="NOT")]
        rnai = [self.row("WBGene1", "aaa-1", "WBPhenotype:0000062", f"WBRNAi{i}", negated="NOT") for i in range(3)]
        mixed = two + [self.row("WBGene1", "aaa-1", "WBPhenotype:0000050", "WBVar3")]

        assert bed.build_worm(one, self.ontology(), {})[0] == {}
        assert bed.build_worm(rnai, self.ontology(), {})[0] == {}              # a knockdown that does not kill is weak evidence
        assert bed.build_worm(two, self.ontology(), {})[0]["AAA-1"] == {"v": "V", "n": [0, 0, 2], "src": "W"}
        record = bed.build_worm(mixed, self.ontology(), {})[0]["AAA-1"]
        assert record["v"] == "V" and record["x"] == 1 and record["n"] == [1, 0, 2]

    def test_sterility_of_an_allele_is_noted(self):
        lines = [self.row("WBGene1", "aaa-1", "WBPhenotype:0000688", "WBVar1")] + \
                [self.row("WBGene1", "aaa-1", "WBPhenotype:0000062", f"WBVar{i}", negated="NOT") for i in (2, 3)]

        assert bed.build_worm(lines, self.ontology(), {})[0]["AAA-1"]["f"] == 1

    def test_papers_with_a_pubmed_id(self):
        data = {"data": [{"evidence": {"crossReference": {"id": "WB:WBPaper00001"}, "publicationId": "PMID:77"}},
                         {"evidence": {"crossReference": {"id": "WB:WBPaper00002"}, "publicationId": "DOI:x"}}]}

        assert bed.parse_worm_papers(data) == {"WBPaper00001": "77"}


class TestOwnMeasurementsBesideTheMouseHint:
    def test_a_directory_listing_gives_the_newest_release(self, monkeypatch):
        class Page:
            text = ('<a href="x_fb_2025_05.tsv.gz">a</a><a href="x_fb_2026_03.tsv.gz">b</a><a href="x_fb_2026_01.tsv.gz">c</a>'
                    '<a href="y_fb_2027_01.tsv.gz">d</a>')

            def raise_for_status(self):
                pass
        monkeypatch.setattr(bed.requests, "get", lambda *a, **k: Page())

        assert bed.latest_in_listing("https://h/dir/", r"x_fb_(\d{4}_\d{2})\.tsv\.gz") == "https://h/dir/x_fb_2026_03.tsv.gz"
        assert bed.latest_in_listing("https://h/dir/", r"y_fb_(\d{4}_\d{2})\.tsv\.gz") == "https://h/dir/y_fb_2027_01.tsv.gz"

    def test_releases_are_compared_as_numbers(self, monkeypatch):
        class Page:
            text = '<a href="p.WS99.wb.gz">a</a><a href="p.WS100.wb.gz">b</a>'

            def raise_for_status(self):
                pass
        monkeypatch.setattr(bed.requests, "get", lambda *a, **k: Page())

        assert bed.latest_in_listing("https://h/", r"p\.(WS\d+)\.wb\.gz", key=lambda v: int(v[2:])) == "https://h/p.WS100.wb.gz"

    def test_an_address_is_only_looked_up_when_the_file_is_missing(self, tmp_path):
        calls = []
        downloader = bed.Downloader(tmp_path)
        (tmp_path / "have.txt").write_text("data")

        path = downloader.fetch("have.txt", lambda: calls.append(1) or "https://h/never")

        assert path.read_text() == "data" and calls == [] and downloader.log["have.txt"]["url"] == "cached"

    def test_a_mouse_hint_and_a_measurement_of_its_own_share_one_record(self):
        pairs = bed.parse_orthology(io.StringIO(TestOtherSpecies.FLY), wanted={frozenset(("7227", "10090"))})
        mouse = {"TDG": {"v": "L", "n": [3, 0, 0], "s": "E"}}
        records = bed.build_inferred(pairs, "7227", mouse, {})
        records.setdefault("DTDG", {}).update({"v": "V", "n": [0, 0, 2], "src": "F"})

        assert records["DTDG"]["m"]["v"] == "L" and records["DTDG"]["v"] == "V"
        assert bed.count_measured({"A": {"o": ["x", "1:1"], "m": {"v": "L"}}, "B": {"v": "L"}}, own_only=True) == 1
        assert bed.count_measured({"A": {"o": ["x", "1:1"], "m": {"v": "L"}}, "B": {"v": "L"}}) == 2

    def test_an_organism_whose_files_are_missing_is_left_out_with_a_warning(self, capsys):
        assert bed.build_model_organisms({}, bed.MODEL_ORGANISMS) == {}
        assert capsys.readouterr().out.count("WARNING") == 3

    def test_the_community_databases_are_optional_and_the_licences_are_recorded(self):
        for key in ("zfin", "flybase", "wormbase"):
            assert bed.SOURCES[key]["optional"] and bed.SOURCES[key]["license"]
        assert not any(s.get("optional") for key, s in bed.SOURCES.items() if key not in ("zfin", "flybase", "wormbase", "ncbi"))     # the NCBI literature counts are optional too
