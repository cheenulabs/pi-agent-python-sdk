"""Real Pi reads models, credentials, and settings from AgentConfig."""

from __future__ import annotations

from typing import Any

import pytest

from pi_agent import AgentConfig
from pi_agent.client import AsyncPiClient

pytestmark = pytest.mark.integration

MODELS = {
    "providers": {
        "configured": {
            "baseUrl": "http://127.0.0.1:9/v1",
            "api": "openai-completions",
            "models": [{"id": "configured-model"}],
        }
    }
}
AUTH = {"configured": {"type": "api_key", "key": "synthetic"}}


async def _probe(pi_options: dict[str, Any], config: AgentConfig) -> tuple[set[str], bool]:
    options = {
        **pi_options,
        "env": {**pi_options["env"], **config.env},
        "provider": None,
        "model": None,
        "no_session": True,
        "extra_args": ["--offline", "--no-extensions"],
    }
    async with AsyncPiClient(**options) as pi:
        models = {f"{m['provider']}/{m['id']}" for m in await pi.get_available_models()}
        return models, (await pi.get_state())["autoCompactionEnabled"]


async def test_models_auth_and_settings_take_effect(pi_options):
    with AgentConfig(
        models=MODELS, auth=AUTH, settings={"compaction": {"enabled": False}}
    ) as config:
        models, auto_compaction = await _probe(pi_options, config)
    assert "configured/configured-model" in models
    assert auto_compaction is False


async def test_omitted_files_use_pi_defaults(pi_options):
    # Without auth.json the declared provider has no credential, so Pi hides it.
    with AgentConfig(models=MODELS) as config:
        models, auto_compaction = await _probe(pi_options, config)
    assert "configured/configured-model" not in models
    assert auto_compaction is True
