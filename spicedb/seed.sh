#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# spicedb/seed.sh
#
# Writes the Sentinel schema and a set of test users into a locally running
# SpiceDB instance.  Assumes SpiceDB is already running in serve-testing mode:
#
#   spicedb serve-testing &
#
# Usage:
#   ./spicedb/seed.sh [endpoint] [token]
#
# Defaults:
#   endpoint  localhost:50051
#   token     anything (serve-testing accepts any token)
# -----------------------------------------------------------------------------
set -euo pipefail

ENDPOINT="${1:-localhost:50051}"
TOKEN="${2:-sentinel-local}"
SCHEMA_FILE="$(dirname "$0")/schema.zed"

ZED_FLAGS="--endpoint=${ENDPOINT} --token=${TOKEN} --insecure"

echo "==> Writing schema from ${SCHEMA_FILE}"
zed ${ZED_FLAGS} schema write "${SCHEMA_FILE}"

echo "==> Seeding test users"

# alice  — finance + public
zed ${ZED_FLAGS} relationship touch tag:finance  member user:alice
zed ${ZED_FLAGS} relationship touch tag:public   member user:alice

# bob    — public + engineering
zed ${ZED_FLAGS} relationship touch tag:public      member user:bob
zed ${ZED_FLAGS} relationship touch tag:engineering member user:bob

# charlie — all three tags
zed ${ZED_FLAGS} relationship touch tag:finance     member user:charlie
zed ${ZED_FLAGS} relationship touch tag:engineering member user:charlie
zed ${ZED_FLAGS} relationship touch tag:public      member user:charlie

echo ""
echo "Done. Users seeded:"
echo "  alice   -> finance, public"
echo "  bob     -> public, engineering"
echo "  charlie -> finance, engineering, public"
