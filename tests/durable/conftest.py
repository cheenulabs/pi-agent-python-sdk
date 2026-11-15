"""Gate only real-host tests; future fake-host unit tests need no Node."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def durable_host_command() -> list[str]:
    root = Path(__file__).resolve().parents[2]
    node = shutil.which("node")
    problem = None
    if node is None or not (root / "host/node_modules").is_dir():
        problem = "Install Node >=22.19 and run npm ci --prefix host --ignore-scripts"
    else:
        version = subprocess.run(
            [node, "--version"], capture_output=True, text=True, timeout=30, check=True
        ).stdout.strip()
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", version)
        if match is None or tuple(map(int, match.groups())) < (22, 19, 0):
            problem = "Durable host requires Node >=22.19"
    if problem:
        if os.environ.get("PI_DURABLE_REQUIRE_INTEGRATION") == "1":
            pytest.fail(problem)
        pytest.skip(problem)
    assert node is not None
    return [node, str(root / "host/src/host.ts")]
