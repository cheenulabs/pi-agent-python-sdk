# RPC structure

This SDK is a Python client for Pi's existing RPC protocol. Pi owns the agent
loop, provider calls, tools, extensions, and session storage. Python owns the
child process and exposes command methods, event subscriptions, and completed
run results.

## Relationship to Pi

Pi documents [RPC mode][upstream-rpc] for integrations in other languages and
provides a [TypeScript RPC client][upstream-client]. This package follows the
same subprocess model and command vocabulary. The references here are pinned
to the source used for the **0.86.0** baseline; current upstream may differ.

| Pi protocol | Python interface |
| --- | --- |
| JSONL commands on stdin | Typed command methods or `request()` |
| Responses correlated by `id` | Checked results; command failures raise `PiCommandError` |
| Original process output and all parsed objects | Opt-in `observe()`; caller owns storage |
| Events on stdout | `events()` subscriptions and `stream()` iterators |
| Wire fields such as `modelId` | `model_id` arguments; returned dictionaries keep wire keys |
| Prompt acceptance followed by events | `prompt()` acknowledgement; `run()` / `stream()` wait for settlement |

Outbound strings preserve JSON-escaped lone UTF-16 surrogate code units,
including values sent back through UI replies. Record limits count the encoded
bytes after escaping. Ordinary Unicode remains UTF-8.

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
extension handles a command without starting an agent run. Subscriptions may enter before `start()` to include extension startup events.
Subscribe before submitting input to avoid missing early events. Acknowledgement does not mean
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

## Output bursts and backpressure

`run()` collects finalized messages without buffering progress events. The
independent result count and byte limits still apply. `stream()`, `events()`,
and `observe()` retain bounded queues and raise `PiSubscriptionOverflow` when
consumers fall behind; an observer's overflow does not abort unrelated RPC work.

The reader yields between records and pauses for 1 ms after each 64 records to
give both async consumers and the blocking caller thread execution time. This
adds scheduling overhead (including roughly 16 ms per 1,000 records before OS
timer overhead); it is not an unlimited-throughput or lossless-storage guarantee.
Responses and extension UI tasks can run during these pauses. Consumers that
perform slow work should move that work out of their iteration loop and choose
explicit storage and capacity policies in their application.

Blocking iterators transfer all already-buffered records per thread crossing,
without waiting to fill a batch. This avoids leaving a backlog solely because
each crossing takes time. Each iterator can retain that additional batch,
bounded by both its configured queue byte and count limits. The queue can refill
while the caller consumes the batch, so total buffered payload can reach twice
those limits. Overflow discards the batch and remains explicit; ordinary
terminal failures deliver the buffered prefix first. Closing a context releases
its batch, and discarding unconsumed observation records marks coverage as lost.

## Internal design assessment

