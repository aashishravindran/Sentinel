# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Post-deploy smoke test of the live gateway with a throwaway Cognito user. Exits 1 on failure.

uv run python -m demo.smoke

Checks: a request without a token and one with a garbage token are rejected; a signed-in user sees
exactly the tags in their identity item, and a `user_id` argument can't change that; `tools/list`
hides the control arguments; after the user's tags are removed, the next call is denied (live scope,
no cache). The user and their identity item are deleted afterwards, pass or fail.
"""

import argparse
import asyncio
import json
import secrets
import sys
from typing import Any

import boto3

from demo.call_gateway import call, list_tools, sign_in
from demo.stack import stack_outputs

SMOKE_TAG = "smoke-test"
HIDDEN = {"filter", "userContext", "user_id", "sentinel_principal"}


async def run(outputs: dict[str, str], region: str) -> list[str]:
    url = outputs["GatewayUrl"]
    cognito: Any = boto3.client("cognito-idp", region_name=region)
    table: Any = boto3.resource("dynamodb", region_name=region).Table(outputs["IdentityTableName"])
    pool = outputs["UserPoolId"]
    username = f"smoke-{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(18) + "aA1!"
    failures: list[str] = []

    def check(ok: bool, label: str, detail: str = "") -> None:
        suffix = f"  ({detail[:120]})" if detail and not ok else ""
        print(f"  {'PASS' if ok else 'FAIL'}  {label}{suffix}")
        if not ok:
            failures.append(label)

    bad_tokens = (("no token is rejected", None), ("garbage token is rejected", "not-a-jwt"))
    for label, token in bad_tokens:
        outcome = await call(url, token)
        check(outcome.startswith(("rejected", "denied")), label, outcome)

    created = cognito.admin_create_user(
        UserPoolId=pool, Username=username, MessageAction="SUPPRESS"
    )
    sub = next(a["Value"] for a in created["User"]["Attributes"] if a["Name"] == "sub")
    try:
        cognito.admin_set_user_password(
            UserPoolId=pool, Username=username, Password=password, Permanent=True
        )
        table.put_item(Item={"user_id": sub, "tags": {SMOKE_TAG}})
        token = sign_in(cognito, outputs["UserPoolClientId"], username, password)

        outcome = await call(url, token)
        tags = json.loads(outcome).get("tags") if outcome.startswith("{") else None
        check(tags == [SMOKE_TAG], "caller sees exactly their identity item's tags", outcome)

        outcome = await call(url, token, user_id="charlie")
        tags = json.loads(outcome).get("tags") if outcome.startswith("{") else None
        label = "a user_id argument can't change whose scope is used"
        check(tags in (None, [SMOKE_TAG]), label, outcome)

        exposed = {
            p for params in (await list_tools(url, token)).values() for p in params if p in HIDDEN
        }
        check(not exposed, "tools/list hides control arguments", ", ".join(sorted(exposed)))

        table.delete_item(Key={"user_id": sub})
        outcome = await call(url, token)
        label = "removing the identity item takes effect on the next call"
        check(SMOKE_TAG not in outcome, label, outcome)
    finally:
        table.delete_item(Key={"user_id": sub})
        cognito.admin_delete_user(UserPoolId=pool, Username=username)
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stack", default="SentinelDemo")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()
    outputs = stack_outputs(args.stack, args.region)
    print(f"Smoke test: {args.stack}")
    failures = asyncio.run(run(outputs, args.region))
    if failures:
        print(f"{len(failures)} check(s) failed")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
