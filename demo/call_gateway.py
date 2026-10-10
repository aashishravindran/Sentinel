# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Call the deployed gateway as each demo persona, with real Cognito tokens.

uv run python -m demo.call_gateway
uv run python -m demo.call_gateway --revoke alice:finance   # live revocation check
"""

import argparse
import asyncio
import json
import os
import warnings
from typing import Any

import boto3
import jwt

os.environ.setdefault("FASTMCP_LOG_LEVEL", "CRITICAL")
warnings.filterwarnings("ignore")

from fastmcp import Client  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402

from demo.stack import CREDENTIALS_FILE, org_users, stack_outputs  # noqa: E402

TOOL = "sentinel___what_can_i_access"
GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def sign_in(cognito: Any, client_id: str, username: str, password: str) -> str:
    result = cognito.initiate_auth(
        ClientId=client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    return result["AuthenticationResult"]["AccessToken"]


async def call(url: str, token: str | None, **arguments: object) -> str:
    try:
        async with Client(url, auth=token) as client:
            result = await client.call_tool(TOOL, arguments)
        return result.content[0].text
    except ToolError as exc:
        return f"denied: {exc}"
    except Exception as exc:
        return f"rejected: {type(exc).__name__}: {str(exc)[:80]}"


async def list_tools(url: str, token: str) -> dict[str, list[str]]:
    async with Client(url, auth=token) as client:
        tools = await client.list_tools()
    return {t.name: sorted((t.inputSchema or {}).get("properties", {})) for t in tools}


def show(label: str, outcome: str) -> None:
    ok = outcome.startswith("{") and '"tags"' in outcome and '"message"' not in outcome
    print(f"  {label:<44} {GREEN if ok else RED}{outcome}{RESET}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stack", default="SentinelDemo")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--revoke", help="user:tag to remove, re-check, then restore")
    args = parser.parse_args()

    outputs = stack_outputs(args.stack, args.region)
    url = outputs["GatewayUrl"]
    cognito: Any = boto3.client("cognito-idp", region_name=args.region)
    passwords: dict[str, str] = json.loads(CREDENTIALS_FILE.read_text())
    tokens = {
        user: sign_in(cognito, outputs["UserPoolClientId"], user, passwords[user])
        for user in org_users()
    }
    print(f"{BOLD}Gateway{RESET} {DIM}{url}{RESET}\n")

    print(f"{BOLD}tools/list as intern{RESET} (control arguments must be hidden)")
    for name, params in (await list_tools(url, tokens["intern"])).items():
        print(f"  {name}  {DIM}params={params}{RESET}")

    print(f"\n{BOLD}what_can_i_access, as each persona{RESET}")
    for user, token in tokens.items():
        show(user, await call(url, token))

    print(f"\n{BOLD}attacks{RESET}")
    show('intern passes user_id="charlie"', await call(url, tokens["intern"], user_id="charlie"))
    show("no token", await call(url, None))
    show("garbage token", await call(url, "not-a-jwt"))

    if args.revoke:
        user, tag = args.revoke.split(":")
        table: Any = boto3.resource("dynamodb", region_name=args.region).Table(
            outputs["IdentityTableName"]
        )
        # The token was just issued by Cognito to this script; read sub without re-verifying.
        sub = jwt.decode(tokens[user], options={"verify_signature": False})["sub"]
        print(f"\n{BOLD}revoke {tag} from {user} in DynamoDB, ask again (no redeploy){RESET}")
        table.update_item(
            Key={"user_id": sub},
            UpdateExpression="DELETE tags :t",
            ExpressionAttributeValues={":t": {tag}},
        )
        try:
            show(f"{user} after revoking {tag}", await call(url, tokens[user]))
        finally:
            table.update_item(
                Key={"user_id": sub},
                UpdateExpression="ADD tags :t",
                ExpressionAttributeValues={":t": {tag}},
            )
            print(f"  {DIM}restored {tag} for {user}{RESET}")


if __name__ == "__main__":
    asyncio.run(main())
