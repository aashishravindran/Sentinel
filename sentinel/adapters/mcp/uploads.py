# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Where PDF bytes for ingest_pdf may come from."""

import base64
import binascii
from pathlib import Path

MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_INLINE_PDF_BYTES = 1024 * 1024


def read_pdf_from_ingest_dir(user_path: str, ingest_dir: Path | None) -> bytes:
    """Read a PDF that lives inside the operator-chosen ingest directory.

    Absolute paths, ``..`` segments and symlinks that resolve outside the
    directory are all rejected. Without ``SENTINEL_INGEST_DIR`` the server
    reads no files at all.
    """
    if ingest_dir is None:
        raise ValueError("pdf_path is disabled: SENTINEL_INGEST_DIR is not set")
    base = ingest_dir.resolve()
    candidate = (base / user_path).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError("pdf_path must stay inside SENTINEL_INGEST_DIR")
    if candidate.suffix.lower() != ".pdf" or not candidate.is_file():
        raise ValueError("pdf_path must name an existing .pdf file")
    if candidate.stat().st_size > MAX_PDF_BYTES:
        raise ValueError(f"PDF exceeds {MAX_PDF_BYTES} bytes")
    return candidate.read_bytes()


def decode_inline_pdf(pdf_base64: str) -> bytes:
    try:
        data = base64.b64decode(pdf_base64, validate=True)
    except binascii.Error as exc:
        raise ValueError("pdf_base64 is not valid base64") from exc
    if len(data) > MAX_INLINE_PDF_BYTES:
        raise ValueError(f"inline PDFs are limited to {MAX_INLINE_PDF_BYTES} bytes")
    return data
