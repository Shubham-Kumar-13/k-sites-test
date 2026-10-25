"""
The small Markdown converter behind the Validation page (webapp/utils/markdown_lite.py).
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def render():
    spec = importlib.util.spec_from_file_location("markdown_lite", ROOT / "webapp" / "utils" / "markdown_lite.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render


def test_headings_and_paragraphs(render):
    html = render("# Title\n\nFirst line\nsecond line.\n\n## Part 2\n\nNext.")

    assert "<h1>Title</h1>" in html and "<h2>Part 2</h2>" in html
    assert "<p>First line second line.</p>" in html and "<p>Next.</p>" in html


def test_inline_marks(render):
    html = render("A *measured* gene, **bold** and `code_with*stars*`.")

    assert "<em>measured</em>" in html and "<strong>bold</strong>" in html
    assert "<code>code_with*stars*</code>" in html


def test_a_link_may_contain_parentheses(render):
    html = render("[Barnes et al. 1998](https://doi.org/10.1016/s0960-9822(98)00021-9) is cited.")

    assert '<a href="https://doi.org/10.1016/s0960-9822(98)00021-9">Barnes et al. 1998</a> is cited.' in html


def test_text_is_escaped(render):
    html = render("<script>alert(1)</script> & more\n\n- <b>x</b>\n\n```\n<i>code</i>\n```")

    assert "<script>" not in html and "<b>" not in html and "<i>" not in html
    assert "&lt;script&gt;" in html and "&amp; more" in html and "&lt;i&gt;code&lt;/i&gt;" in html


def test_a_link_to_another_scheme_is_not_made(render):
    assert "<a " not in render("[click](javascript:alert(1))")


def test_tables(render):
    html = render("| Gene | Verdict |\n|---|---|\n| Tdg | AVOID |\n| Ogg1 | **SAFE** |\n\nAfter.")

    assert html.count("<tr>") == 3 and "<th>Gene</th>" in html and "<td>Tdg</td>" in html
    assert "<td><strong>SAFE</strong></td>" in html and "<p>After.</p>" in html


def test_bullet_lists_join_wrapped_lines(render):
    html = render("- first item\n  continues here\n- second item\n\nDone.")

    assert html.count("<li>") == 2 and "<li>first item continues here</li>" in html and "<p>Done.</p>" in html


def test_a_line_that_looks_like_half_a_table_does_not_hang(render):
    html = render("| not | a table\nstill text\n\n|\n")

    assert "not" in html and "still text" in html


def test_the_validation_report_becomes_a_page(render):
    report = (ROOT / "VALIDATION.md").read_text(encoding="utf-8")
    html = render(report)

    assert html.count("<table") >= 4 and "|---" not in html
    assert "<h1>Validation of the measured knockout evidence</h1>" in html
    assert 'href="https://doi.org/10.1093/emboj/19.6.1397"' in html
    assert "<pre><code>" in html and "<em>measured</em>" in html and "<code>tools/evaluate_knockout_evidence.py</code>" in html
