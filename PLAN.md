# Pi Coding Agent Python Client — Revised Plan

Status: discovery completed on 2026-09-15; implementation in progress.
Evidence: [Discovery findings](docs/discovery.md).

Build a small public Python interface to an existing Pi installation.
One async core serves `AsyncPiClient` and the blocking `PiClient`.
Pi owns models, authentication, tools, extensions, agent execution, and sessions.
Implementation, commits, pull requests, reviews, and merges are now authorized
by the implementation goal. Migrating existing applications and changing live
services remain outside this package's scope.

## 0. Discovery outcome and changes to the proposal

The inspected baseline and npm latest stable are both Pi **0.85.1**, commit
`d981de1229ef899957bbe968bc8dcda02a21f477`. The existing Python client was
located in the remote cheenulabs repository and compared with its tests and
an application caller. Findings, complete coverage tables, pinned sources,
and the limits of the checks are in [discovery.md](docs/discovery.md).

Material revisions:

- Cover all **33 RPC commands**, **23 session event types**, two additional
  RPC record types (`extension_error`, `extension_ui_request`), **12 nested
  assistant event variants** (nine normally emitted block updates), and **9
  extension UI methods**.
- Follow the TypeScript client's naming and concepts, but use the runtime
  and wire serializer to resolve incomplete declarations and documentation.
- Keep submission and settled-run helpers distinct. Extensions can consume
  ordinary input without starting a run; slash-command detection alone
  cannot solve completion.
- Use typed dictionaries for nested wire payloads and small dataclasses for
  conveniences. Avoid a parallel hierarchy of runtime model converters.
- Retain readiness checks, session identity, elapsed time, and honest usage
  accounting from the existing Python client. Keep its application policy,
  goal-extension heuristics, and tracing integrations outside this package.
- Use Dependabot's npm support for the actual test-only Pi dependency,
  alongside Python and GitHub Actions updates. No custom PR-writing bot.

## 1. Scope, installation, and compatibility

Provisional distribution: `pi-coding-agent-client`.
Import: `pi_coding_agent_client`. Its PyPI JSON endpoint returned 404 during
discovery; that is not a reservation. Recheck before publication.

Users install/configure Pi separately, then install this library. Entering a
client context starts an owned `pi --mode rpc` process. Importing the module
does no work. This transport cannot attach to an already-running terminal
session.

Defaults inherit normal Pi configuration and environment. Omitted provider,
model, tool, extension, and persistence options remain omitted. The library
does not read or rewrite Pi credentials or silently install/upgrade Pi.

Initial support target:

- Python 3.11–3.14; expand when new stable versions pass CI.
- Linux, macOS, Windows, verified by real platform tests before claiming support.
- Pi 0.85.1 as the initial minimum and recorded tested version. Later stable
  releases enter the tested set through compatibility checks.
- Zero third-party runtime dependencies. Use pytest, pytest-asyncio, Ruff,
  mypy, build, and Hatchling as development/build tools.
- Recommend MIT license with upstream attribution if public upstream code is
  adapted. Implement generic behavior independently of private code.

Version checking occurs at startup using the selected executable's version.
Reject older-than-minimum versions clearly. For newer untested versions,
expose compatibility status and an opt-in strict check; do not imply they
have been verified. Unparseable custom executable versions require an
explicit override. No network lookup at runtime.

## 2. Public interface

### Normal use

```python
from pi_coding_agent_client import PiClient

with PiClient(cwd="./project") as pi:
    result = pi.run("Explain this project.")
    print(result.text)
    result = pi.run("Where should we add tests?")
```

```python
import asyncio
from pi_coding_agent_client import AsyncPiClient

async def main():
    async with AsyncPiClient(cwd="./project") as pi:
        result = await pi.run("Explain this project.")
        print(result.text)

asyncio.run(main())
```

### Streaming

```python
import asyncio
from pi_coding_agent_client import AsyncPiClient

async def main():
    async with AsyncPiClient(cwd="./project") as pi:
        async with pi.stream("Explain this project.") as stream:
            async for event in stream:
                if event.text_delta is not None:
                    print(event.text_delta, end="", flush=True)
            result = await stream.result()

asyncio.run(main())
```

The synchronous equivalent uses `with pi.stream(...)`, `for event in stream`,
and `stream.result()`. Calling `result()` while actively iterating the same
stream is an error; after iteration, it returns the cached result.
Calling it instead of iterating drains events without retaining them.

### Submission and event access

