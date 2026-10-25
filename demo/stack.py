# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Shared helpers for the live demo scripts: stack outputs and local credentials."""

import json
from pathlib import Path
from typing import Any

import boto3

DEMO_DIR = Path(__file__).parent
ORG_FILE = DEMO_DIR / "org.json"
# Generated passwords for the demo personas. Gitignored; deleted with the stack.
CREDENTIALS_FILE = DEMO_DIR / ".users.json"


def stack_outputs(stack: str, region: str | None) -> dict[str, str]:
    cfn: Any = boto3.client("cloudformation", region_name=region)
    outputs = cfn.describe_stacks(StackName=stack)["Stacks"][0].get("Outputs", [])
    return {o["OutputKey"]: o["OutputValue"] for o in outputs}


def org_users() -> dict[str, list[str]]:
    return json.loads(ORG_FILE.read_text())["users"]
