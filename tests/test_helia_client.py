"""Unit tests for app/helia_client.py against tests/helia_mock.py (a mock of the sidecar's HTTP contract), plus a few
real-socket cases for the transport-level mapping (refused connection, a really hung server, proxy variables)."""
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.helia_client import (
    HeliaClient, HeliaError, HeliaInvalidCid, HeliaMisconfigured, HeliaNotFound, HeliaPayloadTooLarge,
    HeliaTimeout, HeliaUnavailable, is_valid_cid,
)
from tests.helia_mock import Mock, fake_cid

SECRET = "test-secret-not-real"
BASE = "http://sidecar.test:5052"
GOOD_CID = fake_cid(b"anything")


@pytest.fixture
def mock():
    return Mock(secret=SECRET, max_upload=1024)


@pytest.fixture
def client(mock):
    with HeliaClient(BASE, SECRET, max_upload_bytes=1024, transport=mock.transport) as c:
        yield c


def make(mock, **kw):
    return HeliaClient(BASE, kw.pop("secret", SECRET), transport=mock.transport, **kw)


# ---- success ----------------------------------------------------------------------------------------------
def test_put_returns_a_cid_and_get_returns_the_same_bytes(client):
    cid = client.put(b"hello helia")
    assert is_valid_cid(cid) and cid == fake_cid(b"hello helia")
    assert client.get(cid) == b"hello helia"


def test_every_call_but_health_sends_the_secret_and_health_does_not_need_it(mock, client):
    cid = client.put(b"x")
    client.get(cid)
    assert client.health() is True
    sent = {(m, p): t for m, p, t in mock.requests}
    assert sent[("POST", "/upload")] == SECRET and sent[("GET", "/retrieve/" + cid)] == SECRET
    with make(mock, secret=None) as anonymous:
        assert anonymous.health() is True


def test_binary_payload_round_trips_unchanged(client):
    data = bytes(range(256)) * 3
    assert client.get(client.put(data)) == data


def test_prefix_is_used_for_the_tornado_proxy_paths(mock):
    with make(mock, prefix="/meshkit-helia") as c:
        cid = c.put(b"via proxy")
        assert c.get(cid) == b"via proxy"
    assert ("POST", "/meshkit-helia/upload", SECRET) in mock.requests


# ---- 502: unreachable / unavailable -----------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["connect-error", "connect-timeout", "reset", 502, 503])
def test_unreachable_or_unavailable_is_502(mock, client, mode):
    mock.mode = mode
    with pytest.raises(HeliaUnavailable) as e:
        client.put(b"x")
    assert e.value.status == 502
    with pytest.raises(HeliaUnavailable):
        client.get(GOOD_CID)
    assert client.health() is False


def test_wrong_secret_is_a_misconfiguration_reported_as_502(mock):
    with make(mock, secret="not-the-secret") as wrong:
        with pytest.raises(HeliaMisconfigured) as e:
            wrong.put(b"x")
        assert e.value.status == 502 and isinstance(e.value, HeliaUnavailable)
        assert "not-the-secret" not in str(e.value) and "not-the-secret" not in repr(wrong)


# ---- 504: slow / timed out --------------------------------------------------------------------------------
def test_sidecar_504_is_timeout(mock, client):
    mock.mode = 504
    with pytest.raises(HeliaTimeout) as e:
        client.get(GOOD_CID)
    assert e.value.status == 504


def test_unknown_cid_is_timeout_504_like_the_real_offline_sidecar(client):
    with pytest.raises(HeliaTimeout):
        client.get(GOOD_CID)


def test_read_timeout_is_504(mock, client):
    mock.mode = "read-timeout"
    with pytest.raises(HeliaTimeout) as e:
        client.put(b"x")
    assert e.value.status == 504
    assert client.health() is False


# ---- invalid CID ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["", "Qm", "../../etc/passwd", "bafy/../x", GOOD_CID + "\n", GOOD_CID.upper(),
                                   "Qm" + "0" * 44, "b" + "1" * 30, " " + GOOD_CID, GOOD_CID + "?x=1",
                                   "http://evil.invalid/", None, 5, b"bafy"])
def test_invalid_cids_are_refused_locally_without_calling_the_sidecar(mock, client, value):
    with pytest.raises(HeliaInvalidCid) as e:
        client.get(value)
    assert e.value.status == 400
    assert mock.requests == []


def test_sidecar_400_is_invalid_cid_too(mock, client):
    mock.mode = 400
    with pytest.raises(HeliaInvalidCid):
        client.get(GOOD_CID)


# ---- oversize ---------------------------------------------------------------------------------------------
def test_oversized_upload_is_refused_locally_413(mock, client):
    with pytest.raises(HeliaPayloadTooLarge) as e:
        client.put(b"x" * 1025)
    assert e.value.status == 413
    assert mock.requests == []
    assert client.put(b"x" * 1024)                       # exactly the limit is fine


def test_sidecar_413_is_payload_too_large(mock):
    with make(mock, max_upload_bytes=10_000) as bigger:
        with pytest.raises(HeliaPayloadTooLarge):
            bigger.put(b"x" * 2000)                      # the sidecar's own limit (1024) is hit


def test_empty_and_non_bytes_payloads_are_refused(client):
    with pytest.raises(ValueError):
        client.put(b"")
    for bad in ("text", 5, None, ["x"]):
        with pytest.raises(TypeError):
            client.put(bad)
    assert client.put(bytearray(b"ok")) and client.put(memoryview(b"ok2"))


