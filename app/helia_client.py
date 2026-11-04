"""Client for the Helia IPFS sidecar (meshkit-sidecar-helia in seetadev/Tornado-Backend-Stack), on httpx.

SCAFFOLD: nothing in the project imports this module yet (see HELIA_INTEGRATION.md). The app never embeds Helia; it
talks to the sidecar over HTTP:

    put(data: bytes) -> cid       POST {base}{prefix}/upload          raw bytes  ->  {"cid": "..."}
    get(cid)        -> bytes      GET  {base}{prefix}/retrieve/<cid>              ->  raw bytes
    health()        -> bool       GET  {base}{health_path}                        ->  {"status": "ok", ...}

Configuration (``HeliaClient.from_env()``; unset ``HELIA_SIDECAR_URL`` means "Helia disabled" -> ``None``):

    HELIA_SIDECAR_URL          base URL, e.g. http://meshkit-sidecar-helia:5052 (docker network)
    HELIA_SIDECAR_SECRET       sent as X-Meshkit-Helia-Token; must equal the sidecar's MESHKIT_HELIA_SHARED_SECRET.
                               Server-side only, never in a browser, never logged. Leave unset behind a proxy that adds it.
    HELIA_API_PREFIX           "" for the sidecar itself (default); "/meshkit-helia" for the Tornado proxy
    HELIA_HEALTH_PATH          "/health" (default)
    HELIA_MAX_UPLOAD_MB        20 (the sidecar's own default); larger uploads are refused before any request
    HELIA_CONNECT_TIMEOUT      3 seconds
    HELIA_REQUEST_TIMEOUT      8 seconds (per read; downloads are also bounded by a total deadline of the same length)

Errors map the way the Tornado proxy maps them (handlers/meshkit.py), so callers can fall back uniformly:

    unreachable (refused, DNS, reset, connect timeout), 502, 503, 401 (secret mismatch)  -> HeliaUnavailable (502)
    too slow, or the sidecar answered 504 (offline mode: an unknown CID ends up here)     -> HeliaTimeout (504)
    malformed CID (checked locally first)                                                 -> HeliaInvalidCid (400)
    upload over the limit (checked locally first; also the sidecar's 413)                 -> HeliaPayloadTooLarge (413)
    sidecar 404                                                                           -> HeliaNotFound (404)
    anything else (unexpected status, a reply that breaks the contract, download too big) -> HeliaError (500)

The client is synchronous (Django views here are sync). Reuse one instance per process and call ``close()`` on shutdown.
"""
import json
import os
import re
import time
from urllib.parse import quote, urlsplit

import httpx

TOKEN_HEADER = "X-Meshkit-Helia-Token"
DEFAULT_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024

# Same two shapes the sidecar accepts: CIDv0 (base58btc, "Qm...", 46 chars) or CIDv1 (multibase "b" + lowercase
# base32). Matched with fullmatch: Python's "$" would also accept a trailing newline.
_CID_V0 = re.compile(r"Qm[1-9A-HJ-NP-Za-km-z]{44}")
_CID_V1 = re.compile(r"b[a-z2-7]{20,}")


def is_valid_cid(value):
    return isinstance(value, str) and bool(_CID_V0.fullmatch(value) or _CID_V1.fullmatch(value))


class HeliaError(Exception):
    """Base class. ``status`` is the HTTP status a view would answer with."""
    status = 500


class HeliaUnavailable(HeliaError):
    status = 502


class HeliaMisconfigured(HeliaUnavailable):
    """The sidecar rejected our secret: a deployment problem, not the caller's fault."""


class HeliaTimeout(HeliaError):
    status = 504


class HeliaInvalidCid(HeliaError):
    status = 400


class HeliaPayloadTooLarge(HeliaError):
    status = 413


class HeliaNotFound(HeliaError):
    status = 404


def _env_float(env, name, default):
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError("%s must be a number, got %r" % (name, raw)) from None
    if value <= 0:
        raise ValueError("%s must be greater than 0, got %r" % (name, raw))
    return value


def _status_error(code):
    if code == 400:
        return HeliaInvalidCid("the sidecar rejected the request as invalid")
    if code == 401:
        return HeliaMisconfigured("the sidecar rejected our shared secret")
    if code == 404:
        return HeliaNotFound("not found")
    if code == 413:
        return HeliaPayloadTooLarge("the sidecar refused the upload as too large")
    if code in (502, 503):
        return HeliaUnavailable("sidecar unavailable (%d)" % code)
    if code == 504:
        return HeliaTimeout("sidecar timed out")
    return HeliaError("unexpected sidecar status %d" % code)


