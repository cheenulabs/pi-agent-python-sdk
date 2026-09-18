"""A published package must match the reviewed artifacts before promotion."""

import copy
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from urllib.error import HTTPError

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_distribution.py"
spec = importlib.util.spec_from_file_location("check_distribution", SCRIPT)
distribution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(distribution)


@pytest.fixture
def release(tmp_path):
    project, version = "pi-coding-agent-python-sdk", "0.1.0rc1"
    wheel = tmp_path / "pi_coding_agent_python_sdk-0.1.0rc1-py3-none-any.whl"
    sdist = tmp_path / "pi_coding_agent_python_sdk-0.1.0rc1.tar.gz"
    wheel.write_bytes(b"reviewed wheel")
    sdist.write_bytes(b"reviewed source")
    record = {
        "info": {"name": project, "version": version},
        "urls": [
            {
                "filename": path.name,
                "digests": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                "yanked": False,
            }
            for path in (wheel, sdist)
        ],
    }
    return project, version, wheel, sdist, record


def test_index_contains_both_reviewed_artifacts(release):
    project, version, wheel, sdist, record = release
    distribution.verify_index_metadata(record, project, version, [wheel, sdist])


@pytest.mark.parametrize("failure", ["name", "version", "missing", "duplicate", "digest", "yanked"])
def test_index_rejects_wrong_release_or_changed_artifacts(release, failure):
    project, version, wheel, sdist, original = release
    record = copy.deepcopy(original)
    if failure in {"name", "version"}:
        record["info"][failure] = "another-release"
    elif failure == "missing":
        record["urls"].pop()
    elif failure == "duplicate":
        record["urls"].append(record["urls"][0])
    elif failure == "digest":
        record["urls"][1]["digests"]["sha256"] = "0" * 64
    else:
        record["urls"][0]["yanked"] = True
    with pytest.raises(ValueError):
        distribution.verify_index_metadata(record, project, version, [wheel, sdist])


@pytest.mark.parametrize("corrupt", [False, True])
def test_download_pins_index_version_and_hash_and_checks_bytes(
    release, tmp_path, monkeypatch, corrupt
):
    project, version, wheel, sdist, record = release
    metadata_urls = []

    def urlopen(url, timeout):
        metadata_urls.append(url)
        return io.StringIO(json.dumps(record))

    def download(command, **kwargs):
        assert command[command.index("--index-url") + 1] == "https://test.pypi.org/simple/"
        assert "--require-hashes" in command and "--no-deps" in command
        assert "--no-cache-dir" in command and "--isolated" in command
        requirement = Path(command[command.index("-r") + 1]).read_text()
        assert requirement == (
            f"{project}=={version} --hash=sha256:{record['urls'][0]['digests']['sha256']}\n"
        )
        destination = Path(command[command.index("--dest") + 1])
        destination.mkdir()
        (destination / wheel.name).write_bytes(
            b"different wheel" if corrupt else wheel.read_bytes()
        )

    monkeypatch.setattr(distribution, "urlopen", urlopen)
    monkeypatch.setattr(distribution.subprocess, "run", download)
    arguments = ("testpypi", project, version, wheel, sdist, tmp_path, Path(sys.executable))
    if corrupt:
        with pytest.raises(ValueError, match="Downloaded wheel differs"):
            distribution.download_index_wheel(*arguments)
    else:
        result = distribution.download_index_wheel(*arguments)
        assert result.read_bytes() == wheel.read_bytes()
    assert metadata_urls == [f"https://test.pypi.org/pypi/{project}/{version}/json"]


def test_index_visibility_retries_are_bounded(release, tmp_path, monkeypatch):
    project, version, wheel, sdist, _ = release
    calls, sleeps = [], []

    def unavailable(url, timeout):
        calls.append(url)
        raise HTTPError(url, 404, "Not visible yet", {}, None)

    monkeypatch.setattr(distribution, "urlopen", unavailable)
    monkeypatch.setattr(distribution.time, "sleep", sleeps.append)
    with pytest.raises(HTTPError):
        distribution.download_index_wheel(
            "pypi", project, version, wheel, sdist, tmp_path, Path(sys.executable)
        )
    assert len(calls) == 6
    assert sleeps == [10] * 5


def test_hash_mismatch_stops_before_installation(release, tmp_path, monkeypatch):
    project, version, wheel, sdist, record = release
    record["urls"][0]["digests"]["sha256"] = "0" * 64
    monkeypatch.setattr(distribution, "urlopen", lambda *a, **kw: io.StringIO(json.dumps(record)))
    monkeypatch.setattr(distribution.subprocess, "run", lambda *a, **kw: pytest.fail("pip ran"))
    with pytest.raises(ValueError, match="SHA-256"):
        distribution.download_index_wheel(
            "pypi", project, version, wheel, sdist, tmp_path, Path(sys.executable)
        )
