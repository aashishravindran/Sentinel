# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""A signed, short-lived statement of who is calling, for the Lambda target.

AgentCore invokes a Lambda target with only the tool arguments: no headers,
no token. The request interceptor, which has verified the caller's JWT, adds
an envelope to the arguments. The target trusts the user ID inside it only if
the HMAC checks out, it has not expired, and it was issued for this exact
query, so it cannot be forged or replayed for a different search.
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from sentinel_engine.errors import IdentityError
from sentinel_engine.principal import validate_subject

ENVELOPE_ARGUMENT = "_sentinel_principal"
DEFAULT_TTL_SECONDS = 60


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _digest(arguments: dict[str, Any]) -> str:
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def seal(
    user_id: str,
    arguments: dict[str, Any],
    key: bytes,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: float | None = None,
) -> str:
    claims = {
        "sub": validate_subject(user_id),
        "args": _digest(arguments),
        "exp": int((now if now is not None else time.time()) + ttl_seconds),
    }
    payload = _b64(json.dumps(claims, sort_keys=True).encode())
    signature = _b64(hmac.new(key, payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def open_envelope(
    envelope: object, arguments: dict[str, Any], key: bytes, *, now: float | None = None
) -> str:
    """Return the user ID sealed in *envelope*, or raise IdentityError."""
    if not isinstance(envelope, str) or envelope.count(".") != 1:
        raise IdentityError("missing or malformed principal envelope")
    payload, signature = envelope.split(".")
    expected = _b64(hmac.new(key, payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        raise IdentityError("principal envelope signature mismatch")
    claims = json.loads(_unb64(payload))
    if claims.get("exp", 0) < (now if now is not None else time.time()):
        raise IdentityError("principal envelope expired")
    if not hmac.compare_digest(str(claims.get("args")), _digest(arguments)):
        raise IdentityError("principal envelope was issued for different arguments")
    return validate_subject(claims.get("sub"))
