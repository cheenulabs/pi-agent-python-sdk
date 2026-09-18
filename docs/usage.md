# Using the client

## Conversation ownership and results

Use `run()`/`stream()` for settled work, or `prompt()`/events for low-level
submission. After an unowned `prompt()`, `steer()`, `follow_up()`, or raw prompt
request, that client rejects subsequent owned runs with `PiRunOwnershipError`.
Use a fresh client; neither an idle `get_state()` nor `abort()` proves an
extension cannot start delayed work. Steering/follow-up calls during an already
owned run remain supported. Session events do not carry per-prompt attribution.

`RunResult.text` concatenates the final assistant's text blocks in order without
adding separators. `elapsed_seconds` measures prompt submission through receipt
of `agent_settled`, excluding state preflight and final identity refresh. The
overall run timeout still includes those operations.

Usage accumulates finalized assistant messages incrementally. Derived token
counts are nonnegative integers or unknown (`None`); malformed, negative,
fractional, or missing counts remain unknown for that field. A zero reasoning
count accompanied by thinking content, or reasoning exceeding output, is unknown.
Reasoning is already included in output and total tokens. The raw wire messages
remain available, and no totals include unobserved detached child work.

Start with the [README](../README.md) installation and quickstarts. Both clients
launch their own Pi RPC subprocess and preserve Pi's normal defaults. There is
no runtime installation, authentication flow, or network version lookup in this
library.

## Choose sync or async

Use `PiClient` in a script or synchronous application. It keeps one background
event loop for its lifetime; every command uses the same process and session.
Use `AsyncPiClient` in an application that already runs an event loop. Keep all
calls to an async client on the loop that started it.

Prefer a context manager so exceptions also close the process:

```python
from pi_coding_agent_client import PiClient


def main() -> None:
    with PiClient(cwd=".") as pi:
        result = pi.run("Describe the project without changing files.")
        print(result.text)


if __name__ == "__main__":
    main()
```

Explicit lifecycle methods are `start()` and `close()` for sync, or
`await start()` and `await aclose()` for async. Startup checks the executable's
version and waits for a real `get_state` response. Clients are single-use:
construct a new one after closing, failed startup, or process failure.

## Configure the subprocess

Both constructors accept the same keyword-only options. Omitted model, provider,
session, and discovery settings remain omitted from Pi's command line.

```python
from pi_coding_agent_client import Limits, PiClient


def main() -> None:
    with PiClient(
        cwd=".",
        no_session=True,
        limits=Limits(startup_timeout=60, command_timeout=20),
    ) as pi:
        print(pi.get_state()["sessionId"])


if __name__ == "__main__":
    main()
```

`no_session=True` deliberately disables persistence for that child. Leave it
unset to retain Pi's usual persistence. `provider=` and `model=` are explicit
overrides; there is no provider or model selected by the Python library.

`env` overrides the environment inherited by Pi. A value of `None` removes that
variable. With `inherit_env=False`, supply the complete environment Pi needs,
including an appropriate `PATH` when executable resolution requires it. The
library does not open Pi credential files; Pi can use its normal configuration
and inherited environment.

`executable` can be a path/name or an argument sequence such as
`executable=["node", "/path/to/pi/dist/bundle/cli.js"]`. A sequence is passed
directly, without a shell. A string containing spaces is a single executable
path, not a shell command. On Windows, the known npm shim layout is resolved
through Node; for another layout, pass Node and the CLI file explicitly.

