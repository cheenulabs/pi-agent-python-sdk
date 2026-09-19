"""Inspect built archives and exercise an installed wheel outside the checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import venv
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
INDEX_HOSTS = {"testpypi": "test.pypi.org", "pypi": "pypi.org"}


def verify_index_metadata(
    record: dict[str, Any], project: str, version: str, artifacts: list[Path]
) -> None:
    """Reject another release, missing/yanked files, or altered uploaded artifacts."""
    info = record.get("info", {})
    if info.get("name") != project or info.get("version") != version:
        raise ValueError("Index project/version differs from the reviewed build")
    files = record.get("urls", [])
    for artifact in artifacts:
        matches = [item for item in files if item.get("filename") == artifact.name]
        if len(matches) != 1:
            raise ValueError(f"Index must contain exactly one {artifact.name}")
        item = matches[0]
        if item.get("yanked"):
            raise ValueError(f"Index artifact is yanked: {artifact.name}")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if item.get("digests", {}).get("sha256") != digest:
            raise ValueError(f"Index SHA-256 differs from reviewed artifact: {artifact.name}")


def download_index_wheel(
    index: str,
    project: str,
    version: str,
    wheel: Path,
    sdist: Path,
    directory: Path,
    python: Path,
) -> Path:
    """Read index metadata and download a hash-pinned wheel without publishing."""
    host = INDEX_HOSTS[index]
    for attempt in range(6):
        try:
            with urlopen(f"https://{host}/pypi/{project}/{version}/json", timeout=30) as response:
                record = json.load(response)
            break
        except (HTTPError, URLError) as error:
            # An upload may take a moment to become visible. Identity or hash
            # mismatches below fail immediately and are never retried.
            if isinstance(error, HTTPError) and error.code not in {404, 429, 500, 502, 503, 504}:
                raise
            if attempt == 5:
                raise
            time.sleep(10)
    verify_index_metadata(record, project, version, [wheel, sdist])
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    requirement = directory / "release.txt"
    requirement.write_text(f"{project}=={version} --hash=sha256:{digest}\n")
    destination = directory / "download"
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "--isolated",
            "download",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--no-deps",
            "--only-binary=:all:",
            "--require-hashes",
            "--index-url",
            f"https://{host}/simple/",
            "--dest",
            str(destination),
            "-r",
            str(requirement),
        ],
        check=True,
        cwd=directory,
        timeout=180,
    )
    downloaded = destination / wheel.name
    if hashlib.sha256(downloaded.read_bytes()).hexdigest() != digest:
        raise ValueError("Downloaded wheel differs from the reviewed artifact")
    return downloaded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", choices=INDEX_HOSTS, help="Verify a published index copy")
    parser.add_argument(
        "--parity",
        action="store_true",
        help="Compare the installed wheel with TypeScript; requires locked tests/pi installation",
    )
    args = parser.parse_args()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    version = project["version"]
    archive_name = f"pi_agent_python_sdk-{version}"
    (wheel,) = (ROOT / "dist").glob("*.whl")
    (sdist,) = (ROOT / "dist").glob("*.tar.gz")
    assert wheel.name == f"{archive_name}-py3-none-any.whl"
    assert sdist.name == f"{archive_name}.tar.gz"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert "pi_agent/py.typed" in names
        assert all(
            name.startswith(("pi_agent/", f"{archive_name}.dist-info/")) for name in names
        ), names
        metadata_path = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_path).decode()
        headers = Parser().parsestr(metadata)
        assert headers["Name"] == project["name"] == "pi-agent-python-sdk"
        assert headers["Version"] == version
        assert "Requires-Dist:" not in metadata, "Runtime dependencies must remain empty"
        assert "License-Expression: MIT" in metadata
    with tarfile.open(sdist) as archive:
        names += archive.getnames()
    for name in names:
        assert not any(
            part in name.split("/") for part in ("tests", "node_modules", ".git", ".venv")
        ), name
        assert not Path(name).is_absolute() and ".." not in Path(name).parts, name
    with tempfile.TemporaryDirectory(prefix="pi-wheel-check-") as temporary:
        directory = Path(temporary)
        environment = directory / "venv"
        venv.create(environment, with_pip=True)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        if args.index:
            wheel = download_index_wheel(
                args.index, project["name"], version, wheel, sdist, directory, python
            )
        subprocess.run(
            [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
            check=True,
            cwd=directory,
        )
        # -I omits checkout paths and PYTHONPATH; the fake executable imports no package code.
        fake = str(ROOT / "tests/fake_client_pi.py")
        contracts = str(ROOT / "tests/fake_contract_pi.py")
        probe = (
            "import asyncio,sys\n"
            "import pi_agent\n"
            "from pathlib import Path\n"
            # Windows temporary directories may use an 8.3 alias in sys.prefix.
            "assert Path(pi_agent.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())\n"
            "assert Path(pi_agent.__file__).with_name('py.typed').is_file()\n"
            "from importlib.metadata import version\n"
            f"assert version('pi-agent-python-sdk') == {version!r}\n"
            "from pi_agent import AsyncPiClient,PiClient\n"
            f"argv=[sys.executable,{json.dumps(fake)}]\n"
            "with PiClient(executable=argv) as pi:\n"
            "    assert pi.run('normal').text == 'answer'\n"
            "    with pi.stream('normal') as stream:\n"
            "        streamed = list(stream)\n"
            "        assert stream.result().text == 'answer'\n"
            "        assert streamed[-1].type == 'agent_settled'\n"
            "    assert pi.run('empty').text == ''\n"
            "    seen = []\n"
            "    remove = pi.on_event(seen.append)\n"
            "    events = pi.prompt_and_wait('burst:1000:last')\n"
            "    remove()\n"
            "    assert len(events) == len(seen) == 1003\n"
            "    assert events[-1].type == 'agent_settled'\n"
            f"contract_argv=[sys.executable,{json.dumps(contracts)}]\n"
            "with PiClient(executable=contract_argv) as pi:\n"
            "    assert pi.prompt('handled') is None\n"
            "    assert pi.cycle_thinking_level()['futureMetadata'] == {'kept':[1,2]}\n"
            "    assert pi.export_html()['path'] == '/synthetic/export.html'\n"
            "    pi.request('configure', reject_state=True)\n"
            "    assert pi.new_session() == {'cancelled':False}\n"
            "async def main():\n"
            "    async with AsyncPiClient(executable=argv) as pi:\n"
            "        assert (await pi.run('normal')).text == 'answer'\n"
            "        async with pi.stream('normal') as stream:\n"
            "            streamed = [event async for event in stream]\n"
            "            assert (await stream.result()).text == 'answer'\n"
            "            assert streamed[-1].type == 'agent_settled'\n"
            "        assert (await pi.run('empty')).text == ''\n"
            "        seen = []\n"
            "        remove = pi.on_event(seen.append)\n"
            "        events = await pi.prompt_and_wait('burst:1000:last')\n"
            "        remove()\n"
            "        assert len(events) == len(seen) == 1003\n"
            "        assert events[-1].type == 'agent_settled'\n"
            "    async with AsyncPiClient(executable=contract_argv) as pi:\n"
            "        assert await pi.prompt('handled') is None\n"
            "        assert (await pi.cycle_thinking_level())['futureMetadata'] == {'kept':[1,2]}\n"
            "        assert (await pi.export_html())['path'] == '/synthetic/export.html'\n"
            "        await pi.request('configure', reject_state=True)\n"
            "        assert await pi.new_session() == {'cancelled':False}\n"
            "asyncio.run(main())\n"
        )
        if args.parity:
            # Reuse the maintained checker, keeping imports in this wheel's isolated interpreter.
            probe += (
                "import runpy\n"
                f"runpy.run_path({str(ROOT / 'scripts/check_parity.py')!r}, run_name='__main__')\n"
            )
        subprocess.run(
            [str(python), "-I", "-c", probe],
            cwd=directory,
            check=True,
            timeout=90 if args.parity else 30,
        )
    source = args.index or "local artifacts"
    print(f"{source}: wheel/sdist checks and external sync/async installed-wheel runs passed")


if __name__ == "__main__":
    main()
