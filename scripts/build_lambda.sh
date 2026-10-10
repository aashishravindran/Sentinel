#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# scripts/build_lambda.sh
#
# Builds build/lambda: the AgentCore adapter plus sentinel-engine and its AWS
# dependencies, as arm64 manylinux wheels for the Python 3.14 Lambda runtime.
# No Docker needed. ChromaDB and torch are not included.
#
# Usage:
#   ./scripts/build_lambda.sh
#   SENTINEL_ENGINE_SPEC="sentinel-engine[aws] @ git+https://github.com/aashishravindran/sentinel-engine@v0.1.0" \
#     ./scripts/build_lambda.sh
# -----------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/build/lambda"
WHEELS="${ROOT}/build/wheels"

rm -rf "${OUT}" "${WHEELS}"
mkdir -p "${OUT}/sentinel/adapters" "${WHEELS}"

if [[ -z "${SENTINEL_ENGINE_SPEC:-}" && -d "${ROOT}/../sentinel-engine" ]]; then
  # Pure-Python package: build a wheel from a local checkout for side-by-side development.
  uv build --quiet --wheel --out-dir "${WHEELS}" "${ROOT}/../sentinel-engine"
  ENGINE_SPEC="sentinel-engine[aws] @ file://$(ls "${WHEELS}"/sentinel_engine-*.whl)"
else
  ENGINE_SPEC="${SENTINEL_ENGINE_SPEC:-sentinel-engine[aws] @ git+https://github.com/aashishravindran/sentinel-engine@v0.1.0}"
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
