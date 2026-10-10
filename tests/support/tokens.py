# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""A local OIDC issuer for tests: one RSA keypair, tokens on demand."""

from typing import Any

from fastmcp.server.auth.providers.jwt import RSAKeyPair
from sentinel_engine.oidc import OIDCSettings

ISSUER = "https://issuer.sentinel.test"
AUDIENCE = "sentinel"

KEYS = RSAKeyPair.generate()
OIDC = OIDCSettings(issuer=ISSUER, public_key=KEYS.public_key, audience=(AUDIENCE,))


def token_for(
    subject: str,
    *,
    expires_in_seconds: int = 300,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    keys: RSAKeyPair = KEYS,
    **claims: Any,
) -> str:
    return keys.create_token(
        subject=subject,
        issuer=issuer,
        audience=audience,
        expires_in_seconds=expires_in_seconds,
        additional_claims=claims or None,
    )


def bearer(subject: str, **kwargs: Any) -> str:
    return f"Bearer {token_for(subject, **kwargs)}"
