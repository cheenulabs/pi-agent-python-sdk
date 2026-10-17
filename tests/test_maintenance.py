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


def test_source_inventory_includes_imported_payload_definitions():
    assert {
        "packages/coding-agent/src/core/bash-executor.ts",
        "packages/coding-agent/src/core/source-info.ts",
        "packages/coding-agent/src/core/compaction/compaction.ts",
        "packages/coding-agent/src/core/compaction/index.ts",
        "packages/coding-agent/src/core/extensions/types.ts",
        "packages/coding-agent/package.json",
        "packages/coding-agent/src/modes/rpc/jsonl.ts",
        "packages/agent/src/agent-loop.ts",
        "packages/ai/src/providers/model-schema.ts",
        "packages/ai/src/providers/compat-schema.ts",
    }.issubset(upstream.FILES)


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
    (tmp_path / "src/pi_agent").mkdir(parents=True)
    (tmp_path / "src/pi_agent/_launch.py").write_text(
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
    (upstream.ROOT / "src/pi_agent/_launch.py").write_text('TESTED_PI_VERSION = "0.84.0"')
    assert upstream.main() == 1


@pytest.mark.parametrize("commit", [None, "", "not-a-commit", "../main"])
def test_invalid_git_head_is_not_replaced_by_a_tag(commit, monkeypatch):
    def unexpected_fetch(url):
        pytest.fail(f"Invalid gitHead must not fall back to {url}")

    monkeypatch.setattr(upstream, "fetch", unexpected_fetch)
    with pytest.raises(ValueError, match="valid commit"):
        upstream.source_commit({"version": "1.3.0", "gitHead": commit})


def test_missing_git_head_resolves_version_tag_and_checks_package(monkeypatch):
    urls = []

    def fetch(url):
        urls.append(url)
        if url == "https://api.github.com/repos/earendil-works/pi/commits/v1.3.0":
            return json.dumps({"sha": "b" * 40}).encode()
        assert url == (
            "https://raw.githubusercontent.com/earendil-works/pi/"
            + "b" * 40
            + "/packages/coding-agent/package.json"
        )
        return json.dumps({"name": upstream.PACKAGE, "version": "1.3.0"}).encode()

    monkeypatch.setattr(upstream, "fetch", fetch)
    assert upstream.source_commit({"version": "1.3.0"}) == "b" * 40
    assert len(urls) == 2


@pytest.mark.parametrize(
    "package",
    [
        {"name": upstream.PACKAGE, "version": "1.2.0"},
        {"name": "wrong-package", "version": "1.3.0"},
    ],
)
def test_tag_with_wrong_package_is_rejected(package, monkeypatch):
    monkeypatch.setattr(upstream, "fetch", lambda url: json.dumps({"sha": "b" * 40}).encode())
    monkeypatch.setattr(upstream, "source", lambda commit, path: json.dumps(package).encode())
    with pytest.raises(ValueError, match="does not match"):
        upstream.source_commit({"version": "1.3.0"})


def test_moved_tag_fails_without_overwriting_baseline(baseline, monkeypatch):
    original = upstream.BASELINE.read_bytes()
    del baseline["gitHead"]

    def fetch(url):
        if "registry.npmjs.org" in url:
            return json.dumps(baseline).encode()
        return json.dumps({"sha": "b" * 40}).encode()

    def source(commit, path):
        if path == "packages/coding-agent/package.json":
            return json.dumps({"name": upstream.PACKAGE, "version": "0.85.1"}).encode()
        return b"reviewed source\n"

    monkeypatch.setattr(upstream, "fetch", fetch)
    monkeypatch.setattr(upstream, "source", source)
    assert upstream.main() == 1
    assert upstream.BASELINE.read_bytes() == original


def test_new_inventory_file_does_not_fetch_nonexistent_old_source(baseline, monkeypatch):
    original = upstream.BASELINE.read_bytes()
    monkeypatch.setattr(upstream, "FILES", ("rpc-types.ts", "new-schema.ts"))
    baseline["gitHead"] = "b" * 40

    def source(commit, path):
        assert (commit, path) != ("a" * 40, "new-schema.ts")
        return b"reviewed source\n"

    monkeypatch.setattr(upstream, "source", source)
    assert upstream.main() == 1
    assert upstream.BASELINE.read_bytes() == original
    assert "No previous source fingerprint" in (upstream.ROOT / "upstream-report.md").read_text()
