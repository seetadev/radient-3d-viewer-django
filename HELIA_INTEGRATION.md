# Helia integration points (plan and scaffold)

Status: **planning + scaffold only.** `app/helia_client.py` is a tested client; nothing in the project imports it and no view, URL, setting or template uses it (a test enforces that). This document says where Helia would plug in and what is still undecided.

The app never embeds Helia. It calls the **Helia sidecar** (`meshkit-sidecar-helia`, in `seetadev/Tornado-Backend-Stack`) over HTTP.

## The sidecar contract (read from the source at commit `8afe218`, then confirmed by running it)

| Call | Behaviour |
|---|---|
| `POST /upload` (raw bytes) | `200 {"cid": "..."}`. Over the limit (`MESHKIT_HELIA_MAX_UPLOAD_MB`, default **20**) -> `413 {"error":"payload_too_large"}`. |
| `GET /retrieve/<cid>` | `200` raw bytes. Malformed CID -> `400 {"error":"invalid CID"}` (fast, including CID-shaped strings that do not decode). A CID it does not hold -> **`504` after 5 s** (`HELIA_RETRIEVE_TIMEOUT_MS`), **not 404**, in the default `HELIA_NETWORK=offline` mode. |
| `GET /list` | every CID uploaded since the sidecar started (global, not per user). |
| `GET /health` | `200 {"status":"ok","peerId":...}`, unauthenticated. |
| auth | every route except `/health` needs `X-Meshkit-Helia-Token: <MESHKIT_HELIA_SHARED_SECRET>` (constant-time compare) -> otherwise `401`. The sidecar exposes **no host port** in its compose file: it is meant to be reached only over the docker network. |

Verified against the real sidecar (`tests/integration/test_helia_real.py`): a 47-byte payload came back with the CID `bafkrei...` that equals `CIDv1/raw/sha2-256` computed locally; the same bytes always give the same CID; unknown CID -> `HeliaTimeout` after 5.0 s; 413 at 1 MiB + 1 with a 1 MB limit; 400 for malformed CIDs; 401 on every route without the token except `/health`.

Not in the sidecar: **delete**, per-user ownership, and (offline mode) any replication or fetching from the network. Payloads over one chunk (1 MiB) get a DAG root CID, so the client cannot recompute the CID to check the bytes; keep a separate `sha256`.

**Sidecar bug found while testing (commit `8afe218`):** `POST /upload` **without a `Content-Type` header** is answered `200` with the CID of an *empty* file (`bafkreihdwdcef...`) and **nothing is stored** (the body is never parsed, so the size limit is not enforced either). Clients must always send `Content-Type: application/octet-stream`; `HeliaClient` and the Tornado proxy do. An `xfail` integration test documents the desired behaviour and flips to XPASS when it is fixed upstream.

Tornado-Backend-Stack also has a proxy, `/meshkit-helia/*` (`handlers/meshkit.py`), that holds the secret and maps errors the same way (unreachable -> 502, slow -> 504, 413/400 locally). It has **no caller authentication** (only a CORS allowlist, which is not authentication) and no `/health` route, and its `/list` is open. See the add-on's document for why that matters.

