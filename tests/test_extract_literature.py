"""tools/extract_literature.py: the abstract reader checks every answer of the model against the abstract. No network is used here."""

import gzip
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("extract_literature", ROOT / "tools" / "extract_literature.py")
el = importlib.util.module_from_spec(spec)
sys.modules["extract_literature"] = el
spec.loader.exec_module(el)

ABSTRACT = ("Loss of Abc1 in mice. Homozygous Abc1 knockout embryos died at embryonic day 10.5, showing that the gene is essential "
            "for development.  Heterozygous animals were normal.")
QUOTE = "Homozygous Abc1 knockout embryos died at embryonic day 10.5"


class FakeResponse:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code, self._payload, self.content = status, payload or {}, content

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise el.requests.HTTPError(str(self.status_code))


def answer(outcome, quote="", stage=""):
    return json.dumps({"outcome": outcome, "stage": stage, "quote": quote})


class TestCheckAnswer:
    def test_an_answer_with_a_quote_from_the_abstract_is_accepted_even_if_spacing_and_case_differ(self):
        checked = el.check_answer(answer("lethal", QUOTE.lower().replace(" ", "  "), "E10.5"), ABSTRACT)

        assert checked["outcome"] == "lethal" and checked["stage"] == "E10.5"

    def test_an_invented_quote_is_thrown_away(self):
        assert el.check_answer(answer("lethal", "Knockout mice died within hours of birth in every litter"), ABSTRACT) is None

    def test_a_result_without_a_quote_is_thrown_away(self):
        assert el.check_answer(answer("lethal", ""), ABSTRACT) is None
        assert el.check_answer(answer("viable", "short"), ABSTRACT) is None

    def test_not_reported_needs_no_quote(self):
        assert el.check_answer(answer("not_reported"), ABSTRACT)["outcome"] == "not_reported"

    def test_malformed_answers_are_thrown_away(self):
        assert el.check_answer("not json at all", ABSTRACT) is None
        assert el.check_answer(answer("probably lethal", QUOTE), ABSTRACT) is None
        assert el.check_answer(None, ABSTRACT) is None


class TestPubMed:
    XML = (b"<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>111</PMID><Article><ArticleTitle>A title</ArticleTitle>"
           b"<Abstract><AbstractText>First part.</AbstractText><AbstractText>Second part.</AbstractText></Abstract></Article>"
           b"</MedlineCitation></PubmedArticle><PubmedArticle><MedlineCitation><PMID>222</PMID><Article>"
           b"<ArticleTitle>No abstract here</ArticleTitle></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>")

    def test_abstracts_are_read_and_articles_without_one_are_left_out(self):
        assert el.parse_abstracts(self.XML) == {"111": "A title First part. Second part."}

    def test_an_abstract_is_fetched_once_and_remembered_on_disk(self, tmp_path):
        calls = []

        class Session:
            def get(self, url, params, timeout):
                calls.append(params["id"])
                return FakeResponse(content=TestPubMed.XML)

        first = el.PubMed(tmp_path, Session(), sleep=lambda s: None)
        assert first.get(["111", "222"])["111"].startswith("A title")
        again = el.PubMed(tmp_path, Session(), sleep=lambda s: None)       # a new run reads the file
        assert again.get(["111", "222"])["222"] == ""
        assert calls == ["111,222"]


