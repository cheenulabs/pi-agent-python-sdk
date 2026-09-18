# RPC structure

This SDK is a Python client for Pi's existing RPC protocol. Pi owns the agent
loop, provider calls, tools, extensions, and session storage. Python owns the
child process and exposes command methods, event subscriptions, and completed
run results.

## Relationship to Pi

Pi documents [RPC mode][upstream-rpc] for integrations in other languages and
provides a [TypeScript RPC client][upstream-client]. This package follows the
same subprocess model and command vocabulary. The references here are pinned
to the source used for the **0.85.1** baseline; current upstream may differ.

| Pi protocol | Python interface |
| --- | --- |
| JSONL commands on stdin | Typed command methods or `request()` |
| Responses correlated by `id` | Checked results; command failures raise `PiCommandError` |
| Events on stdout | `events()` subscriptions and `stream()` iterators |
| Wire fields such as `modelId` | `model_id` arguments; returned dictionaries keep wire keys |
| Prompt acceptance followed by events | `prompt()` acknowledgement; `run()` / `stream()` wait for settlement |

Records are split on LF (`\n`); Unicode line separators inside JSON strings do
not delimit records. Responses and events share stdout. Request IDs correlate
command responses, but session events are not generally attributable to a
particular prompt. See [protocol discovery](discovery.md) for the detailed
wire evidence and [the command reference](api.md#all-33-rpc-commands) for coverage.

## Choosing an interface

Start with `run()` for a result or `stream()` for incremental events. These
methods own a conversation until `agent_settled`, handle retries and queued
continuations, and produce a `RunResult`. Context managers clean up the child
process and unfinished owned work.

An extension may start and settle a conversation before acknowledging the prompt.
Stream consumption becomes available on acknowledgement or an observed start;
successful completion still requires both acknowledgement and settlement. These
are separate lifecycle facts. Early exit with an unacknowledged prompt closes Pi
to prevent delayed extension work from escaping ownership.

Use `prompt()` and `events()` when your application owns event handling or an
extension handles a command without starting an agent run. Subscribe before
submitting input to avoid missing early events. Acknowledgement does not mean
completion, and `agent_end` alone does not mean the conversation has settled.

After an unowned `prompt()`, `steer()`, or `follow_up()` submission (including raw
requests), that client rejects later `run()` / `stream()` calls with
`PiRunOwnershipError`. Create a fresh client for owned runs. Steering and
follow-ups within an already owned run remain supported. See
[conversation ownership](usage.md#conversation-ownership-and-results).

`request()` exposes the checked response envelope for raw command access. It
still assigns request IDs and enforces ownership rules. `Event.raw` retains
unknown event fields and types; retaining them does not certify compatibility
with a newer Pi release.

## Module layout

The Python implementation keeps process I/O separate from conversation behavior:

| Module | Responsibility |
| --- | --- |
| [`client.py`](../src/pi_agent/client.py) | Async lifecycle, typed commands, ownership checks, and extension UI dispatch |
| [`_transport.py`](../src/pi_agent/_transport.py) | Subprocess pipes, JSONL framing, request correlation, deadlines, and process cleanup |
| [`_launch.py`](../src/pi_agent/_launch.py) | Executable resolution, version checks, and launch argument validation |
| [`_events.py`](../src/pi_agent/_events.py) | Bounded event subscriptions |
| [`_runs.py`](../src/pi_agent/_runs.py) | Run ownership, settlement, result collection, and cancellation |
| [`_usage.py`](../src/pi_agent/_usage.py) | Usage accumulation from observed assistant messages |
| [`sync.py`](../src/pi_agent/sync.py) | Synchronous calls through the same async client on one background event loop |
| [`types.py`](../src/pi_agent/types.py), [`errors.py`](../src/pi_agent/errors.py) | Typed wire dictionaries, Python results, and explicit failures |

Underscored modules are private implementation details. Applications import
`PiClient` and `AsyncPiClient` from `pi_agent`.

Keep protocol compatibility at the wire and command-method level. Copying Pi's
TypeScript directory structure would not simplify the Python interface. The
existing transport and run modules keep framing, cleanup, and settlement logic
in one place, while the sync client reuses the async implementation. Additional
transport interfaces should follow concrete requirements for another transport.

The core stays focused on RPC. Extension installation, application workflows,
and application-specific observability belong to callers. Changes to supported
commands or payloads need matching types, fixtures, documentation, and coverage;
see [maintenance](maintenance.md).

[upstream-rpc]: https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/rpc.md
[upstream-client]: https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-client.ts
