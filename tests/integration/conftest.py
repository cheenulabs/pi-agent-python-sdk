"""Start real Pi with only temporary state and the offline extension."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from pi_agent.client import AsyncPiClient


@pytest.fixture
def pi_options(tmp_path: Path) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    runtime = root / "tests/pi/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"
    node = shutil.which("node")
    if node is None or not runtime.is_file():
        if os.environ.get("PI_CLIENT_REQUIRE_INTEGRATION") == "1":
            pytest.fail("Required real-Pi runtime is missing; integration cannot be skipped in CI")
        pytest.skip("Install Node and run: npm ci --prefix tests/pi --ignore-scripts")
    expected = os.environ.get("PI_CLIENT_EXPECTED_PI_VERSION")
    if expected is not None:
        actual = subprocess.run(
            [node, str(runtime), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        assert actual == expected, f"Expected real Pi {expected}, got {actual}"
    project = tmp_path / "project"
    config = tmp_path / "config"
    project.mkdir()
    config.mkdir()
    (config / "settings.json").write_text(
        json.dumps(
            {
                "retry": {"enabled": True, "maxRetries": 2, "baseDelayMs": 1},
                "compaction": {"enabled": False, "keepRecentTokens": 1},
            }
        ),
        encoding="utf-8",
    )
    # Preserve executable lookup and Windows process requirements, never auth.
    env = {
        key: os.environ[key]
        for key in ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP")
        if key in os.environ
    }
    env.update(PI_CODING_AGENT_DIR=str(config), NO_COLOR="1")
    return {
        "executable": [node, str(runtime)],
        "cwd": project,
        "env": env,
        "inherit_env": False,
        "provider": "python-fixture",
        "model": "fixture",
        "extra_args": [
            "--no-builtin-tools",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-context-files",
            "--no-themes",
            "--no-approve",
            "--extension",
            str(root / "tests/integration/fixture.ts"),
        ],
    }


@pytest.fixture
def pi_client_factory(pi_options: dict[str, Any]) -> Callable[..., AsyncPiClient]:
    """Additional clients share this test's isolated project/configuration only."""

    def factory(**overrides: Any) -> AsyncPiClient:
        return AsyncPiClient(**{**pi_options, **overrides})

    return factory


@pytest_asyncio.fixture
async def pi_client(
    pi_client_factory: Callable[..., AsyncPiClient],
) -> AsyncIterator[AsyncPiClient]:
    async with pi_client_factory() as client:
        yield client
