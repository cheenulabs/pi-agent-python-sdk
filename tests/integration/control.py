"""Configure synthetic responses without submitting conversation work."""

import json
from pathlib import Path
from typing import Any

from pi_coding_agent_client import AsyncPiClient, PiClient


def set_responses(client: AsyncPiClient | PiClient, steps: list[dict[str, Any]]) -> None:
    path = client.session.session_file
    assert path is not None, "Fixture requires an isolated persisted session directory"
    directory = Path(path).parent
    directory.mkdir(parents=True, exist_ok=True)
    staging = directory / "fixture-responses.tmp"
    staging.write_text(json.dumps(steps), encoding="utf-8")
    staging.replace(directory / "fixture-responses.json")
