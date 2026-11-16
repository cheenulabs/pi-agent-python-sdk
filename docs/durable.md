# Experimental Pi Durable backend design

**M1 implements the experimental Node host's core protocol** in `host/`.
**M2 adds the coding namespace, error codes, and shared child environment helper.**
**M3 adds `pi_agent.durable.AsyncDurableClient`** with async lifecycle, root,
submit, wait, entries, and abort, built on the shared transport and limits.
**M4 extracts the shared synchronous lifecycle and subscription bridge** without
changing coding-agent behavior. **M5 adds `DurableClient`**, delegating its core
methods to `AsyncDurableClient` on that bridge. **M6 adds async and synchronous
watch**, including bounded subscriptions, snapshots, entry diffs and explicit gaps.
The protocol and API follow sections 5, 6, 8, and 9 of [#116]. The milestone plan and acceptance
criteria remain in that issue. Each milestone is a separate PR; start the next
only after the previous PR is approved and merged, unless explicitly requested
as a stacked PR targeting the previous milestone's branch. Before a stack merges,
restack onto `main` after its base merges and rerun checks. The owner approved Q1 (scope, including M2) and Q2 (shared sync bridge and sync
Durable client) in [the updated instruction][owner-decisions]. Q3 uses
caller-supplied `host_command` (skip M9); Q4 is Linux/macOS only, Windows
unsupported, with `durable` left out of `required.needs`. The current delivery
is an unmerged stack followed by one combined PR for owner review. Nothing is
to be merged, auto-merged, published, or released by this work.

[owner-decisions]: https://github.com/cheenulabs/pi-agent-python-sdk/issues/116#issuecomment-6902908994

## Bring your own host (M9 skipped)

Q3 selected an explicit caller-supplied `host_command`. Neither wheel nor sdist
includes the host or its npm dependencies, and the SDK never downloads them.
From the source checkout, install Node ≥22.19 and the Python package, then:

```sh
npm ci --prefix host --ignore-scripts --no-audit --no-fund
```

Pass `host_command=["node", "/absolute/path/to/checkout/host/src/host.ts"]` to
`AsyncDurableClient` or `DurableClient`. `host_command=None` raises
`PiProcessError` explaining the prerequisites. Keep the pinned checkout and its
`host/node_modules` together; Node's built-in type stripping runs `host.ts`
directly, without a build step. Linux and macOS are supported targets; Windows
Durable v0 is unsupported.

Run the credential-free [recovery example](../examples/durable_recovery.py):

```sh
uv run python examples/durable_recovery.py
uv run python scripts/check_examples.py --durable
```

It creates temporary SQLite storage, kills a faux run's host, and reopens the
same submission key. It requires no Pi coding-agent CLI or model credentials.
The example defaults to the host path relative to its own file. To use another
host, set `PI_DURABLE_HOST` to a JSON argv array, for example
`["node", "/absolute/path/to/host.ts"]`. The checker always overrides that with
the checkout's isolated host. The default example-check mode still runs only
coding-agent examples; `--durable` runs only Durable examples.

For local host development:

```sh
npm ci --prefix host --ignore-scripts --no-audit --no-fund
npm run --prefix host typecheck
npm test --prefix host
PI_DURABLE_REQUIRE_INTEGRATION=1 uv run pytest tests/durable
node host/src/host.ts
```

The host accepts JSONL on stdin and shuts down on EOF. M1 supports `hello`,
`open`, `root`, `submit`, `wait`, `entries`, and `abort`, with memory or SQLite
storage and pinned upstream 1.5.2. M6 adds `watch`/`unwatch` and their events. The host is not bundled in
the Python wheel or sdist. The separate `durable` CI matrix covers Linux/macOS
and Python 3.11/3.14 on Node 22, and is not a required merge gate. The owner
explicitly chose to leave it out of `required.needs` (Q4); Windows Durable v0 is
unsupported. `TESTED_PI_DURABLE_VERSION` and `compatibility.json` record 1.5.2.
M8's `scripts/check_durable.py` checks all three manifest/lock pins and that
constant; coding-agent `--record` preserves the independent Durable record.
The Latest Pi workflow uploads a non-blocking npm-latest drift report, and
Dependabot groups the three `/host` upstream packages.

The experimental `pi_agent.durable` drives the real upstream
[`@earendil-works/pi-durable` Harness][upstream], not a port. Python and the host
must not implement agent, storage, or recovery logic. Existing `PiClient` and
`AsyncPiClient` behavior stays unchanged. The only public API additions outside
`pi_agent.durable` are the optional `PiCommandError.code` attribute and the
`pi_agent.coding` module, which re-exports the existing clients (both M2).
No existing module or class is moved or renamed.

Pin `@earendil-works/pi-durable`, `@earendil-works/pi-ai`, and
`@earendil-works/chord` to published **1.5.2**, matching upstream commit
`b4afdddf44e059c67ccf5097e5317d913521b470`. Do not use unreleased main APIs.
Signals, TS extension loading, Python-defined tools, custom tasks, code mode,
compaction controls, forks, multi-client attach, remote transports, and a
`run()` convenience call are out of scope. This differs from Python ports such
as [pi-durable-python](https://github.com/arpesenti/pi-durable-python) and
[pi-py](https://github.com/nivalume/pi-py): it trades a Node prerequisite for
upstream fidelity rather than reimplementing the engine.

## Read the answer text

`wait()` returns the upstream settlement record, not an assistant message.
`settled.answer_id` is the opaque answer entry ID from `settled.raw["answer"]`,
or `None` when no answer is present. Match that ID in `entries()` and use the
read-only `entry_text(entry)` helper:

```python
from pi_agent.durable import entry_text

# Inside an AsyncDurableClient context, after submit() returned sid:
settled = await client.wait(sid)
if settled.status == "done":
    entries = await client.entries(cid)
    answer = next((e for e in entries if e["id"] == settled.answer_id), None)
    if answer is None:
        raise LookupError("Answer is outside this entries window; increase limit")
    print(entry_text(answer))
else:
    print(settled.status, settled.reason)
```

The synchronous client uses the same pattern without `await`. `entries()`
returns the newest 50 entries by default: request a larger `limit` within your
record-size budget for an older answer. Do not assume the last assistant entry
belongs to the submission you waited for. `entry_text()` joins string content
and text blocks in model-message order, ignores thinking/images/tool calls and
unknown or malformed parts, and returns `""` if there is no text. Neither helper
modifies entries or the preserved raw record.

A missing or unknown model settles as **`status="unanswered", reason="no_model"`**
rather than raising. Check both fields before looking up an answer.

## Use a real model

Without `faux`, the host uses pi-ai `builtinModels()` with provider environment
variables. For example, configure standard AWS credentials (`AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN` for temporary credentials), plus
`AWS_REGION` and access to the chosen Bedrock model, then run:

```python
from pi_agent.durable import DurableClient, entry_text

with DurableClient(
    "bedrock.db",
    host_command=["node", "/absolute/path/to/checkout/host/src/host.ts"],
) as client:
    cid = client.root(
        model={
            "provider": "amazon-bedrock",
            "modelId": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
        }
    )
    sid = client.submit(cid, "Say hello", request_id="bedrock-1")
    settled = client.wait(sid)
    if settled.status == "done":
        answer = next(e for e in client.entries(cid) if e["id"] == settled.answer_id)
        print(entry_text(answer))
    else:
        print(settled.status, settled.reason)
```

The default `inherit_env=True` passes provider environment variables to the
host. When disabling inheritance, provide the required variables explicitly
through `env`. Durable **does not read Pi CLI logins** from
`~/.pi/agent/auth.json`, including OAuth logins; configure provider credentials
separately. Selecting a missing/unknown model returns `unanswered/no_model`.
Real provider calls may incur charges. CI and all Durable examples/tests use
faux; no live-provider tests are enabled automatically.

## Troubleshooting

- **Host exits during startup:** check the explicit `host_command` path, Node
  ≥22.19, and `npm ci --prefix host` in the matching checkout. The SDK reports
  these hints as `PiProcessError`, without attaching stderr.
- **Need host diagnostics:** opt in with `limits=Limits(stderr_tail_bytes=8192)`
  (import `Limits` from `pi_agent`) and inspect `client.stderr_tail` after the
  failure. Retention is disabled by default. Inspect it locally: stderr may
  contain application data and must not be copied into shared logs or reports.
- **No answer:** inspect `settled.status` and `settled.reason`; `no_model` is an
  upstream settlement, not a Python exception. Select an available provider/model
  explicitly, and configure its environment credentials rather than Pi CLI auth.
- **Relative working directory:** constructor `cwd` is resolved once at startup,
  used for the host and as the default agent directory. A `root(cwd=...)` override
  remains relative to the host directory when you supply a relative value.
- **Cancelled close:** cleanup is shielded from caller cancellation. A subsequent
  `await client.aclose()` joins the same teardown; keep the owning event loop
  alive until it completes.

## Design decisions

1. **Thin-host rule.** `host/` translates protocol commands to upstream calls.
   It may keep **protocol bookkeeping only**: a lifecycle state (not open /
   opening / open / closing), the open harness, the configured record-size
   limit, watch handles by watch ID, and the last entry ID sent per watch.
   It has no retries, caching, agent logic, or durable state of its own. Any
   other state needs a written exception in this document.
2. **Share the core, add only what is new.** Use the existing `Transport`,
   `Limits`, `_Subscription`, error classes, and approved sync bridge described
   below. Add no second transport, new error classes, or separate timeout arguments.
3. **SDK transport envelope, not a Pi RPC server.** The host uses the framing
   `Transport` already implements for Pi RPC. It implements none of Pi's
   commands; the RPC parity inventory in [compatibility](compatibility.md) does
   not apply to it. An envelope change must update the host in the same PR;
   bump the host `protocol` on any breaking change.
4. **Experimental and isolated, one way.** Durable code lives in
   `src/pi_agent/durable/` and is not imported by `pi_agent/__init__.py`.
   Durable depends on the core; the core never imports durable. Host and
   integration tests run in a separate `durable` CI job that stays out of
   `required.needs` until the owner promotes it. Pure-Python durable unit tests
   (fake host) run in the existing required `test` matrix. M2/M4 core changes
   ship in coding-agent releases, so use separate PRs that pass every existing
   test unmodified.
5. **Runtime dependencies stay zero.** Keep `pyproject.toml`'s
   `dependencies = []`. Node ≥ 22.19 is required only for `pi_agent.durable`.
6. **Single writer.** One host owns one storage path; upstream has no
   cross-process locking. Concurrent clients on one storage are out of scope.
7. **Idempotency is the caller's key.** `submit` requires a non-empty string
   `request_id`, scoped to the conversation. Resubmitting the same key after
   any crash returns the same submission.
8. **Pinned upstream.** Use the exact published pins above and commit
   `host/package-lock.json`. Check API names against the installed package's
   `dist/**/*.d.ts`, not upstream main.
9. **IDs are opaque.** Python types `ConversationId = int` and
   `SubmissionId = int` and never constructs them.
10. **Two backend namespaces.** `pi_agent.coding` (the coding agent) and
    `pi_agent.durable` are the two backends of one SDK. `pi_agent.coding` only
    re-exports `PiClient` and `AsyncPiClient`: there is one class per name and
    no second implementation. The top-level `pi_agent` exports stay, so existing
    code keeps working. `pi_agent/__init__.py` does not import `pi_agent.durable`.
11. **Diagnostics follow the repository.** Never embed host stderr in
    exceptions. Retention is opt-in via `Limits.stderr_tail_bytes`, read via
    `stderr_tail`.

## Shared core and new components

| Concern | Durable uses | Core change needed |
| --- | --- | --- |
| Process spawn, pipes, JSONL framing, write lock, exit monitoring, shutdown (stdin EOF → terminate → kill), late replies | `_transport.Transport`, unchanged | None |
| Error-code passthrough | `PiCommandError.code` | M2: optional `code`, read from an error response's `code` field when it is a string |
| Limits and deadlines | `types.Limits` | None |
| Child environment (`inherit_env` + overrides) | `_launch.child_env()` | M2: extract the inline merge in `AsyncPiClient.start` into this helper |
| Argv resolution | `_launch.executable_argv()` | None; Durable rewords the not-found error (it says “install Pi”) |
| Errors | `PiCommandError`, `PiProcessError`, `PiProtocolError`, `PiTimeoutError`, `PiVersionError`, `PiSubscriptionOverflow` | None; no new error classes; messages saying “Pi …” are accepted as is |
| Timeout argument convention | `client.Timeout` / `client.DEFAULT_TIMEOUT` | None |
| Bounded streaming with explicit overflow | `_events._Subscription[T]`, subclassed for watch | None |
| Sync facade (loop thread, call bridging, interrupt handling, blocking subscriptions) | `_sync_bridge._SyncBridge`, `_SyncSubscription` | M4, only if Q2 is approved: extract from `sync.py` as a base class; `PiClient` inherits it with identical behavior |
| Test pattern | A fake host executable, like `tests/fake_pi.py` | None |
| Compatibility record and docs | `compatibility.json` (`durable` section), `docs/` | M8, M0 |

Durable uses `startup_timeout`, `command_timeout`, `cleanup_timeout`,
`max_record_bytes`, `event_queue_size`, `event_queue_bytes`, and
`stderr_tail_bytes` from `Limits`. It does not use `run_start_timeout`,
`result_message_*`, or `collection_event_*`.

New components are `host/` (Node), `src/pi_agent/durable/` (clients and types),
`tests/durable/`, and the `durable` CI job. New for the coding agent is only
`src/pi_agent/coding.py`, a re-export module (M2). Deliberately do not share
`_runs.py`, `RunResult`, `check_version`, `validate_extra_args`, or `Transport.send_ui`:
these are tied to coding-agent concepts (`agent_settled`, run ownership,
`SessionInfo`, Pi CLI flags).

## Host protocol v0

The host reads requests on stdin and writes responses and events on stdout,
one UTF-8 JSON object per line. **stdout carries only protocol lines.**
Diagnostics go to stderr.

### Envelope

- Request: `{"type": "<command>", "id": "<string>", ...fields}`. Fields are
  top-level; `id` and `type` are reserved.
- Success: `{"type": "response", "id": "<same>", "command": "<same type>", "success": true, "data": {...}}`.
  `data` is always an object (`{}` when there is nothing to return).
- Failure: `{"type": "response", "id": "<same>", "command": "<same type>", "success": false, "error": "<message>", "code": "<code>"}`.
  `error` is a string.
- Event: `{"type": "durable_<name>", ...}`. Any record whose `type` is not
  `"response"` is an event.

`Transport` validates only the envelope. A malformed envelope is fatal:
`PiProtocolError`, connection closed. It silently drops a response whose `id`
it is not waiting for. It does not validate `data` or event payloads; the
Durable client validates these and raises `PiProtocolError` on a wrong shape.
The host must:

- echo the string `id` and `command` exactly, never responding without an `id`;
- respond only to a request it received;
- never write a record larger than `maxRecordBytes` (see below);
- answer invalid input with an **event**, not a response: an unparseable line
  produces `{"type": "durable_protocol_error", "code": "parse_error", "message": "..."}`;
  a record lacking a string `id` or string `type` produces the same event with
  `code: "bad_request"`.

### Lifecycle

- **Readiness:** read immediately. The client's first request is `hello`;
  there is no startup event.
- **Before `open` completes:** every command except `hello` and `open` returns
  `not_open`. The client awaits `open` during `start()`, so SDK users never
  see this. A second `open`, while opening or open, returns `already_open`.
  A failed `open` leaves the host not open.
- **Open:** call `Harness.open(...)`, then `harness.resume()` so work a previous
  process left unfinished continues.
- **After open:** requests run concurrently. `wait` may remain pending
  indefinitely without blocking other requests.
- **Shutdown is stdin EOF:** no `close` command. Stop all watches, close the
  harness, and exit 0. Ignore `EPIPE` on stdout and stderr because the parent
  may be gone. Do not answer pending requests. Unfinished durable work stays
  in storage for the next `open`.

### Commands

| Command | Fields | `data` on success | Error codes |
| --- | --- | --- | --- |
| `hello` | — | `{protocol: 0, piDurable: "<version>", pid: <int>}` | — |
| `open` | `storage: {kind: "sqlite", path: string} \| {kind: "memory"}`, `codingTools?: bool = true`, `settings?: {retry?, progress?}`, `maxRecordBytes?: int`, `faux?: FauxStep[]`, `fauxTokensPerSecond?: number` | `{}` | `already_open`, `bad_params`, upstream |
| `root` | `agent?: {model?: {provider: string, modelId: string}, cwd?: string, thinkingLevel?: string}` | `{conversationId}` | `not_open`, `bad_params` |
| `submit` | `conversationId`, `content: string`, `requestId: string`, `whenBusy?: "followUp" \| "steer" \| "reject"` | `{submissionId}` | `not_open`, `not_found`, `bad_params`, `ConversationBusy` |
| `wait` | `submissionId` | `{submission}`: upstream settled-submission record, unchanged | `not_open`, `not_found`, `bad_params` |
| `entries` | `conversationId`, `limit?: int = 50` | `{entries}`: newest `limit` entries, oldest → newest | `not_open`, `not_found`, `bad_params`, `too_large` |
| `watch` | `conversationId`, `watchId: string` (client-chosen) | `{}` | `not_open`, `not_found`, `bad_params` (duplicate `watchId`) |
| `unwatch` | `watchId: string` | `{}` (unknown ID is a no-op) | `not_open`, `bad_params` |
| `abort` | `conversationId` | `{}`, after the conversation is idle | `not_open`, `not_found`, `bad_params` |

Any command may also return `too_large` or an upstream code as described below.
`root` agent options apply only on first creation: an existing root ignores them,
matching upstream. An omitted model invents no default; a run without a model
ends unanswered. `settings.retry` and `settings.progress` pass through unchanged
as upstream `HarnessSettings.retry` and `.progress`.

`maxRecordBytes` defaults to 16777216 (16 MiB). `faux` and
`fauxTokensPerSecond` are for tests and examples. With `faux`, models come only
from the faux provider (`provider: "faux"`, `modelId: "faux-1"`); otherwise
use pi-ai `builtinModels()`, which reads the usual provider environment
variables. A `FauxStep` is a string (text answer) or `{tool: string, args: object}`
(tool call).

### Error codes and size limit

Host codes are `bad_params` (missing required field or wrong type),
`unknown_command`, `not_open`, `already_open`, `not_found`, and `too_large`.
For upstream errors, `code` is the error's `name` when specific (for example,
`ConversationBusy`), or `upstream_error` for plain `Error`. `error` is the
upstream message.

`maxRecordBytes` comes from `Limits.max_record_bytes`. Before writing any
record, check the UTF-8 byte length of the line **excluding the newline**, as
`Transport` measures it:

- Replace an oversized response with a `too_large` error response.
- Replace an oversized watch event with the same event carrying `entries: []`,
  `live: null`, and `gap: true`. Still advance that watch's last-sent entry ID
  to the newest ID in the window, so later events do not repeat skipped entries.
- Drop oversized `durable_report` and `durable_protocol_error` events: they carry
  diagnostics only and must not stop the host.
- If a response's or watch event's replacement itself cannot fit (tiny limit or
  very long `id`), write nothing more, close stdout, and exit non-zero. The client
  sees a transport failure.
- Apply `open`'s limit only when that open succeeds; a failed open preserves the
  previous limit.

### Events and watch semantics

| Event `type` | Fields |
| --- | --- |
| `durable_watch` | `watchId`, `entries`, `live`, `gap: bool`, `snapshot: bool` |
| `durable_watch_end` | `watchId`, `kind` (upstream `WatchEnd.kind`) |
| `durable_report` | `report`: upstream `Report`, with `error` serialized as `{name, message}` |
| `durable_protocol_error` | `code`, `message` (see envelope) |

Upstream watch values are a bounded, coalesced window (newest 50, trimmed past
100), not a log. After answering `watch`, send one `durable_watch` with
`snapshot: true` holding the current window. Later events have
`snapshot: false`. All updates travel as events, so their order never depends
on when the caller sees the response.

Each later event's `entries` contains only IDs greater than the last one sent
on that watch, oldest → newest. Implement this diff as the pure function
`nextWatchUpdate(lastSentId, entries) → {entries, gap}` in
`host/src/watch-window.ts`; importing it must not start the host.
`gap: true` means the window no longer contains the last sent entry, so entries
may have been skipped. Recover with `entries`. `live` is upstream
`docs["pi.live"]`, unchanged.

## Python API

The async core methods below are implemented in M3 and the synchronous facade
in M5. M6 implements watch in both clients.

### Async client

```python
class AsyncDurableClient:
    def __init__(
        self,
        storage_path: str | os.PathLike[str] | None,  # None = in-memory
        *,
        host_command: Sequence[str] | None = None,  # ["node", "/path/host/src/host.ts"]
        cwd: str | os.PathLike[str] | None = None,  # host cwd and default agent cwd
        env: Mapping[str, str | None] | None = None,  # None removes a variable
        inherit_env: bool = True,
        limits: Limits | None = None,
        coding_tools: bool = True,
        settings: Mapping[str, Any] | None = None,  # sent as open.settings
        faux: Sequence[str | Mapping[str, Any]] | None = None,
        faux_tokens_per_second: float | None = None,
    ) -> None: ...  # no side effects

    async def start(self) -> None: ...
    async def aclose(self) -> None: ...  # repeatable, safe after host exit
    async def __aenter__(self) -> Self: ...  # start()
    async def __aexit__(self, *exc: object) -> None: ...  # aclose()

    async def root(
        self,
        *,
        model: Mapping[str, str] | None = None,
        cwd: str | None = None,
        thinking_level: str | None = None,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> ConversationId: ...
    async def submit(
        self,
        conversation_id: ConversationId,
        content: str,
        *,
        request_id: str,
        when_busy: Literal["followUp", "steer", "reject"] | None = None,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> SubmissionId: ...
    async def wait(
        self, submission_id: SubmissionId, *, timeout: float | None = None
    ) -> SettledSubmission: ...
    async def entries(
        self,
        conversation_id: ConversationId,
        *,
        limit: int = 50,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> list[dict[str, Any]]: ...
    async def abort(
        self, conversation_id: ConversationId, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> None: ...
    def watch(self, conversation_id: ConversationId) -> WatchSubscription: ...  # M6

    @property
    def limits(self) -> Limits: ...
    @property
    def running(self) -> bool: ...
    @property
    def host_pid(self) -> int | None: ...  # from hello
    @property
    def pi_durable_version(self) -> str | None: ...  # from hello
    @property
    def stderr_tail(self) -> str: ...  # needs Limits.stderr_tail_bytes > 0
```

**Startup** runs within `limits.startup_timeout`:

1. Build the child env with `_launch.child_env(inherit_env, env)`.
2. Resolve argv with `_launch.executable_argv(host_command, child_env)`.
   Before M9, `host_command=None`, or a program not found, raises
   `PiProcessError` naming Node ≥ 22.19 and `host_command`.
3. Create `Transport(limits=..., on_event=..., on_failure=...)` and await
   `transport.start(argv, cwd=cwd, env=child_env)`.
4. Request `hello`; a `protocol != 0` raises `PiVersionError`. Store `pid` and
   `piDurable`.
5. Request `open` with storage, options, and
   `maxRecordBytes=limits.max_record_bytes`.

On any failure, close the transport and re-raise. Startup timeout raises
`PiTimeoutError(..., uncertain=False)`, like `AsyncPiClient.start`.

**Timeouts:** `DEFAULT_TIMEOUT` resolves to `limits.command_timeout`.
A `Transport` response timeout raises `PiTimeoutError(uncertain=True)`, correct
for `root`, `submit`, and `abort`. After uncertain `submit`, retrying the same
`request_id` is safe. `wait` and `entries` submit no work, so re-raise their
timeouts with `uncertain=False`. `wait` has no default response deadline.

**Cancellation:** a response timeout or cancellation after writing abandons
only the local wait. The host keeps working; `Transport` drops the late reply.
Cancellation or timeout during the write itself closes the transport (existing
behavior), shutting down the host. Unfinished work stays in storage and resumes
on next open.

**Errors:** failed commands raise `PiCommandError` with `.code` (for example,
`"not_found"` or `"ConversationBusy"`). Host exit raises `PiProcessError`;
malformed records raise `PiProtocolError`.

**Events:** log `durable_report` and `durable_protocol_error` at debug level on
`pi_agent.durable`, otherwise ignore them in v0. Log only event type and its
`code` or `kind`, never payloads: conversations and credentials must not enter
diagnostics. Ignore unknown event types and `durable_watch` for unknown
`watchId` values.

**Clients are single-use**, like `AsyncPiClient`; create a new client to reopen.

Types in `src/pi_agent/durable/types.py`:

- `ConversationId = int`, `SubmissionId = int`.
- `SettledSubmission`: `status: Literal["done", "unanswered"]`,
  `reason: str | None`, `raw: dict[str, Any]` (the upstream record), and read-only
  `answer_id: int | None` for its answer entry.
- `entry_text(entry: Mapping[str, Any]) -> str`: pure text extraction from an
  entry's model messages; non-text and malformed parts are ignored.
- `WatchUpdate`: `entries: list[dict[str, Any]]`,
  `live: dict[str, Any] | None`, `gap: bool`, `snapshot: bool`,
  `raw: dict[str, Any]`. Entries, live state and raw data are omitted from repr.
- `TypedDict`s for every command's fields and `data`, and for every event.
  Keep unknown upstream fields in `raw`.

### Watch

`WatchSubscription` subclasses `_events._Subscription[WatchUpdate]`. Use
`async with client.watch(cid) as updates: async for update in updates: ...`.

- **Enter:** choose a fresh `watchId`, register under it, then request `watch`.
  On failure, timeout, or cancellation, unregister, send best-effort `unwatch`
  from a tracked background task (an await inside a cancelled task would
  re-raise), then raise. The first item is the snapshot: `snapshot=True`,
  `gap=False` unless it exceeded the size limit.
- **Routing:** `on_event` routes `durable_watch` by `watchId` using
  `_put(update, size)`, where `size` is the encoded record length computed as
  in `AsyncPiClient._on_event`.
- **End:** `durable_watch_end` finishes the subscription (iteration stops).
  Transport failure finishes every subscription with that error.
- **Overflow:** a slow consumer gets `PiSubscriptionOverflow`, bounded by
  `limits.event_queue_size` and `event_queue_bytes`. `_put` is synchronous,
  so send `unwatch` from the same kind of tracked background task. `aclose()`
  awaits these tasks. Call `watch()` again for a fresh snapshot.
- **Exit:** override subscription `aclose()` to unregister, then send
  best-effort `unwatch`; swallow errors from a dead host.

### Sync client

`DurableClient(_SyncBridge)` has the same constructor, methods, and properties
as the async client, with `start()` / `close()` and `with` support. Every call
delegates to a private `AsyncDurableClient` on the bridge's loop thread.
`watch()` returns `_SyncSubscription[WatchUpdate]`, a blocking context manager
and iterator. Inherit the bridge's rules: calls from client callbacks are
rejected, and `KeyboardInterrupt` cancels a call but never interrupts shutdown.

## Recovery and verification boundaries

Recovery belongs entirely to upstream. `open` resumes unfinished work; a new
client reuses the same SQLite path and conversation-scoped `request_id` to
recover the original submission after a host or Python crash. This is not
permission to retry with a new key or attach multiple writers. The issue's
M7 suite exercises host SIGKILL after at least 200 characters of partial live
text, Python SIGKILL followed by host EOF shutdown, and settled-key resubmission
without a second user entry. Every reopen uses the same 400-word faux answer,
50 tokens/second, and 50 ms persistence/retry settings. CI repeats recovery three
times in each Durable matrix row; the upstream spike alone is not SDK coverage. Partial assistant output may
produce an aborted entry before the final answer; its persistence is not
guaranteed before the configured progress window.

Use isolated synthetic data. Host/integration tests require installed host
modules and Node ≥ 22.19; `PI_DURABLE_REQUIRE_INTEGRATION=1` must fail rather than
skip when prerequisites are absent. SIGKILL tests skip Windows.
Python client unit tests use a fake host without Node. See [CONTRIBUTING.md](../CONTRIBUTING.md) for standard
checks and [#116] for each milestone's additional validation. M1's direct-host
suite covers command envelopes and failures, memory/SQLite flows, concurrent
wait/control, EOF shutdown (including opening and a pending wait), and record
limits. M3/M5 add async/sync client flow and failure coverage; M6 adds watch
snapshots, bounds and gaps; M7 adds the crash scenarios above. Host packaging is
not provided (bring your own host). No live providers are used or certified by
these tests.

[#116]: https://github.com/cheenulabs/pi-agent-python-sdk/issues/116
[upstream]: https://github.com/earendil-works/pi/tree/v1.5.2/packages/durable
