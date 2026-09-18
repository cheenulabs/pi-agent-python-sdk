"""Inspect built archives and exercise an installed wheel outside the checkout."""

from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
import zipfile
from email.parser import Parser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    version = project["version"]
    archive_name = f"pi_coding_agent_python_sdk-{version}"
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
        assert headers["Name"] == project["name"] == "pi-coding-agent-python-sdk"
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
        subprocess.run(
            [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
            check=True,
            cwd=directory,
        )
        # -I omits checkout paths and PYTHONPATH; the fake executable imports no package code.
        fake = str(ROOT / "tests/fake_client_pi.py")
        probe = (
            "import asyncio,sys\n"
            "import pi_agent\n"
            "from importlib.metadata import version\n"
            f"assert version('pi-coding-agent-python-sdk') == {version!r}\n"
            "from pi_agent import AsyncPiClient,PiClient\n"
            f"argv=[sys.executable,{json.dumps(fake)}]\n"
            "with PiClient(executable=argv) as pi:\n"
            "    assert pi.run('normal').text == 'answer'\n"
            "async def main():\n"
            "    async with AsyncPiClient(executable=argv) as pi:\n"
            "        assert (await pi.run('normal')).text == 'answer'\n"
            "asyncio.run(main())\n"
        )
        subprocess.run([str(python), "-I", "-c", probe], cwd=directory, check=True, timeout=30)
    print("Wheel/sdist contents and external sync/async installed-wheel runs passed")


if __name__ == "__main__":
    main()
