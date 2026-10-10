# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Load demo/org.json into the gateway's DynamoDB identity table.

Usernames are translated to Cognito ``sub`` values, the key the interceptors
look up. Prints the plan; writes only with --apply.

    uv run python scripts/sync_identity.py --table <IdentityTableName> \\
        --user-pool-id <UserPoolId> [--prune] [--apply]
"""

import argparse
import json
from pathlib import Path

import boto3

from sentinel.ingest.identity_sync import plan_sync

ORG_FILE = Path(__file__).parent.parent / "demo" / "org.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", required=True)
    parser.add_argument("--user-pool-id", help="translate usernames to Cognito sub values")
    parser.add_argument("--region", default=None)
    parser.add_argument("--prune", action="store_true", help="delete users not in the org file")
    parser.add_argument("--apply", action="store_true", help="write the changes")
    args = parser.parse_args()

    users: dict[str, list[str]] = json.loads(ORG_FILE.read_text())["users"]
    cognito = boto3.client("cognito-idp", region_name=args.region)
    table = boto3.resource("dynamodb", region_name=args.region).Table(args.table)

    def subject(username: str) -> str:
        if not args.user_pool_id:
            return username
        attrs = cognito.admin_get_user(UserPoolId=args.user_pool_id, Username=username)
        return next(a["Value"] for a in attrs["UserAttributes"] if a["Name"] == "sub")

    desired = {subject(name): set(tags) for name, tags in users.items()}
    current = {item["user_id"]: set(item.get("tags", [])) for item in table.scan()["Items"]}
    plan = plan_sync(current, desired, prune=args.prune)

    for sub, tags in plan.put.items():
        print(f"put     {sub}  {sorted(tags)}")
    for sub in sorted(plan.delete):
        print(f"delete  {sub}")
    if not args.apply:
        print("Dry run. Re-run with --apply to write.")
        return
    with table.batch_writer() as batch:
        for sub, tags in plan.put.items():
            batch.put_item(Item={"user_id": sub, "tags": set(tags)})
        for sub in plan.delete:
            batch.delete_item(Key={"user_id": sub})
    print(f"Applied: {len(plan.put)} written, {len(plan.delete)} deleted.")


if __name__ == "__main__":
    main()
