"""HTTPS-only, host-allowlisted client with retries. Collectors depend on the Fetcher protocol,
so tests inject recorded fixtures and never touch the network."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pqc_tracker.errors import CollectionError

ALLOWED_HOSTS = frozenset(
    {
        "api.github.com",
        "datatracker.ietf.org",
        "firefox-source-docs.mozilla.org",
    }
)
USER_AGENT = "silastron-pqc-tracker (+https://pqc.silastron.com)"
MAX_BYTES = 20 * 1024 * 1024
RETRYABLE = {408, 429, 500, 502, 503, 504}


class Fetcher(Protocol):
    def get_json(self, url: str) -> Any: ...

    def get_text(self, url: str) -> str: ...

    def request_json(self, method: str, url: str, body: dict | None = None) -> Any: ...


class _NoCrossHostRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != "https" or urlparse(newurl).hostname not in ALLOWED_HOSTS:
            raise CollectionError(f"redirect to disallowed location: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpFetcher:
    def __init__(self, timeout: float = 30.0, attempts: int = 3, token: str | None = None):
        self.timeout = timeout
        self.attempts = attempts
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self._opener = build_opener(_NoCrossHostRedirect())

    def _check(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise CollectionError(f"URL not allowed: {url}")

    def _send(self, method: str, url: str, body: dict | None) -> bytes:
        self._check(url)
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.8"}
        if urlparse(url).hostname == "api.github.com":
            headers["Accept"] = "application/vnd.github+json"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        last: Exception | None = None
        # Never retry writes: a retried POST could open a duplicate issue.
        attempts = self.attempts if method == "GET" else 1
        for attempt in range(1, attempts + 1):
            try:
                req = Request(url, data=data, headers=headers, method=method)
                with self._opener.open(req, timeout=self.timeout) as resp:
                    raw = resp.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise CollectionError(f"response too large: {url}")
                return raw
            except HTTPError as exc:
                if exc.code not in RETRYABLE:
                    raise CollectionError(f"HTTP {exc.code} for {method} {url}") from exc
                last = exc
            except (URLError, TimeoutError, OSError) as exc:
                last = exc
            if attempt < attempts:
                time.sleep(2**attempt)
        raise CollectionError(f"giving up on {method} {url}: {last}")

    def get_text(self, url: str) -> str:
        return self._send("GET", url, None).decode("utf-8", errors="strict")

    def get_json(self, url: str) -> Any:
        return self.request_json("GET", url)

    def request_json(self, method: str, url: str, body: dict | None = None) -> Any:
        raw = self._send(method, url, body)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise CollectionError(f"malformed JSON from {url}") from exc
