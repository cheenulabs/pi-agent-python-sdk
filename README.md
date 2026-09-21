# Pi Agent Python SDK

[![PyPI](https://img.shields.io/pypi/v/pi-agent-python-sdk.svg?style=flat-square)][pypi]
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square)][metadata]
[![MIT license](https://img.shields.io/badge/license-MIT-blue?style=flat-square)][license]

**Use your installed Pi coding agent as a Python API. Stream responses,
continue conversations, and control sessions from Python.**

[Pi](https://github.com/earendil-works/pi) is an open-source coding agent that
runs in your terminal. This unofficial community SDK launches the Pi CLI in RPC
mode and exposes prompts, streaming events, and sessions through typed
synchronous and asynchronous Python APIs.

```python
from pi_agent import PiClient

with PiClient() as pi:
    print(pi.run("Explain the current project without changing files.").text)
```

Requires an installed, configured Pi CLI — see [Prerequisites](#prerequisites).

[Prerequisites](#prerequisites) · [Quick start](#quick-start) ·
[Streaming](#streaming) · [Async](#async-usage) ·
[Configuration](#configuration) · [Thinking](#models-and-thinking) ·
[RPC](#rpc-access) · [Documentation](#documentation) ·
[Support](#support)

## Prerequisites

| Requirement | Notes |
| --- | --- |
| Python **3.11+** | Package metadata requires 3.11 or newer |
| Node.js **22.19.0+** | Required by Pi 0.86.0 |
| Pi **0.85.1+** | Minimum accepted version; **0.86.0** is the tested baseline |
| Model provider | Required; configure with the Pi CLI (see Quick start) |

## What you can do

- Automate coding or analysis from Python scripts, apps, or services.
- Stream text, thinking, and tool events, or wait for a completed result.
- Continue, resume, fork, or clone conversations across calls.
- Select models, adjust thinking, steer work, compact context, and call Pi RPC
  commands — reusing your existing Pi configuration, tools, and extensions.

## Quick start

Install Pi with Node.js **22.19.0 or newer** (pin matches the tested baseline):

```sh
npm install -g @earendil-works/pi-coding-agent@0.86.0
pi --version
```

Run `pi` once to configure your provider and model. The SDK uses that
configuration when it starts Pi.

Install the Python package from [PyPI][pypi]:

```sh
python -m pip install pi-agent-python-sdk
```

The distribution is named `pi-agent-python-sdk`; import it as
`pi_agent`.

```python
from pi_agent import PiClient

with PiClient() as pi:
    result = pi.run("Explain the current project without changing files.")
    print(result.text)
```

The context manager starts and closes Pi. `run()` waits for the conversation to
settle. The result includes finalized messages, session identity, elapsed time,
and observed assistant usage.

Continue the conversation with another call on the same client:

```python
from pi_agent import PiClient

with PiClient() as pi:
    print(pi.run("Explain this project's entry points without editing files.").text)
    print(pi.run("Which of those entry points handles configuration?").text)
```

Pi keeps the conversation context. Each result contains only the messages and
answer from that call; a call with no assistant output has empty text.

### Troubleshooting

| Symptom | What to check |
| --- | --- |
| `pi` not found / launch fails | Ensure the Pi CLI is on `PATH`, or pass `executable=` to the client |
| Version rejected | Upgrade to Pi **0.85.1+**; prefer the tested baseline **0.86.0** |
| No model / auth errors | Run `pi` once and complete provider setup |
| Unexpected file or command changes | Review Pi tool/extension settings before automation |

## Streaming

```python
from pi_agent import PiClient

with PiClient() as pi:
    with pi.stream("Explain this project's entry points without editing files.") as stream:
        for event in stream:
            if event.text_delta is not None:
                print(event.text_delta, end="", flush=True)
        result = stream.result()
    print(f"\nStop reason: {result.stop_reason}")
```

`event.raw` contains the full Pi event, including fields the SDK does not yet
recognize. Keep the stream inside its context: leaving early cleans up unfinished
work. See [errors and cancellation][errors] for handling timeouts and partial
results.

## Async usage

Use `AsyncPiClient` in applications that already run an event loop. Command
arguments and results match the synchronous client.

```python
import asyncio

from pi_agent import AsyncPiClient


async def main() -> None:
    async with AsyncPiClient() as pi:
        result = await pi.run("Explain the current project without changing files.")
        print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
```

Async streaming uses `async with pi.stream(...)`, `async for event in stream`,
and `await stream.result()`. See the [complete streaming example][stream-example].

## Configuration

Choose the project directory and whether to save the conversation:

```python
from pi_agent import PiClient

with PiClient(cwd=".", no_session=True) as pi:
    print(pi.run("Describe this project without changing files.").text)
```

Leave `no_session` unset to preserve Pi's normal session persistence. Use
`provider=` and `model=` to override Pi's configured model, or `session=` to open
an existing session. See [constructor options][constructor-options]
for environment overrides, executable paths, and deadlines.

Extensions are installed and configured through Pi. To load your own extension,
pass `extra_args=["--extension", "/absolute/path/to/your-extension.ts"]` to either
client. See [using your own extensions][extensions]
for details and [extension UI][ui-example] for an interactive example.

## Models and thinking

The SDK uses Pi's configured model unless you pass `provider=` and `model=`.
Query supported thinking levels before setting one:

```python
from pi_agent import PiClient

with PiClient() as pi:
    levels = pi.get_available_thinking_levels()
    if "high" in levels:
        pi.set_thinking_level("high")
    print(pi.run("Analyse this project's architecture without changing files.").text)
```

Set the model and thinking level before `run()` or `stream()`. Pi may adjust
unsupported levels; read `get_state()["thinkingLevel"]` for the effective value.
Thinking **output** is separate from `result.text`: when Pi emits it, deltas
appear in `event.raw` during streaming and finalized blocks in `result.messages`.

See the [model and thinking commands][thinking-reference] for cycling levels and
other controls.

## RPC access

The SDK speaks Pi's existing JSONL protocol over stdin/stdout:

```text
Your Python application
    PiClient / AsyncPiClient
        pi --mode rpc
            Models · tools · extensions · sessions
```

Choose the interface that fits the work:

| You need | Use |
| --- | --- |
| A completed conversation result | `run()` |
| Events while a conversation runs | `stream()` |
| Prompt acknowledgement and your own event handling | `prompt()` with `events()` |
| Session events through the next settlement | `prompt_and_wait()` or `collect_events()` |
| Every event without retaining history | `on_event(callback)` |
| A specific Pi operation | `get_state()`, `set_model()`, `fork()`, and other command methods |
| A raw command response envelope | `request()` |

For example, inspect session state without starting a model run:

```python
from pi_agent import PiClient

with PiClient() as pi:
    state = pi.get_state()
    print(state["sessionId"])
```

Python arguments use `snake_case`; wire dictionaries retain Pi's `camelCase`
fields. `prompt()` acknowledges submission, which may be handled entirely by an
extension. It does not wait for a completed answer.

Each client starts its own Pi subprocess. Use one client per conversation and
wait for each `run()` or stream to finish before starting the next. After using
`prompt()` for your own event handling, use a fresh client for `run()` or
`stream()` so results cannot include delayed events from earlier work.

See [RPC structure][rpc] for the protocol mapping and module layout, and
the [command reference][commands] for every method.

## Documentation

| Guide | Contents |
| --- | --- |
| [Usage][usage] | Sessions, images, concurrency, events, and extension UI |
| [API reference][api] | Constructors, commands, types, and results |
| [Errors and cancellation][errors] | Deadlines, partial results, cleanup, and recovery |
| [RPC structure][rpc] | How the Python client maps to Pi's protocol |
| [Compatibility][compatibility] | Runtime versions and platform validation |
| [Examples][examples] | Runnable sync, async, streaming, sessions, steering, and UI examples |
| [Release notes][release] | Changes included in 0.2.1 |

Examples use your configured Pi and may make provider calls. Development checks
use an isolated local test provider; see [CONTRIBUTING.md][contributing] for
setup and validation commands.

## Support

- [Open an issue][issues] for bugs, questions, or compatibility reports.
- See [CONTRIBUTING.md][contributing] for local setup and pull requests.
- For security reports, open a [private security advisory][security].

## License

[MIT][license]

[pypi]: https://pypi.org/project/pi-agent-python-sdk/
[release]: https://github.com/cheenulabs/pi-agent-python-sdk/releases/tag/v0.2.1
[metadata]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.1/pyproject.toml
[license]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.1/LICENSE
[compatibility]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.1/docs/compatibility.md
[errors]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.1/docs/errors.md
[stream-example]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.1/examples/stream.py
[constructor-options]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.1/docs/api.md#constructor-options
[extensions]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.1/docs/usage.md#using-your-own-extensions
[ui-example]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.1/examples/ui.py
[rpc]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.1/docs/rpc.md
[commands]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.1/docs/api.md#all-33-rpc-commands
[thinking-reference]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.1/docs/api.md#models-state-and-compaction
[usage]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.1/docs/usage.md
[api]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.1/docs/api.md
[examples]: https://github.com/cheenulabs/pi-agent-python-sdk/tree/v0.2.1/examples
[contributing]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.1/CONTRIBUTING.md
[issues]: https://github.com/cheenulabs/pi-agent-python-sdk/issues
[security]: https://github.com/cheenulabs/pi-agent-python-sdk/security/advisories/new
