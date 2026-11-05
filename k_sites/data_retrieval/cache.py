"""
HTTP response cache for K-Sites data retrieval.

Caches GET responses from external APIs (QuickGO, UniProt, NCBI, etc.)
on disk with a configurable TTL. This avoids repeating slow or rate-limited
queries when the same gene/GO term/organism is analysed more than once.
"""

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CACHE_ENABLED = os.environ.get("KSITES_CACHE_DISABLE", "").lower() not in (
    "1", "true", "yes", "on"
)
DEFAULT_CACHE_TTL = int(os.environ.get("KSITES_CACHE_TTL_SECONDS", "3600"))
MAX_CACHE_ENTRIES = int(os.environ.get("KSITES_CACHE_MAX_ENTRIES", "5000"))

# Per-endpoint TTLs (seconds). Stable reference data gets longer TTLs;
# annotation databases that update more often get shorter TTLs.
URL_TTL_OVERRIDES = [
    # NCBI Taxonomy lookups change very rarely.
    ("eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", 7 * 24 * 3600),
    ("eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi", 7 * 24 * 3600),
    ("eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi", 7 * 24 * 3600),
    # Gene annotation databases.
    ("www.ebi.ac.uk/QuickGO", 24 * 3600),
    ("rest.uniprot.org", 24 * 3600),
    ("mygene.info", 24 * 3600),
    ("www.ebi.ac.uk/ols4", 24 * 3600),
    ("eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi", 24 * 3600),
]


def ttl_for_url(url: str) -> int:
    """Return the cache TTL that best fits the URL being requested."""
    url_lower = url.lower()
    for pattern, ttl in URL_TTL_OVERRIDES:
        if pattern.lower() in url_lower:
            return ttl
    return DEFAULT_CACHE_TTL

CACHE_DIR = Path(
    os.environ.get("KSITES_CACHE_DIR") or Path.home() / ".k_sites_cache"
)
CACHE_DB_PATH = CACHE_DIR / "http_cache.db"

_write_lock = threading.Lock()
_db_initialized = False
_db_init_lock = threading.Lock()

# Per-request cache events, used to surface "cached" / "live" status in the UI.
_request_cache_events: ContextVar[Optional[List[dict]]] = ContextVar(
    "request_cache_events", default=None
)


def start_cache_tracking() -> None:
    """Begin collecting cache hit/miss events for the current request."""
    _request_cache_events.set([])


def get_cache_events() -> List[dict]:
    """Return the cache events collected for the current request."""
    return list(_request_cache_events.get() or [])


def _record_cache_event(event_type: str, url: str) -> None:
    """Record a cache hit or miss if tracking is active for this request."""
    events = _request_cache_events.get()
    if events is not None:
        events.append({"type": event_type, "url": url, "time": time.time()})


def _normalize_params(params: Any) -> Any:
    """Make query parameters hash-stable for caching."""
    if params is None:
        return None
    if isinstance(params, dict):
        return {k: params[k] for k in sorted(params)}
    if isinstance(params, list):
        # list of tuples -> sorted; strings/ints kept as-is
        return sorted(params, key=lambda x: json.dumps(x, sort_keys=True) if isinstance(x, (dict, list)) else str(x))
    return params


def _init_db() -> None:
    """Create the cache table and indexes if they do not exist."""
    global _db_initialized
    if _db_initialized:
        return
    with _db_init_lock:
        if _db_initialized:
            return
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(CACHE_DB_PATH), check_same_thread=False)
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS http_cache (
                        key TEXT PRIMARY KEY,
                        url TEXT,
                        params TEXT,
                        status_code INTEGER,
                        text TEXT,
                        headers TEXT,
                        created REAL,
                        expires REAL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_expires ON http_cache(expires)"
                )
                conn.commit()
            finally:
                conn.close()
            _db_initialized = True
        except Exception as e:
            logger.warning(f"Could not initialise HTTP cache database: {e}")