- `prompt(message, *, images=None, streaming_behavior=None, timeout=...)`
  waits for the command response only. It returns an acceptance receipt.
- `run(...)` and `stream(...)` expect an agent run and wait for settlement.
- `events()` is a context-managed subscription established on entry, usable
  before `prompt()`, `bash()`, or state changes. It exposes future events,
  including extension errors and display requests, without implicit history.
- Explicit methods cover every row of the discovery command table. Preserve
  meaningful response values such as `cancelled`, nullable results, and
  fork text.
- `request(command_type, **fields)` returns a raw checked response as an
  escape hatch. The library assigns IDs; callers cannot replace envelope
  fields. This uses the same validation and ownership rules as typed methods.
- `start()`, `close()`/`aclose()`, `running`, `busy`, and current session
  identity support explicit lifecycle use.

Constructor options: executable, cwd, provider, model, environment overrides,
session selection/persistence options, additional Pi arguments, UI handler,
and a small limits/timeouts configuration. Validate conflicting session flags
and reject extra arguments that override RPC mode or introduce startup prompts.
Use keyword-only options and omit unset fields on the wire.

## 3. Types and result semantics

- Use `TypedDict` and `Literal` for documented wire records, with Pi's original
  field spelling. Nested payloads stay ordinary dictionaries.
- Use a small `Event` dataclass containing the raw record plus `type` and
  `text_delta` conveniences. Unknown event types/fields remain accessible.
- Use `RunResult`, `SessionInfo`, and a small usage summary dataclass.
  Results contain final assistant text, finalized messages from this run,
  stop reason, session identity snapshot, elapsed seconds, and optional usage.
- Build results from `message_end` records observed within the owned run;
  never substitute a previous session answer when no assistant message appeared.
- Streaming forwards deltas directly. Do not reconstruct every partial
  message; finalized `message_end.message` is authoritative.
- Sum usage once per finalized assistant message, not per cumulative delta.
  Describe this as observed assistant usage, not total billing: compaction
  and provider-side work may not be fully represented. Missing measurements
  stay unknown; reasoning counts are not added to output a second time.
- Preserve all stop reasons. Final `error`/`aborted` raises a run exception
  carrying partial result information; recovered retry errors remain events.
  `length`, `pending`, and `deferred` must remain distinguishable and must
  not be presented as a guaranteed complete textual answer.
- Empty results are valid when a started run settles without an assistant
  response; distinguish them from a run that never started.

Validate envelopes and fields used by helpers at runtime. Do not recursively
reject valid new provider metadata merely because our type annotations lag.
Treat model metadata and raw messages as potentially sensitive in repr/logging.
Account for verified declaration/runtime differences: normalize missing or
null last-assistant text to None, and allow omitted fork text on a veto.

## 4. Small module structure

```text
src/pi_coding_agent_client/
    __init__.py       # Public exports
    client.py         # Async methods, subscriptions, run ownership/results
    _transport.py     # Subprocess, framing, response routing, shutdown
    sync.py           # Blocking facade over the async client
    types.py          # Wire types and small public dataclasses
    errors.py         # Public exceptions
    py.typed
tests/
    fake_pi.py
    test_transport.py
    test_client.py
    test_sync.py
    integration/
    pi/              # Private npm manifest/lock for the test runtime
examples/
docs/
pyproject.toml
README.md
LICENSE
CONTRIBUTING.md
CHANGELOG.md
.github/
```

Keep command methods explicit and short. Start without transport plugins,
a schema generator, an event bus framework, or a class for every command.
The private subprocess seam also permits testing through a fake executable.
Split a growing file only when that makes review easier.

## 5. Transport and failure behavior

One reader owns stdout; one task drains stderr; a lock serializes writes.
Register each pending request before writing and resolve it by ID and command.
A failed response always raises `PiCommandError`, including void commands.

Framing: UTF-8, LF only, optional trailing CR; preserve Unicode separators.
Allow a final complete JSON record at EOF as upstream does, then report process
closure to remaining operations. Reject malformed/incomplete records and
non-object envelopes. Ignore empty lines. Bound individual record size and
validate output JSON rather than silently swallowing parser errors.

Proposed defaults, centralized and configurable:

| Limit | Initial proposal |
|---|---|
| Startup/version/readiness | 30 seconds |
| Short command response | 30 seconds |
| Long commands: bash, compact, session fork/switch/export | No fixed execution deadline unless supplied |
| Overall run | No deadline unless supplied |
| Waiting for an expected agent run after acceptance | 30 seconds |
| Shutdown/abort cleanup | 5 seconds before escalation |
| Record size | 16 MiB |
| Each event subscription | 256 records and 16 MiB total |
| Diagnostic stderr retention | Off by default; bounded opt-in tail |

