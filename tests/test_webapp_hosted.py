"""
Tests for the web app in hosted mode (API-only backend for the GitHub Pages front-end).

The app reads its settings when it is imported, so a throw-away copy is imported in a
subprocess-free way: environment variables are set, the module is loaded fresh, and the
database lives in a temporary folder.
"""

import importlib
import json
import sqlite3
import sys
import types
from pathlib import Path

import pytest

TOKEN = "lab-secret-token"
ORIGIN = "https://kkokay07.github.io"
WEBAPP_DIR = str(Path(__file__).resolve().parent.parent / "webapp")


def load_app(monkeypatch, tmp_path, hosted=True):
    """Import webapp/app.py fresh with the requested configuration."""
    monkeypatch.setenv("KSITES_DATA_DIR", str(tmp_path))
    if hosted:
        monkeypatch.setenv("KSITES_ACCESS_TOKEN", TOKEN)
        monkeypatch.setenv("KSITES_ALLOWED_ORIGINS", ORIGIN)
    else:
        monkeypatch.delenv("KSITES_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("KSITES_ALLOWED_ORIGINS", raising=False)
    monkeypatch.syspath_prepend(WEBAPP_DIR)
    for name in [n for n in sys.modules if n in ("app", "config") or n.startswith("utils")]:
        sys.modules.pop(name, None)
    module = importlib.import_module("app")
    module.app.config["TESTING"] = True
    return module


@pytest.fixture
def hosted(monkeypatch, tmp_path):
    return load_app(monkeypatch, tmp_path, hosted=True)


@pytest.fixture
def client(hosted):
    return hosted.app.test_client()


AUTH = {"X-KSites-Token": TOKEN}


class TestAccess:
    def test_health_is_open_so_the_site_can_wake_the_backend(self, client):
        data = client.get("/api/health").get_json()

        assert data["status"] == "ok"
        assert data["hosted"] is True

    def test_api_requires_the_token(self, client):
        assert client.get("/api/jobs").status_code == 401
        assert client.get("/api/databases").status_code == 401
        assert client.get("/api/auth/check").status_code == 401

    def test_wrong_token_is_rejected(self, client):
        response = client.get("/api/jobs", headers={"X-KSites-Token": "guess"})

        assert response.status_code == 401

    def test_correct_token_is_accepted(self, client):
        assert client.get("/api/jobs", headers=AUTH).status_code == 200
        assert client.get("/api/auth/check", headers=AUTH).get_json()["ok"] is True

    def test_starting_a_job_requires_the_token(self, client):
        response = client.post("/api/analyze/start", json={"organism": "9606", "go_term": "GO:0006281"})

        assert response.status_code == 401

    def test_login_page_and_html_routes_are_not_served(self, client):
        for path in ("/", "/login", "/jobs", "/help", "/results/abc"):
            response = client.get(path)
            assert response.status_code == 200
            assert "backend is running" in response.get_data(as_text=True)
            assert "<form" not in response.get_data(as_text=True)

    def test_cors_allows_only_the_configured_origin(self, client):
        allowed = client.options("/api/jobs", headers={
            "Origin": ORIGIN, "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-KSites-Token"})
        blocked = client.options("/api/jobs", headers={
            "Origin": "https://evil.example", "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-KSites-Token"})

        assert allowed.headers.get("Access-Control-Allow-Origin") == ORIGIN
        assert "X-KSites-Token" in allowed.headers.get("Access-Control-Allow-Headers", "")
        assert blocked.headers.get("Access-Control-Allow-Origin") is None

    def test_actual_response_carries_the_cors_header_for_the_site(self, client):
        response = client.get("/api/jobs", headers={**AUTH, "Origin": ORIGIN})

        assert response.headers.get("Access-Control-Allow-Origin") == ORIGIN


class TestJobs:
    def test_validate_rejects_bad_cutoff_with_token(self, client):
        response = client.post("/api/analyze/validate", headers=AUTH,
                               json={"organism": "", "go_term": "", "max_pleiotropy": 11})

        assert any("between 0 and 10" in e for e in response.get_json()["errors"])

    def test_submitter_email_comes_from_the_header(self, hosted, client, monkeypatch):
        # do not actually run an analysis
        monkeypatch.setattr(hosted, "run_analysis_job", lambda job_id: None)
        response = client.post("/api/analyze/start", headers={**AUTH, "X-KSites-User-Email": "a@lab.org"}, json={
            "organism": "9606", "go_term": "GO:0006281", "max_genes": 5, "max_pleiotropy": 5,
            "evidence_filter": "all", "databases": ["quickgo"]})

        body = response.get_json()
        assert body["success"] is True
        status = client.get(f"/api/jobs/{body['job_id']}/status", headers=AUTH).get_json()
        assert status["evidence_filter"] == "all"
        with hosted.app.app_context():
            assert hosted.AnalysisJob.query.get(body["job_id"]).user_email == "a@lab.org"

    def test_unknown_job_is_404(self, client):
        assert client.get("/api/jobs/nope/status", headers=AUTH).status_code == 404

    def test_download_types(self, hosted, client, tmp_path):
        results_dir = tmp_path / "job1"
        results_dir.mkdir()
        (results_dir / "report_1.html").write_text("<html></html>")
        (results_dir / "results_1.json").write_text("{}")
        (results_dir / "report_1_comprehensive.csv").write_text("a,b")
        (results_dir / "report_1_gene_summary.csv").write_text("a,b")
        with hosted.app.app_context():
            hosted.db.session.add(hosted.AnalysisJob(
                id="job1", organism="9606", go_term="GO:0006281", status="completed",
                results_path=str(results_dir)))
            hosted.db.session.commit()

        for file_type in ("html", "json", "csv", "summary"):
            response = client.get(f"/api/jobs/job1/download/{file_type}", headers=AUTH)
            assert response.status_code == 200, file_type
        assert client.get("/api/jobs/job1/download/exe", headers=AUTH).status_code == 400

    def test_interrupted_jobs_are_marked_failed_on_startup(self, monkeypatch, tmp_path):
        first = load_app(monkeypatch, tmp_path, hosted=True)
        with first.app.app_context():
            first.db.session.add(first.AnalysisJob(
                id="stuck", organism="9606", go_term="GO:0006281", status="running"))
            first.db.session.commit()

        second = load_app(monkeypatch, tmp_path, hosted=True)
        with second.app.app_context():
            job = second.AnalysisJob.query.get("stuck")
            assert job.status == "failed"
            assert "restarted" in job.error_message


class TestEvidenceDetails:
    def test_traceable_records_are_returned_without_changing_scoring(self, hosted, client, tmp_path):
        directory = tmp_path / "evidence-details"
        directory.mkdir()
        record = {"call": "LETHAL", "conflicting": False, "sources": ["tair"], "records": [{
            "source": "tair", "source_record_id": "SALK_052897", "call": "LETHAL",
            "experiment_type": "mutant_not_otherwise_specified", "zygosity": "homozygous",
            "evidence_level": "qualified", "phenotype": "Homozygotes are embryo lethal.", "references": ["26555280"],
        }]}
        (directory / "3702.json").write_text(json.dumps({
            "format": 1, "built": "2026-11-04", "pilot": {"tair_gene_limit": 100}, "genes": {"AT1G02660": record},
        }), encoding="utf-8")

        response = client.get("/api/evidence/details?taxid=3702&symbol=at1g02660", headers=AUTH)

        assert response.status_code == 200
        body = response.get_json()
        assert body["evidence"]["records"][0]["source_record_id"] == "SALK_052897"
        assert body["evidence"]["records"][0]["references"] == ["26555280"]
        assert body["pilot"]["tair_gene_limit"] == 100

    def test_sqlite_details_are_read_by_gene(self, client, tmp_path):
        directory = tmp_path / "evidence-details"
        directory.mkdir()
        with sqlite3.connect(directory / "10090.sqlite") as connection:
            connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
            connection.execute("CREATE TABLE genes (symbol TEXT PRIMARY KEY, payload TEXT)")
            connection.executemany("INSERT INTO metadata VALUES (?, ?)", [("built", "2026-11-04"), ("pilot", "{}")])
            connection.execute("INSERT INTO genes VALUES ('TDG', ?)", (json.dumps({"call": "LETHAL", "records": []}),))

        response = client.get("/api/evidence/details?taxid=10090&symbol=tdg", headers=AUTH)

        assert response.status_code == 200
        assert response.get_json()["evidence"]["call"] == "LETHAL"
        assert response.get_json()["version"] == "2026-11-04"

    def test_unknown_gene_and_invalid_request(self, client, tmp_path):
        directory = tmp_path / "evidence-details"
        directory.mkdir(exist_ok=True)
        (directory / "3702.json").write_text(json.dumps({"built": "2026-11-04", "genes": {}}), encoding="utf-8")

        assert client.get("/api/evidence/details?taxid=3702&symbol=UNKNOWN", headers=AUTH).status_code == 404
        assert client.get("/api/evidence/details?taxid=plants&symbol=UNKNOWN", headers=AUTH).status_code == 400
        assert client.get("/api/evidence/details?taxid=3702&symbol=AT1G02660").status_code == 401


class TestLocalModeUnchanged:
    def test_local_mode_still_uses_the_login_session(self, monkeypatch, tmp_path):
        local = load_app(monkeypatch, tmp_path, hosted=False)
        client = local.app.test_client()

        assert client.get("/api/jobs").status_code == 401           # API: JSON 401, not a redirect
        assert client.get("/").status_code == 302                    # page: redirect to login

        client.post("/login", data={"name": "A", "email": "a@lab.org", "institute": "L", "country": "C"})
        assert client.get("/api/jobs").status_code == 200
        assert "K-Sites" in client.get("/help").get_data(as_text=True)
        assert "Validation of the measured knockout evidence" in client.get("/validation").get_data(as_text=True)
