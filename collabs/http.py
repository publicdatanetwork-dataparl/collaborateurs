"""Session HTTP partagée : User-Agent identifiable, retries avec backoff."""

from __future__ import annotations

import os

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = os.environ.get(
    "COLLABS_USER_AGENT",
    "dataparl-collaborateurs/1.0 (+https://github.com/dataparl/collaborateurs; suivi civique des collaborateurs parlementaires)",
)
TIMEOUT = 60


def make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=3,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", TIMEOUT)
    r = session.get(url, **kwargs)
    r.raise_for_status()
    return r