A slow subscription must never block response routing or extension replies.
Overflow fails that subscription explicitly. If it owns a run, trigger its
cancellation policy. Inactive subscriptions do not cause hidden history growth.
Consumers that require all events must keep up or select larger limits.

Unknown response IDs and duplicates are handled separately from events;
late responses never complete a different request. Uncorrelated protocol
errors are surfaced. Partial-write failures invalidate and close the transport.
A response timeout after a complete write reports an uncertain outcome, never
replays a command, and does not silently pretend the operation was cancelled.

EOF, reader failure, and process exit wake all pending calls, subscriptions,
and run waiters. Close is idempotent; close stdin, allow bounded graceful
shutdown, then terminate/kill/reap the owned process as needed. Test
platform-specific process and pipe behavior, including Windows launch shims.
Do not promise control over arbitrary descendants spawned by third-party extensions.

## 6. Run ownership, cancellation, and extension interaction

One high-level run owns the conversation at a time. Separate clients provide
independent concurrent conversations. Permit steering, follow-ups, abort,
state reads, and UI responses while a run is active. Reject competing ordinary
prompts, session/model/thinking changes, and manual compaction during an owned
run; the lower-level submission interface exposes normal upstream behavior
when no high-level run owns the session.

Register before submission; account for events before the acknowledgement.
Wait through retries and queued continuations until `agent_settled`.
A successful acknowledgement alone is never a completed run.

**No-start ambiguity:** an extension command or input handler may acknowledge
without starting work, or schedule work later. `run()`/`stream()` therefore
have a configurable start deadline after acceptance. If no start was observed,
raise `PiRunStartTimeout` with acceptance status and close the owned process
to prevent delayed work escaping the failed call. Do not label this a known
successful no-op. Applications using handled commands use `prompt()` and
`events()`; no fixed grace-period completion heuristic or command allowlist.

An overall timeout includes preflight/UI handling. Record start events that
arrive before acceptance. UI callbacks can require longer command timeouts;
document overrides rather than silently extending deadlines.

Public `abort()` preserves upstream semantics; queue clearing is explicit.
For cancellation of an owned run (task cancellation, stream context exit,
run timeout, sync Ctrl-C), clear its queued work and abort with bounded cleanup.
Hold ownership until cleanup completes. Close the client if the outcome
remains uncertain. Direct low-level request cancellation only abandons that
response wait; callers must explicitly abort state-changing work.

Offer one optional UI handler. The reader dispatches handlers independently
and continues processing output; dialog responses use their original IDs and
expect no command acknowledgement. Unhandled dialogs send cancellation and
remain visible as events. Notifications/status/widgets/titles/editor-text
updates are forwarded without inventing a terminal UI.

Handler exceptions send cancellation and surface a dedicated handler error.
Run synchronous handlers outside the event-loop thread; document that Python
cannot forcibly stop a blocked callback thread. Give late replies no effect
after closure, and reject reentrant calls from synchronous handlers to avoid
deadlocks. Do not treat every extension error as a fatal model error; expose
it even when the associated prompt acknowledgement succeeds.

Refresh identity after successful new/switch/fork/clone operations. On an
uncertain outcome invalidate cached identity; do not attribute later results
to stale session state. Extensions can change sessions internally, so refresh
state before finalizing a result and define its session snapshot as the session
current at completion; do not claim every event is attributable to that ID.
No implicit session changes or retries.

## 7. Synchronous facade

Implement after the async core is validated. One persistent background event
loop per `PiClient` owns all async objects and subprocess I/O. Synchronous
methods submit work safely to that loop and block for the corresponding result.

Mirror methods, return values, exceptions, context managers, and streaming.
Test Ctrl-C, timeouts, concurrent abort/close, repeated close, failed startup,
iteration exit, and callback failures. Avoid `asyncio.run()` per method and
a second protocol implementation. Recommend `AsyncPiClient` inside async apps.

## 8. Tests and compatibility gates

Follow the evidence-to-test table in [discovery.md](docs/discovery.md).
Three test layers:

1. A deterministic fake executable tests fragmented/coalesced bytes, Unicode,
   large records, invalid JSON/envelopes, unknown and duplicate IDs, response
   errors, blocked/partial writes, process failure, cancellation, and overflow.
