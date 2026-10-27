#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# scripts/build_lambda.sh
#
# Builds build/lambda: the AgentCore adapter plus sentinel-authz (imported as
# sentinel_engine) and its AWS dependencies, as arm64 manylinux wheels for the
# Python 3.14 Lambda runtime. No Docker needed. ChromaDB and torch are not included.
#
# Usage:
#   ./scripts/build_lambda.sh                                         # version from uv.lock
#   SENTINEL_ENGINE_DIR=../sentinel-engine ./scripts/build_lambda.sh  # a local engine checkout
# -----------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/build/lambda"
WHEELS="${ROOT}/build/wheels"

rm -rf "${OUT}" "${WHEELS}"
mkdir -p "${OUT}/sentinel/adapters" "${WHEELS}"

if [[ -n "${SENTINEL_ENGINE_DIR:-}" ]]; then
  # Co-development: build the local checkout instead of the published release.
  uv build --quiet --wheel --out-dir "${WHEELS}" "${SENTINEL_ENGINE_DIR}"
  ENGINE_SPEC="sentinel-authz[aws] @ file://$(ls "${WHEELS}"/sentinel_authz-*.whl)"
else
  # The same version the tests ran against.
  VERSION=$(cd "${ROOT}" && uv export --quiet --frozen --no-dev --no-hashes --no-annotate \
    | sed -n 's/^sentinel-authz==\([^ ;]*\).*/\1/p')
  [[ -n "${VERSION}" ]] || { echo "sentinel-authz not found in uv.lock" >&2; exit 1; }
  ENGINE_SPEC="sentinel-authz[aws]==${VERSION}"
fi

uv pip install \
  --quiet \
  --target "${OUT}" \
  --python-platform aarch64-manylinux2014 \
  --python-version 3.14 \
  --only-binary :all: \
  "${ENGINE_SPEC}"

cp "${ROOT}/sentinel/__init__.py" "${OUT}/sentinel/"
cp "${ROOT}/sentinel/adapters/__init__.py" "${OUT}/sentinel/adapters/"
cp -R "${ROOT}/sentinel/adapters/agentcore" "${OUT}/sentinel/adapters/"
find "${OUT}" -name "__pycache__" -prune -exec rm -rf {} +

echo "Built ${OUT} ($(du -sh "${OUT}" | cut -f1))"
