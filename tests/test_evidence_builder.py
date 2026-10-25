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
        assert human["HGNC:2"][2] == "n:1" and human["HGNC:3"][2] == "n:1"      # two human genes share one mouse gene
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