`extra_args` permits Pi discovery options and extension flags, for example
`extra_args=["--extension", "./extensions/example.ts", "--custom-mode=review"]`.
The named file must exist and the extension must understand the custom flag.
Options managed by the constructor, RPC mode overrides, print/help/version
flags, positional prompts, and `@file` startup attachments are rejected. Supply
message images through `images=` instead. See the
[constructor reference](api.md#constructor-options) for session flag conflicts.

## Using your own extensions

Install or write extensions separately and configure them through Pi's normal
configuration, or pass their paths using `extra_args`. The Python package
ships no extensions and does not install, configure, or select them. Both
clients work without extensions or any Cheenulabs code.

For an extension you have already placed at the following example path:

```python
from pi_coding_agent_client import PiClient


def main() -> None:
    with PiClient(
        extra_args=["--extension", "/absolute/path/to/your-extension.ts"],
    ) as pi:
        print(pi.get_state()["sessionId"])


if __name__ == "__main__":
    main()
```

Replace the path with your own file. Pi loads it and owns its behavior; the same
`extra_args` option is available on `AsyncPiClient`. Extension-specific flags
can also be forwarded when supported by that extension.

Use `prompt()` for extension commands that only need an acknowledgement, and
`events()` to observe subsequent protocol events. Use `run()` when the input
starts an agent conversation that will settle. An extension can handle a
command without starting a run, so acknowledgement does not imply a result.
For interactive extensions, configure the client's generic extension UI handler
as described below; application-specific responses remain the caller's choice.

## Acceptance, settlement, and results

`prompt(message, ...)` returns Pi's successful acknowledgement envelope. It does
not assert that an agent started or produced a response. Slash commands and
extension input handlers can consume ordinary text without starting the agent.
Use it when your application controls the event lifecycle or calls a command
that is expected to be handled entirely by an extension.

`run(message, ...)` owns a conversation run and waits for `agent_settled`. It
continues through retries, automatic compaction, and queued continuations that
belong to that run. `agent_end` alone is not treated as settlement. A prompt that
is accepted but produces no observed start before `run_start_timeout` raises
`PiRunStartTimeout` and closes the process to prevent delayed execution. Use
`prompt()` for known handled commands; the client does not guess from a slash
prefix or a period of silence.

`RunResult` contains:

- `text`: text blocks from the final assistant message observed during this run.
- `messages`: finalized `message_end` messages observed during the run.
- `stop_reason`: the final assistant stop reason, or `None` for no assistant message.
- `session`: session identity refreshed when the run completes.
- `elapsed_seconds`: submission-to-settlement time, including continuations.
- `usage`: observed assistant usage, or `None` if no usage was available.

A started run can settle with no assistant message, producing empty text.
The client never substitutes an answer from a previous run. The session snapshot
describes the identity current at completion; extensions can change sessions,
so it does not attribute every event to that same session.

Usage is summed once per finalized assistant message. It is not a billing total:
compaction or provider-side work may be absent. Missing measurements stay
`None`, and reasoning tokens are a subset of output tokens rather than an extra
amount to add. Final `error` and `aborted` stop reasons raise `PiRunError`, whose
`.result` retains partial work. `length`, `pending`, `deferred`, `toolUse`, and
`stop` remain distinguishable. See [errors](errors.md).

## Stream or subscribe to events

`stream()` combines run ownership with a bounded event iterator. Use its context
manager even when breaking early. The synchronous example is in the README;
[examples/stream.py](../examples/stream.py) shows the async form.

Choose one consumption mode:

1. Iterate the stream, then call `result()` for the finalized result.
2. Call `result()` without iterating; it drains events without retaining history.

For an async stream, await `result()`. Calling it while an iterator is active is
an error. After iteration completes, repeated result calls return the cached
result. Results and iteration should be consumed within the client lifecycle.

An `Event` exposes `type`, `text_delta`, and the complete parsed `raw` dictionary.
`text_delta` is `None` for non-text events; an empty string is a valid delta.
Unknown event types and additional fields remain available in `raw`. The library
does not retain or reconstruct every partial assistant message. Pi's serialized
updates contain nine text/thinking/tool-call block variants, not cumulative
`message`/`partial` snapshots; finalized `message_end.message` is authoritative.

`events()` is a separate context-managed subscription to future events. Enter it
before submitting work. It includes extension UI, extension errors, and events
from low-level commands, and does not own or cancel a run by itself. See
[examples/events.py](../examples/events.py) for a concurrent observer.

Subscriptions have count and byte limits. A slow consumer receives
`PiSubscriptionOverflow`; response routing and UI replies continue. Overflow in
the stream that owns a run triggers run cleanup. No subscription means no hidden
event-history buffer. Increase limits when needed, and keep consumers moving.

## Images

Use a base64 string and the image's MIME type in an `ImageContent` dictionary.
The same `images=` argument is accepted by `run`, `stream`, `prompt`, `steer`, and
`follow_up`. The client does not resize images or infer provider support.

```python
import base64
from pathlib import Path

from pi_coding_agent_client import ImageContent, PiClient


def main() -> None:
    image: ImageContent = {
        "type": "image",
        "data": base64.b64encode(Path("diagram.png").read_bytes()).decode("ascii"),
        "mimeType": "image/png",
    }
    with PiClient() as pi:
        print(pi.run("Explain this diagram.", images=[image]).text)


if __name__ == "__main__":
    main()
```

Provide the image file before running this example. The
[image CLI example](../examples/images.py) accepts an explicit path. The encoded
request must fit `max_record_bytes`.

## Sessions

Normal Pi persistence is retained unless explicitly disabled. `pi.session`
exposes the cached `SessionInfo`; `get_state()` refreshes it from Pi. The session
file and name may be absent. Session operations also refresh cached identity;
an ambiguous failed mutation invalidates it rather than retaining stale state.

Use constructor options to select an initial session:

- `session="..."` opens a session selected by Pi's `--session` rules.
- `continue_session=True` passes Pi's continuation option for the chosen cwd.
- `fork_session="..."` passes its startup fork option.
- `session_dir="..."` selects a persistence directory.

Once running, use `new_session()`, `switch_session(session_path)`, `fork(entry_id)`,
or `clone()`. Extension hooks can veto a session change; inspect the returned
`cancelled` flag. A cancelled fork may omit `text`. `get_entries()` returns saved
entries and the nullable leaf ID; `get_tree()` returns their tree structure.
`get_fork_messages()` supplies valid message entry IDs for an in-process fork.

`get_last_assistant_text()` is a session-history query and can return `None`.
It is distinct from `RunResult.text`, which only uses the current run.
[examples/sessions.py](../examples/sessions.py) shows an initial session and its
identity without assuming that a session file is always present.

## Steering, follow-ups, and concurrency

One `run()` or `stream()` owns a client conversation. Another ordinary prompt,
model change, compaction, bash command, or session mutation is rejected with
`PiBusyError` while that owner is active. A run also checks Pi for existing
low-level streaming, compaction, or queued input before submitting its prompt.
Use separate clients for independent work.

State/history reads, `steer`, `follow_up`, `abort`, `clear_queue`, `abort_retry`,
and `abort_bash` remain available during an owned run. A low-level `prompt()` with
`streaming_behavior="steer"` or `"followUp"` is also permitted. Queue modes are
`"one-at-a-time"` and `"all"`.

`steer()` supplies input at Pi's next steering opportunity; `follow_up()` queues
input after the current response. Their acknowledgements do not mean the queued
input has been consumed. Pi decides the precise timing. Avoid scheduling these
after a run has already settled if you expect them to belong to that run. The
[steering example](../examples/steering.py) submits them when it observes a start.

Calling `abort()` directly follows Pi's semantics and does not implicitly clear
the queue. Cancelling an owned run or leaving its stream early first clears
queued work and then aborts. See [cancellation](errors.md#cancellation-and-close)
and [examples/cancellation.py](../examples/cancellation.py).

## Extension UI

Pass `ui_handler=` to either client. It receives the original typed request.
It can be async or synchronous; synchronous handlers run outside the event loop.

| Request method | Handler return |
|---|---|
| `confirm` | `True`, `False`, or `None` to cancel |
| `select`, `input`, `editor` | String value, or `None` to cancel |
| `notify`, `setStatus`, `setWidget`, `setTitle`, `set_editor_text` | No reply; return value ignored |

With no handler, dialogs are cancelled and display requests remain visible to
event subscribers. Handler failures attempt a dialog cancellation and surface
`PiUIHandlerError`. The original exception is available through `__cause__`.
Pi may provide a dialog timeout in milliseconds; the client applies that deadline
to the handler and does not send an acknowledgement-waiting RPC for a UI reply.

Keep handlers short. Do not call blocking `PiClient` methods from a UI callback:
reentrancy is rejected to prevent deadlock. Async callbacks can use the async
client on its loop, subject to normal conversation ownership. They can also close
the client. Python cannot forcibly stop a synchronous callback blocked in user
code; closing the client stops waiting for it, but the callback must eventually
return on its own. Python or an enclosing `asyncio.run()` may still wait for
executor threads during final shutdown.

Outstanding handler work shares the configured event count and byte limits.
Exceeding that budget closes the client with `PiUIHandlerError`, rather than
allowing an extension to create unlimited callback tasks.

[examples/ui.py](../examples/ui.py) supplies a small terminal handler. It renders
dialog choices and notifications; it does not attempt to reproduce Pi's TUI.

## Raw access and diagnostics

`request(command_type, **fields)` is the escape hatch for new or application-level
RPC use. It returns a checked response envelope, assigns the request ID, and
applies the same run-ownership restrictions as named methods. Callers cannot
replace `id` or `type`. It is not a separate transport or a bypass for unsupported
Pi capabilities.

Wire types in `pi_coding_agent_client.types` are `TypedDict`/`Literal` annotations;
nested payloads remain dictionaries with Pi's original field spelling. They
describe the known protocol rather than recursively converting provider data.

Standard result/event reprs avoid printing their payloads, and command errors do
not automatically include Pi's error text. Explicit fields such as `.raw`,
`.messages`, `.error`, model headers, and handler exception causes may contain
application data. Diagnostic stderr retention is off by default. Enable a bounded
tail with `Limits(stderr_tail_bytes=...)` and inspect `pi.stderr_tail` explicitly
when troubleshooting your own process.
