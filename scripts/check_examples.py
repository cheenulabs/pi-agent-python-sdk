"""Smoke every example main() against isolated real Pi and its local faux provider.

Run with the development dependencies installed and `npm ci --prefix tests/pi
--ignore-scripts` completed. This checks runnable example entry points, not every
CLI option or provider behavior. It never uses live agents, credentials, existing
Pi configuration, or a network provider. Integration tests cover protocol details.
"""

from __future__ import annotations

import asyncio
import base64
import builtins
import contextlib
import importlib.util
import inspect
import io
import shutil
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

from pi_agent import AsyncPiClient, PiClient

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = (
    "async_client.py",
    "cancellation.py",
    "events.py",
    "images.py",
    "process_output.py",
    "sessions.py",
    "steering.py",
    "stream.py",
    "sync.py",
    "ui.py",
)
ANSWER = "Synthetic example answer."
PIXEL = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII="
)


def load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load example/check fixture: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_closed(client: AsyncPiClient) -> None:
    """Check actual process completion rather than only the public running flag."""
    assert not client.running, "Example left its Pi client running"
    transport = client._transport
    if transport is not None and transport._process is not None:
        assert transport._process.returncode is not None, "Example did not reap its Pi process"


def check_example(path: Path, fixture: ModuleType) -> str:
    with tempfile.TemporaryDirectory(prefix="pi-example-check-") as temporary:
        directory = Path(temporary)
        # Reuse the same reviewed minimal environment/project isolation as tests.
        # Missing runtime is checked by main(), so pytest.skip cannot conceal it.
        options = fixture.pi_options.__wrapped__(directory)
        sync_clients: list[PiClient] = []
        async_clients: list[AsyncPiClient] = []
        versions: list[str | None] = []
        control = load(ROOT / "tests/integration/control.py", "pi_example_control")

        class SyncFixture(PiClient):
            def __init__(self, **kwargs: Any) -> None:
                # Isolation takes precedence over example cwd/provider/env options.
                # Preserve options such as the example's UI handler.
                super().__init__(**{**kwargs, **options})
                sync_clients.append(self)

            def start(self) -> None:
                super().start()
                versions.append(self.pi_version)
                control.set_responses(self, [{"text": ANSWER}] * 6)

        class AsyncFixture(AsyncPiClient):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**{**kwargs, **options})
                async_clients.append(self)

            async def start(self) -> None:
                await super().start()
                versions.append(self.pi_version)
                control.set_responses(self, [{"text": ANSWER}] * 6)

        module = load(path, f"pi_checked_example_{path.stem}")
        for name, replacement in (("PiClient", SyncFixture), ("AsyncPiClient", AsyncFixture)):
            if hasattr(module, name):
                setattr(module, name, replacement)
        argv = [str(path)]
        if path.stem == "images":
            image = directory / "pixel.png"
            image.write_bytes(base64.b64decode(PIXEL))
            argv.append(str(image))
        elif path.stem == "ui":
            argv.append("/fixture-ui confirm")

        async def run_async() -> None:
            try:
                async with asyncio.timeout(60):
                    await module.main()
                for client in async_clients:
                    assert_closed(client)
            finally:
                # Cleanup runs on the clients' original loop, including when an
                # example raises before entering its context successfully.
                for client in async_clients:
                    await client.aclose()

        original_argv, original_input = sys.argv, builtins.input
        output = io.StringIO()
        try:
            sys.argv = argv
            builtins.input = lambda prompt="": "y"
            with contextlib.redirect_stdout(output):
                if inspect.iscoroutinefunction(module.main):
                    asyncio.run(run_async())
                else:
                    module.main()
                    for client in sync_clients:
                        assert_closed(client._client)
                        assert client._thread is not None and not client._thread.is_alive(), (
                            "Example did not join its background loop thread"
                        )
        finally:
            try:
                for client in sync_clients:
                    client.close()
            finally:
                sys.argv, builtins.input = original_argv, original_input

        text = output.getvalue()
        assert text, f"{path.name} produced no output"
        if path.stem in {"sync", "async_client", "images", "stream", "events"}:
            assert ANSWER in text, f"{path.name} did not display its synthetic answer"
        elif path.stem == "cancellation":
            assert "Run ownership released: True" in text
        elif path.stem == "sessions":
            assert "Session ID:" in text and "Entries:" in text
        elif path.stem == "steering":
            assert "Stop reason: stop" in text
        elif path.stem == "ui":
            assert "Command acknowledged: True" in text
        assert versions and len(set(versions)) == 1 and versions[0] is not None
        return versions[0]


def main() -> None:
    runtime = ROOT / "tests/pi/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"
    if shutil.which("node") is None or not runtime.is_file():
        raise RuntimeError(
            "Example checks require Node and real Pi; run npm ci --prefix tests/pi --ignore-scripts"
        )
    actual = {path.name for path in (ROOT / "examples").glob("*.py")}
    if actual != set(EXAMPLES):
        raise RuntimeError("Update check_examples.py to cover the current complete example set")
    fixture = load(ROOT / "tests/integration/conftest.py", "pi_example_fixture")
    for name in EXAMPLES:
        version = check_example(ROOT / "examples" / name, fixture)
        print(f"PASS {name}: isolated real Pi {version} faux provider")
    print(f"All {len(EXAMPLES)} example entry points passed; no live provider calls were used")


if __name__ == "__main__":
    main()