def _make_key(method: str, url: str, params: Any) -> str:
    """Stable cache key for a request."""
    norm = _normalize_params(params)
    payload = f"{method.upper()}:{url}:{json.dumps(norm, sort_keys=True, default=str)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_cached(key: str) -> Optional[tuple]:
    """Return cached (status_code, text, headers_json) if it exists and is fresh."""
    if not CACHE_ENABLED:
        return None
    _init_db()
    try:
        conn = sqlite3.connect(str(CACHE_DB_PATH), check_same_thread=False)
        try:
            row = conn.execute(
                "SELECT status_code, text, headers, expires FROM http_cache WHERE key = ?",
                (key,),
            ).fetchone()
            if row and row[3] > time.time():
                _record_cache_event("cache_hit", url)
                return row
        finally:
            conn.close()
    except Exception as e:
        logger.debug(f"HTTP cache read failed: {e}")
    return None


def _store_cache(
    key: str,
    url: str,
    params: Any,
    status_code: int,
    text: str,
    headers: Dict[str, str],
    ttl: int = DEFAULT_CACHE_TTL,
) -> None:
    """Store a response in the cache, pruning old/over-large entries."""
    if not CACHE_ENABLED:
        return
    _init_db()
    try:
        params_json = json.dumps(_normalize_params(params), sort_keys=True, default=str)
        headers_json = json.dumps(dict(headers) if headers else {}, default=str)
        now = time.time()
        expires = now + ttl

        with _write_lock:
            conn = sqlite3.connect(str(CACHE_DB_PATH), check_same_thread=False)
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO http_cache
                    (key, url, params, status_code, text, headers, created, expires)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (key, url, params_json, status_code, text, headers_json, now, expires),
                )
                # Remove expired entries
                conn.execute("DELETE FROM http_cache WHERE expires <= ?", (now,))
                # Keep the cache from growing without bound
                count = conn.execute("SELECT COUNT(*) FROM http_cache").fetchone()[0]
                if count > MAX_CACHE_ENTRIES:
                    to_remove = count - MAX_CACHE_ENTRIES
                    conn.execute(
                        "DELETE FROM http_cache WHERE key IN ("
                        "SELECT key FROM http_cache ORDER BY created ASC LIMIT ?)",
                        (to_remove,),
                    )
                conn.commit()
            finally:
                conn.close()
    except Exception as e:
        logger.debug(f"HTTP cache write failed: {e}")


class CachedResponse:
    """Lightweight response object returned from the cache."""

    def __init__(
        self,
        status_code: int,
        text: str,
        headers: Dict[str, str],
        url: str,
        from_cache: bool = True,
    ):
        self.status_code = status_code
        self.text = text
        self.headers = headers
        self.url = url
        self.ok = 200 <= status_code < 300
        self.reason = ""
        self.from_cache = from_cache
        self._json: Any = None

    def json(self) -> Any:
        if self._json is None:
            self._json = json.loads(self.text)
        return self._json

    def __repr__(self) -> str:
        return f"<CachedResponse [{self.status_code}]>"


def cached_get(
    real_get,
    url: str,
    params: Any = None,
    **kwargs,
) -> Any:
    """
    Wrap a real GET callable with disk caching.

    ``real_get`` should accept ``url`` and ``**kwargs`` and return an object
    with ``status_code``, ``text``, ``headers`` and ``json()``.
    The returned object gets a ``from_cache`` attribute (``True`` for cache hits).
    """
    key = _make_key("GET", url, params)
    cached = _get_cached(key)
    if cached is not None:
        status_code, text, headers_json, _expires = cached
        try:
            headers = json.loads(headers_json)
        except Exception:
            headers = {}
        return CachedResponse(status_code, text, headers, url, from_cache=True)

    _record_cache_event("cache_miss", url)
    response = real_get(url, params=params, **kwargs)

    # Cache successful GETs and 404s (they are expensive to re-fetch too).
    # Do not cache 5xx; retry logic handles those.
    try:
        if response.status_code in (200, 404) and response.text is not None:
            ttl = ttl_for_url(url)
            _store_cache(
                key,
                url,
                params,
                response.status_code,
                response.text,
                dict(response.headers) if hasattr(response, "headers") else {},
                ttl=ttl,
            )
    except Exception as e:
        logger.debug(f"Could not cache response: {e}")

    # Tag live responses so callers can tell whether data came from cache.
    try:
        response.from_cache = False
    except Exception:
        pass
    return response