class TestKimi:
    def test_the_key_is_required_and_comes_from_the_environment(self):
        with pytest.raises(SystemExit):
            el.Kimi(session=object(), environ={})

    def test_the_request_carries_the_key_only_in_the_header_and_asks_for_json(self):
        sent = {}

        class Session:
            def post(self, url, json, timeout, headers):
                sent.update(url=url, body=json, headers=headers)
                return FakeResponse(payload={"choices": [{"message": {"content": answer("not_reported")}}]})

        llm = el.Kimi(Session(), environ={"KIMI_API_KEY": "secret-key-123", "KIMI_MODEL": "some-model"})
        text = llm.ask("Abc1", "Mus musculus", ABSTRACT)

        assert sent["url"] == "https://api.moonshot.ai/v1/chat/completions"
        assert sent["headers"] == {"Authorization": "Bearer secret-key-123"}
        assert sent["body"]["response_format"] == {"type": "json_object"} and sent["body"]["model"] == "some-model"
        assert "secret-key-123" not in json.dumps(sent["body"]) and text == answer("not_reported")

    def test_an_error_answer_names_the_servers_reason_and_never_the_key(self):
        class Session:
            def post(self, *args, **kwargs):
                return FakeResponse(400, payload={"error": {"message": "invalid temperature: only 1 is allowed for this model"}})

        llm = el.Kimi(Session(), environ={"KIMI_API_KEY": "secret-key-123", "KIMI_MODEL": "m1"})
        with pytest.raises(el.requests.RequestException) as caught:
            llm.ask("g", "o", "a")

        assert "invalid temperature" in str(caught.value) and "m1" in str(caught.value) and "secret-key-123" not in str(caught.value)

    def test_the_models_of_a_key_can_be_listed(self):
        class Session:
            def get(self, url, timeout, headers):
                assert url.endswith("/models") and headers["Authorization"] == "Bearer k"
                return FakeResponse(payload={"data": [{"id": "model-b"}, {"id": "model-a"}]})

        assert el.Kimi(Session(), environ={"KIMI_API_KEY": "k"}).models() == ["model-a", "model-b"]

    def test_a_busy_server_is_retried(self, monkeypatch):
        monkeypatch.setattr(el.time, "sleep", lambda s: None)
        replies = [FakeResponse(429), FakeResponse(payload={"choices": [{"message": {"content": "ok"}}]})]

        class Session:
            def post(self, *args, **kwargs):
                return replies.pop(0)

        assert el.Kimi(Session(), environ={"MOONSHOT_API_KEY": "k"}).ask("g", "o", "a") == "ok"


class ScriptedLlm:
    def __init__(self, replies):
        self.replies, self.asked = list(replies), 0

    def ask(self, gene, organism, abstract):
        self.asked += 1
        return self.replies.pop(0)


class FakePubMed:
    def __init__(self, abstracts):
        self.abstracts = abstracts

    def get(self, pmids):
        return {str(p): self.abstracts.get(str(p), "") for p in pmids}


class TestReadGene:
    def abstracts(self, n):
        return {str(i): f"Study {i}. {QUOTE} in line {i}." for i in range(1, n + 1)}

    def test_the_most_common_outcome_wins_and_disagreement_is_reported(self):
        quotes = {str(i): f"{QUOTE} in line {i}" for i in (1, 2, 3)}
        llm = ScriptedLlm([answer("lethal", quotes["3"]), answer("lethal", quotes["2"]), answer("viable", quotes["1"])])

        result = el.read_gene(llm, FakePubMed(self.abstracts(3)), "Abc1", "Mus musculus", [3, 2, 1])

        assert result["outcome"] == "lethal" and result["agree"] == 2 and result["mixed"] is True and result["papers"] == 3

    def test_a_tie_goes_to_the_more_cautious_outcome(self):
        quotes = {str(i): f"{QUOTE} in line {i}" for i in (1, 2)}
        llm = ScriptedLlm([answer("viable", quotes["2"]), answer("lethal", quotes["1"])])

        assert el.read_gene(llm, FakePubMed(self.abstracts(2)), "Abc1", "Mus musculus", [2, 1])["outcome"] == "lethal"

    def test_abstracts_that_do_not_mention_a_knockout_are_not_sent_to_the_model(self):
        llm = ScriptedLlm([])

        result = el.read_gene(llm, FakePubMed({"1": "A review of gene expression in the liver."}), "Abc1", "Mus musculus", [1])

        assert result is None and llm.asked == 0

    def test_nothing_is_returned_when_no_paper_reports_a_result(self):
        llm = ScriptedLlm([answer("not_reported")])

        assert el.read_gene(llm, FakePubMed(self.abstracts(1)), "Abc1", "Mus musculus", [1]) is None


class TestGeneLinks:
    def test_papers_are_listed_newest_first_for_the_requested_genes_only(self, tmp_path):
        with gzip.open(tmp_path / "ncbi_gene_info_10090.gz", "wt", encoding="utf-8") as handle:
            handle.write("#tax_id\tGeneID\tSymbol\n10090\t1\tAbc1\n10090\t2\tOther\n")
        with gzip.open(tmp_path / "ncbi_gene2pubmed.gz", "wt", encoding="utf-8") as handle:
            handle.write("#tax_id\tGeneID\tPubMed_ID\n10090\t1\t100\n10090\t1\t300\n10090\t1\t200\n10090\t2\t999\n9606\t1\t555\n")

        assert el.read_gene_links("10090", {"ABC1"}, tmp_path) == {"ABC1": ["300", "200", "100"]}
