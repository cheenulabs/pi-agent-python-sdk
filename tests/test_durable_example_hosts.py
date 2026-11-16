"""Keep host selection identical across the standalone Durable examples."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=["durable_async", "durable_recovery", "durable_sync"])
def example(request: pytest.FixtureRequest) -> ModuleType:
    path = ROOT / "examples" / f"{request.param}.py"
    spec = importlib.util.spec_from_file_location(str(request.param), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_file_relative_host(
    example: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("PI_DURABLE_HOST", raising=False)
    monkeypatch.chdir(tmp_path)
    assert example.host_command() == ["node", str(ROOT / "durable-host/src/host.ts")]


def test_host_override(example: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    command = ["/custom/node", "/custom host/host.ts", "--custom"]
    monkeypatch.setenv("PI_DURABLE_HOST", json.dumps(command))
    assert example.host_command() == command


@pytest.mark.parametrize("configured", ["[]", "null", '"node"', '["node", 3]', "{"])
def test_invalid_override(
    example: ModuleType, monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    monkeypatch.setenv("PI_DURABLE_HOST", configured)
    with pytest.raises(ValueError):
        example.host_command()
