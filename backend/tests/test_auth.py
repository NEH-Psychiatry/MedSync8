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


def test_chat_stream_rejected_without_token(access_client):
    client, _ = access_client
    r = client.post("/api/chat/stream", json={
        "tool": "chat",
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 401
    assert "missing" in r.json()["detail"].lower()


def test_chat_stream_accepted_with_valid_token(access_client):
    client, keypair = access_client
    good_token = _issue_token(
        keypair, aud="test-aud-xyz", iss="https://acme.cloudflareaccess.com"
    )
    r = client.post(
        "/api/chat/stream",
        json={"tool": "chat", "messages": [{"role": "user", "content": "hi"}]},
        headers={"CF-Access-JWT-Assertion": good_token},
    )
    assert r.status_code == 200, r.text
    assert r.text.startswith("event: citations")
