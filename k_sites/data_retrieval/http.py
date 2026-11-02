"""
Shared HTTP helper for the K-Sites data retrieval modules.

One pooled session with retry/backoff so a busy public API (HTTP 429/5xx) is retried
instead of silently turning into "no data".
"""

import threading
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from k_sites.data_retrieval.cache import cached_get

DEFAULT_TIMEOUT = 30
USER_AGENT = "K-Sites/1.2 (safe gene selection for knockout studies)"

_session: Optional[requests.Session] = None
_lock = threading.Lock()


def get_session() -> requests.Session:
    """Return the shared session (created on first use, safe across threads)."""
    global _session
    if _session is None:
        with _lock:
            if _session is None:
                session = requests.Session()
                retry = Retry(
                    total=4,
                    backoff_factor=0.8,
                    status_forcelist=(429, 500, 502, 503, 504),
                    allowed_methods=("GET",),
                    respect_retry_after_header=True,
                    raise_on_status=False,
                )
                adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=32)
                session.mount("https://", adapter)
                session.mount("http://", adapter)
                session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
                _session = session
    return _session


def _real_http_get(url: str, **kwargs) -> requests.Response:
    """Uncached GET through the shared session."""
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    return get_session().get(url, **kwargs)


def http_get(url: str, **kwargs) -> requests.Response:
    """GET through the shared session, with disk caching for repeated requests."""
    params = kwargs.pop("params", None)
    use_cache = kwargs.pop("use_cache", True)
    if not use_cache:
        kwargs["params"] = params
        return _real_http_get(url, **kwargs)
    return cached_get(_real_http_get, url, params=params, **kwargs)
