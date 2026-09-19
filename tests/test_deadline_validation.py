"""Invalid public deadlines fail locally and leave the client usable."""

import sys
from pathlib import Path

import pytest

from pi_agent import AsyncPiClient, Limits, PiClient

FAKE = [sys.executable, str(Path(__file__).with_name("fake_client_pi.py"))]
OPERATIONS = ["run", "stream", "prompt_and_wait", "get_state", "collect_events", "wait_for_idle"]
INVALID = ["invalid", 10**400]


@pytest.mark.parametrize("timeout", INVALID, ids=["string", "oversized-integer"])
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_async_invalid_deadline_does_not_submit_or_claim_the_conversation(operation, timeout):
    async with AsyncPiClient(executable=FAKE) as pi:
        with pytest.raises(ValueError, match="positive finite"):
            if operation == "stream":
                async with pi.stream("paused", timeout=timeout):
                    pytest.fail("Invalid deadline entered the stream")
            elif operation in {"run", "prompt_and_wait"}:
                await getattr(pi, operation)("paused", timeout=timeout)
            else:
                await getattr(pi, operation)(timeout=timeout)
        assert pi.running and not pi.busy
        assert (await pi.run("normal")).text == "answer"


@pytest.mark.parametrize("timeout", INVALID, ids=["string", "oversized-integer"])
@pytest.mark.parametrize("operation", OPERATIONS)
def test_blocking_invalid_deadline_preserves_async_behavior(operation, timeout):
    with PiClient(executable=FAKE) as pi:
        with pytest.raises(ValueError, match="positive finite"):
            if operation == "stream":
                with pi.stream("paused", timeout=timeout):
                    pytest.fail("Invalid deadline entered the stream")
            elif operation in {"run", "prompt_and_wait"}:
                getattr(pi, operation)("paused", timeout=timeout)
            else:
                getattr(pi, operation)(timeout=timeout)
        assert pi.running and not pi.busy
        assert pi.run("normal").text == "answer"


@pytest.mark.parametrize(
    "field", ["startup_timeout", "command_timeout", "run_start_timeout", "cleanup_timeout"]
)
def test_unrepresentable_limit_is_a_value_error(field):
    with pytest.raises(ValueError, match=field):
        Limits(**{field: 10**400})