**Dependency:** the sidecar exists only in the open PR [seetadev/Tornado-Backend-Stack#15](https://github.com/seetadev/Tornado-Backend-Stack/pull/15) (`migrate/07b-helia` -> `staging`, stacked on other unmerged PRs). The repository is private.

## What the scaffold provides

`app/helia_client.py`: `HeliaClient(base_url, secret, ...)` with `put(bytes) -> cid`, `get(cid) -> bytes`, `health() -> bool`, **synchronous**, built on `httpx` (pinned in `requirements.txt`; Django views here are sync, and one client instance is reused per process).

- Checked **locally before any request**: CID shape (same two formats as the sidecar, matched with `fullmatch`), payload size (default 20 MiB), non-empty bytes.
- Secret is sent only as `X-Meshkit-Helia-Token`, never logged, never in `repr()` or an error message; **redirects are never followed** (the token cannot be forwarded elsewhere).
- Errors, mapped like the Tornado proxy so callers can fall back uniformly: unreachable / 502 / 503 / secret mismatch (401) -> `HeliaUnavailable` (502, secret mismatch is the subclass `HeliaMisconfigured`); slow or 504 -> `HeliaTimeout` (504); bad CID -> `HeliaInvalidCid` (400); too large -> `HeliaPayloadTooLarge` (413); 404 -> `HeliaNotFound`; anything else -> `HeliaError` (500).
- Upload replies are validated (a reply without a valid CID is an error, not trusted).
- Downloads are streamed and counted: a reply bigger than `max_download_bytes` (64 MiB) is a plain `HeliaError`, and a total deadline of `HELIA_REQUEST_TIMEOUT` bounds slow-drip responses (`httpx` timeouts are per read). `HTTP(S)_PROXY` variables are ignored (the sidecar is on a private network).

## Configuration

| Variable | Meaning |
|---|---|
| `HELIA_SIDECAR_URL` | Base URL, e.g. `http://meshkit-sidecar-helia:5052`. **Unset = Helia disabled** (`HeliaClient.from_env()` returns `None`). |
| `HELIA_SIDECAR_SECRET` | Must equal the sidecar's `MESHKIT_HELIA_SHARED_SECRET`. Server-side only. Plain `http://` is acceptable only on a private network; use TLS otherwise, since the secret is in a header. |
| `HELIA_API_PREFIX`, `HELIA_HEALTH_PATH` | `""` and `/health` for the sidecar itself; `/meshkit-helia` if going through the Tornado proxy. |
| `HELIA_MAX_UPLOAD_MB`, `HELIA_CONNECT_TIMEOUT`, `HELIA_REQUEST_TIMEOUT` | 20, 3 s, 8 s. |

## Integration points

1. **GLB models by CID (the main one).** Today WhiteNoise serves `app/static/models/<name>.glb` and the template hands the viewer `data-models-url="{% static 'models/' %}"` (`app/static/app.js` loads `${MODELS_URL}<name>.glb`). The models are the same five GLBs as in the Tornado app (0.18-1.9 MB, 4.1 MB total, under the 20 MB cap).
   - Publish step (a management command, not written yet): `put()` each GLB and write `models/manifest.json` with `{name: {cid, bytes, sha256}}`. **Identical bytes give identical CIDs, so the Tornado and Django apps would share one set of CIDs** and one stored copy.
   - Serve step: a view at `/models/<name>.glb` (and the template's `data-models-url` pointing at it) fetches by CID, verifies `sha256` against the manifest (the sidecar is a separate process, and for files over 1 MiB the CID cannot be re-derived), and answers with `ETag: "<cid>"` and `Cache-Control: public, max-age=31536000, immutable`. The view stays same-origin, so `CSPMiddleware`'s policy does not change and no browser ever talks to the sidecar.
   - A synchronous view holds a gunicorn worker for up to the request timeout when the sidecar is slow, so keep the timeouts short (8 s total, 3 s connect), cache the verified bytes in-process, and use the "down" flag below.
2. **User-uploaded models (future).** There is no upload endpoint today. A real one would validate that the bytes are a GLB, `put()` them and store the CID against the user in the database (the sidecar has no ownership, and its `/list` is global). This is where encryption and deletion questions bite (below).
3. **Health gating.** At startup and then every ~30 s, `health()` decides whether to try Helia at all; after a 502/504 mark it "down" briefly so requests do not each pay the timeout.

## Fallback on 502 / 504

Helia must never be the only copy until the mentor decides otherwise. The bundled files in `models/` stay the fallback:

- `HeliaUnavailable` (502) or `HeliaTimeout` (504) -> serve the local file for that `<name>`, log one warning (no secret, no payload), mark Helia "down" briefly.
- A `504` can mean "slow" **or** "this sidecar does not hold that CID" (offline mode), so both take the same path.
- `HeliaMisconfigured` is a deployment bug: log it loudly, fall back, and surface it in `/health` rather than failing user requests.
- If there is no local copy either (a CID-only model), answer `503` with `Retry-After`, never a 500. The files in `app/static/models/` stay the fallback (and WhiteNoise keeps serving them).

When this is wired in, read the `HELIA_*` variables in `Radient_Django/settings.py` (next to the existing `DJANGO_*` ones), pass them through `docker-compose.yml`, and list them in the README. No `Dockerfile` change is needed: the whole `app` package is already copied.

## Is encryption needed?

- **The bundled demo models: no.** They are public assets; content addressing and sharing them is the point.
- **User-uploaded models: depends on the product.** The sidecar stores plaintext, has no delete, and `/list` shows every CID; in `online` mode a queried CID is visible to peers and gateways. If uploads can be private, encrypt before `put()` (for example AES-256-GCM with a per-user key kept by the app, never by the sidecar) and keep `HELIA_NETWORK=offline`. Encrypting also defeats de-duplication across users.

## Open questions

1. Where does the sidecar run for this app: inside this repo's compose, or the shared Tornado-Backend-Stack network? (Its source is in a private repo, so this repo's compose cannot build it without credentials.)
2. Should Helia become the source of truth for models, or stay a cache with the files in `app/static/models/` as the master? And should the Tornado and Django apps share one manifest?
3. Do users upload models? If so: size limit, GLB validation, ownership, privacy, and what "delete" means when the sidecar has no delete.
4. Online or offline Helia? Offline is a single node with one volume: nothing replicates and a lost volume loses the models.
5. Should the fetch be public (`/models/by-cid/<cid>`)? Because `/list` and CIDs are not secret, anyone with a CID can read it through such a route.

## Running the opt-in integration test (real sidecar)

```bash
git clone git@github.com:seetadev/Tornado-Backend-Stack.git ../Tornado-Backend-Stack
git -C ../Tornado-Backend-Stack checkout 8afe218
export HELIA_SIDECAR_BUILD_CONTEXT=$PWD/../Tornado-Backend-Stack/meshkit-sidecar-helia
export HELIA_SIDECAR_SECRET=$(openssl rand -hex 32)
docker compose -f tests/integration/docker-compose.helia.yml up -d --build --wait
HELIA_SIDECAR_URL=http://127.0.0.1:5052 pytest tests/integration -v -s
docker compose -f tests/integration/docker-compose.helia.yml down -v
```

Without `HELIA_SIDECAR_URL` those tests are skipped (CI never needs the sidecar). The regular unit tests (`pytest`) use `tests/helia_mock.py`, a **mock** of the contract above, not the real sidecar.
