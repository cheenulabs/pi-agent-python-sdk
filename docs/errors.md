# Errors, deadlines, and cancellation

The client never automatically replays a command. A timeout or broken pipe can
leave uncertainty about whether Pi accepted work. High-level runs have an owned
cleanup policy; lower-level requests retain Pi's explicit control semantics.

## Exception reference

All library exceptions derive from `PiError` and are exported from the package.

| Exception | Meaning and useful fields |
|---|---|
| `PiCommandError` | Pi returned `success=False`; inspect `command`, `request_id`, and explicit `.error` text |
| `PiProtocolError` | Invalid UTF-8/JSON, malformed envelope/payload, oversized inbound record, or response mismatch |
| `PiProcessError` | Missing/unstartable process, process exit, closed client, or broken transport; optional `returncode` |
| `PiTimeoutError` | A deadline elapsed; also derives from Python `TimeoutError`; `command`, `request_id`, and `uncertain` describe available context |
| `PiRunStartTimeout` | Accepted prompt produced no observed agent start before its deadline; derives from `PiTimeoutError` and closes Pi |
| `PiBusyError` | Competing owned run, incompatible command, or simultaneous stream consumption modes |
| `PiSubscriptionOverflow` | An event consumer exceeded its count or byte budget |
| `PiResultOverflow` | An owned run or settlement collection exceeded its independent retained count/byte limit; only owned runs perform owned cleanup |
| `PiRunOwnershipError` | Prior low-level conversation submission prevents owned-run attribution; derives from `PiBusyError`, requires a fresh client |
| `PiUIHandlerError` | UI handler failure or outstanding-handler budget exceeded; callback failures retain their cause |
| `PiRunError` | Final assistant stopped with `error` or `aborted`; `.result` contains partial work |
| `PiVersionError` | Unsupported or unrecognized Pi version under the selected compatibility policy |

Invalid constructor flags, invalid deadlines, or an outbound record above the
configured size limit raise `ValueError`. Misusing single-use contexts or calling
blocking methods from a UI or event callback raises `RuntimeError`. Application task
cancellation remains `asyncio.CancelledError`; synchronous Ctrl-C remains
`KeyboardInterrupt` after cleanup.

Input rejected locally before a write (for example, an oversized record or
non-JSON value) does not claim the conversation or close a healthy client.
Correct the input and retry. This does not undo any earlier real submission:
the existing ownership restriction still applies after low-level conversation
work may have reached Pi.

Exception messages avoid automatically dumping wire payloads. Pi's command error
text is explicitly available as `.error`, while a handler's original exception
is in `__cause__`. Those fields can contain application data. Transport failure
usually requires a new client; command rejection alone does not necessarily
close the process.

Stream context entry can precede prompt acknowledgement when an extension starts
work before returning. A late command rejection is therefore raised by iteration
or `result()`; observed events alone never establish a successful result. Rejection
after an observed start closes Pi conservatively, even if settlement was observed.

Owned runs and the synchronous facade preserve the callback's original cause,
including an existing nested cause. Internal cancellation used to stop an owned
run does not replace it. Once the owner reports a UI failure, that same error is
not reported again as a failure of an otherwise successful cleanup command.

## Settlement helpers

`collect_events()`, `wait_for_idle()`, and `prompt_and_wait()` cancel local waits
on timeout, cancellation, or collection overflow. They do not abort Pi, clear
queues, or close a healthy process. A standalone observation timeout has
`uncertain=False` because the helper submitted no command; a prompt timeout may
have submitted work and has `uncertain=True`. There is no automatic retry.
Successful settlement does not override a later prompt rejection. The helper
deadline still applies while waiting for that acknowledgement. Cancellation
after a completed write only abandons local waits; an interrupted or partially
performed write can close Pi because transport delivery is uncertain.
`prompt_and_wait()` preserves UI handler error causes. Model failure remains in
raw events and is not converted into `PiRunError`.

