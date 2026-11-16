"""Relative SQLite paths follow the caller, not a changing host working directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from pi_agent.durable import AsyncDurableClient


async def test_relative_storage_survives_host_cwd_change(
    durable_host_command: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("first", "second"):
        (tmp_path / name).mkdir()
    first_sid = None
    for name in ("first", "second"):
        async with AsyncDurableClient(
            "state.db",
            host_command=durable_host_command,
            cwd=tmp_path / name,
            inherit_env=False,
            faux=["Persisted in the caller directory."],
        ) as client:
            assert client._storage["path"] == str(tmp_path / "state.db")
            cid = await client.root(model={"provider": "faux", "modelId": "faux-1"})
            sid = await client.submit(cid, "Synthetic question", request_id="same-storage")
            settled = await client.wait(sid, timeout=15)
            assert settled.status == "done"
            assert await client.answer_text(settled) == "Persisted in the caller directory."
            assert sum(e["kind"] == "pi.user" for e in await client.entries(cid)) == 1
            if first_sid is None:
                first_sid = sid
            else:
                assert sid == first_sid
    assert (tmp_path / "state.db").exists()
    assert not (tmp_path / "first/state.db").exists()
    assert not (tmp_path / "second/state.db").exists()
