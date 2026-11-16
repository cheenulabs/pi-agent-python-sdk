"""Durable version checks are local and independent of coding-agent recording."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_durable", ROOT / "scripts/check_durable.py")
durable = importlib.util.module_from_spec(spec)
spec.loader.exec_module(durable)


@pytest.fixture
def pins(tmp_path, monkeypatch):
    for relative in [
        "compatibility.json",
        "durable-host/package.json",
        "durable-host/package-lock.json",
        "src/pi_agent/durable/__init__.py",
    ]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    monkeypatch.setattr(durable, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_durable.py"])
    return tmp_path


def mutate(path, change):
    value = json.loads(path.read_text())
    change(value)
    path.write_text(json.dumps(value))


def test_pins_agree_without_installed_node_modules(pins):
    assert durable.main() == 0
    assert not (pins / "durable-host/node_modules").exists()


@pytest.mark.parametrize("package", durable.PACKAGES)
@pytest.mark.parametrize("location", ["manifest", "root", "installed", "nested"])
def test_disagreement_in_each_package_fails(pins, package, location):
    if location == "manifest":
        mutate(
            pins / "durable-host/package.json",
            lambda data: data["dependencies"].update({package: "1.5.3"}),
        )
    else:

        def change(data):
            if location == "root":
                data["packages"][""]["dependencies"][package] = "1.5.3"
            elif location == "installed":
                data["packages"][f"node_modules/{package}"]["version"] = "1.5.3"
            else:
                data["packages"][f"node_modules/other/node_modules/{package}"] = {
                    "version": "1.5.3"
                }

        mutate(pins / "durable-host/package-lock.json", change)
    assert durable.main() == 1


def test_missing_locked_package_fails(pins):
    mutate(
        pins / "durable-host/package-lock.json",
        lambda data: data["packages"].pop(f"node_modules/{durable.PACKAGES[0]}"),
    )
    assert durable.main() == 1


def test_constant_disagreement_fails(pins):
    (pins / "src/pi_agent/durable/__init__.py").write_text('TESTED_PI_DURABLE_VERSION = "1.5.3"\n')
    assert durable.main() == 1


def test_record_disagreement_fails(pins):
    mutate(pins / "compatibility.json", lambda data: data["durable"].update(testedVersion="1.5.3"))
    assert durable.main() == 1


@pytest.mark.parametrize("latest,expected", [("1.5.2", 0), ("1.5.3", 1)])
def test_latest_report_does_not_change_pins(pins, monkeypatch, latest, expected):
    baseline = (pins / "compatibility.json").read_bytes()
    monkeypatch.setattr(sys, "argv", ["check_durable.py", "--latest", latest])
    assert durable.main() == expected
    assert latest in (pins / "durable-drift-report.md").read_text()
    assert (pins / "compatibility.json").read_bytes() == baseline
