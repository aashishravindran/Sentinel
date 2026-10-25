# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Create the demo personas in Cognito and load their tags into the identity table.

Each user in demo/org.json gets a Cognito login with a random password, saved
to demo/.users.json (gitignored). Their tags are written to DynamoDB under
their Cognito ``sub``, the value the gateway reads from the token.

    uv run python -m demo.provision_users            # show the plan
    uv run python -m demo.provision_users --apply    # create users, write tags
"""

import argparse
import json
import secrets
import string
from typing import Any

import boto3

from demo.stack import CREDENTIALS_FILE, org_users, stack_outputs
from sentinel.ingest.identity_sync import plan_sync


def _password() -> str:
    alphabet = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"{core}aA1!"  # satisfies every class the pool requires


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stack", default="SentinelDemo")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    outputs = stack_outputs(args.stack, args.region)
    pool = outputs["UserPoolId"]
    cognito: Any = boto3.client("cognito-idp", region_name=args.region)
    table: Any = boto3.resource("dynamodb", region_name=args.region).Table(
        outputs["IdentityTableName"]
    )
    users = org_users()
    existing = {
        u["Username"]: next(a["Value"] for a in u["Attributes"] if a["Name"] == "sub")
        for u in cognito.list_users(UserPoolId=pool)["Users"]
    }
    to_create = [name for name in users if name not in existing]
    print(f"user pool {pool}: create {to_create or 'nobody'}")
    if not args.apply:
        print("Dry run. Re-run with --apply.")
        return

    credentials: dict[str, str] = (
        json.loads(CREDENTIALS_FILE.read_text()) if CREDENTIALS_FILE.exists() else {}
    )
    for name in to_create:
        sub = cognito.admin_create_user(UserPoolId=pool, Username=name, MessageAction="SUPPRESS")
        existing[name] = next(a["Value"] for a in sub["User"]["Attributes"] if a["Name"] == "sub")
        credentials[name] = _password()
        cognito.admin_set_user_password(
            UserPoolId=pool, Username=name, Password=credentials[name], Permanent=True
        )
    CREDENTIALS_FILE.write_text(json.dumps(credentials, indent=2))
    CREDENTIALS_FILE.chmod(0o600)

    desired = {existing[name]: set(tags) for name, tags in users.items()}
    current = {i["user_id"]: set(i.get("tags", [])) for i in table.scan()["Items"]}
    plan = plan_sync(current, desired, prune=True)
    with table.batch_writer() as batch:
        for sub, tags in plan.put.items():
            batch.put_item(Item={"user_id": sub, "tags": set(tags)})
        for sub in plan.delete:
            batch.delete_item(Key={"user_id": sub})
    for name, tags in users.items():
        print(f"  {name:<8} sub={existing[name]}  tags={tags}")
    print(f"Saved passwords to {CREDENTIALS_FILE} (gitignored).")


if __name__ == "__main__":
    main()