def test_download_over_the_limit_is_an_error_not_a_buffer(mock):
    mock.mode = "huge"
    with make(mock, max_download_bytes=100) as small:
        with pytest.raises(HeliaError) as e:
            small.get(GOOD_CID)
    assert "download limit" in str(e.value) and type(e.value) is HeliaError


# ---- other failure shapes ---------------------------------------------------------------------------------
def test_sidecar_404_is_not_found(mock, client):
    mock.mode = 404
    with pytest.raises(HeliaNotFound) as e:
        client.get(GOOD_CID)
    assert e.value.status == 404


def test_unexpected_status_is_a_plain_error(mock, client):
    mock.mode = 500
    with pytest.raises(HeliaError) as e:
        client.put(b"x")
    assert type(e.value) is HeliaError and e.value.status == 500


@pytest.mark.parametrize("mode", ["bad-json", "bad-cid"])
def test_malformed_upload_replies_are_rejected(mock, client, mode):
    mock.mode = mode
    with pytest.raises(HeliaError):
        client.put(b"x")


def test_redirects_are_never_followed(mock, client):
    mock.mode = 302
    with pytest.raises(HeliaError):
        client.put(b"x")
    assert [p for _, p, _ in mock.requests] == ["/upload"]       # never asked elsewhere with the secret


# ---- real sockets ------------------------------------------------------------------------------------------
def closed_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_real_connection_refused_is_unavailable_502():
    with HeliaClient("http://127.0.0.1:%d" % closed_port(), SECRET, connect_timeout=1) as c:
        with pytest.raises(HeliaUnavailable) as e:
            c.put(b"x")
        assert e.value.status == 502
        assert c.health() is False


class _Slow(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = b'{"status": "ok"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        import time
        time.sleep(2)

    do_POST = do_GET

    def log_message(self, *a):
        pass


@pytest.fixture
def slow_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Slow)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()


def test_a_really_hung_server_times_out_fast_as_504(slow_server):
    with HeliaClient(slow_server, SECRET, request_timeout=0.4) as c:
        with pytest.raises(HeliaTimeout) as e:
            c.get(GOOD_CID)
        assert e.value.status == 504
        with pytest.raises(HeliaTimeout):
            c.put(b"x")


def test_proxy_environment_variables_are_ignored(slow_server, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:%d" % closed_port())
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:%d" % closed_port())
    with HeliaClient(slow_server, SECRET) as c:
        assert c.health() is True                                 # went straight to the sidecar, not to the proxy


# ---- configuration ----------------------------------------------------------------------------------------
def test_unset_url_means_disabled():
    assert HeliaClient.from_env({}) is None
    assert HeliaClient.from_env({"HELIA_SIDECAR_URL": "  "}) is None


def test_from_env_reads_every_setting():
    with HeliaClient.from_env({"HELIA_SIDECAR_URL": "http://sidecar:5052/", "HELIA_SIDECAR_SECRET": "s",
                               "HELIA_API_PREFIX": "/meshkit-helia/", "HELIA_HEALTH_PATH": "/h",
                               "HELIA_MAX_UPLOAD_MB": "0.5", "HELIA_CONNECT_TIMEOUT": "2",
                               "HELIA_REQUEST_TIMEOUT": "4"}) as c:
        assert (c.base_url, c.prefix, c.health_path) == ("http://sidecar:5052", "/meshkit-helia", "/h")
        assert (c.max_upload_bytes, c.request_timeout) == (524288, 4.0)
        assert "secret=set" in repr(c) and "'s'" not in repr(c)


@pytest.mark.parametrize("env", [
    {"HELIA_SIDECAR_URL": "ftp://x"}, {"HELIA_SIDECAR_URL": "not a url"},
    {"HELIA_SIDECAR_URL": "http://user:pw@host:1"}, {"HELIA_SIDECAR_URL": "http://h:1/?a=1"},
    {"HELIA_SIDECAR_URL": "http://h:1", "HELIA_API_PREFIX": "no-slash"},
    {"HELIA_SIDECAR_URL": "http://h:1", "HELIA_API_PREFIX": "/a b"},
    {"HELIA_SIDECAR_URL": "http://h:1", "HELIA_API_PREFIX": "//evil.invalid"},
    {"HELIA_SIDECAR_URL": "http://h:1", "HELIA_API_PREFIX": "/../x"},
    {"HELIA_SIDECAR_URL": "http://h:1", "HELIA_HEALTH_PATH": "/a/./b"},
    {"HELIA_SIDECAR_URL": "http://h:1", "HELIA_MAX_UPLOAD_MB": "lots"},
    {"HELIA_SIDECAR_URL": "http://h:1", "HELIA_REQUEST_TIMEOUT": "0"},
])
def test_bad_values_fail_loudly(env):
    with pytest.raises(ValueError):
        HeliaClient.from_env(env)


def test_the_module_is_not_wired_into_the_project():
    """Scaffold only: no view, setting, URL or template knows about Helia yet."""
    root = Path(__file__).resolve().parent.parent
    files = [root / "Radient_Django" / n for n in ("settings.py", "urls.py", "wsgi.py")]
    files += [p for p in (root / "app").glob("*.py") if p.name != "helia_client.py"]
    files += list((root / "app" / "templates").rglob("*.html"))
    for path in files:
        assert "helia" not in path.read_text().lower(), path
