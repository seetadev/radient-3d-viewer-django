"""MOCK of the Helia sidecar's HTTP contract (meshkit-sidecar-helia/index.js) as an httpx transport. NOT the real
sidecar and not real IPFS. CIDs are computed locally as CIDv1/raw/sha2-256 (what a one-chunk payload gets); the opt-in
integration test (tests/integration/test_helia_real.py) checks the real sidecar returns exactly that.

Behaviour copied from the real sidecar: every route but /health needs X-Meshkit-Helia-Token (else 401); POST /upload
takes raw bytes, answers {"cid"} and 413 over the limit; GET /retrieve/<cid> answers 400 for a malformed CID and, for a
CID it does not hold, 504 (the real sidecar's default offline mode waits 5 s and then answers 504).
"""
import base64
import hashlib
import re

import httpx

_CID = re.compile(r"Qm[1-9A-HJ-NP-Za-km-z]{44}|b[a-z2-7]{20,}")


def fake_cid(data):
    multihash = bytes([0x01, 0x55, 0x12, 0x20]) + hashlib.sha256(data).digest()
    return "b" + base64.b32encode(multihash).decode().lower().rstrip("=")


class Mock:
    def __init__(self, secret="test-secret-not-real", max_upload=1024):
        self.secret = secret
        self.max_upload = max_upload
        self.store = {}
        self.requests = []     # (method, path, token header or None)
        self.mode = None       # None | an int status | "connect-error" | "connect-timeout" | "read-timeout" | "reset"
                               # | "bad-json" | "bad-cid" | "huge"
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request):
        path = request.url.path
        token = request.headers.get("X-Meshkit-Helia-Token")
        self.requests.append((request.method, path, token))
        if self.mode == "connect-error":
            raise httpx.ConnectError("connection refused", request=request)
        if self.mode == "connect-timeout":
            raise httpx.ConnectTimeout("timed out connecting", request=request)
        if self.mode == "read-timeout":
            raise httpx.ReadTimeout("timed out reading", request=request)
        if self.mode == "reset":
            raise httpx.RemoteProtocolError("connection reset", request=request)
        route = path.removeprefix("/meshkit-helia")
        if route != "/health" and token != self.secret:
            return httpx.Response(401, json={"error": "unauthorized", "message": "missing or invalid X-Meshkit-Helia-Token"})
        if isinstance(self.mode, int) and self.mode not in (302,):
            return httpx.Response(self.mode, json={"error": "forced %d" % self.mode})
        if self.mode == 302:
            return httpx.Response(302, headers={"Location": "http://elsewhere.invalid/"})
        if route == "/health":
            return httpx.Response(200, json={"status": "ok", "peerId": "12D3KooWMock"})
        if route == "/upload" and request.method == "POST":
            body = request.content
            if len(body) > self.max_upload:
                return httpx.Response(413, json={"error": "payload_too_large", "message": "upload exceeds the limit"})
            cid = fake_cid(body)
            self.store[cid] = body
            if self.mode == "bad-json":
                return httpx.Response(200, text="<html>not json</html>")
            if self.mode == "bad-cid":
                return httpx.Response(200, json={"cid": "../../etc/passwd"})
            return httpx.Response(200, json={"cid": cid})
        if route.startswith("/retrieve/") and request.method == "GET":
            cid = route.removeprefix("/retrieve/")
            if not _CID.fullmatch(cid):
                return httpx.Response(400, json={"error": "invalid CID"})
            if self.mode == "huge":
                return httpx.Response(200, content=b"z" * 5000)
            if cid not in self.store:
                return httpx.Response(504, json={"error": "retrieve timed out after 5s"})   # offline mode: unknown CID
            return httpx.Response(200, content=self.store[cid], headers={"Content-Type": "application/octet-stream"})
        return httpx.Response(404, json={"error": "no such route"})
