# Compatibility

For installation, see the [README](../README.md). Compatibility claims below
distinguish the recorded protocol baseline from platform test targets.

Check the proposed commit's CI results before relying on platform support.

## Runtime requirements

| Component | Policy |
|---|---|
| Python | Package requires 3.11 or newer; Linux CI targets 3.11, 3.12, 3.13, and 3.14 |
| Pi | Minimum **0.85.1**; recorded tested protocol version **0.86.0** |
| Node.js | Pi 0.86.0 requires **22.19.0 or newer** |
| Python runtime dependencies | None beyond the standard library |
| Platforms | CI targets Linux with Python 3.11–3.14; macOS and Windows with Python 3.14 |

Python's open-ended `>=3.11` metadata does not assert that every future Python
version has passed tests. Similarly, successfully launching an untested Pi
version is not a compatibility certification.

The pinned Pi source is commit
[`ecac0a9c4edad3dac5d9f8b40e0c7db7a56471fc`](https://github.com/earendil-works/pi/tree/ecac0a9c4edad3dac5d9f8b40e0c7db7a56471fc).
The [discovery document](discovery.md) records the upstream types, serializer,
implementation, and observed runtime behavior used to build the client. The
package wraps Pi's RPC protocol and is not an official upstream Python SDK.

Pi 0.86.0 adds system transcript messages, session usage entries, compaction
system snapshots, and model prompt-cache metadata. These remain wire dictionaries;
Python does not replay system messages or implement cache warming. The optional
`addedToolNames` annotation remains for Pi 0.85.1 tool results. Session statistics
may include cache-warming usage; `RunResult.usage` still summarizes only observed
assistant messages. CI also exercises the minimum version on Linux.

## Startup version policy

Startup invokes the selected executable with `--version`; it does not contact npm,
PyPI, GitHub, or another version service. After startup:

| Selected executable | Behavior |
|---|---|
| Recognized version below 0.85.1 | Reject with `PiVersionError` |
| Exactly 0.86.0 | `pi_version="0.86.0"`, `compatibility="tested"` |
| Other recognized version at or above the minimum | Allow by default, with `compatibility="untested"` |
| Recognized untested version and `strict_version=True` | Reject with `PiVersionError` |
| Unparseable/custom version output | Reject unless `allow_unknown_version=True` |
| Explicit unknown-version override | `pi_version=None`, `compatibility="unknown"` |

Before startup, compatibility is `"unchecked"`. The unknown-version option is an
explicit override for custom executables and also permits unknown output when
strict checking is enabled. It does not allow a recognized version below the
minimum. Version output must be a plain numeric `major.minor.patch` string;
prerelease suffixes and custom banners are treated as unknown.

Strict checking can be useful when an application requires the recorded Pi
baseline. Applications that accept newer versions should inspect compatibility
and run their own integration checks before depending on new behavior.

## Runtime ownership and defaults

Pi must be installed separately. The client never silently installs, downloads,
or upgrades it. It also does not load credentials into Python models, implement
provider authentication, install extensions, or replace Pi's configuration.
Normal Pi configuration and environment inheritance remain in effect unless the
caller supplies overrides.

Each client owns a new `pi --mode rpc` subprocess. It cannot attach to a running
Pi terminal UI, and selecting an existing session file is different from
attaching to another process. The protocol has no general capability/version RPC,
shutdown command, session-listing RPC, tree-navigation RPC, or arbitrary
register-tool RPC. The Python client does not invent these capabilities.

## Windows executable resolution

Pi's known npm `.cmd`/`.bat` shim layout is resolved to Node and the installed Pi
CLI file without using a shell. If your package manager uses another layout,
provide the actual paths explicitly:

```python
from pi_agent import PiClient


def main() -> None:
    # Replace both paths with the locations in your installation.
    with PiClient(executable=["node", "C:/path/to/pi/dist/bundle/cli.js"]) as pi:
        print(pi.get_state()["sessionId"])


if __name__ == "__main__":
    main()
```

This launch support does not substitute for testing Windows process cancellation,
pipes, or Pi's own tool prerequisites. The current verification scope remains
the platform table above.

## New protocol fields and events

Typed dictionaries describe the known wire surface. Unknown event types and
additional fields remain accessible through `Event.raw`; provider metadata stays
ordinary JSON-compatible data. The client does not discard those fields or
reconstruct a parallel assistant state machine.

Forward access to raw fields does not guarantee semantic compatibility. A future
Pi change to command results, event ordering, settlement, or UI behavior may need
a client update. Use `request()` for raw command access while retaining checked
responses and ownership restrictions, not to bypass them.

## Compatibility validation

Tests separate deterministic synthetic-process behavior from integration with a
real Pi installation. Real integration tests use a local faux provider and
isolated temporary config/projects, so they need no external credentials or
provider calls. Model-backed smoke tests must be explicitly enabled.

The compatibility gates cover command mappings, wire omissions, extension UI,
sessions, retries and compaction, streaming settlement, and cancellation.
See [CONTRIBUTING.md](../CONTRIBUTING.md) for validation commands and the
[integration setup](../tests/integration/README.md) for fixture configuration.
Automated latest-stable checks run in CI, not during package import or startup.
The [maintenance guide](maintenance.md) describes upstream protocol review,
and the [release checklist](releasing.md) records publication requirements.

## TypeScript-style observation helpers

Version 0.2.0 adds `on_event`, `collect_events`, `wait_for_idle`, and
`prompt_and_wait`, following the pinned TypeScript client's listener and
settlement pattern. Python uses `Event` carriers with unchanged wire dictionaries
at `.raw`, plus a blocking facade delegating to the async client. Collection is
session-wide and does not infer prompt ownership. These helpers are not available in 0.1.0.

Intentional differences remain: bounded retention and backlog, checked command
failures, surfaced callback errors, single-use process lifecycle, and opt-in
stderr forwarding/retention. Version 0.2.0 matches TS object returns for thinking-level cycling and
HTML export, and returns `None` from `prompt()`. Session mutations do not trigger
hidden state queries. See the [migration from 0.1.0](api.md#migrating-from-010).
`run()`, `stream()`, and `RunResult` remain intentional Python conveniences.
Their [ownership and cleanup rules](rpc.md#internal-design-assessment) protect
result attribution without changing the shared command/event protocol.

## TypeScript behavior contract

The [pinned TS client](https://github.com/earendil-works/pi/blob/ecac0a9c4edad3dac5d9f8b40e0c7db7a56471fc/packages/coding-agent/src/modes/rpc/rpc-client.ts)
is the comparison reference. All 33 command wrappers have Python equivalents;
the [command table](api.md#all-33-rpc-commands) records wire arguments and results.
Current source matches TS object results for thinking-level cycling and HTML
export, and its void prompt result. Session mutation commands issue no implicit
state refresh. The [migration guide](api.md#migrating-from-010) describes the changes from
0.1.0. The retained `run()`/`stream()` interface is additional Python
behavior, assessed in [#50](https://github.com/cheenulabs/pi-agent-python-sdk/issues/50).

Normal event delivery preserves every emitted wire field, including thinking,
tool results, usage, extension errors/UI, and unknown future fields. `text_delta`
is a convenience accessor, not the complete event stream. Collection observes
session-wide future events through `agent_settled`; neither client can attribute
those events to a particular prompt or produce provider traces Pi did not emit.

| Area | Deliberate Python behavior |
| --- | --- |
| Language interface | Snake-case names, keyword arguments, deadlines in seconds, async context managers, and a blocking facade over the same core |
| Completed results | `run()` and `stream().result()` provide current-operation text, finalized messages, usage, and session identity; TS settlement helpers return events |
| Owned-stream cleanup | Leaving a stream early clears/aborts accepted work or closes uncertain work. Observation-helper cancellation only stops local waiting; TS has no matching owned-stream API |
| Event carrier | `Event.raw` retains the wire dictionary; no second event representation or derived run result is added by collection |
| Command options | `streaming_behavior` and `exclude_from_context` expose existing RPC fields absent from TS convenience methods |
| Failed acknowledgement | All Python commands raise on `success=False`, including void methods; TS only checks methods that extract response data |
| Listener failure/mutation | Failures reach the loop exception handler without skipping other listeners; payload copies and defined add/remove ordering prevent mutation from changing another listener's delivery |
| Retention | Record bytes, subscription backlog, collected history and optional stderr retention are bounded; TS collection/stderr histories are unbounded |
| Deadline | Python's helper deadline includes ACK plus settlement; TS's collector timer ends at settlement, even with ACK outstanding |
| Long commands | `bash`, `compact`, `new_session`, `switch_session`, `fork`, `clone`, and `export_html` have no default Python response deadline; TS uses 30 seconds. Explicit Python deadlines and finite write limits remain available |
| Cancellation/terminal failure | Observation cancellation does not abort submitted work after a completed write. Interrupted writes can still close Pi for transport integrity; terminal failures wake collectors |
| Responses vs events | Late/duplicate response envelopes stay in `observe(rpc=True)` rather than agent listeners; TS dispatches unmatched responses to listeners |
| Framing | Valid LF/CRLF, fragmented UTF-8, Unicode separators, and final complete records work. Python rejects malformed UTF-8/JSON/envelopes; raw stdout remains explicitly observable |
| Lifecycle | Python checks version and readiness, reaps its child, and uses a fresh client for restart; TS uses a short startup delay and allows another start after stop |
| Diagnostics | Explicit output observation and opt-in bounded stderr tail; TS automatically forwards and accumulates stderr and embeds it in errors |
| Generic UI | Python provides handler replies and default dialog cancellation. TS delivers UI requests without a reply policy. Extensions and application behavior remain outside the SDK |

Do not copy TS's mutable-listener-array bug: removing a collector during
settlement dispatch can skip the next collector. Python intentionally lets
independent collectors and idle waiters complete on the same settlement.
The [TS dispatch/helpers](https://github.com/earendil-works/pi/blob/ecac0a9c4edad3dac5d9f8b40e0c7db7a56471fc/packages/coding-agent/src/modes/rpc/rpc-client.ts#L464)
and [JSONL implementation](https://github.com/earendil-works/pi/blob/ecac0a9c4edad3dac5d9f8b40e0c7db7a56471fc/packages/coding-agent/src/modes/rpc/jsonl.ts)
are the source for these distinctions.

## Repeatable comparison and regression coverage

After the locked development and `tests/pi` installations:

```sh
uv run python scripts/check_parity.py
uv run python -m build
uv run python scripts/check_distribution.py --parity
```

This checks the installed Pi version and embedded TS source hashes against
`compatibility.json`, then runs the actual TS client and both Python clients
against the same synthetic subprocess. It compares 42 cases spanning all 33
commands, including null cycles, omitted arguments, empty values, and false
flags. A 39-record corpus covers all 25 declared session/extension event types,
the nine serialized assistant update variants, and unknown metadata. Returned
payloads, request sequences, event order, and both listeners must match.
No client methods are patched, and no provider or live Pi configuration is used.
The command cases exercise wire construction/results, not a real model's command
semantics; isolated real-Pi integration supplies that complementary coverage.

`check_distribution.py --parity` installs the built wheel into a fresh virtual
environment outside the checkout and runs the same checker with Python's `-I`
isolation. It verifies that `pi_agent` is imported from that environment. Both
facades also exercise completed runs, streaming results, empty output after a
prior answer, listeners, settlement helpers, and changed command results. This
uses the locked Node fixture, not a provider or published package index. Omit
`--parity` for the package smoke checks alone when Node is unavailable.

| Contract | Existing or focused coverage |
| --- | --- |
| Complete results, raw receipts, no hidden mutation requests | `tests/test_command_results.py`, `tests/integration/test_commands.py`, and installed-wheel checks |
| Common TS commands and complete event corpus | `scripts/check_parity.py`, `tests/fixtures/rpc_parity.json`, shared peer under `tests/pi` |
| Concurrent collectors, safe registration, delayed ACK deadline, listener behavior | `tests/test_collections.py` |
| Finite 100/1,000/5,000-event delivery and ACK ordering | `tests/test_collections.py`, `tests/test_bursts.py`, `tests/test_preack_runs.py` |
| Timeout/cancel, bounded writes, strict framing, response correlation, child cleanup | `tests/test_transport.py` |
| Raw output, stderr, failed/late envelopes and completeness/loss | `tests/test_rpc_observation.py`, `tests/test_process_output.py`, `tests/test_terminal_events.py` |
| Generic UI, causes, dialog deadlines | `tests/test_client.py`, `tests/test_ui_deadlines.py`, isolated integration |
| Retained result/stream semantics, usage/session identity, empty/error runs, retries/follow-ups | `tests/test_client.py`, `tests/test_preack_runs.py`, `tests/integration/test_runs.py`, and installed-wheel convenience checks |
| Escaped surrogate send/receive, UI replies and encoded-byte limits | `tests/test_outbound_strings.py`, `tests/test_collections.py` |

CI runs both checkout and installed-wheel comparisons on the pinned runtime for
each supported Python/OS row. The installed-wheel convenience checks run there too.
Older-runtime compatibility rows, when present, use their integration tests
rather than comparing an unreviewed TS implementation. Preserve this coverage
when simplifying internals; rerun on the final candidate and installed wheel,
including both retained convenience calls and protocol helpers.
[#45](https://github.com/cheenulabs/pi-agent-python-sdk/issues/45) tracks that
validation; [#41](https://github.com/cheenulabs/pi-agent-python-sdk/issues/41)
tracks release and Cheenulabs adoption. A green source branch is not proof that
adoption or a published release is complete.