Event listener exceptions go to asyncio's exception handler and delivery
continues. Extension UI handlers retain their existing reply and failure rules.
See [the helper contract](api.md#listeners-and-settlement-helpers).

## Partial results and stop reasons

```python
from pi_agent import PiClient, PiRunError


def main() -> None:
    with PiClient() as pi:
        try:
            result = pi.run("Summarize this project without changing files.")
        except PiRunError as error:
            print(f"Run ended with {error.result.stop_reason}")
            print(error.result.text)
        else:
            print(result.text)


if __name__ == "__main__":
    main()
```

A recovered retry error remains an event. `PiRunError` is based on the final
assistant message at settlement, not every intermediate error message.

| Final stop reason | High-level behavior |
|---|---|
| `stop` | Return the result |
| `length` | Return the result with this reason preserved; text may be truncated |
| `toolUse` | Return the result with this reason preserved |
| `pending` | Return the result with this reason preserved; do not assume a complete answer |
| `deferred` | Return the result with this reason preserved; no automatic provider polling |
| `error` | Raise `PiRunError` with the partial result |
| `aborted` | Raise `PiRunError` with the partial result |
| No assistant message | Return empty text and `stop_reason=None` for a run that started and settled |

An accepted prompt that never starts is a separate failure, not an empty answer.
`get_last_assistant_text()` queries history and is never used as a fallback for
the current run.

## Deadlines

All configured deadlines use seconds. The UI protocol's optional handler timeout
is supplied by Pi in milliseconds and converted internally.

Caller-supplied numeric deadlines must be positive and finite. Invalid types,
booleans, and integers too large for the timer raise `ValueError`. Where allowed,
`None` disables that particular deadline; configured `Limits` require numbers.

Expiry of that UI deadline cancels the dialog, following Pi's normal default
response, and does not itself fail an owned run. It is distinct from a callback
that raises `TimeoutError` independently, an overall run deadline, or caller
cancellation. A handler that returns after its deadline cannot supply a late
answer; synchronous callback threads still have the shutdown limitations below.

| Operation | Omitted deadline | Explicit `None` |
|---|---|---|
| Short RPC command response | `Limits.command_timeout`, initially 30 seconds | No response deadline |
| Long RPC command response | No fixed deadline | No response deadline |
| Entire `run()` / `stream()` | No fixed deadline | No run deadline |
| Run's `command_timeout` | Configured prompt-response default | No prompt-response deadline |

Long commands are `bash`, `compact`, `new_session`, `switch_session`, `fork`,
`clone`, and `export_html`. Numeric values override the defaults. Startup,
expected-run-start, writes, and cleanup retain their separately configured
limits; passing `timeout=None` to a command does not disable them.

Every write is bounded by `Limits.command_timeout`, including time waiting for
the serialization lock. The response deadline starts after the write completes.
Consequently `get_state(timeout=2)` can spend time waiting to write before its
two-second response window begins. A run's overall `timeout` includes its state
preflight, prompt acknowledgement, execution, retries, and final state refresh.
Cleanup can take additional time after a deadline expires.

For example, `pi.bash("...", timeout=60)` bounds the command response;
`pi.run("...", timeout=120, command_timeout=10)` bounds the whole run and uses
a separate ten-second acknowledgement deadline.

## Uncertain outcomes

`PiTimeoutError.uncertain=True` means work may have taken effect. A completed write
followed by no response is uncertain; the library abandons that response wait and
does not pretend to undo the operation. Late replies do not complete another
request. A partial or interrupted write invalidates the transport and closes it.

For a low-level `request()` or `prompt()` timeout, choose explicitly whether to
read state, abort, clear queued work, or close the client. Do not blindly retry a
session mutation or a tool-producing prompt: the original could already have
changed state. A timeout while mutating session identity invalidates the cached
identity until an authoritative refresh succeeds.

For `run()` or `stream()`, the client owns cleanup: it clears queued input and
aborts unfinished work, closing the child if cleanup cannot establish a safe end.

`PiRunStartTimeout` specifically means the prompt was acknowledged but no agent
start was observed. A slash command, input handler, or another extension may have
handled it. The client closes the child so queued or delayed work cannot begin
after the caller treats the run as failed. Use low-level `prompt()` for commands
that intentionally do not start an agent.

## Cancellation and close

Cancelling an async `run()` task or leaving an owned stream early clears queued
input and then sends `abort`. Ownership is held until cleanup finishes. If
cleanup fails or exceeds its bound, the client closes Pi. Synchronous Ctrl-C
cancels the corresponding async operation and waits for its actual task cleanup
before re-raising `KeyboardInterrupt`.

If the prompt has not yet been acknowledged, early exit or cancellation closes
the child instead: `abort` cannot establish that extension preflight or deferred
input cannot start later. Entering a stream after observing `agent_start` is not
proof that acknowledgement has arrived.

Direct `abort()` preserves Pi's protocol behavior: it does not implicitly call
`clear_queue()`. Similarly, cancelling a raw request only abandons its response
wait; explicitly abort or close if that low-level work must stop. A run preflight
failure before prompt submission does not cancel someone else's low-level work.

Close wakes pending operations and event consumers, closes stdin, gives the
child a bounded graceful exit period, and escalates to terminate/kill if needed.
The owned process is reaped; repeated close is safe. The synchronous facade also
stops and joins its persistent loop thread. This is not a guarantee to control
arbitrary descendants launched by third-party extensions.

A synchronous UI handler blocked in user code cannot be forcibly stopped by
Python. Client shutdown stops waiting for it, but the worker can continue until
the handler returns; Python or an enclosing `asyncio.run()` can still wait for
executor threads during final shutdown. Keep callbacks bounded and do not call blocking client
methods from them. Async UI callbacks run on the client loop and may await its
`aclose()`.

## Buffer overflow

Finalized run messages have independent `Limits.result_message_count` (4096)
and `Limits.result_message_bytes` (64 MiB) bounds. Bytes count serialized
`message_end` records, not Python object heap usage. A fast event consumer cannot
bypass these bounds. Exceeding either raises `PiResultOverflow` and performs
owned cancellation/cleanup; it never silently returns a truncated result.

An independent `events()` subscription that falls behind fails explicitly with
`PiSubscriptionOverflow`; it does not stall Pi's response routing. If the
overflowing subscription belongs to an owned stream, run cleanup is triggered.
Increasing count and byte limits can accommodate bursts, but does not replace a
consumer that keeps up.

A healthy subscription retains events already accepted before a terminal process,
protocol, or handler failure. Read those events in FIFO order, then iteration
raises the original failure; pending requests and process cleanup do not wait
for this drain. Overflow instead fails immediately and discards that subscriber's
unread queue, because delivery is already incomplete. Explicit subscription close
always discards unread events and its stored error, then ends iteration normally.

Outstanding UI-handler tasks are also bounded by the configured count and byte
limits. Exceeding this budget raises `PiUIHandlerError` through the transport's
failure path and closes the child. Handler exceptions normally attempt a dialog
cancellation and surface the error without treating every extension error event
as a fatal model failure.

## Troubleshooting

- **Executable not found:** verify Pi is installed and visible on the child `PATH`,
  or pass an executable path/argument sequence.
- **Version rejected:** inspect `pi --version` for the selected executable and read
  the [compatibility policy](compatibility.md). Custom wrappers need an explicit
  unknown-version override; recognized older versions remain rejected.
- **No agent start:** check whether the command is handled by an extension and
  belongs on `prompt()` instead of `run()`.
- **Busy:** wait for the active owned run, use a supported steering/control method,
  or create another client for an independent conversation.
- **UI handler failure:** inspect its cause and return the right dialog value type.
- **Protocol failure:** check that the selected executable really runs Pi RPC and
  that extensions do not write non-protocol text to stdout.

The library does not automatically retain stderr. For explicit diagnostics,
construct with `Limits(stderr_tail_bytes=8192)` and inspect `pi.stderr_tail`.
The tail is bounded and is not attached automatically to exceptions.

Pre-start event subscriptions terminate on version, spawn, or readiness failure
with that failure after their queued events. Cancelling startup still raises
`CancelledError` to its caller; observers receive `PiProcessError`. Closing before
startup also wakes observers with `PiProcessError` and launches no process. The
blocking client permits draining terminal queues after its loop has stopped.

Process observers use the same independent count/byte budgets as event queues.
Overflow raises `PiSubscriptionOverflow` immediately, marks `status.lost=True`
and `complete=False`, and unregisters only that observer. Process failures instead
allow buffered output to drain and iteration ends normally; inspect `status.error`
for the primary failure. Shutdown drains both pipes for at most `cleanup_timeout`
after the child exits before releasing inherited pipe handles. If EOF was not
observed before forced pipe closure, the affected EOF flag is false and observers selecting that pipe have
`complete=False`.
Observation failure cannot replace the primary command/run failure.

Parsed RPC observation reports valid JSON objects before envelope validation.
Invalid envelopes are observable and still fail the RPC client. After that first
failure, cleanup parsing cannot replace its exception or resume RPC routing.
Raw output continues through bounded cleanup. Observe `.status.error` after the
iterator ends, including when `start()` failed. No process was successfully
observed if version checking or spawn failed, so completion remains false.
