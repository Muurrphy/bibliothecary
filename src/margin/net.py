"""HTTPS requests over kept-alive connections (no dependencies).

Every call to OpenAI or ElevenLabs over a fresh connection first spends a few hundred
milliseconds on the TCP and TLS handshakes. A question needs three such calls in a row
(speech to text, the answer, the voice), so Margin keeps connections open and reuses
them, and opens them before the first question (``warm``).

When a proxy is configured in the environment, plain ``urllib`` is used instead.
"""

from __future__ import annotations

import contextlib
import http.client
import os
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from urllib.parse import urlsplit

_idle: dict[str, list[http.client.HTTPSConnection]] = {}
_context = None   # an ssl.SSLContext to use instead of the default (tests)
_lock = threading.Lock()


def _proxied() -> bool:
    return any(os.environ.get(k) for k in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"))


class Response:
    """Status, body (or lines while streaming) of one request."""

    def __init__(self, status: int, raw, release) -> None:
        self.status, self._raw, self._release = status, raw, release

    def read(self) -> bytes:
        try:
            return self._raw.read()
        finally:
            self._release()

    def lines(self) -> Iterator[bytes]:
        try:
            while True:
                line = self._raw.readline()
                if not line:
                    return
                yield line
        finally:
            self._release()


def _get(host: str, timeout: float) -> http.client.HTTPSConnection:
    with _lock:
        pool = _idle.setdefault(host, [])
        if pool:
            conn = pool.pop()
            conn.timeout = timeout
            if conn.sock is not None:
                conn.sock.settimeout(timeout)
            return conn
    return http.client.HTTPSConnection(host, timeout=timeout, context=_context)


def _put(host: str, conn: http.client.HTTPSConnection) -> None:
    with _lock:
        pool = _idle.setdefault(host, [])
        if len(pool) < 4:
            pool.append(conn)
            return
    conn.close()


def request(method: str, url: str, body: bytes | None = None, headers: dict | None = None,
            timeout: float = 60.0) -> Response:
    """Send a request; raises ``urllib.error.HTTPError`` for 4xx/5xx like urllib does."""
    headers = dict(headers or {})
    if _proxied():
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        res = urllib.request.urlopen(req, timeout=timeout)   # raises HTTPError itself
        return Response(res.status, res, res.close)
    parts = urlsplit(url)
    host, path = parts.netloc, parts.path + (f"?{parts.query}" if parts.query else "")
    for attempt in (1, 2):
        conn = _get(host, timeout)
        try:
            conn.request(method, path, body=body, headers=headers)
            res = conn.getresponse()
            break
        except (http.client.HTTPException, OSError):
            conn.close()
            if attempt == 2:
                raise
            # an idle connection the server had already closed: try once on a new one
    if res.status >= 400:
        data = res.read()
        if res.will_close:
            conn.close()
        else:
            _put(host, conn)
        import io

        raise urllib.error.HTTPError(url, res.status, res.reason, res.headers, io.BytesIO(data))

    def release() -> None:
        if res.isclosed() and not res.will_close:   # fully read and the server keeps it open
            _put(host, conn)
        else:
            conn.close()

    return Response(res.status, res, release)


def warm(url: str, headers: dict | None = None) -> None:
    """Open a connection ahead of time (in the background) so the first real call is quick."""

    def run() -> None:
        with contextlib.suppress(Exception):   # only a head start; the real call retries anyway
            request("GET", url, headers=headers, timeout=10).read()

    threading.Thread(target=run, daemon=True, name="margin-warm").start()
