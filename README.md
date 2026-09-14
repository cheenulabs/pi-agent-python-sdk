# Pi coding agent Python client

Use [Pi coding agent](https://github.com/earendil-works/pi) from Python, with
synchronous and asynchronous clients, streamed events, and typed access to its
RPC commands. Pi remains the runtime: it loads its usual models, authentication,
tools, extensions, skills, and project configuration.

The library owns a `pi --mode rpc` subprocess. It has no third-party Python
runtime dependencies and does nothing on import.

**Development preview: not yet published to PyPI.** The initial protocol baseline
is Pi **0.85.1**. Python **3.11+** is required. Linux has local validation;
macOS and Windows are test targets awaiting platform verification. See
[compatibility][compatibility] for the exact policy.

## Install from source

Install Pi separately using Node.js **22.19.0 or newer**:

```sh
npm install -g @earendil-works/pi-coding-agent@0.85.1
pi --version
```

Configure Pi normally and make sure it can run with your selected provider.
The Python package does not install Pi, manage credentials, or download a model.
Then install this checkout in your Python environment:

```sh
git clone https://github.com/cheenulabs/pi-coding-agent-python-client.git
cd pi-coding-agent-python-client
python -m pip install .
```

The distribution name is `pi-coding-agent-client`; the import name is
`pi_coding_agent_client`. A PyPI installation command will be added when a release
has actually been published.

## Get a result

```python
from pi_coding_agent_client import PiClient


def main() -> None:
    with PiClient() as pi:
        result = pi.run("Explain the current project without changing files.")
        print(result.text)


if __name__ == "__main__":
    main()
```

Use `AsyncPiClient` inside an async application:

```python
import asyncio

from pi_coding_agent_client import AsyncPiClient


async def main() -> None:
    async with AsyncPiClient() as pi:
        result = await pi.run("Explain the current project without changing files.")
        print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
```

`run()` waits for `agent_settled`, including Pi's retry and queued-continuation
behavior. The lower-level `prompt()` waits only for an acknowledgement: an
extension can handle a prompt without starting an agent run.

## Stream a response

```python
from pi_coding_agent_client import PiClient


def main() -> None:
    with PiClient() as pi:
        with pi.stream("Explain this project's entry points without editing files.") as stream:
            for event in stream:
                if event.text_delta is not None:
                    print(event.text_delta, end="", flush=True)
            result = stream.result()
        print(f"\nStop reason: {result.stop_reason}")


if __name__ == "__main__":
    main()
```

Keep the stream inside its context. Leaving early cancels owned work by clearing
queued input and aborting Pi. Finalized messages, session identity, elapsed time,
and observed assistant usage are available on `RunResult`.

## What is covered

- All 33 Pi RPC commands, including model selection, sessions, compaction, bash,
  steering, follow-ups, and state reads.
- Synchronous and asynchronous APIs with the same command arguments and results.
- Bounded event subscriptions, raw event dictionaries, and extension UI handlers.
- Checked command failures, process cleanup, configurable deadlines, and partial
  results on a final model error or abortion.

One client owns one conversation at a time. Use separate clients for independent
conversations. The library cannot attach to an existing Pi terminal session or
add capabilities that Pi's RPC protocol does not expose.

## Documentation and examples

- [Usage][usage]: configuration, sessions, images, concurrency, and UI.
- [API reference][api]: every command, constructor option, and result type.
- [Errors and cancellation][errors]: deadlines, cleanup, and recovery.
- [Compatibility][compatibility]: Python, Pi versions, and platform scope.
- [Runnable examples][examples]: sync, async, streaming, images, sessions, steering,
  events, UI, and cancellation. They use your normal Pi installation and may make
  provider calls when you run them.
- [Protocol discovery][discovery]: pinned upstream evidence and wire details.

For development commands and test setup, see [CONTRIBUTING.md][contributing].
The [plan][plan] and [implementation record][implementation] track work
remaining before release. Maintainers can follow the
[update process][maintenance] and [release checklist][releasing].
The package is [MIT licensed][license].

[usage]: https://github.com/cheenulabs/pi-coding-agent-python-client/blob/main/docs/usage.md
[api]: https://github.com/cheenulabs/pi-coding-agent-python-client/blob/main/docs/api.md
[errors]: https://github.com/cheenulabs/pi-coding-agent-python-client/blob/main/docs/errors.md
[compatibility]: https://github.com/cheenulabs/pi-coding-agent-python-client/blob/main/docs/compatibility.md
[examples]: https://github.com/cheenulabs/pi-coding-agent-python-client/tree/main/examples
[discovery]: https://github.com/cheenulabs/pi-coding-agent-python-client/blob/main/docs/discovery.md
[contributing]: https://github.com/cheenulabs/pi-coding-agent-python-client/blob/main/CONTRIBUTING.md
[plan]: https://github.com/cheenulabs/pi-coding-agent-python-client/blob/main/PLAN.md
[implementation]: https://github.com/cheenulabs/pi-coding-agent-python-client/blob/main/docs/implementation.md
[maintenance]: https://github.com/cheenulabs/pi-coding-agent-python-client/blob/main/docs/maintenance.md
[releasing]: https://github.com/cheenulabs/pi-coding-agent-python-client/blob/main/docs/releasing.md
[license]: https://github.com/cheenulabs/pi-coding-agent-python-client/blob/main/LICENSE
