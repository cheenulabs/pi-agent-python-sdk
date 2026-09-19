# Pi Agent Python SDK

[![PyPI](https://img.shields.io/pypi/v/pi-agent-python-sdk?style=flat-square)][pypi]
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square)][metadata]
[![MIT license](https://img.shields.io/badge/license-MIT-blue?style=flat-square)][license]

**Run Pi from Python. Stream responses, continue conversations, and control sessions.**

A community Python SDK for [Pi coding agent](https://github.com/earendil-works/pi).
Use synchronous or asynchronous clients with typed access to Pi's RPC commands
and no third-party Python runtime dependencies. Pi runs as a subprocess and keeps
its usual models, authentication, tools, extensions, skills, and configuration.

> Requires Python **3.11+** and a separate Pi installation. The tested protocol
> baseline is **Pi 0.85.1**; see [compatibility][compatibility] for version and
> platform scope.

[Quick start](#quick-start) · [Streaming](#streaming) · [Async](#async-usage) ·
[Configuration](#configuration) · [RPC](#rpc-access) · [Documentation](#documentation)

## Quick start

Install Pi with Node.js **22.19.0 or newer**:

```sh
npm install -g @earendil-works/pi-coding-agent@0.85.1
pi --version
```

Run `pi` once to configure your provider and model using Pi's normal setup.
The SDK uses that configuration when it starts Pi.

Install the Python package from [PyPI][pypi]:

```sh
python -m pip install pi-agent-python-sdk==0.2.0
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
settle, including retries and queued follow-ups. The result includes finalized
messages, session identity, elapsed time, and observed assistant usage.

Continue the conversation with another call on the same client:

```python
from pi_agent import PiClient

with PiClient() as pi:
    print(pi.run("Explain this project's entry points without editing files.").text)
    print(pi.run("Which of those entry points handles configuration?").text)
```

Pi keeps the conversation context. Each result contains only the messages and
answer from that call; a call with no assistant output has empty text.

## What you can do

- **Run and stream:** get a final answer or consume text, thinking, and tool events.
- **Keep a conversation:** send follow-up prompts, resume sessions, fork, or clone.
- **Control Pi:** select models, adjust thinking, steer work, compact context, and
  call all 33 RPC commands in the pinned baseline.
- **Integrate with your application:** use sync or async clients, typed results,
  raw event dictionaries, and extension UI callbacks.

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
recognize. Keep the stream inside its context: leaving early cleans up unfinished work. See [errors and cancellation][errors] for
handling timeouts and partial results.

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

Use one client per conversation and wait for each `run()` or stream to finish
before starting the next. After using `prompt()` for your own event handling,
use a fresh client for `run()` or `stream()` so results cannot include delayed
events from earlier work. The SDK launches a new process and cannot attach to an existing
Pi terminal session.

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
| [Release notes][release] | Changes included in 0.2.0 |

Examples use your configured Pi and may make provider calls. Development checks
use an isolated local test provider; see [CONTRIBUTING.md][contributing] for
setup and validation commands.

Maintainers: [protocol discovery][discovery] ·
[maintenance][maintenance] · [release checklist][releasing].

## License

[MIT][license]

[pypi]: https://pypi.org/project/pi-agent-python-sdk/
[release]: https://github.com/cheenulabs/pi-agent-python-sdk/releases/tag/v0.2.0
[metadata]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.0/pyproject.toml
[license]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.0/LICENSE
[compatibility]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.0/docs/compatibility.md
[errors]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.0/docs/errors.md
[stream-example]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.0/examples/stream.py
[constructor-options]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.0/docs/api.md#constructor-options
[extensions]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.0/docs/usage.md#using-your-own-extensions
[ui-example]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.0/examples/ui.py
[rpc]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.0/docs/rpc.md
[commands]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.0/docs/api.md#all-33-rpc-commands
[usage]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.0/docs/usage.md
[api]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.0/docs/api.md
[examples]: https://github.com/cheenulabs/pi-agent-python-sdk/tree/v0.2.0/examples
[contributing]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.0/CONTRIBUTING.md
[discovery]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.0/docs/discovery.md
[maintenance]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.0/docs/maintenance.md
[releasing]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.2.0/docs/releasing.md