The retained public contract is `run()` returning `RunResult`, context-managed
streaming with `result()`, and equivalent async calls. Command and observation
helpers remain available. The following decisions address
[#50](https://github.com/cheenulabs/pi-agent-python-sdk/issues/50); fewer internal
fields alone would not make that contract simpler or safer.

| Mechanism | Decision | Correctness purpose and caller cost |
| --- | --- | --- |
| `_owner` and conflicting-command gate | Keep | Prevent overlapping results and session/model changes during a run. Callers wait for completion; reads, steering, and cancellation remain available. |
| `_unowned_submission` | Keep | An idle state or ACK cannot rule out delayed extension work. After low-level submission, use a fresh client for results; repeated protocol helpers remain supported. |
| Run preflight and final state reads | Keep | Reject existing streaming/compaction/queued input; capture identity after extension session changes. Two extra reads per successful run, included in its overall deadline. |
| Cached `session` snapshot | Keep | Supports existing session/result metadata. Session mutations invalidate it; an explicit `get_state()` refreshes it without hidden mutation-time queries. |
| Separate ACK, start, and settlement state | Keep | Events can precede ACK, and rejection can follow settlement. Streaming can begin early, but success requires checked ACK and settlement. |
| Run versus collection cleanup | Keep distinct | Stream exit cancels owned work or closes uncertain work; cancelling an observation helper only stops local observation. Combining them would change caller control. |
| Bounded result and event storage | Keep distinct | `run()` retains finalized messages without buffering progress; streaming and collectors have separate budgets. Callers get explicit overflow instead of partial success. |
| Async implementation and blocking facade | Keep | Share protocol/result behavior; blocking iteration and interruption still need thread coordination. No additional public wrapper. |
| Positive finite deadline checks | Simplify | One private validator serves limits, commands, runs, and collectors. Invalid types and unrepresentable integers raise `ValueError`; defaults and `None` policies stay with each caller. |
| Repeated deadline predicates | Remove | Replace four copies of the same policy with that validator; add public async/blocking regressions proving invalid deadlines leave the client usable. |

The existing regressions exercise these boundaries in `test_client.py`,
`test_preack_runs.py`, `test_collections.py`, and isolated Pi integration,
including delayed extension input, pre-ACK settlement, retries, follow-ups,
empty/error results, session changes, and cleanup. `test_deadline_validation.py`
covers the shared validation change. The [compatibility contract](compatibility.md#typescript-behavior-contract)
records the command/event comparison and remaining intentional differences.

Current examples already use completed results, streaming, session snapshots,
steering, and independent observations. The
[Cheenulabs smoke caller](https://github.com/cheenulabs/cheenulabs/blob/065f144601903266823eb39e9f591ca6f8ab13f7/pi-agent/tests/smoke_rpc.py)
likewise reads text, usage, elapsed time, and session identity across sequential
calls. Its existing `PiRpcSession.prompt()` waits for results, whereas this SDK's
`prompt()` only acknowledges input: ordinary result callers must use `run()`.
Its [extension tests](https://github.com/cheenulabs/cheenulabs/blob/065f144601903266823eb39e9f591ca6f8ab13f7/pi-agent/tests/test_rpc.py)
also synthesize results for handled goal commands. Those application rules,
capture formats, and tracing stay in Cheenulabs; they are not SDK result semantics.
Adoption remains separate work under
[#41](https://github.com/cheenulabs/pi-agent-python-sdk/issues/41), using this
package directly rather than adding an SDK adapter.

## Module layout

The Python implementation keeps process I/O separate from conversation behavior:

| Module | Responsibility |
| --- | --- |
| [`client.py`](../src/pi_agent/client.py) | Async lifecycle, typed commands, ownership checks, and extension UI dispatch |
| [`_transport.py`](../src/pi_agent/_transport.py) | Subprocess pipes, JSONL framing, request correlation, deadlines, and process cleanup |
| [`_launch.py`](../src/pi_agent/_launch.py) | Executable resolution, version checks, and launch argument validation |
| [`_events.py`](../src/pi_agent/_events.py) | Shared bounded subscriptions and event specialization |
| [`_observation.py`](../src/pi_agent/_observation.py) | Process output records and delivery status |
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

[upstream-rpc]: https://github.com/earendil-works/pi/blob/ecac0a9c4edad3dac5d9f8b40e0c7db7a56471fc/packages/coding-agent/docs/rpc.md
[upstream-client]: https://github.com/earendil-works/pi/blob/ecac0a9c4edad3dac5d9f8b40e0c7db7a56471fc/packages/coding-agent/src/modes/rpc/rpc-client.ts

## Settlement collection

`_collections.py` drains an existing event subscription through the next
`agent_settled`, with independent finite aggregate limits. Registration happens
before the returned task runs. `prompt_and_wait()` starts that collector before
sending and awaits both collection and acknowledgement. Blocking helpers use the
same async implementation. This path creates no run owner and makes no implicit
abort or queue-clear decisions.

`on_event()` uses the existing dispatch path with synchronous callbacks. Each
listener receives a separate JSON dictionary so mutation cannot alter subsequent
routing. Callback failures go to the loop exception handler; no worker pool or
second event bus is involved. See the [public contract](api.md#listeners-and-settlement-helpers).
