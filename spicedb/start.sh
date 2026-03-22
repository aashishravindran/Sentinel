#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# spicedb/start.sh
#
# Starts SpiceDB in serve-testing mode (in-memory, accepts any token, no TLS)
# and seeds it with the Sentinel schema + test users.
#
# Run this once before starting the MCP server.  SpiceDB will stay running in
# the foreground; press Ctrl-C to stop it.
#
# Usage:
#   ./spicedb/start.sh
# -----------------------------------------------------------------------------
set -euo pipefail

ENDPOINT="localhost:50051"
TOKEN="sentinel-local"

# Ensure the ChromaDB data directory exists
mkdir -p data/chroma

echo "==> Starting SpiceDB (serve-testing, port 50051)..."
spicedb serve-testing \
  --grpc-addr=":50051" \
  --http-addr=":8443" &

SPICEDB_PID=$!
echo "    PID ${SPICEDB_PID}"

# Give it a moment to start
sleep 1

echo "==> Seeding schema and relationships..."
"$(dirname "$0")/seed.sh" "${ENDPOINT}" "${TOKEN}"

echo ""
echo "SpiceDB is ready."
echo "  gRPC endpoint : ${ENDPOINT}"
echo "  Token         : ${TOKEN} (any value works in serve-testing mode)"
echo ""
echo "MCP config to use (spicedb + chroma):"
echo "  SENTINEL_IDENTITY_STORE=spicedb"
echo "  SPICEDB_ENDPOINT=${ENDPOINT}"
echo "  SPICEDB_TOKEN=${TOKEN}"
echo "  SPICEDB_TLS=false"
echo "  SENTINEL_KNOWLEDGE_STORE=chroma"
echo "  CHROMA_PATH=./data/chroma"
echo ""
echo "Press Ctrl-C to stop SpiceDB."
wait ${SPICEDB_PID}
