# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Shared fixtures and skip markers for E2E tests.

E2E tests hit real backends. Run them with:
    uv run pytest -m e2e

Local stack (SpiceDB + ChromaDB):
    Requires SpiceDB running: ./spicedb/start.sh

AWS stack (DynamoDB + Bedrock):
    Requires env vars: DDB_TABLE_NAME, BEDROCK_KB_ID, BEDROCK_S3_BUCKET, AWS_REGION
"""

import os
import socket

import pytest


# ---------------------------------------------------------------------------
# Availability probes
# ---------------------------------------------------------------------------

def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def spicedb_available() -> bool:
    return _port_open("localhost", 50051)


def aws_e2e_configured() -> bool:
    return all(
        os.environ.get(v)
        for v in ["DDB_TABLE_NAME", "BEDROCK_KB_ID", "BEDROCK_S3_BUCKET", "AWS_REGION"]
    )


# ---------------------------------------------------------------------------
# Pytest markers / skip decorators
# ---------------------------------------------------------------------------

requires_spicedb = pytest.mark.skipif(
    not spicedb_available(),
    reason="SpiceDB not running at localhost:50051 — run ./spicedb/start.sh first",
)

requires_aws = pytest.mark.skipif(
    not aws_e2e_configured(),
    reason="AWS E2E env vars not set (DDB_TABLE_NAME, BEDROCK_KB_ID, BEDROCK_S3_BUCKET, AWS_REGION)",
)