class HeliaClient:
    def __init__(self, base_url, secret=None, *, prefix="", health_path="/health",
                 max_upload_bytes=DEFAULT_MAX_UPLOAD_BYTES, max_download_bytes=DEFAULT_MAX_DOWNLOAD_BYTES,
                 connect_timeout=3.0, request_timeout=8.0, transport=None):
        parts = urlsplit(str(base_url or ""))
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("HELIA_SIDECAR_URL must be an http(s) URL, got %r" % (base_url,))
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("HELIA_SIDECAR_URL must not contain credentials, a query or a fragment")
        for name, value in (("prefix", prefix), ("health_path", health_path)):
            if value and not re.fullmatch(r"(?:/[A-Za-z0-9_~-][A-Za-z0-9._~-]*)+/?", value):   # plain segments: no '//', '.', '..
                raise ValueError("%s must be a plain path like '/health' (no '//', '.' or '..'), got %r" % (name, value))
        self.base_url = base_url.rstrip("/")
        self._secret = secret or None
        self.prefix = (prefix or "").rstrip("/")
        self.health_path = health_path or "/health"
        self.max_upload_bytes = int(max_upload_bytes)
        self.max_download_bytes = int(max_download_bytes)
        self.request_timeout = request_timeout
        self._http = httpx.Client(
            timeout=httpx.Timeout(request_timeout, connect=connect_timeout),
            follow_redirects=False,    # a redirect must never carry the secret somewhere else
            trust_env=False,           # ignore HTTP(S)_PROXY: the sidecar is on a private network
            transport=transport,
        )

    def __repr__(self):  # never print the secret
        return "<HeliaClient %s prefix=%r secret=%s>" % (self.base_url, self.prefix, "set" if self._secret else "none")

    @classmethod
    def from_env(cls, env=None, **overrides):
        """A client from HELIA_* variables, or None when HELIA_SIDECAR_URL is unset (Helia disabled)."""
        env = os.environ if env is None else env
        url = env.get("HELIA_SIDECAR_URL", "").strip()
        if not url:
            return None
        kwargs = dict(
            secret=env.get("HELIA_SIDECAR_SECRET") or None,
            prefix=env.get("HELIA_API_PREFIX", "").strip(),
            health_path=env.get("HELIA_HEALTH_PATH", "").strip() or "/health",
            max_upload_bytes=int(_env_float(env, "HELIA_MAX_UPLOAD_MB", 20) * 1024 * 1024),
            connect_timeout=_env_float(env, "HELIA_CONNECT_TIMEOUT", 3.0),
            request_timeout=_env_float(env, "HELIA_REQUEST_TIMEOUT", 8.0),
        )
        kwargs.update(overrides)
        return cls(url, **kwargs)

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- public API -------------------------------------------------------------------------------------

    def put(self, data):
        """Store ``data`` and return its CID (a str)."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("put() takes bytes, got %s" % type(data).__name__)
        data = bytes(data)
        if not data:
            raise ValueError("put() refuses an empty payload")
        if len(data) > self.max_upload_bytes:
            raise HeliaPayloadTooLarge("upload is %d bytes, the limit is %d" % (len(data), self.max_upload_bytes))
        body = self._request("POST", self.prefix + "/upload", content=data,
                             headers={"Content-Type": "application/octet-stream"})
        try:
            cid = json.loads(body.decode("utf-8")).get("cid")
        except (ValueError, AttributeError):
            cid = None
        if not is_valid_cid(cid):
            raise HeliaError("the sidecar's upload reply did not contain a valid CID")
        return cid

    def get(self, cid):
        """Return the bytes stored under ``cid``."""
        if not is_valid_cid(cid):
            raise HeliaInvalidCid("not a valid CID")
        return self._request("GET", "%s/retrieve/%s" % (self.prefix, quote(cid, safe="")), limit=self.max_download_bytes)

    def health(self):
        """True if the sidecar answers its health check; False for any failure (never raises)."""
        try:
            return json.loads(self._request("GET", self.health_path).decode("utf-8")).get("status") == "ok"
        except Exception:
            return False

    # ---- internals --------------------------------------------------------------------------------------

    def _request(self, method, path, *, content=None, headers=None, limit=None):
        headers = dict(headers or {})
        if self._secret:
            headers[TOKEN_HEADER] = self._secret
        deadline = time.monotonic() + self.request_timeout
        try:
            with self._http.stream(method, self.base_url + path, content=content, headers=headers) as response:
                if response.status_code != 200:
                    raise _status_error(response.status_code)
                chunks, total = [], 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if limit is not None and total > limit:
                        raise HeliaError("the sidecar's reply is larger than the %d-byte download limit" % limit)
                    if time.monotonic() > deadline:
                        raise HeliaTimeout("sidecar timed out")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.TimeoutException as e:
            # Connect timeout: nothing is listening (unreachable). Read/write/pool: it is there but too slow.
            raise (HeliaUnavailable("sidecar unreachable") if isinstance(e, httpx.ConnectTimeout)
                   else HeliaTimeout("sidecar timed out")) from None
        except httpx.HTTPError:
            raise HeliaUnavailable("sidecar unreachable") from None
