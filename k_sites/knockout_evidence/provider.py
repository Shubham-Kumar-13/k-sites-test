"""
Where the measured knockout evidence comes from.

The data files are built by tools/build_evidence_data.py and published with the K-Sites website (evidence-data/).
A provider reads them either from a folder or from a web address (and keeps a copy on disk), so the Python package
and the website use exactly the same files.

    KSITES_EVIDENCE_DIR   a folder with index.json and the organism files (e.g. site/evidence-data)
    KSITES_EVIDENCE_URL   a web address of that folder (default: the K-Sites website); "off" switches it off
"""

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://shubham-kumar-13.github.io/k-sites-test/evidence-data/"
DEFAULT_CACHE = Path.home() / ".k_sites" / "evidence-data"

# Taxon ids that share one evidence file (the file is named after the first)
TAXID_ALIASES = {"4932": "559292", "559292": "559292", "9606": "9606", "10090": "10090", "10116": "10116"}
FORMAT_VERSION = 1


class EvidenceUnavailable(Exception):
    """The evidence files could not be read."""


class DirectorySource:
    def __init__(self, path):
        self.path = Path(path)

    def read(self, name: str) -> dict:
        file = self.path / name
        if not file.exists():
            raise EvidenceUnavailable(f"{file} does not exist")
        with open(file, encoding="utf-8") as handle:
            return json.load(handle)


class UrlSource:
    """Downloads the files once per data release and keeps them in ``cache_dir/<release date>/``."""

    def __init__(self, base_url: str, cache_dir=DEFAULT_CACHE, timeout: int = 30, session=None):
        self.base_url = base_url.rstrip("/") + "/"
        self.cache_dir = Path(cache_dir)
        self.timeout = timeout
        self.session = session or requests
        self._release: Optional[str] = None

    def _download(self, name: str) -> dict:
        response = self.session.get(self.base_url + name, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def read(self, name: str) -> dict:
        if name == "index.json":
            try:
                index = self._download(name)
            except (requests.RequestException, ValueError) as error:
                cached = self._latest_cached_index()
                if cached is None:
                    raise EvidenceUnavailable(f"Could not download {self.base_url}{name}: {error}") from error
                logger.warning("Using the saved knockout evidence (could not reach %s: %s)", self.base_url, error)
                self._release = cached[0]
                return cached[1]
            self._release = str(index.get("built", "unknown"))
            folder = self.cache_dir / self._release
            folder.mkdir(parents=True, exist_ok=True)
            (folder / name).write_text(json.dumps(index), encoding="utf-8")
            for old in self.cache_dir.iterdir():
                if old.is_dir() and old.name != self._release:
                    shutil.rmtree(old, ignore_errors=True)
            return index
        if self._release is None:
            self.read("index.json")
        file = self.cache_dir / self._release / name
        if file.exists():
            with open(file, encoding="utf-8") as handle:
                return json.load(handle)
        try:
            data = self._download(name)
        except (requests.RequestException, ValueError) as error:
            raise EvidenceUnavailable(f"Could not download {self.base_url}{name}: {error}") from error
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(data), encoding="utf-8")
        return data

    def _latest_cached_index(self):
        if not self.cache_dir.exists():
            return None
        folders = sorted((p for p in self.cache_dir.iterdir() if (p / "index.json").exists()), key=lambda p: p.name)
        if not folders:
            return None
        with open(folders[-1] / "index.json", encoding="utf-8") as handle:
            return folders[-1].name, json.load(handle)


class OrganismEvidence:
    """The records of one organism: look a gene up by symbol, or by an older name or alias."""

    def __init__(self, taxid: str, info: dict, genes: Dict[str, dict], aliases: Dict[str, str]):
        self.taxid = taxid
        self.info = info
        self.genes = genes
        self.aliases = aliases

    def lookup(self, symbol: str) -> Optional[dict]:
        key = (symbol or "").strip().upper()
        if not key:
            return None
        record = self.genes.get(key)
        if record is None:
            current = self.aliases.get(key)
            record = self.genes.get(current.upper()) if current else None
        return record


class EvidenceProvider:
    def __init__(self, source):
        self.source = source
        self._index = None
        self._organisms: Dict[str, Optional[OrganismEvidence]] = {}

    @property
    def index(self) -> dict:
        if self._index is None:
            index = self.source.read("index.json")
            if index.get("format") != FORMAT_VERSION:
                raise EvidenceUnavailable(
                    f"The knockout evidence files have format {index.get('format')}; this version of K-Sites reads format {FORMAT_VERSION}")
            self._index = index
        return self._index

    def organism(self, taxid) -> Optional[OrganismEvidence]:
        """The evidence of an organism, or None when there are no files for it."""
        key = TAXID_ALIASES.get(str(taxid), str(taxid))
        if key not in self._organisms:
            info = self.index.get("organisms", {}).get(key)
            if not info:
                self._organisms[key] = None
            else:
                data = self.source.read(info["file"])
                self._organisms[key] = OrganismEvidence(key, info, data.get("genes", {}), data.get("aliases", {}))
        return self._organisms[key]

    @classmethod
    def from_directory(cls, path) -> "EvidenceProvider":
        return cls(DirectorySource(path))

    @classmethod
    def from_url(cls, url: str = DEFAULT_URL, cache_dir=DEFAULT_CACHE) -> "EvidenceProvider":
        return cls(UrlSource(url, cache_dir))


def evidence_disabled() -> bool:
    """True when the environment switches measured evidence off (KSITES_EVIDENCE_URL=off, no directory given)."""
    return (not os.environ.get("KSITES_EVIDENCE_DIR")
            and os.environ.get("KSITES_EVIDENCE_URL", DEFAULT_URL).strip().lower() in ("", "off", "none"))


def default_provider() -> Optional[EvidenceProvider]:
    """The provider set up by the environment, or None (with a warning) when no evidence can be read."""
    directory = os.environ.get("KSITES_EVIDENCE_DIR")
    url = os.environ.get("KSITES_EVIDENCE_URL", DEFAULT_URL)
    try:
        if directory:
            provider = EvidenceProvider.from_directory(directory)
        elif evidence_disabled():
            return None
        else:
            provider = EvidenceProvider.from_url(url)
        provider.index          # read it now so that a problem shows up here
        return provider
    except EvidenceUnavailable as error:
        logger.warning("Measured knockout evidence is not available: %s", error)
        return None
