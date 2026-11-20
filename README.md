# Pi Agent Python SDK

<p align="center">
  <strong>Run Pi from Python.</strong><br>
  Your two Pi runtimes. Your Python API.
</p>

<p align="center">
  <a href="https://github.com/cheenulabs/pi-agent-python-sdk">
    <img alt="Pi Agent Python SDK" src="https://raw.githubusercontent.com/cheenulabs/pi-agent-python-sdk/v0.3.0/docs/logo.svg" width="160">
  </a>
</p>

[![PyPI](https://img.shields.io/pypi/v/pi-agent-python-sdk.svg?style=flat-square)][pypi]
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square)][metadata]
[![MIT license](https://img.shields.io/badge/license-MIT-blue?style=flat-square)][license]

Two ways to run [Pi](https://github.com/earendil-works/pi) from Python, with typed
synchronous and async APIs:

- **Coding agent — Run Pi from scripts, apps and bots.** Prompt, stream text and
  tool events, and keep sessions going through your installed Pi CLI over
  `pi --mode rpc`.
- **Pi Durable (experimental) — Agent jobs that survive crashes.** Submit work
  with an idempotency key and resume after a crash through a caller-supplied
  Node host.

This unofficial community SDK reuses your Pi configuration for models and
credentials. The coding agent also uses your CLI tools, extensions and sessions.

Both backends run upstream Pi's original TypeScript/Node.js code. This package
adds Python APIs around it; it is **not a Python port** of Pi's agent or Durable
engine.

> **Imports:** Since 0.3.0, use `pi_agent.coding` for coding-agent clients and
> `pi_agent.durable` for the experimental Durable backend. Existing top-level
> imports remain supported and silent.

The [experimental Pi Durable backend](#pi-durable-experimental) is documented
separately after the coding-agent/RPC guide below.

<!-- Inline player: GitHub auto-embeds bare user-attachments URLs. -->
https://github.com/user-attachments/assets/6c40bbc9-d322-473e-affa-b63b7f4362be

**Watch the 33.5-second demo:** coding-agent streaming and experimental Durable
crash recovery.

```python
from pi_agent.coding import PiClient

with PiClient() as pi:
    print(pi.run("Explain the current project without changing files.").text)
```

[Prerequisites](#prerequisites) · [Quick start](#quick-start) ·
[Streaming](#streaming) · [Async](#async-usage) ·
[Configuration](#configuration) · [Unattended](#run-unattended) ·
[Thinking](#models-and-thinking) · [RPC](#rpc-access) · [Testing](#test-without-a-model) ·
[Durable (experimental)](#pi-durable-experimental) ·
[Documentation](#documentation) · [Further reading](#further-reading) ·
[Troubleshooting](#troubleshooting) · [Support](#support)

## What you can do

- **Run prompts from Python** — get a final answer, or stream text, thinking, and
  tool events as they happen.
- **Keep conversations going** — send follow-ups on the same client, or resume,
  fork, and clone sessions.
- **Control the agent** — switch models, set thinking level, steer mid-run, and
  compact context.
- **Reuse your coding-agent Pi setup** — same configuration, tools, and extensions
  as the CLI, with sync or async clients.
- **Recover interrupted work with experimental Durable** — resume from persisted
  state and retry submissions with the same request key; requires a
  caller-supplied Node host.

## Prerequisites

These requirements apply to running the real coding agent. For scripted tests
with only Python, see [Test without a model](#test-without-a-model).

| Requirement | Notes |
| --- | --- |
| Python **3.11+** | Package metadata requires 3.11 or newer |
| Node.js **22.19.0+** | Required by the coding-agent baseline **1.6.0** |
| Pi CLI **0.85.1+** | **1.6.0** is the tested baseline |
| Model provider | Configure your provider and model with the Pi CLI |

## Quick start

Install Pi with Node.js **22.19.0 or newer** (pin matches the tested baseline):

```sh
npm install -g @earendil-works/pi-coding-agent@1.6.0
pi --version
```

Run `pi` once to configure your provider and model. The SDK uses that
configuration when it starts Pi.

Install the Python package from [PyPI][pypi]:

```sh
python -m pip install pi-agent-python-sdk
```

The distribution is named `pi-agent-python-sdk`; import it as `pi_agent`.
For installation from this checkout instead, use `python -m pip install -e .`.

```python
from pi_agent.coding import PiClient

with PiClient() as pi:
    result = pi.run("Explain the current project without changing files.")
    print(result.text)
```

The context manager starts and closes Pi. `run()` waits for the conversation to
settle. The result includes finalized messages, session identity, elapsed time,
and observed assistant usage.

<details>
<summary>Continue the conversation</summary>

Continue the conversation with another call on the same client:

```python
from pi_agent.coding import PiClient

with PiClient() as pi:
    print(pi.run("Explain this project's entry points without editing files.").text)
    print(pi.run("Which of those entry points handles configuration?").text)
```

Pi keeps the conversation context. Each result contains only the messages and
answer from that call; a call with no assistant output has empty text.

</details>

## Streaming

```python
from pi_agent.coding import PiClient

with PiClient() as pi:
    with pi.stream("Explain this project's entry points without editing files.") as stream:
        for event in stream:
            if event.text_delta is not None:
                print(event.text_delta, end="", flush=True)
        result = stream.result()
    print(f"\nStop reason: {result.stop_reason}")
```

<details>
<summary>Streaming details</summary>

`event.raw` contains the full Pi event, including fields the SDK does not yet
recognize. Keep the stream inside its context: leaving early cleans up unfinished
work. See [errors and cancellation][errors] for handling timeouts and partial
results.

</details>

## Async usage

Use `AsyncPiClient` in applications that already run an event loop. Command
arguments and results match the synchronous client.

```python
import asyncio

from pi_agent.coding import AsyncPiClient


async def main() -> None:
    async with AsyncPiClient() as pi:
        result = await pi.run("Explain the current project without changing files.")
        print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
```

<details>
<summary>Async streaming</summary>

Use `async with pi.stream(...)`, `async for event in stream`, and
`await stream.result()`. See the [complete streaming example][stream-example].

</details>

## Configuration

Choose the project directory and whether to save the conversation:

```python
from pi_agent.coding import PiClient

with PiClient(cwd=".", no_session=True) as pi:
    print(pi.run("Describe this project without changing files.").text)
```

Leave `no_session` unset to preserve Pi's normal session persistence. Use
`session=` to open an existing session. For model overrides, see
[Models and thinking](#models-and-thinking).

<details>
<summary>More configuration</summary>

See [constructor options][constructor-options] for environment overrides,
executable paths, and deadlines.

Extensions are installed and configured through Pi. To load your own extension,
pass `extra_args=["--extension", "/absolute/path/to/your-extension.ts"]` to
either client. See [using your own extensions][extensions] for details and
[extension UI][ui-example] for an interactive example.

</details>

## Run unattended

For scripts, services, and CI, choose exactly what Pi loads instead of inheriting
your `~/.pi/agent` setup. These helpers are unreleased: install from a checkout
(`python -m pip install -e .`).

```python
from pi_agent import AgentConfig, headless_args
from pi_agent.coding import PiClient

models = {"providers": {"local": {
    "baseUrl": "http://127.0.0.1:8000/v1",
    "api": "openai-completions",
    "models": [{"id": "my-model"}],
}}}
auth = {"local": {"type": "api_key", "key": "local"}}

with AgentConfig(models=models, auth=auth) as config:
    with PiClient(
        env=config.env,
        provider="local",
        model="my-model",
        no_session=True,
        extra_args=headless_args(tools=["read", "grep"]),
    ) as pi:
        print(pi.run("Summarise data.csv.").raise_for_incomplete().text)
```

- `AgentConfig` writes your configuration to a private temporary folder. **Pass
  `env=config.env`**, or the client still uses `~/.pi/agent`. The folder is
  deleted when the `with` block ends.
- `headless_args()` loads only the tools, extensions, and skills you name.
- `raise_for_incomplete()` raises if the run ended without a complete answer.

<details>
<summary>What AgentConfig writes and removes</summary>

- Each mapping is written unchanged as `models.json`, `settings.json`, or
  `auth.json`; Pi owns their format. Omitted files are not written, so Pi uses
  its built-in defaults.
- A provider's models appear only once it has a credential: in `auth`, as an
  `apiKey` in `models`, or as an environment variable.
- The folder is private and `auth.json` is owner-only. Values never appear in
  `repr` or errors.
- Everything Pi writes there is deleted on exit, including default session
  files. Use `no_session=True` or `session_dir=` to keep sessions.
- Packages and logins from your own `~/.pi/agent` are not available inside it.
- Combine with other overrides as `env={**config.env, "PATH": path}`.

</details>

<details>
<summary>What headless_args disables</summary>

Discovery of extensions, skills, prompt templates, themes, `AGENTS.md`/`CLAUDE.md`
and project-local files; `SYSTEM.md`/`APPEND_SYSTEM.md` (unless
`prompt_files=True`); MCP; and startup network work. Named extensions and skills
still load. With no `tools`, all tools are off. Pi before 1.3.0 rejects
`--no-mcp`; pass `mcp=True` there.

</details>

See [unattended runs](docs/usage.md#unattended-headless-runs) and
[configure Pi from code](docs/usage.md#configure-pi-from-code) for every option.

## Models and thinking

By default the SDK uses whatever model you already configured in the Pi CLI.
Override it when you construct the client, or switch later on the same client.
Set the model and thinking level **before** `run()` or `stream()`.

Select a model at construction:

```python
from pi_agent.coding import PiClient

with PiClient(provider="openai", model="gpt-5") as pi:
    print(pi.run("Summarise this repo without changing files.").text)
```

Replace the example provider/model ids with ones from your Pi install
(`pi --list-models` or `get_available_models()`).

<details>
<summary>Query and set thinking levels</summary>

Thinking levels depend on the current model. Query them, set one, then confirm
what Pi actually applied:

```python
from pi_agent.coding import PiClient

with PiClient() as pi:
    levels = pi.get_available_thinking_levels()
    print("available:", levels)
    if "high" in levels:
        pi.set_thinking_level("high")
    print("effective:", pi.get_state()["thinkingLevel"])
    print(pi.run("Analyse this project's architecture without changing files.").text)
```

</details>

<details>
<summary>List models and switch after start</summary>

```python
from pi_agent.coding import PiClient

with PiClient() as pi:
    for model in pi.get_available_models():
        print(model["provider"], model["id"])
    selected = pi.set_model("openai", "gpt-5")
    print("using", selected["provider"], selected["id"])
    print(pi.run("Summarise this repo without changing files.").text)
```

</details>

## RPC access

The SDK speaks Pi's existing JSONL protocol over stdin/stdout:

```text
Your Python application
    PiClient / AsyncPiClient
        pi --mode rpc
            Models · tools · extensions · sessions
```

Inspect session state without starting a model run:

```python
from pi_agent.coding import PiClient

with PiClient() as pi:
    state = pi.get_state()
    print(state["sessionId"])
```

<details>
<summary>Which interface to use</summary>

| You need | Use |
| --- | --- |
| A completed conversation result | `run()` |
| Events while a conversation runs | `stream()` |
| Prompt acknowledgement and your own event handling | `prompt()` with `events()` |
| Session events through the next settlement | `prompt_and_wait()` or `collect_events()` |
| Every event without retaining history | `on_event(callback)` |
| A specific Pi operation | `get_state()`, `set_model()`, `fork()`, and other command methods |
| A raw command response envelope | `request()` |

Python arguments use `snake_case`; wire dictionaries retain Pi's `camelCase`
fields. `prompt()` acknowledges submission, which may be handled entirely by an
extension. It does not wait for a completed answer.

Each client starts its own Pi subprocess. Use one client per conversation and
wait for each `run()` or stream to finish before starting the next. After using
`prompt()` for your own event handling, use a fresh client for `run()` or
`stream()` so results cannot include delayed events from earlier work.

See [RPC structure][rpc] for the protocol mapping and module layout, and
the [command reference][commands] for every method.

</details>

## Test without a model

`pi_agent.testing.FakePi` lets your tests use the real `PiClient` or
`AsyncPiClient` with scripted replies, without a model, credentials, Node.js,
or network access. This helper is unreleased: install from a checkout containing
this change (`python -m pip install -e .`), rather than the published 0.3.0 package.

```python
from pi_agent.coding import PiClient
from pi_agent.testing import FakePi, FakeReply

with FakePi(["Hello!", FakeReply("cut off", stop_reason="length")]) as fake:
    with PiClient(executable=fake.executable) as pi:
        assert pi.run("Hi").text == "Hello!"
        assert pi.run("Again").stop_reason == "length"
    assert fake.prompts() == ["Hi", "Again"]
```

Each prompt consumes the next reply; an exhausted script or unsupported command
raises `PiCommandError`. Each client starts again from the first reply. The fake
does not simulate tool calls, extension UI, compaction, or session branching.
See the [testing guide](docs/usage.md#test-without-a-model) for reply options,
request recording, and supported commands.

## Pi Durable (experimental)

The source checkout adds Python APIs for the original upstream Durable Harness,
not a Python reimplementation: crash-safe resume, idempotent submissions, and
bounded conversation watches.
It is experimental and Linux/macOS only (Windows unsupported). Both backends
expose synchronous and async clients.

### Durable quick start

**Bring your own host.** From a source checkout, install the Python package and
the pinned host dependencies with Node **22.19+**:

```sh
python -m pip install -e .
npm ci --prefix durable-host --ignore-scripts --no-audit --no-fund
```

The wheel does not bundle or download a host. Pass an explicit `host_command`.
This credential-free example submits work and prints its answer:

```python
from pi_agent.durable import DurableClient

with DurableClient(
    "state.db",
    host_command=["node", "/absolute/path/to/checkout/durable-host/src/host.ts"],
    faux=["Hello from Durable."],
) as durable:
    cid = durable.root(model={"provider": "faux", "modelId": "faux-1"})
    sid = durable.submit(cid, "Hello", request_id="job-1")
    settled = durable.wait(sid)
    print(durable.answer_text(settled))
```

The complete [sync example](https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/examples/durable_sync.py)
and [async example](https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/examples/durable_async.py)
use temporary SQLite storage and need no provider credentials. Both accept
`PI_DURABLE_HOST` as a JSON argv array to override the file-relative host.

<details>
<summary>Namespaces, answer text and unanswered submissions</summary>

```python
from pi_agent.coding import PiClient, AsyncPiClient  # Existing coding-agent clients
from pi_agent.durable import DurableClient, AsyncDurableClient  # Experimental
```

`answer_text(settled)` reads the answer without exposing entry internals. It
expands beyond the default 50-entry window when necessary, returning `None` when
no answer entry is available. Very large history reads can exceed the configured
record-size budget and raise `too_large` rather than silently choosing the wrong
answer. For entries you already fetched, `entry_text(entry)` remains a pure
helper; `settled.answer_id` exposes the opaque answer entry ID.

A missing or unknown model does **not** raise: upstream settles as
`status="unanswered", reason="no_model"`. Check `settled.status` and
`settled.reason` before looking for an answer; unanswered submissions have no
`answer_id`.

</details>

<details>
<summary>Async Durable usage</summary>

The async client exposes the same flow, with awaited methods:

```python
import asyncio

from pi_agent.durable import AsyncDurableClient


async def main() -> None:
    async with AsyncDurableClient(
        "state.db",
        host_command=["node", "/absolute/path/to/checkout/durable-host/src/host.ts"],
        faux=["Hello from async Durable."],
    ) as durable:
        cid = await durable.root(model={"provider": "faux", "modelId": "faux-1"})
        sid = await durable.submit(cid, "Hello", request_id="async-job-1")
        settled = await durable.wait(sid)
        print(await durable.answer_text(settled))


if __name__ == "__main__":
    asyncio.run(main())
```

</details>

<details>
<summary>Real models: Pi CLI logins, Codex and Bedrock</summary>

Omit `faux` for real models. By default Durable uses your Pi CLI configuration
(`~/.pi/agent`: logins such as ChatGPT/Codex, stored keys, custom providers in
`models.json`), like `PiClient`. Pass `models="builtin"` for environment-variable-only
providers. Set `pi_agent_dir` to use a different agent directory; otherwise upstream
honors `PI_CODING_AGENT_DIR` or `~/.pi/agent`.

By default `coding_tools=True` gives the model unattended `read`/`write`/`edit`/`bash`
in the host `cwd`, with the inherited environment. Set `coding_tools=False` to
disable those tools, as these real-model examples do. Credentials/catalogs are
shared with Pi; still choose the root model explicitly rather than relying on
Pi CLI's last-selected model.

For example, configure `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
and `AWS_SESSION_TOKEN` when using temporary AWS credentials, then use Bedrock:

```python
from pi_agent.durable import DurableClient

with DurableClient(
    "bedrock.db",
    host_command=["node", "/absolute/path/to/checkout/durable-host/src/host.ts"],
    coding_tools=False,
) as durable:
    cid = durable.root(
        model={
            "provider": "amazon-bedrock",
            "modelId": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
        }
    )
    sid = durable.submit(cid, "Say hello", request_id="bedrock-1")
    settled = durable.wait(sid)
    if settled.status == "done":
        print(durable.answer_text(settled))
    else:
        print(settled.status, settled.reason)
```

Or use your existing Pi CLI ChatGPT/Codex login with a fresh root:

```python
from pi_agent.durable import DurableClient

with DurableClient(
    "codex.db",
    host_command=["node", "/absolute/path/to/checkout/durable-host/src/host.ts"],
    coding_tools=False,
) as durable:
    cid = durable.root(model={"provider": "openai-codex", "modelId": "gpt-6.1-sol"})
    sid = durable.submit(cid, "Say hello", request_id="codex-1")
    settled = durable.wait(sid)
    if settled.status == "done":
        print(durable.answer_text(settled))
    else:
        print(settled.status, settled.reason)
```

The host delegates credential loading and OAuth refresh to upstream Pi, without
reading or logging credentials itself. Real provider calls may incur charges;
CI uses only faux models and a local HTTP stub, never live providers.

</details>

Use one writer per storage path and retry uncertain submissions only with the
same conversation-scoped request key. See the
[Durable API, failure semantics and host setup](https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/docs/durable.md)
and [credential-free crash recovery example](https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/examples/durable_recovery.py).

## Documentation

| Guide | Contents |
| --- | --- |
| [Usage](docs/usage.md) | Sessions, images, concurrency, events, extension UI, and testing without a model |
| [API reference][api] | Constructors, commands, types, and results |
| [Errors and cancellation][errors] | Deadlines, partial results, cleanup, and recovery |
| [RPC structure][rpc] | How the Python client maps to Pi's protocol |
| [Compatibility][compatibility] | Runtime versions and platform validation |
| [Examples][examples] | Runnable sync, async, streaming, sessions, steering, and UI examples |
| [Release notes][release] | Changes included in 0.3.0 |

Coding-agent examples use your configured Pi and may make provider calls.
Development checks use an isolated local test provider; see
[CONTRIBUTING.md][contributing] for setup and validation commands.

## Further reading

- [Pi Unchained](https://hasc.substack.com/p/pi-unchained) — why this SDK exists
  and how Pi fits into Python workflows.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `pi` not found / launch fails | Ensure the Pi CLI is on `PATH`, or pass `executable=` to the client |
| Version rejected | Upgrade to Pi **0.85.1+**; prefer the tested baseline **1.6.0** |
| No model / auth errors | Run `pi` once and complete provider setup |
| Unexpected file or command changes | Review Pi tool/extension settings before automation |

## Support

- [Open an issue][issues] for bugs, questions, or compatibility reports.
- See [CONTRIBUTING.md][contributing] for local setup and pull requests.
- For security reports, open a [private security advisory][security].

## License

[MIT][license]

[pypi]: https://pypi.org/project/pi-agent-python-sdk/
[release]: https://github.com/cheenulabs/pi-agent-python-sdk/releases/tag/v0.3.0
[metadata]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/pyproject.toml
[license]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/LICENSE
[compatibility]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/docs/compatibility.md
[errors]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/docs/errors.md
[stream-example]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/examples/stream.py
[constructor-options]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/docs/api.md#constructor-options
[extensions]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/docs/usage.md#using-your-own-extensions
[ui-example]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/examples/ui.py
[rpc]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/docs/rpc.md
[commands]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/docs/api.md#all-33-rpc-commands
[usage]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/docs/usage.md
[api]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/docs/api.md
[examples]: https://github.com/cheenulabs/pi-agent-python-sdk/tree/v0.3.0/examples
[contributing]: https://github.com/cheenulabs/pi-agent-python-sdk/blob/v0.3.0/CONTRIBUTING.md
[issues]: https://github.com/cheenulabs/pi-agent-python-sdk/issues
[security]: https://github.com/cheenulabs/pi-agent-python-sdk/security/advisories/new
