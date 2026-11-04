"""Opt-in: the client against the REAL Helia sidecar. Skipped unless HELIA_SIDECAR_URL is set.

    export HELIA_SIDECAR_SECRET=$(openssl rand -hex 32)
    docker compose -f tests/integration/docker-compose.helia.yml up -d --build --wait
    HELIA_SIDECAR_URL=http://127.0.0.1:5052 pytest tests/integration -v -s
    docker compose -f tests/integration/docker-compose.helia.yml down -v

HELIA_MAX_UPLOAD_MB must match the sidecar's (the compose file uses 1). Takes ~10 s: one test waits for the sidecar's
own 5 s retrieve timeout.
"""
import base64
import hashlib
import json
import os
import socket
import time

import httpx
import pytest

from app.helia_client import (
    HeliaClient, HeliaInvalidCid, HeliaMisconfigured, HeliaPayloadTooLarge, HeliaTimeout, HeliaUnavailable, is_valid_cid,
)

URL = os.environ.get("HELIA_SIDECAR_URL", "").strip()
SECRET = os.environ.get("HELIA_SIDECAR_SECRET", "")
LIMIT = int(float(os.environ.get("HELIA_MAX_UPLOAD_MB", "1")) * 1024 * 1024)

pytestmark = pytest.mark.skipif(not URL, reason="set HELIA_SIDECAR_URL (and HELIA_SIDECAR_SECRET) to run against the real sidecar")


def raw_cid(data):
    """CIDv1 / raw / sha2-256, computed locally."""
    return "b" + base64.b32encode(bytes([0x01, 0x55, 0x12, 0x20]) + hashlib.sha256(data).digest()).decode().lower().rstrip("=")


def raw_http(method, path, body=None, token=SECRET, content_type="application/octet-stream"):
    """A request that bypasses the client, to see what the sidecar itself answers."""
    headers = {"X-Meshkit-Helia-Token": token} if token else {}
    if body is not None and content_type:
        headers["Content-Type"] = content_type
    r = httpx.request(method, URL.rstrip("/") + path, content=body, headers=headers, timeout=15, trust_env=False)
    return r.status_code, r.content


@pytest.fixture
def client():
    with HeliaClient.from_env() as c:
        yield c


def test_health(client):
    assert client.health() is True


def test_put_get_round_trip_and_deterministic_cid(client):
    data = b"radient-django/helia integration test " + os.urandom(16)
    cid = client.put(data)
    print("\n  put %d bytes -> %s" % (len(data), cid))
    assert is_valid_cid(cid)
    assert cid == raw_cid(data), "a one-chunk payload should get the raw-leaf CIDv1 computed locally"
    assert client.get(cid) == data
    assert client.put(data) == cid                          # same bytes, same CID


def test_binary_payload_near_the_limit(client):
    data = os.urandom(LIMIT - 1024)
    cid = client.put(data)
    assert client.get(cid) == data


def test_unknown_cid_is_a_504_after_the_sidecars_own_timeout(client):
    missing = raw_cid(os.urandom(32))                       # well-formed, never stored
    start = time.monotonic()
    with pytest.raises(HeliaTimeout) as e:
        client.get(missing)
    took = time.monotonic() - start
    print("\n  unknown CID -> %s (%d) after %.1fs" % (type(e.value).__name__, e.value.status, took))
    assert 4 <= took < 8


def test_wrong_secret_is_misconfigured_502():
    with HeliaClient(URL, "definitely-not-the-secret") as wrong:
        with pytest.raises(HeliaMisconfigured) as e:
            wrong.put(b"x")
        assert e.value.status == 502
        assert wrong.health() is True                       # /health is unauthenticated on the real sidecar


def test_unreachable_is_502():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with HeliaClient("http://127.0.0.1:%d" % port, SECRET, connect_timeout=1) as down:
        with pytest.raises(HeliaUnavailable) as e:
            down.put(b"x")
        assert e.value.status == 502 and down.health() is False


def test_invalid_cid_client_side_and_sidecar_side(client):
    with pytest.raises(HeliaInvalidCid):
        client.get("not-a-cid")
    status, body = raw_http("GET", "/retrieve/not-a-cid")
    print("\n  sidecar itself, GET /retrieve/not-a-cid -> %d %s" % (status, body.decode()))
    assert status == 400
    # shaped like a CID but not a decodable one: also a fast 400 from the sidecar, not a hang
    status, body = raw_http("GET", "/retrieve/b" + "a" * 30)
    print("  sidecar itself, shaped-but-undecodable CID -> %d %s" % (status, body.decode()))
    assert status == 400


def test_oversized_upload_client_side_and_sidecar_side(client):
    with pytest.raises(HeliaPayloadTooLarge):
        client.put(b"x" * (LIMIT + 1))
    status, body = raw_http("POST", "/upload", b"x" * (LIMIT + 1))
    print("\n  sidecar itself, %d-byte upload -> %d %s" % (LIMIT + 1, status, body.decode()))
    assert status == 413
    assert json.loads(body)["error"] == "payload_too_large"


def test_sidecar_requires_the_secret_on_every_route_but_health():
    for method, path, body in (("POST", "/upload", b"x"), ("GET", "/list", None), ("GET", "/retrieve/" + raw_cid(b"x"), None)):
        assert raw_http(method, path, body, token="")[0] == 401, (method, path)
    assert raw_http("GET", "/health", token="")[0] == 200


@pytest.mark.xfail(strict=False, reason="upstream sidecar bug (Tornado-Backend-Stack#15, 8afe218): an upload with no Content-Type "
                                         "header is answered 200 with the EMPTY-file CID and nothing is stored. HeliaClient always "
                                         "sends application/octet-stream, so it is not affected. Passes (XPASS) once fixed upstream.")
def test_sidecar_should_not_silently_store_nothing_when_content_type_is_missing():
    status, body = raw_http("POST", "/upload", b"hello world", content_type=None)
    assert status != 200 or json.loads(body)["cid"] == raw_cid(b"hello world")