2. Real Pi integration uses temporary config/projects and synthetic extensions
   and a faux provider. Cover all 33 command mappings, session persistence,
   cancellation/veto, event shapes, retry/compaction settlement, dialogs,
   handled input, and command errors. No external credentials or model calls.
3. Opt-in model-backed smoke tests cover real prompt/tool/stream behavior;
   never auto-enable merely because an environment contains a credential.

Run identical user-visible scenarios through async and sync clients.
Use explicit fixture coordination instead of arbitrary timing sleeps.
Validate nullable/omitted fields, new fields/events, all stop reasons, and
unknown usage. Test built wheels from outside the checkout.

CI: Python 3.11–3.14 on Linux; newest supported Python on macOS/Windows.
Add Windows event-loop and executable resolution coverage. Run minimum Pi and
recorded current Pi integration jobs; collapse them when versions are equal.
Use Ruff, mypy, tests, package build, and metadata checks as required checks.
Do not declare untested OS/version combinations supported.

## 9. Documentation and comments

Write docs with each milestone. Public docstrings explain behavior, values,
exceptions, and relevant ordering/ownership rules. Comments explain why
non-obvious logic exists; avoid repeating the code or mandatory boilerplate
on every trivial function.

README: prerequisites, installation, sync/async quickstarts, existing Pi setup,
and links to compatibility and detailed usage. Include runnable examples for
streaming, steering/follow-ups, cancellation, images, saved sessions, dialogs,
and lower-level submission.

Keep guides in Markdown. Document limits, no-start ambiguity, errors,
callback constraints, stop reasons, platform setup, and coverage. Explain
which Pi TUI features are unavailable in RPC. Keep application output
validation, tracing integrations, and credential management outside the client.
Use generic, self-contained examples; never export private fixtures or settings.

## 10. Review milestones and first release

| Milestone | Deliverable and acceptance gate |
|---|---|
| 1. Foundation | Package/types/errors plus owned subprocess; readiness, framing, routing, and failure tests pass |
| 2. Protocol coverage | All discovery command/event/UI rows mapped; omission/null semantics and real Pi command checks pass |
| 3. Run/stream behavior | Ownership, no-start policy, results, retries, cancellation, and buffering scenarios pass |
| 4. Sync interface | Public behavior parity, thread lifecycle, Ctrl-C and callback tests pass |
| 5. Public package | Documentation examples, three-OS CI, clean wheel/sdist install and content inspection pass |
| 6. Release setup | Dependabot and compatibility workflows ready, TestPyPI rehearsal, then reviewed 0.1.0 release |

Each milestone should be a small reviewable change with tests and docs.
Do not implement the next layer merely to hide an unresolved behavior below it.
Use one version source; explicit package inclusion prevents development fixtures,
private data, and the test npm runtime entering distributions.

Before release, finalize name/license, ensure GitHub and PyPI metadata link to
the actual public client repository, set required checks, and configure
GitHub Release-triggered PyPI Trusted Publishing with an approval environment.
Build artifacts once, validate them, and publish those exact artifacts.
This is future authorized release work, not part of the discovery task.

## 11. Dependabot and latest Pi maintenance

- Use a private `tests/pi/package.json` with exact
  `@earendil-works/pi-coding-agent` dev dependency and committed npm lockfile.
  CI installs that runtime; Python consumers never install it as a dependency.
- Configure Dependabot daily for this npm dependency and weekly for Python
  development/build dependencies and GitHub Actions; enable applicable
  security updates. Its Pi bump PR is the compatibility PR.
- Daily and manual compatibility jobs resolve npm latest stable, record the
  exact version/commit, install it into disposable CI storage, and run the
  integration suite independently of the recorded pin.
- Compare the pinned command/event/type/serializer sources against the new
  release, including changelog changes. Flag drift even if existing tests
  pass; maintainers update types, fixtures, coverage and the tested-version
  record deliberately. No automatic generation that silently blesses changes.
- Attach results to the version PR. Failures stay visible and block merging.
  Avoid duplicate custom update PRs. Keep write permissions in the metadata/
  reporting job; untrusted pull-request test jobs receive no publishing credentials.
- Scheduled workflows can be delayed or disabled after inactivity in public
  repositories. Document checking their health and manual dispatch; never
  promise instantaneous compatibility with unseen releases.
- Release fixes promptly once validated. A compatible upstream release may
  require only updated tested-version documentation, not a Python package bump.
  User runtime upgrades remain explicit.

Sources: [Dependabot](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference),
[scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule),
[packaging](https://packaging.python.org/en/latest/tutorials/packaging-projects/),
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/).
