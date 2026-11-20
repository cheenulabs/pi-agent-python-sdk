"""Temporary in-code agent configuration."""

from __future__ import annotations

import json
import os
import stat
import sys

import pytest

import pi_agent
from pi_agent import AgentConfig

SECRET = "synthetic-secret-value"


def test_writes_only_supplied_files_and_cleans_up() -> None:
    models = {"providers": {"local": {"baseUrl": "http://127.0.0.1:9/v1"}}}
    with AgentConfig(models=models, auth={"local": {"type": "api_key", "key": SECRET}}) as config:
        root = config.path
        assert config.env == {"PI_CODING_AGENT_DIR": os.fspath(root)}
        assert sorted(p.name for p in root.iterdir()) == ["auth.json", "models.json"]
        assert json.loads((root / "models.json").read_text(encoding="utf-8")) == models
        (root / "sessions").mkdir()  # Pi may write its own state here.
    assert not root.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_directory_and_credentials_are_private() -> None:
    with AgentConfig(settings={}, auth={}) as config:
        assert stat.S_IMODE(config.path.stat().st_mode) == 0o700
        assert stat.S_IMODE((config.path / "auth.json").stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "options",
    [
        {"models": ["not", "a", "mapping"]},
        {"settings": {"value": object()}},
        {"auth": {"key": float("nan")}},
    ],
)
def test_invalid_values_raise_without_echoing_them(options: dict[str, object]) -> None:
    with pytest.raises(ValueError) as caught:
        AgentConfig(**options)  # type: ignore[arg-type]
    assert "nan" not in str(caught.value).lower() and "object at" not in str(caught.value)


def test_values_stay_out_of_repr() -> None:
    config = AgentConfig(auth={"local": {"type": "api_key", "key": SECRET}})
    assert SECRET not in repr(config)
    with config:
        assert SECRET not in repr(config)


def test_context_is_required_and_single_use_while_active() -> None:
    config = AgentConfig()
    with pytest.raises(RuntimeError, match="context manager"):
        _ = config.env
    with config:
        with pytest.raises(RuntimeError, match="already active"):
            config.__enter__()
    with config:  # Reusable after exit.
        assert config.path.is_dir()
    assert "AgentConfig" in pi_agent.__all__
