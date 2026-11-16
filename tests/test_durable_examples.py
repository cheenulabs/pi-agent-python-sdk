"""Example inventory and modes stay isolated from provider/configuration state."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(relative: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location("tested_example_module", ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checker(tmp_path, monkeypatch):
    module = load("scripts/check_examples.py")
    (tmp_path / "examples").mkdir()
    for name in module.EXAMPLES + module.DURABLE_EXAMPLES:
        (tmp_path / "examples" / name).touch()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module.shutil, "which", lambda _: "/synthetic/node")
    return module


def test_durable_mode_needs_no_coding_runtime(checker, monkeypatch):
    (checker.ROOT / "host/node_modules").mkdir(parents=True)
    called = []
    monkeypatch.setattr(
        checker, "check_durable_example", lambda path, command: called.append(path.name)
    )
    monkeypatch.setattr(checker, "load", lambda *args: pytest.fail("Loaded coding fixture"))
    monkeypatch.setattr(sys, "argv", ["check_examples.py", "--durable"])
    checker.main()
    assert called == list(checker.DURABLE_EXAMPLES)
    assert not (checker.ROOT / "tests/pi").exists()


def test_default_mode_still_runs_only_coding_examples(checker, monkeypatch):
    runtime = (
        checker.ROOT / "tests/pi/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"
    )
    runtime.parent.mkdir(parents=True)
    runtime.touch()
    called = []
    monkeypatch.setattr(checker, "load", lambda *args: ModuleType("fixture"))
    monkeypatch.setattr(
        checker, "check_example", lambda path, _: called.append(path.name) or "1.5.2"
    )
    monkeypatch.setattr(checker, "check_durable_example", lambda *args: pytest.fail("Ran Durable"))
    monkeypatch.setattr(sys, "argv", ["check_examples.py"])
    checker.main()
    assert called == list(checker.EXAMPLES)


def test_union_inventory_rejects_uncovered_example(checker, monkeypatch):
    (checker.ROOT / "examples/uncovered.py").touch()
    monkeypatch.setattr(sys, "argv", ["check_examples.py", "--durable"])
    with pytest.raises(RuntimeError, match="complete example set"):
        checker.main()


def test_durable_mode_requires_host_modules(checker, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check_examples.py", "--durable"])
    with pytest.raises(RuntimeError, match="npm ci --prefix host"):
        checker.main()


def test_recovery_example_default_path_and_explicit_argv(monkeypatch):
    example = load("examples/durable_recovery.py")
    monkeypatch.delenv("PI_DURABLE_HOST", raising=False)
    assert example.host_command() == ["node", str(ROOT / "host/src/host.ts")]
    monkeypatch.setenv("PI_DURABLE_HOST", '["/node with spaces", "/host path/host.ts"]')
    assert example.host_command() == ["/node with spaces", "/host path/host.ts"]
    monkeypatch.setenv("PI_DURABLE_HOST", '"not an argv array"')
    with pytest.raises(ValueError, match="argv array"):
        example.host_command()
