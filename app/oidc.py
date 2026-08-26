"""RS256 JWT verification against an OIDC provider's JWKS (Authentik or any
standards-compliant IdP). Additive to the app/auth.py stub, not a replacement:
see docs/adr/011-oidc-auth.md for why both paths coexist.
"""

from __future__ import annotations

import os

import jwt
from fastapi import HTTPException

JWKS_URL = os.environ.get("OIDC_JWKS_URL", "")
ISSUER = os.environ.get("OIDC_ISSUER", "")
AUDIENCE = os.environ.get("OIDC_AUDIENCE", "")

_jwk_client: "jwt.PyJWKClient | None" = None


def _client() -> "jwt.PyJWKClient":
    global _jwk_client
    if _jwk_client is None or _jwk_client.uri != JWKS_URL:
        _jwk_client = jwt.PyJWKClient(JWKS_URL)
    return _jwk_client


def looks_like_jwt(token: str) -> bool:
    """Three dot-separated segments — enough to route to this path without
    ever mistaking a stub token ("org:<uuid>") for one."""
    return token.count(".") == 2


def configured() -> bool:
    return bool(JWKS_URL and ISSUER and AUDIENCE)


def decode(token: str) -> dict:
    if not configured():
        raise HTTPException(401, "OIDC is not configured on this server")
    try:
        signing_key = _client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token, signing_key.key, algorithms=["RS256"],
            audience=AUDIENCE, issuer=ISSUER,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"invalid token: {exc}") from exc
