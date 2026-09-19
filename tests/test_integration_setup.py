"""Missing real runtimes must fail CI rather than turn integration into skips."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

path = Path(__file__).parent / "integration/conftest.py"
spec = importlib.util.spec_from_file_location("integration_setup", path)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_missing_runtime_fails_when_integration_is_required(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_CLIENT_REQUIRE_INTEGRATION", "1")
    monkeypatch.setattr(setup.shutil, "which", lambda executable: None)
    with pytest.raises(pytest.fail.Exception, match="cannot be skipped"):
        setup.pi_options.__wrapped__(tmp_path)


def test_missing_runtime_remains_optional_for_local_unit_work(tmp_path, monkeypatch):
    monkeypatch.delenv("PI_CLIENT_REQUIRE_INTEGRATION", raising=False)
    monkeypatch.setattr(setup.shutil, "which", lambda executable: None)
    with pytest.raises(pytest.skip.Exception, match="Install Node"):
        setup.pi_options.__wrapped__(tmp_path)


def test_wrong_runtime_version_cannot_satisfy_ci(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_CLIENT_REQUIRE_INTEGRATION", "1")
    monkeypatch.setenv("PI_CLIENT_EXPECTED_PI_VERSION", "0.85.1")
    monkeypatch.setattr(setup.shutil, "which", lambda executable: "node")
    monkeypatch.setattr(setup.Path, "is_file", lambda path: True)
    monkeypatch.setattr(
        setup.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout="0.84.0\n"),
    )
    with pytest.raises(AssertionError, match="Expected real Pi 0.85.1"):
        setup.pi_options.__wrapped__(tmp_path)


def test_isolated_runtime_preserves_shell_locations_without_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("PI_CLIENT_EXPECTED_PI_VERSION", raising=False)
    monkeypatch.setenv("ProgramFiles", "C:/synthetic-programs")
    monkeypatch.setenv("ProgramFiles(x86)", "C:/synthetic-programs-x86")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-not-a-credential")
    monkeypatch.setattr(setup.shutil, "which", lambda executable: "node")
    monkeypatch.setattr(setup.Path, "is_file", lambda path: True)
    options = setup.pi_options.__wrapped__(tmp_path)
    assert options["inherit_env"] is False
    assert options["env"]["ProgramFiles"] == "C:/synthetic-programs"
    assert options["env"]["ProgramFiles(x86)"] == "C:/synthetic-programs-x86"
    assert "ANTHROPIC_API_KEY" not in options["env"]
