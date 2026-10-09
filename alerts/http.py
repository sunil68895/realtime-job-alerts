"""Polite HTTP client: browser User-Agent, per-host delay, retries on 429/5xx."""

import time
from urllib.parse import urlparse

import requests

from .models import FetchError

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class Http:
    def __init__(self, min_gap_seconds: float = 1.0, timeout: int = 30, retries: int = 3):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.min_gap = min_gap_seconds
        self.timeout = timeout
        self.retries = retries
        self._last_call = {}

    def _wait_for_host(self, url: str) -> None:
        host = urlparse(url).netloc
        gap = time.monotonic() - self._last_call.get(host, 0)
        if gap < self.min_gap:
            time.sleep(self.min_gap - gap)
        self._last_call[host] = time.monotonic()

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        last_error = None
        for attempt in range(1, self.retries + 1):
            self._wait_for_host(url)
            try:
                resp = self.session.request(method, url, **kwargs)
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code < 400:
                    return resp
                last_error = f"HTTP {resp.status_code} from {url}"
                if resp.status_code not in (429, 500, 502, 503, 504):
                    break
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    time.sleep(min(int(retry_after), 60))
                    continue
            time.sleep(2 ** attempt)
        raise FetchError(last_error or f"Request failed: {url}")

    def get_json(self, url: str, params=None, headers=None):
        resp = self.request("GET", url, params=params, headers=_json_headers(headers))
        return _parse_json(resp)

    def post_json(self, url: str, body, headers=None):
        resp = self.request("POST", url, json=body, headers=_json_headers(headers))
        return _parse_json(resp)

    def get_text(self, url: str, params=None):
        resp = self.request("GET", url, params=params)
        return resp.text, resp.url


def _json_headers(extra):
    headers = {"Accept": "application/json"}
    if extra:
        headers.update(extra)
    return headers


def _parse_json(resp):
    try:
        return resp.json()
    except ValueError as exc:
        raise FetchError(f"Expected JSON from {resp.url}, got: {resp.text[:120]!r}") from exc
