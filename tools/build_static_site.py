#!/usr/bin/env python3
"""
Build the static K-Sites website for GitHub Pages.

The pages are rendered from the same Flask templates the local app uses, so there is one
source for the interface. The result talks to the K-Sites backend (hosted elsewhere, for
example a Hugging Face Space) through the address given with --api-base.

    python tools/build_static_site.py --out site                                  # analysis in the browser
    python tools/build_static_site.py --api-base https://your-space.hf.space --out site   # separate backend

The browser version also needs the KEGG data files and the measured knockout evidence:
    python tools/build_kegg_data.py --out site/kegg-data
    python tools/build_evidence_data.py --out site/evidence-data
Only Jinja2 is needed; the K-Sites analysis code is not imported.
"""

import argparse
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parent.parent
WEBAPP = ROOT / "webapp"

# Pages built from templates: output file -> (template, needs the help content)
PAGES = {
    "index.html": ("index.html", False),
    "jobs.html": ("jobs.html", False),
    "help.html": ("help.html", True),
    "results.html": ("results.html", False),
}
# The sign-in page is only needed when a separate backend with an access code is used
REMOTE_ONLY_PAGES = {"login.html": ("hosted_login.html", False)}

# Site-absolute links in the templates -> the static page that replaces them
LINKS = {
    '"/"': '"index.html"',
    '"/jobs"': '"jobs.html"',
    '"/help"': '"help.html"',
    '"/validation"': '"validation.html"',
    '"/profile"': '"#"',
    '"/logout"': '"login.html"',
}


def load_help_content():
    """webapp/utils/help_content.py is plain data, so it is loaded without the Flask app."""
    spec = importlib.util.spec_from_file_location("help_content", WEBAPP / "utils" / "help_content.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_markdown_renderer():
    """webapp/utils/markdown_lite.py has no dependencies, so it is loaded without the Flask app."""
    spec = importlib.util.spec_from_file_location("markdown_lite", WEBAPP / "utils" / "markdown_lite.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render


def make_environment():
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(WEBAPP / "templates")),
        autoescape=jinja2.select_autoescape(["html"]),
    )

    def url_for(endpoint, **values):
        if endpoint == "static":
            return "static/" + values["filename"]
        raise ValueError(f"The static site has no route named {endpoint!r}")

    env.globals.update(url_for=url_for, session={}, get_flashed_messages=lambda **kwargs: [])
    return env


def rewrite_links(html: str) -> str:
    """Point the app's absolute links (/jobs, /help#x, ...) at the static pages."""
    for old, new in LINKS.items():
        html = html.replace(f"href={old}", f"href={new}")
    # in-page anchors on the help page, e.g. href="/help#pleiotropy"
    html = re.sub(r'href="/help#', 'href="help.html#', html)
    return html


def placeholder_job():
    """The results page ships empty; its script fills it in from ?job=<id>."""
    return {
        "id": "", "status": "pending", "current_step": "Loading...", "progress_percent": 0,
        "estimated_completion": None, "user_email": None, "error_message": "",
        "organism": "", "taxid": "", "go_term": "", "go_term_name": None, "max_genes": "",
        "max_pleiotropy": "", "evidence_filter": "", "predict_phenotypes": False,
        "selected_databases": None, "total_genes_found": None, "genes_processed": None,
    }


def build(api_base: str, out: Path) -> list:
    """
    Build the site.

    With an ``api_base`` the pages talk to a separate backend that needs an access code.
    With ``api_base`` empty (the default) the analysis runs in each visitor's browser.
    """
    browser_mode = not api_base
    pages = dict(PAGES) if browser_mode else {**PAGES, **REMOTE_ONLY_PAGES}
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    env = make_environment()
    help_content = load_help_content()
    written = []

    for filename, (template_name, needs_help) in pages.items():
        context = {"hosted_build": True, "browser_build": browser_mode, "user_name": "", "job": placeholder_job()}
        if needs_help:
            context.update(
                analytical_terms=help_content.ANALYTICAL_TERMS,
                methodology_sections=help_content.METHODOLOGY_SECTIONS,
                faq_items=help_content.FAQ_ITEMS,
            )
        html = rewrite_links(env.get_template(template_name).render(**context))
        (out / filename).write_text(html, encoding="utf-8")
        written.append(filename)

    # The validation page: VALIDATION.md (how the knockout evidence was checked) as a page of the site
    report = ROOT / "VALIDATION.md"
    body = load_markdown_renderer()(report.read_text(encoding="utf-8")) if report.exists() else \
        "<p>The validation report has not been generated yet (run tools/evaluate_knockout_evidence.py).</p>"
    context = {"hosted_build": True, "browser_build": browser_mode, "user_name": "", "job": placeholder_job(), "validation_html": body}
    (out / "validation.html").write_text(rewrite_links(env.get_template("validation.html").render(**context)), encoding="utf-8")
    written.append("validation.html")

    shutil.copytree(WEBAPP / "static", out / "static")
    config = {"mode": "browser", "keggBase": "kegg-data/", "evidenceBase": "evidence-data/"} if browser_mode else {"apiBase": api_base.rstrip("/")}
    (out / "config.js").write_text("window.KSITES_CONFIG = " + json.dumps(config) + ";\n", encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (out / "404.html").write_text(
        '<!DOCTYPE html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=index.html">'
        '<title>K-Sites</title><p>Page not found. <a href="index.html">Go to K-Sites</a>.</p>',
        encoding="utf-8",
    )
    written += ["config.js", "static/", ".nojekyll", "robots.txt", "404.html"]
    return written


def main():
    parser = argparse.ArgumentParser(description="Build the static K-Sites website for GitHub Pages.")
    parser.add_argument("--api-base", default="",
                        help="Address of a separate K-Sites backend (needs an access code). Leave out to run the "
                             "analysis in each visitor's browser (default).")
    parser.add_argument("--out", default="site", help="Output folder (default: site)")
    args = parser.parse_args()

    if args.api_base and not re.match(r"^https?://", args.api_base):
        sys.exit("--api-base must start with http:// or https://")

    out = Path(args.out)
    written = build(args.api_base, out)
    mode = f"separate backend {args.api_base}" if args.api_base else "analysis runs in the visitor's browser"
    print(f"Built the K-Sites site in {out.resolve()} ({mode})")
    for name in written:
        print(f"  {name}")


if __name__ == "__main__":
    main()
