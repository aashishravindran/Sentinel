"""The SpiceDB schema grants exactly what spicedb/validation.yaml asserts."""

import shutil
import subprocess
from pathlib import Path

import pytest

VALIDATION = Path(__file__).parent.parent / "spicedb" / "validation.yaml"


@pytest.mark.skipif(shutil.which("zed") is None, reason="zed CLI not installed")
def test_schema_assertions_hold():
    result = subprocess.run(
        ["zed", "validate", str(VALIDATION)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
