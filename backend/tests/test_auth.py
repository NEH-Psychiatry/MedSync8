"""Tests for Cloudflare Access JWT verification."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jose import jwt

from backend import auth as auth_module
from backend import server as server_module
from backend.retriever import Retriever


# Generate a throwaway RSA keypair per test session and build a minimal JWKS
# that the auth module's JWKSCache can consume.
@pytest.fixture(scope="module")
def rsa_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return {"private_pem": private_pem, "public_pem": public_pem, "kid": "test-kid"}


def _issue_token(keypair, *, aud: str, iss: str, email: str = "user@example.com",
                 exp_offset: int = 300) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "aud": aud,
            "iss": iss,
            "email": email,
            "iat": now,
            "exp": now + exp_offset,
        },
        keypair["private_pem"],
        algorithm="RS256",
        headers={"kid": keypair["kid"]},
    )


@pytest.fixture
def access_client(monkeypatch, tiny_corpus: Path, stub_embedder, stub_anthropic, rsa_keypair):
    # Enable Access by setting env vars
    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", "acme")
    monkeypatch.setenv("CF_ACCESS_AUD", "test-aud-xyz")

    # Stub out JWKS fetch to return the test public key
    async def fake_get(_config, **_kwargs):
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": rsa_keypair["kid"],
                    "use": "sig",
                    "alg": "RS256",
                    # jose accepts full PEM when passed as a JWKS key dict; use 'x5c' or fall back to direct PEM
                    # Simpler path: patch jwt.decode to accept the PEM directly.
                }
            ]
        }

    # Rather than hand-rolling a JWK, monkeypatch the jose.jwt.decode call to
    # verify against the PEM. This keeps the test focused on the middleware
    # wiring, not on key-format plumbing.
    from jose import jwt as real_jwt
    original_decode = real_jwt.decode

    def patched_decode(token, _key, **kwargs):
        return original_decode(token, rsa_keypair["public_pem"], **kwargs)

    monkeypatch.setattr(auth_module.jwt, "decode", patched_decode)
    monkeypatch.setattr(auth_module._cache, "get", fake_get)

    # Wire retriever + anthropic stubs
    retriever = Retriever(str(tiny_corpus), stub_embedder)
    retriever.load_or_build()
    monkeypatch.setattr(server_module.app.router, "lifespan_context", None)
    server_module.app.state.retriever = retriever
    server_module.app.state.anthropic = stub_anthropic

    return TestClient(server_module.app), rsa_keypair


def test_chat_rejected_without_token(access_client):
    client, _ = access_client
    r = client.post("/api/chat", json={
        "tool": "chat",
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 401
    assert "missing" in r.json()["detail"].lower()


def test_chat_rejected_with_wrong_audience(access_client):
    client, keypair = access_client
    bad_token = _issue_token(
        keypair, aud="wrong-aud", iss="https://acme.cloudflareaccess.com"
    )
    r = client.post(
        "/api/chat",
        json={"tool": "chat", "messages": [{"role": "user", "content": "hi"}]},
        headers={"CF-Access-JWT-Assertion": bad_token},
    )
    assert r.status_code == 401


def test_chat_accepted_with_valid_token(access_client):
    client, keypair = access_client
    good_token = _issue_token(
        keypair, aud="test-aud-xyz", iss="https://acme.cloudflareaccess.com"
    )
    r = client.post(
        "/api/chat",
        json={"tool": "chat", "messages": [{"role": "user", "content": "hi"}]},
        headers={"CF-Access-JWT-Assertion": good_token},
    )
    assert r.status_code == 200, r.text


def test_health_reports_access_enforced(access_client):
    client, _ = access_client
    body = client.get("/api/health").json()
    assert body["access_enforced"] is True


def test_jwks_cache_force_refetch_and_rate_limit(monkeypatch):
    """Regression: unknown-kid rotation forces a refetch, but never more often
    than the rate-limit floor, and never while the TTL is valid without force."""
    import asyncio

    fetches = []

    class _Resp:
        def __init__(self, n: int) -> None:
            self._n = n

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"keys": [{"kid": f"kid-{self._n}"}]}

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url: str) -> _Resp:
            fetches.append(url)
            return _Resp(len(fetches))

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", _Client)
    cache = auth_module._JWKSCache()
    config = auth_module.AccessConfig(team_domain="acme", aud="aud")

    async def scenario():
        first = await cache.get(config)
        assert await cache.get(config) == first  # TTL valid — served from cache
        assert await cache.get(config, force=True) == first  # rate-limited
        cache._last_fetch = 0  # age past the refetch floor
        return await cache.get(config, force=True)

    rotated = asyncio.run(scenario())
    assert len(fetches) == 2
    assert rotated["keys"][0]["kid"] == "kid-2"
    assert cache.has_kid("kid-2")
    assert not cache.has_kid("kid-1")


def _jwk(public_pem: str, kid: str) -> dict:
    """Build a real RS256 JWK entry from a PEM public key.

    Lets the rotation test exercise jose's actual JWKS verification path
    instead of monkeypatching jwt.decode.
    """
    import base64

    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    numbers = load_pem_public_key(public_pem.encode()).public_numbers()

    def b64(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": b64(numbers.n),
        "e": b64(numbers.e),
    }


def _stub_transport(monkeypatch, payloads):
    """Patch httpx.AsyncClient so each JWKS fetch pops the next payload.

    Returns the list that records one entry per fetch actually issued.
    """
    import asyncio

    fetches: list[str] = []

    class _Resp:
        def __init__(self, body: dict) -> None:
            self._body = body

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return self._body

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url: str) -> _Resp:
            fetches.append(url)
            # Yield control so concurrent callers can interleave -- without this
            # the stampede the lock prevents would not be observable in a test.
            await asyncio.sleep(0.01)
            return _Resp(payloads[min(len(fetches) - 1, len(payloads) - 1)])

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", _Client)
    return fetches


def test_jwks_forced_refetch_coalesces_concurrent_callers(monkeypatch):
    """Regression: a burst of tokens carrying the same unknown kid must trigger
    exactly one JWKS fetch, not one per request.

    Before the lock, every caller read ``_last_fetch`` before any fetch had
    resolved, so all of them passed the rate-limit floor and stampeded the
    Cloudflare certs endpoint -- the exact case the floor exists to prevent.
    """
    import asyncio

    fetches = _stub_transport(monkeypatch, [{"keys": [{"kid": "kid-1"}]}])
    cache = auth_module._JWKSCache()
    config = auth_module.AccessConfig(team_domain="acme", aud="aud")

    async def scenario():
        await cache.get(config)            # prime the cache (fetch 1)
        cache._last_fetch = 0              # age past the refetch floor
        fetches.clear()
        await asyncio.gather(*(cache.get(config, force=True) for _ in range(8)))

    asyncio.run(scenario())
    assert len(fetches) == 1, f"expected one coalesced refetch, got {len(fetches)}"


def test_cold_cache_coalesces_concurrent_callers(monkeypatch):
    """Concurrent first-time callers share a single fetch rather than one each."""
    import asyncio

    fetches = _stub_transport(monkeypatch, [{"keys": [{"kid": "kid-1"}]}])
    cache = auth_module._JWKSCache()
    config = auth_module.AccessConfig(team_domain="acme", aud="aud")

    async def scenario():
        await asyncio.gather(*(cache.get(config) for _ in range(8)))

    asyncio.run(scenario())
    assert len(fetches) == 1, f"expected one coalesced fetch, got {len(fetches)}"


def test_token_signed_by_rotated_key_is_accepted(monkeypatch, rsa_keypair):
    """End-to-end: Cloudflare rotates its signing key, a token arrives signed by
    the new key, and require_access refetches the JWKS and accepts it.

    Uses real JWKs and real jose verification -- no patched decode.
    """
    import asyncio

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa as rsa_mod
    from starlette.requests import Request

    new_key = rsa_mod.generate_private_key(public_exponent=65537, key_size=2048)
    new_pair = {
        "kid": "rotated-kid",
        "private_pem": new_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode(),
        "public_pem": new_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode(),
    }

    stale = {"keys": [_jwk(rsa_keypair["public_pem"], rsa_keypair["kid"])]}
    rotated = {"keys": [_jwk(new_pair["public_pem"], new_pair["kid"])]}
    fetches = _stub_transport(monkeypatch, [stale, rotated])

    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", "acme")
    monkeypatch.setenv("CF_ACCESS_AUD", "test-aud-xyz")
    fresh_cache = auth_module._JWKSCache()
    monkeypatch.setattr(auth_module, "_cache", fresh_cache)

    token = _issue_token(
        new_pair, aud="test-aud-xyz", iss="https://acme.cloudflareaccess.com"
    )
    request = Request({"type": "http", "headers": [], "method": "POST", "path": "/api/chat"})

    async def scenario():
        await fresh_cache.get(auth_module.AccessConfig(team_domain="acme", aud="test-aud-xyz"))
        assert fresh_cache.has_kid(rsa_keypair["kid"])
        assert not fresh_cache.has_kid(new_pair["kid"])
        fresh_cache._last_fetch = 0  # rotation noticed after the refetch floor
        return await auth_module.require_access(request, token)

    claims = asyncio.run(scenario())
    assert claims["email"] == "user@example.com"
    assert fresh_cache.has_kid(new_pair["kid"])
    assert len(fetches) == 2
