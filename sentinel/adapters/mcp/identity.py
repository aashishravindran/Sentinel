# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Resolve the caller from the transport. Tool arguments are never consulted."""

from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token
from sentinel_engine.errors import IdentityError
from sentinel_engine.oidc import OIDCSettings, principal_from_claims
from sentinel_engine.principal import Principal

from sentinel.adapters.mcp.settings import ServerSettings


def build_auth(oidc: OIDCSettings) -> JWTVerifier:
    """FastMCP verifies signature, issuer and audience before any tool runs."""
    return JWTVerifier(
        jwks_uri=oidc.jwks_uri,
        public_key=oidc.public_key,
        issuer=oidc.issuer,
        audience=list(oidc.audience) or None,
        algorithm=oidc.algorithms[0],
    )


def resolve_principal(settings: ServerSettings) -> Principal:
    token = get_access_token()
    if settings.transport == "stdio":
        if token is not None:
            raise IdentityError("bearer token on a stdio server: refusing ambiguous identity")
        return Principal(settings.stdio_user or "", "stdio")
    if token is None or settings.oidc is None:
        raise IdentityError("missing bearer token")
    # FastMCP's AccessToken.client_id falls back to "sub"; read the claims directly.
    return principal_from_claims(token.claims, settings.oidc)
