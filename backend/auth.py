"""Cloudflare Access JWT verification.

When CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD are set, the backend validates
the CF-Access-JWT-Assertion header (or CF_Authorization cookie) on every
/api/chat request using Cloudflare's published JWKS.

If either env var is unset, auth is disabled -- appropriate for local dev
only. Production deployments MUST set both.

Reference: https://developers.cloudflare.com/cloudflare-one/identity/authorization-cookie/validating-json/
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Header, HTTPException, Request
from jose import jwt
from jose.exceptions import JWTError

log = logging.getLogger(__name__)

JWKS_TTL_SECONDS = 3600
# Floor between forced refetches so a flood of bad tokens can't hammer the
# certs endpoint after a key rotation.
JWKS_MIN_REFETCH_SECONDS = 60


@dataclass
class AccessConfig:
    team_domain: str    # e.g. "acme" -> https://acme.cloudflareaccess.com
    aud: str            # Application AUD tag from the Access dashboard

    @property
    def certs_url(self) -> str:
        return f"https://{self.team_domain}.cloudflareaccess.com/cdn-cgi/access/certs"

    @property
    def issuer(self) -> str:
        return f"https://{self.team_domain}.cloudflareaccess.com"


def load_config() -> AccessConfig | None:
    team = os.environ.get("CF_ACCESS_TEAM_DOMAIN", "").strip()
    aud = os.environ.get("CF_ACCESS_AUD", "").strip()
    if not team or not aud:
        return None
    return AccessConfig(team_domain=team, aud=aud)


class _JWKSCache:
    def __init__(self) -> None:
        self._keys: dict[str, Any] | None = None
        self._expires: float = 0
        # Time of the last fetch *attempt*, successful or not -- the floor has
        # to hold during an outage too, not just after a successful refresh.
        self._last_fetch: float = 0
        self._lock = asyncio.Lock()

    def _fresh(self, now: float, *, force: bool) -> dict[str, Any] | None:
        """Return cached keys if they still satisfy the TTL / refetch floor."""
        if not self._keys:
            return None
        if not force and now < self._expires:
            return self._keys
        if force and now - self._last_fetch < JWKS_MIN_REFETCH_SECONDS:
            return self._keys
        return None

    async def get(self, config: AccessConfig, *, force: bool = False) -> dict[str, Any]:
        cached = self._fresh(time.time(), force=force)
        if cached is not None:
            return cached

        # Serialize the fetch. Without this, a burst of tokens carrying the same
        # unknown kid all pass the check above (``_last_fetch`` is only updated
        # after the await resolves) and each issues its own request -- exactly
        # the stampede JWKS_MIN_REFETCH_SECONDS exists to prevent. Re-check the
        # condition inside the lock so only the first waiter fetches.
        async with self._lock:
            cached = self._fresh(time.time(), force=force)
            if cached is not None:
                return cached
            # Stamp the *attempt*, not the success. If the certs endpoint is
            # down, every queued caller would otherwise re-check an unchanged
            # timestamp, still read as stale, and retry in turn -- an outage
            # would serialize the stampede rather than stop it. Recording it
            # here means later waiters honour the floor and fall back to the
            # stale keys they already have.
            self._last_fetch = time.time()
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(config.certs_url)
            resp.raise_for_status()
            now = time.time()
            self._keys = resp.json()
            self._last_fetch = now
            self._expires = now + JWKS_TTL_SECONDS
            return self._keys

    def has_kid(self, kid: str) -> bool:
        keys = (self._keys or {}).get("keys", [])
        return any(k.get("kid") == kid for k in keys)


_cache = _JWKSCache()


def _extract_token(request: Request, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    # Cloudflare also sets a cookie on browser requests.
    return request.cookies.get("CF_Authorization")


async def require_access(
    request: Request,
    cf_access_jwt_assertion: str | None = Header(default=None, alias="CF-Access-JWT-Assertion"),
) -> dict[str, Any]:
    """FastAPI dependency that returns the decoded Access claims.

    If Access is not configured (dev / test), returns an empty dict so routes
    still work -- production deployments must set CF_ACCESS_* env vars.
    """
    config = load_config()
    if config is None:
        return {}

    token = _extract_token(request, cf_access_jwt_assertion)
    if not token:
        raise HTTPException(401, "missing Cloudflare Access JWT")

    try:
        jwks = await _cache.get(config)
    except httpx.HTTPError as e:  # pragma: no cover -- network
        log.error("could not fetch Access JWKS: %s", e)
        raise HTTPException(503, "auth service unavailable") from e

    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except JWTError as e:
        raise HTTPException(401, f"invalid Access JWT: {e}") from e

    if kid and not _cache.has_kid(kid):
        # Cloudflare rotates Access signing keys; a token signed by a key we
        # have not cached means the JWKS is stale. Refetch (rate-limited)
        # instead of rejecting valid tokens until the TTL expires.
        try:
            jwks = await _cache.get(config, force=True)
        except httpx.HTTPError:  # pragma: no cover -- network
            log.warning("JWKS refetch after unknown kid failed; using cached keys")

    try:
        claims = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=config.aud,
            issuer=config.issuer,
        )
    except JWTError as e:
        raise HTTPException(401, f"invalid Access JWT: {e}") from e

    return claims
