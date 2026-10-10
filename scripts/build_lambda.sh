#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# scripts/build_lambda.sh
#
# Builds build/lambda: the AgentCore adapter plus sentinel-engine and its AWS
# dependencies, as arm64 manylinux wheels for the Python 3.14 Lambda runtime.
# No Docker needed. ChromaDB and torch are not included.
#
# Usage:
#   ./scripts/build_lambda.sh                          # ../sentinel-engine if present,
#                                                      # else the pinned tag from GitHub
#   SENTINEL_ENGINE_REF=v0.2.0 ./scripts/build_lambda.sh
# -----------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/build/lambda"
WHEELS="${ROOT}/build/wheels"
ENGINE_DIR="${SENTINEL_ENGINE_DIR:-${ROOT}/../sentinel-engine}"
ENGINE_REF="${SENTINEL_ENGINE_REF:-v0.1.0}"

rm -rf "${OUT}" "${WHEELS}" "${ROOT}/build/sentinel-engine"
mkdir -p "${OUT}/sentinel/adapters" "${WHEELS}"

if [[ ! -d "${ENGINE_DIR}" ]]; then
  # No local checkout: build the pinned release.
  ENGINE_DIR="${ROOT}/build/sentinel-engine"
  git clone --quiet --depth 1 --branch "${ENGINE_REF}" \
    https://github.com/aashishravindran/sentinel-engine "${ENGINE_DIR}"
fi
# Pure-Python package: build its wheel here so every dependency can stay binary-only.
uv build --quiet --wheel --out-dir "${WHEELS}" "${ENGINE_DIR}"
ENGINE_SPEC="sentinel-engine[aws] @ file://$(ls "${WHEELS}"/sentinel_engine-*.whl)"

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
