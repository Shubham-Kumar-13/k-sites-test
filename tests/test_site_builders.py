"""
Tests for the two deployment builders: the static website (GitHub Pages) and the
backend folder for the Hugging Face Space.
"""

import importlib.util
import re
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


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("built") / "site"
    load_tool("build_static_site").build("https://example-space.hf.space/", out)
    return out


class TestStaticSite:
    def test_all_pages_are_built(self, site):
        for page in ("index.html", "jobs.html", "help.html", "results.html", "login.html",
                     "config.js", "404.html", ".nojekyll", "robots.txt"):
            assert (site / page).exists(), page
        assert (site / "static" / "js" / "api.js").exists()
        assert (site / "static" / "js" / "main.js").exists()
        assert (site / "static" / "js" / "results.js").exists()

    def test_backend_address_is_written_without_trailing_slash(self, site):
        config = (site / "config.js").read_text(encoding="utf-8")

        assert 'https://example-space.hf.space"' in config
        assert "KSITES_CONFIG" in config

    def test_no_template_syntax_is_left_in_the_pages(self, site):
        for page in site.glob("*.html"):
            text = page.read_text(encoding="utf-8")
            assert "{{" not in text and "{%" not in text, page.name

    def test_links_point_at_static_pages_not_server_routes(self, site):
        for page in site.glob("*.html"):
            hrefs = re.findall(r'href="(/[^"]*)"', page.read_text(encoding="utf-8"))
            assert hrefs == [], f"{page.name}: {hrefs}"

    def test_every_local_script_and_page_link_exists(self, site):
        for page in site.glob("*.html"):
            text = page.read_text(encoding="utf-8")
            for target in re.findall(r'(?:src|href)="([^"#:?]+\.(?:js|html))(?:[?#][^"]*)?"', text):
                assert (site / target).exists(), f"{page.name} -> {target}"

    def test_config_loads_before_the_api_helper(self, site):
        for name in ("index.html", "jobs.html", "results.html", "help.html", "login.html"):
            text = (site / name).read_text(encoding="utf-8")
            assert text.index('src="config.js"') < text.index("static/js/api.js"), name

    def test_only_the_login_page_is_public(self, site):
        assert "KSITES_PUBLIC_PAGE = true" in (site / "login.html").read_text(encoding="utf-8")
        for name in ("index.html", "jobs.html", "results.html", "help.html"):
            assert "KSITES_PUBLIC_PAGE" not in (site / name).read_text(encoding="utf-8"), name

    def test_site_asks_search_engines_not_to_index_it(self, site):
        assert "Disallow: /" in (site / "robots.txt").read_text(encoding="utf-8")
        assert "noindex" in (site / "index.html").read_text(encoding="utf-8")

    def test_results_page_is_a_blank_shell_filled_in_by_script(self, site):
        text = (site / "results.html").read_text(encoding="utf-8")

        assert 'data-job-id=""' in text
        assert 'data-job-field="organism"' in text
        assert 'id="downloadCsv"' in text and 'id="downloadXlsx"' in text

    def test_help_page_carries_the_documentation(self, site):
        text = (site / "help.html").read_text(encoding="utf-8")

        assert "Max pleiotropy (cutoff)" in text
        assert 'href="#pleiotropy"' in text or 'id="pleiotropy' in text

    def test_logout_returns_to_the_login_page(self, site):
        assert 'id="logoutLink" href="login.html"' in (site / "index.html").read_text(encoding="utf-8")

    def test_rejects_a_backend_address_without_scheme(self, tmp_path, monkeypatch, capsys):
        tool = load_tool("build_static_site")
        monkeypatch.setattr(sys, "argv", ["x", "--api-base", "example.com", "--out", str(tmp_path / "s")])

        with pytest.raises(SystemExit):
            tool.main()


@pytest.fixture(scope="module")
def space(tmp_path_factory):
    out = tmp_path_factory.mktemp("space") / "hf_space"
    files = load_tool("build_hf_space").build(out)
    return out, files


class TestSpaceFolder:

    def test_has_what_a_docker_space_needs(self, space):
        out, files = space

        for name in ("Dockerfile", "README.md", "requirements.txt"):
            assert name in files
        assert (out / "README.md").read_text(encoding="utf-8").startswith("---")
        assert "sdk: docker" in (out / "README.md").read_text(encoding="utf-8")
        assert "app_port: 7860" in (out / "README.md").read_text(encoding="utf-8")

    def test_contains_the_package_and_the_api(self, space):
        _, files = space

        assert "k_sites/workflow/pipeline.py" in files
        assert "webapp/app.py" in files

    def test_leaves_out_databases_caches_and_tests(self, space):
        _, files = space

        assert not any(f.endswith((".db", ".pyc")) for f in files)
        assert not any("__pycache__" in f for f in files)
        assert not any(f.startswith("tests/") for f in files)
        assert not any(f.startswith("webapp/results") for f in files)

    def test_dockerfile_serves_the_flask_app_on_the_spaces_port(self, space):
        dockerfile = (space[0] / "Dockerfile").read_text(encoding="utf-8")

        assert "app:app" in dockerfile and "7860" in dockerfile
        assert "--workers" in dockerfile and '"1"' in dockerfile
        assert "KSITES_DATA_DIR" in dockerfile

    def test_every_import_the_backend_needs_is_in_the_requirements(self, space):
        requirements = (space[0] / "requirements.txt").read_text(encoding="utf-8").lower()

        for package in ("flask", "flask-cors", "flask-sqlalchemy", "flask-mail", "gunicorn", "requests",
                        "biopython", "pandas", "openpyxl", "sentence-transformers", "faiss-cpu",
                        "dataclasses-json", "pyyaml"):
            assert package in requirements, package


class TestBrowserSite:
    """Without a backend address the analysis runs in the visitor's browser."""

    @pytest.fixture(scope="class")
    def browser_site(self, tmp_path_factory):
        out = tmp_path_factory.mktemp("browser") / "site"
        load_tool("build_static_site").build("", out)
        return out

    def test_pages_and_engine_are_built_without_a_sign_in_page(self, browser_site):
        for page in ("index.html", "jobs.html", "help.html", "results.html", "config.js"):
            assert (browser_site / page).exists(), page
        assert not (browser_site / "login.html").exists()
        for module in ("pipeline.js", "rag.js", "browserBackend.js", "localApi.js", "store.js"):
            assert (browser_site / "static" / "js" / "engine" / module).exists(), module

    def test_config_selects_browser_mode_and_the_kegg_data_folder(self, browser_site):
        config = (browser_site / "config.js").read_text(encoding="utf-8")

        assert '"mode": "browser"' in config
        assert '"keggBase": "kegg-data/"' in config

    def test_footer_says_nothing_is_sent_to_a_server(self, browser_site):
        assert "nothing is sent to a K-Sites server" in (browser_site / "index.html").read_text(encoding="utf-8")
