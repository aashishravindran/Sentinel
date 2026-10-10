"""Every malformed, forged or misdirected token is denied by every networked adapter."""

import time

import jwt
import pytest
from fastmcp.server.auth.providers.jwt import RSAKeyPair

from tests.conformance.harness import ADAPTERS, DENIED, Backend
from tests.support.fakes import DictIdentity, StubBedrockKB
from tests.support.tokens import AUDIENCE, ISSUER, KEYS, token_for

pytestmark = pytest.mark.redteam

NETWORKED = ["mcp-http", "gateway-lambda-target", "gateway-managed-kb"]
ATTACKER = RSAKeyPair.generate()


def _signed(claims: dict, key: str | None = None, algorithm: str = "RS256") -> str:
    now = int(time.time())
    base = {"iss": ISSUER, "aud": AUDIENCE, "sub": "charlie", "iat": now, "exp": now + 300}
    payload = {k: v for k, v in {**base, **claims}.items() if v is not None}
    return jwt.encode(payload, key or KEYS.private_key.get_secret_value(), algorithm=algorithm)


BAD_TOKENS = {
    "garbage": lambda: "not-a-jwt",
    "expired": lambda: token_for("charlie", expires_in_seconds=-3600),
    "not-yet-valid": lambda: _signed({"nbf": int(time.time()) + 3600}),
    "wrong-issuer": lambda: token_for("charlie", issuer="https://evil.example.com"),
    "wrong-audience": lambda: token_for("charlie", audience="another-api"),
    "foreign-key": lambda: token_for("charlie", keys=ATTACKER),
    "alg-none": lambda: jwt.encode(
        {"sub": "charlie", "iss": ISSUER, "aud": AUDIENCE}, None, "none"
    ),
    "no-expiry": lambda: _signed({"exp": None}),
    "no-subject": lambda: _signed({"sub": None}),
    "wildcard-subject": lambda: _signed({"sub": "*"}),
    "email-subject": lambda: _signed({"sub": "charlie@example.com"}),
}


@pytest.mark.parametrize("token", sorted(BAD_TOKENS))
@pytest.mark.parametrize("adapter", NETWORKED)
async def test_bad_tokens_are_denied(adapter, token):
    backend = Backend(DictIdentity(), StubBedrockKB.seeded())
    outcome = await ADAPTERS[adapter](backend, "charlie", "budget", token=BAD_TOKENS[token]())
    assert outcome == DENIED
    assert backend.kb.calls == 0
