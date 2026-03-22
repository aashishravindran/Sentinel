# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

#!/usr/bin/env python3
"""
scripts/seed_ddb.py — Seed the DynamoDB identity table with example users.

Each item has:
    user_id  (String, partition key)
    tags     (String Set)

Usage:
    python scripts/seed_ddb.py --table sentinel-identity --region us-east-1
    python scripts/seed_ddb.py --table sentinel-identity --region us-east-1 --no-seed
"""
import argparse
import sys

import boto3

SEED_DATA = [
    ("alice",   {"finance", "public"}),
    ("bob",     {"public", "engineering"}),
    ("charlie", {"finance", "engineering", "public"}),
]


def seed_table(table_name: str, region: str, seed: bool = True) -> None:
    ddb = boto3.resource("dynamodb", region_name=region)
    table = ddb.Table(table_name)

    # Verify the table exists before writing.
    try:
        status = table.table_status
    except ddb.meta.client.exceptions.ResourceNotFoundException:
        sys.exit(f"ERROR: DynamoDB table '{table_name}' not found in {region}.")

    if not seed:
        print(f"Table '{table_name}' is ready (--no-seed, skipping data).")
        return

    with table.batch_writer() as batch:
        for user_id, tags in SEED_DATA:
            batch.put_item(Item={"user_id": user_id, "tags": tags})

    print(f"Seeded {len(SEED_DATA)} users into '{table_name}':")
    for user_id, tags in SEED_DATA:
        print(f"  {user_id}: {sorted(tags)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Seed the Sentinel DynamoDB identity table.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--table",   required=True,          help="DynamoDB table name")
    p.add_argument("--region",  default="us-east-1",    help="AWS region")
    p.add_argument("--no-seed", action="store_true",    help="Verify table exists but skip seeding")
    args = p.parse_args()

    seed_table(args.table, args.region, seed=not args.no_seed)
