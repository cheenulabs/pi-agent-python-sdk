"""Source drift must require review even when existing behavior still passes."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_upstream.py"
spec = importlib.util.spec_from_file_location("check_upstream", SCRIPT)
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)


@pytest.fixture
def baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(upstream, "ROOT", tmp_path)
    monkeypatch.setattr(upstream, "BASELINE", tmp_path / "compatibility.json")
    monkeypatch.setattr(upstream, "FILES", ("rpc-types.ts",))
    metadata = {"version": "0.85.1", "gitHead": "a" * 40}
    monkeypatch.setattr(upstream, "fetch", lambda url: json.dumps(metadata).encode())
    monkeypatch.setattr(upstream, "source", lambda commit, path: b"reviewed source\n")
    monkeypatch.setattr(sys, "argv", ["check_upstream.py"])
    (tmp_path / "tests/pi").mkdir(parents=True)
    (tmp_path / "tests/pi/package.json").write_text(
        json.dumps({"devDependencies": {upstream.PACKAGE: "0.85.1"}})
    )
    (tmp_path / "src/pi_coding_agent_client").mkdir(parents=True)
    (tmp_path / "src/pi_coding_agent_client/_launch.py").write_text(
        'MINIMUM_PI_VERSION = "0.85.1"\nTESTED_PI_VERSION = "0.85.1"\n'
    )
    upstream.BASELINE.write_text(
        json.dumps(
            {
                "minimumVersion": "0.85.1",
                "testedVersion": "0.85.1",
                "upstreamCommit": "a" * 40,
                "sourceSha256": {"rpc-types.ts": hashlib.sha256(b"reviewed source\n").hexdigest()},
            }
        )
    )
    return metadata


def test_unchanged_candidate_passes(baseline):
    assert upstream.main() == 0


def test_drift_fails_without_overwriting_reviewed_baseline(baseline, monkeypatch):
    original = upstream.BASELINE.read_bytes()
    monkeypatch.setattr(upstream, "source", lambda commit, path: b"new field\n")
    assert upstream.main() == 1
    assert upstream.BASELINE.read_bytes() == original
    assert "rpc-types.ts" in (upstream.ROOT / "upstream-report.md").read_text()


def test_new_version_needs_review_even_with_identical_source(baseline):
    baseline["version"] = "0.86.0"
    assert upstream.main() == 1


def test_record_is_explicit(baseline, monkeypatch):
    baseline["version"] = "0.86.0"
    monkeypatch.setattr(sys, "argv", ["check_upstream.py", "--record"])
    assert upstream.main() == 0
    assert json.loads(upstream.BASELINE.read_text())["testedVersion"] == "0.86.0"


def test_offline_claim_cannot_disagree_with_record(baseline):
    (upstream.ROOT / "src/pi_coding_agent_client/_launch.py").write_text(
        'TESTED_PI_VERSION = "0.84.0"'
    )
    assert upstream.main() == 1
