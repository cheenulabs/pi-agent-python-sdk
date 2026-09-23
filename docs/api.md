# API reference

Import `PiClient` or `AsyncPiClient` from `pi_agent`. Both expose
the same command arguments and return values. Await command methods on the async
client; call them directly on the synchronous client. Types named below are
defined in `pi_agent.types`, except `ProcessOutput` and `ObservationStatus`,
which are exported directly from `pi_agent`.

Wire values remain ordinary dictionaries, with camelCase keys matching Pi.
Python method arguments use snake_case. Optional arguments are omitted from the
wire when unset; explicitly supplied `False`, empty strings, and empty lists
remain meaningful values. The client checks response success even for commands
whose Python return value is `None`.

## Constructor options

Every constructor parameter is keyword-only. Construction starts neither a
subprocess nor a background thread.

| Parameter | Default | Meaning |
|---|---|---|
| `executable` | `"pi"` | Executable name/path, or sequence of arguments such as `["node", "/path/to/cli.js"] |
| `cwd` | `None` | Child working directory; unset inherits the caller's cwd |
| `provider` | `None` | Explicit Pi provider override |
| `model` | `None` | Explicit Pi model override |
| `env` | `None` | Environment overrides; a value of `None` removes that variable |
| `inherit_env` | `True` | Start from the caller's environment before applying overrides |
| `session` | `None` | Initial session selected using Pi's `--session` option |
| `session_dir` | `None` | Pi's session persistence directory |
| `session_id` | `None` | Explicit Pi startup session ID |
| `continue_session` | `False` | Pass Pi's `--continue` option |
| `no_session` | `False` | Disable session persistence explicitly |
| `fork_session` | `None` | Pass Pi's startup `--fork` option |
| `extra_args` | `()` | Additional permitted Pi or extension arguments |
| `ui_handler` | `None` | Sync or async extension UI callback; absent handlers cancel dialogs |
| `limits` | `None` | Use `Limits()` defaults, or pass an explicit configuration |
| `strict_version` | `False` | Reject recognized Pi versions outside the recorded tested version |
| `allow_unknown_version` | `False` | Explicitly permit a custom executable with unparseable version output |

Choose at most one of `session`, `continue_session`, and `fork_session`.
`no_session` conflicts with opening, continuing, or forking a persisted session,
and with `session_dir`. `session_id` conflicts with `session` and
`continue_session`. Pi can impose additional validity rules on supplied values.

Do not repeat constructor-owned flags in `extra_args`. The client also rejects
RPC mode overrides, print/help/version/export/list-models modes, positional
prompts, and startup attachments. Arguments are passed without a shell.

## Lifecycle and convenience methods

| API | Result and behavior |
|---|---|
| `start()` | Check version, launch RPC mode, and wait for `get_state`; returns `None` |
| `close()` / async `aclose()` | Wake operations, close stdin, escalate if needed, and reap the owned child; sync also joins its loop thread |
| `on_event(listener)` | Register a synchronous event callback; return an idempotent unsubscribe function; may register before startup |
| `collect_events(*, timeout=60.0)` | Collect future `Event` objects through the next `agent_settled`, inclusive |
| `wait_for_idle(*, timeout=60.0)` | Wait for the next `agent_settled`, retaining no event history; returns `None` |
| `prompt_and_wait(message, *, images=None, timeout=60.0, command_timeout=DEFAULT_TIMEOUT)` | Register collection before submitting a prompt; return `list[Event]` after both successful acknowledgement and settlement |
| `run(message, *, images=None, timeout=None, command_timeout=DEFAULT_TIMEOUT)` | `RunResult` after an observed run settles; final model failure raises `PiRunError` with a partial result |
| `stream(message, *, images=None, timeout=None, command_timeout=DEFAULT_TIMEOUT)` | Context-managed owned run with an event iterator and `result()` |
| `observe(*, stderr=True, stdout=False, rpc=False)` | Context-managed selected process output; enter before `start()`, drain through close, then inspect `.status` |
| `events()` | Context-managed future-event subscription; enter before `start()` for startup events; it does not own the conversation |
| `request(command_type, *, timeout=DEFAULT_TIMEOUT, **fields)` | Checked raw response envelope; assigns ID and enforces normal ownership rules |

`start()` is single-use; construct a new client for another process. Repeated
close calls are safe. Use `with` / `async with` for lifecycle management.
`stream()` and `events()` return their context objects directly, even on the async
client: use `async with pi.stream(...)`, without awaiting its construction.

`run()` does not buffer progress events; finalized-result limits still apply.
See [output bursts and backpressure](rpc.md#output-bursts-and-backpressure) for
queue bounds, blocking iterator batches, and dispatch scheduling costs.

Within a stream context, iterate and then call `result()`, or call `result()`
alone to drain. Await it for async streams. An active iterator and a simultaneous
result drain are mutually exclusive. Contexts are single-use. The async iterator
can be obtained repeatedly or continued with `async for` after `anext(stream)`;
overlapping reads remain invalid.

Stream entry occurs on prompt acknowledgement or an observed agent start,
whichever comes first. Completion still requires successful acknowledgement and
settlement. A late command rejection can therefore surface during iteration or
`result()`. Early exit before acknowledgement closes Pi conservatively; see
[run ownership and cleanup](errors.md#cancellation-and-close).

| Property | Meaning |
|---|---|
| `running` | Child is running and initial readiness has completed |
| `busy` | A high-level run/stream currently owns the conversation; not a global Pi idle indicator |
| `session` | Cached `SessionInfo`; use `get_state()` for an authoritative refresh |
| `pi_version` | Recognized version string, or `None` |
| `compatibility` | `unchecked` before startup, then `tested`, `untested`, or `unknown` |
| `stderr_tail` | Explicit diagnostic text; empty by default because retention is disabled |
| `limits` | The configured `Limits` object |

## Listeners and settlement helpers

These helpers were added for 0.2.0. Runnable examples:
[`rpc_async.py`](../examples/rpc_async.py) and [`rpc_sync.py`](../examples/rpc_sync.py).

`on_event()` delivers future session events in wire order, including unknown
events, extension errors, and UI requests. Responses are returned by command
methods; raw RPC envelopes and stderr remain available through `observe()`.
Each listener receives an `Event` with a separate mutable `.raw` dictionary.
Callbacks run synchronously on the async client's owning loop, or on `PiClient`'s
background loop thread. Keep them short; blocking callbacks delay all RPC work.
Coroutine functions are rejected. Prefer `async for` on `events()` or `stream()`
when application work needs `await`; see the [streaming example](../examples/stream.py).
If a callback schedules tasks itself, the application owns their bounds and cleanup.
Blocking client calls from
callbacks raise `RuntimeError`; unsubscribe itself is safe inside a callback.

Registration order determines callback order. Removing a listener before its
turn skips it; a listener added during delivery starts with the next event.
Repeated registrations are independent. Exceptions are sent to the standard
asyncio loop exception handler and do not stop other listeners or the transport.
A callback returning a cold coroutine is also reported there and the coroutine
is closed. Client close/failure releases all listeners.

On `AsyncPiClient`, `collect_events()` and `wait_for_idle()` register **at the
method call** and return already scheduled, cancellable tasks. Await the returned
task directly; do not pass it to `asyncio.create_task()`. Both can register before
`start()`. For separate submission and collection:

```python
pending = pi.collect_events(timeout=60)
try:
    await pi.prompt("Explain this project.")
    events = await pending
finally:
    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)
```

This snippet assumes an async client and `import asyncio`. Usually
`events = await pi.prompt_and_wait(...)` is simpler and handles local cleanup.
On `PiClient`, both methods block until settlement and expose no registration
readiness signal. Starting a collector thread does not guarantee registration
before a prompt's events arrive. Use `prompt_and_wait()` when collection must
register before submission; it guarantees that ordering internally. See the
[runnable blocking example](../examples/rpc_sync.py).

All three helpers observe **session-wide** events, without claiming run ownership
or correlating them to a particular prompt. `wait_for_idle()` waits for a future
settlement even if Pi is already idle; use `get_state()` to query current state.
`prompt_and_wait()` requires a successful prompt acknowledgement even when
settlement arrives first. A handled extension command that never settles reaches
the configured deadline. Model stop reasons, usage, retries, and tool results
remain in the original events; these helpers do not create `RunResult`, aggregate
usage, or raise `PiRunError` for a model failure.

The timeout covers the whole helper call (60 seconds by default, `None` disables
it). `command_timeout` separately bounds prompt acknowledgement. Timeout,
cancellation, or collection overflow releases local observation only: no hidden
`abort()`, `clear_queue()`, or process shutdown. Transport failure still follows
normal process cleanup; an interrupted stdin write can also close Pi to protect
framing integrity. Call abort/clear/close explicitly when desired.

`collect_events()` and `prompt_and_wait()` retain at most the configured
`collection_event_count` and `collection_event_bytes`, including the settlement
record. These aggregate limits are separate from subscription backlog limits;
`wait_for_idle()` retains no history but still uses a bounded subscription.
Overflow raises `PiResultOverflow` for retained history or
`PiSubscriptionOverflow` for backlog. Neither returns a silently truncated list.

`run()` and `stream()` remain supported Python conveniences alongside these
protocol helpers; see the [internal assessment](rpc.md#internal-design-assessment).
`prompt_and_wait()` uses low-level `prompt()`, so the existing ownership rule
still prevents a subsequent owned `run()`/`stream()` on that same client. Use
one style per client; repeated settlement helpers and sequential completed runs
are supported.

## All 33 RPC commands

Each method below additionally accepts keyword-only
`timeout=DEFAULT_TIMEOUT`. That shared parameter is omitted from table signatures
to keep them readable. Omission uses the configured short-command deadline, or
no execution deadline for the long commands listed under [limits](#limits).
Explicit `timeout=None` disables only the response deadline; the write is still
bounded. See [errors and deadlines](errors.md#deadlines).

### Input and queues

| Method | Return | Meaning |
|---|---|---|
| `prompt(message, *, images=None, streaming_behavior=None)` | `None` | Checked acknowledgement; not proof of an agent start; use `request("prompt", ...)` for the envelope |
| `steer(message, *, images=None)` | `None` | Queue input for Pi's next steering opportunity |
| `follow_up(message, *, images=None)` | `None` | Queue input after the current response |
| `abort()` | `None` | Abort using Pi semantics; does not implicitly clear queued input |
| `clear_queue()` | `QueueState` | Cleared queued text in `steering` and `followUp` lists |
| `set_steering_mode(mode)` | `None` | Set `"all"` or `"one-at-a-time"` |
| `set_follow_up_mode(mode)` | `None` | Set `"all"` or `"one-at-a-time"` |

`streaming_behavior` accepts `"steer"` or `"followUp"`. `images` accepts
`list[ImageContent]`. Steering and follow-up responses acknowledge submission,
not consumption.

### Models, state, and compaction

| Method | Return | Meaning |
|---|---|---|
| `get_state()` | `SessionState` | Model, thinking level, streaming/compaction flags, queue modes, session identity, auto-compaction flag, and message counts |
| `set_model(provider, model_id)` | `Model` | Select the provider/model and return its metadata |
| `cycle_model()` | `ModelCycleResult` or `None` | Next model with `thinkingLevel` and `isScoped`; `None` when no cycle result exists |
| `get_available_models()` | `list[Model]` | Available model metadata |
| `set_thinking_level(level)` | `None` | Request a thinking level supported by Pi |
| `cycle_thinking_level()` | `ThinkingLevelCycleResult` or `None` | Full `{level: ...}` result with unknown fields, or no cycle result |
| `get_available_thinking_levels()` | `list[ThinkingLevel]` | Levels available for the current model |
| `compact(*, custom_instructions=None)` | `CompactionResult` | Summary, first kept entry ID, tokens before compaction, and any available estimates/usage/details |
| `set_auto_compaction(enabled)` | `None` | Enable or disable Pi's automatic compaction |
| `set_auto_retry(enabled)` | `None` | Enable or disable Pi's automatic retry |
| `abort_retry()` | `None` | Abort Pi's retry sequence |

`ThinkingLevel` is `"off"`, `"minimal"`, `"low"`, `"medium"`, `"high"`,
`"xhigh"`, or `"max"`. Availability depends on the selected model; the Python
client does not redefine Pi's model behavior. Model metadata retains provider
compatibility fields and may contain headers, so do not assume it is safe to log.

### Sessions and history

| Method | Return | Meaning |
|---|---|---|
| `new_session(*, parent_session=None)` | `SessionChangeResult` | Start a new session; inspect `cancelled` for an extension veto |
| `switch_session(session_path)` | `SessionChangeResult` | Switch to the specified session path; inspect `cancelled` |
| `fork(entry_id)` | `ForkResult` | Fork at an eligible entry; contains `cancelled` and optional editable `text` |
| `clone()` | `SessionChangeResult` | Clone the current session; inspect `cancelled` |
| `get_fork_messages()` | `list[ForkMessage]` | Eligible `{entryId, text}` records for choosing a fork point |
| `get_entries(*, since=None)` | `EntriesResult` | `entries` after the optional referenced ID, plus nullable `leafId`; the referenced entry is excluded |
| `get_tree()` | `TreeResult` | Recursive `tree` nodes and nullable `leafId` |
| `get_last_assistant_text()` | `str` or `None` | Most recent usable assistant text in session history; absent/null text becomes `None` |
| `set_session_name(name)` | `None` | Update the current name; query state explicitly afterward |
| `get_messages()` | `list[AgentMessage]` | Current conversation messages |
| `get_session_stats()` | `SessionStats` | Message/tool counts, token totals, cost, and optional context usage |
| `export_html(*, output_path=None)` | `ExportHtmlResult` | Full `{path: ...}` result, preserving unknown fields |

Session mutations send only the requested command. The cached `session` snapshot
is invalidated after a successful mutation (including an extension veto); call
`get_state()` explicitly when updated identity is needed. Startup and the
run driver still perform their own state reads. `cancelled=True` is a normal return value; it is
not converted into an exception. In particular, a vetoed fork can omit `text`.
An unknown `since` entry ID is rejected by Pi. `clone()` requires a selected leaf,
and `set_session_name()` follows Pi's trimming and nonempty-name rules.

### Bash and extension discovery

| Method | Return | Meaning |
|---|---|---|
| `bash(command, *, exclude_from_context=None)` | `BashResult` | Output, optional exit code, cancellation/truncation flags, and optional full-output path |
| `abort_bash()` | `None` | Abort Pi's active bash execution |
| `get_commands()` | `list[SlashCommand]` | Commands from extensions, prompt templates, and skills, including their `sourceInfo` |

`bash_execution_update` events carry output deltas; their optional `id` identifies
the originating request. `exclude_from_context=False` is transmitted explicitly;
omitting it preserves Pi's default. `get_commands()` is discovery, not a promise
that all terminal built-in commands are callable through RPC.

## Migrating from 0.1.0

Version 0.2.0 changes three convenience results and session-cache refresh
behavior from 0.1.0:

| Previous use | Updated use |
| --- | --- |
| `receipt = pi.prompt(text)` | `pi.prompt(text)` returns `None`; use `pi.request("prompt", message=text)` when the response ID/envelope is needed |
| `level = pi.cycle_thinking_level()` | Read `result["level"]` when the returned result is not `None` |
| `path = pi.export_html()` | Read `result["path"]`; other returned metadata stays available |
| Read cached session identity immediately after a mutation | Explicitly call `pi.get_state()` and read its returned dictionary |

Await the equivalent methods on `AsyncPiClient`. Command rejection still raises
`PiCommandError`; a `None` prompt result means acknowledgement succeeded, not
that Pi finished or even started an agent run. These changes align command
results with the pinned TypeScript client. `run()`, `stream()`, and `RunResult`
remain supported. `AcceptanceReceipt` is removed; raw response access continues
through `request()`.

## Events and wire types

`Event.raw` preserves the complete parsed record, including unknown fields.
`Event.type` exposes its string discriminator. `Event.text_delta` extracts only
`message_update.assistantMessageEvent.type == "text_delta"`; other event types
return `None`.

The recorded protocol contains 23 session events plus `extension_error` and
`extension_ui_request`. Its nested assistant declaration has 12 variants, but
normal serialized `message_update` records carry the nine text/thinking/tool-call
start, delta, and end variants. Pi removes cumulative outer `message` and nested
`partial` snapshots. Read finalized messages from `message_end`, and use the
[complete discovery inventory](discovery.md#complete-output-event-surface) for
the event fields.

Known wire annotations include `RpcCommand`, `RpcResponse`, `RpcEvent`,
`AgentMessage`, `SessionEntry`, `SessionTreeNode`, `Model`, `Usage`,
`ExtensionUIRequest`, and `ExtensionUIResponse`. They are annotations for plain
dictionaries, not recursively validating models. Unknown future records remain
available through raw access.

The Pi 0.87.0 annotations include `SessionEntry` values with
`type="context_edit"` and optional `Model.inputLimits` metadata. These fields
pass through the same command results and event records as earlier entry and
model fields.

These wire annotations and `RunResult` do not validate an assistant's answer
against a Pydantic model or JSON schema. `RunResult.text` is ordinary text; parse
and validate structured answers in your application when needed. The SDK adds
no schema-driven prompting or model-output retry loop.

UI handlers receive a typed request and return `str`, `bool`, or `None`, directly
or through an awaitable. The client assigns matching reply envelopes internally.
Use `bool` for confirm, `str` for select/input/editor, and `None` for cancellation.
Display requests need no reply. See [UI usage](usage.md#extension-ui).

## Result dataclasses

`RunResult`, `SessionInfo`, `UsageSummary`, and `Event` are small frozen
dataclasses. Their nested dictionaries/lists remain ordinary mutable Python
objects; frozen fields do not imply a deep immutable copy.

| Type | Fields |
|---|---|
| `RunResult` | `text`, `messages`, `stop_reason`, `session`, `elapsed_seconds`, optional `usage` |
| `SessionInfo` | Optional `session_id`, `session_file`, `session_name` |
| `UsageSummary` | Optional `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `cache_write_1h_tokens`, `reasoning_tokens`, `total_tokens`, `cost`; `assistant_messages` count |
| `Event` | `raw`, with `type` and `text_delta` properties |

`RunResult.messages` retains finalized messages up to independent count/byte
limits; overflow fails the run with `PiResultOverflow`. Usage is observed
assistant usage, not total billing; a missing measurement in any contributing
assistant message keeps that summary field unknown. Reasoning is not added to
output tokens a second time.

## Limits

Pass `limits=Limits(...)` to either client. Timeouts are positive finite seconds;
capacities are positive integers except `stderr_tail_bytes`, which may be zero.

| Field | Default | Scope |
|---|---|---|
| `startup_timeout` | `30.0` | Version check, launch, and readiness |
| `command_timeout` | `30.0` | Default short-response deadline; also bounds each write including waiting for the write lock |
| `run_start_timeout` | `30.0` | Wait for an observed agent start after prompt acceptance |
| `cleanup_timeout` | `5.0` | Run cancellation cleanup and subprocess shutdown escalation stages |
| `max_record_bytes` | `16 * 1024 * 1024` | Each inbound or outbound JSON record |
| `event_queue_size` | `256` | Records per subscription; also outstanding UI-handler count |
| `event_queue_bytes` | `16 * 1024 * 1024` | Bytes per subscription; also outstanding UI-handler payload bytes |
| `stderr_tail_bytes` | `0` | Retained diagnostic stderr tail; zero disables retention |
| `collection_event_count` | `16384` | Events retained by one settlement collection |
| `collection_event_bytes` | `64 * 1024 * 1024` | UTF-8 serialized event bytes retained by one settlement collection |
| `result_message_count` | `4096` | Finalized messages retained by one owned run |
| `result_message_bytes` | `64 * 1024 * 1024` | Serialized finalized-message event bytes retained by one owned run |

`bash`, `compact`, `new_session`, `switch_session`, `fork`, `clone`, and
`export_html` have no default command execution deadline. A numeric `timeout=`
overrides that. `run(timeout=...)` bounds the whole run, including preflight;
`command_timeout=` separately selects its prompt-acknowledgement deadline.
The internal `DEFAULT_TIMEOUT` sentinel means “use configured defaults”; normal
callers obtain that behavior by omitting the argument.

Response deadlines begin after the separately bounded write completes. A
numeric response timeout is therefore not a maximum wall time for the entire
call. See [failure semantics](errors.md) before retrying an uncertain operation.

## Process observation

`observe()` returns an async or blocking context and iterator over `ProcessOutput`.
`source` is `"stderr"`, `"stdout"`, or `"rpc"`. `data` contains original bytes for
pipe sources and a separate mutable dictionary for each RPC observer. `time_ns` is the SDK's
wall-clock receipt time in Unix nanoseconds. Receipt times can reflect system
clock adjustments; they are not provider execution times. Chunk boundaries are
unspecified; concatenate bytes before decoding or use an incremental decoder.

`ObservationStatus` exposes `started_at_ns` (RPC spawn attempt), `ended_at_ns`
(observation end), `from_start`, `stdout_eof`, `stderr_eof`, `rpc_complete`,
`complete`, `lost`, `error`, and `end_reason`.
`complete` means a subscription attached before spawn received all selected output
through natural pipe EOF with no queue loss. It does not promise successful RPC
execution or that a caller saved every record. `error` preserves the terminal
process/startup error separately from output delivery. A normal explicit close has
`error=None`; incomplete pipe drainage is still reported separately. A failed version/spawn or early unsubscribe is
incomplete. A late subscriber has `from_start=False` and cannot claim full coverage.

After client shutdown, drain queued records before leaving the observer context;
this works even after a blocking client's loop has stopped. Leaving the context
unsubscribes and discards unread records, marking loss if records were queued.
All data fields and errors are omitted from default observation representations.

To end a scoped observation while keeping Pi alive, call `await output.stop()`
(async) or `output.stop()` (blocking), then drain the iterator. Stop unregisters
immediately and preserves accepted records, including blocking iterator batches.
It sends no RPC command, does not wait for future output, and does not establish a
provider or prompt boundary. Accepted records retain SDK delivery order within
each source; relative ordering across stdout and stderr is not guaranteed.
They retain their `time_ns`; use that receipt timestamp when storing them,
rather than the time a worker eventually processes them.

`end_reason` is `None` while active, `"stopped"` after a scoped stop, `"closed"`
after explicit close/discard, `"overflow"` for queue loss, or `"process_end"` after
client/process termination (including startup failure). Check `error` separately
for terminal failure. A stopped observation never claims `complete=True`.
Stopping after a known terminal failure preserves `error`, even while process
cleanup is still draining pipes. The buffered records remain available to iterate.
Repeated stop preserves the existing end reason and errors. Context exit or
`aclose()` / `close()` still discards unread records, setting `lost=True` and
`end_reason="closed"`; overflow remains marked as overflow. Closing an already
drained observation preserves its status. Stop requires an entered context.

Select at least one source. Raw stdout includes blank lines, invalid UTF-8, malformed
JSON and partial trailing bytes. RPC observation includes every parsed JSON object
within `max_record_bytes`, including invalid envelopes, startup/internal responses,
command failures, late/duplicate responses and unknown event types. It excludes
blank lines, invalid JSON and non-object JSON values. Ordinary RPC validation and
routing are unchanged. Parsed and raw stdout deliberately overlap.

After protocol failure, routing stops and cleanup continues raw delivery and
best-effort object parsing within the same framing limit. `rpc_complete=False`
indicates records were too large to parse within that limit; observers selecting
RPC cannot then claim complete delivery, even when raw-only observers can. A
protocol failure itself does not mean raw bytes were lost. Other parsing failures
remain visible in raw output. There is no order guarantee between pipes, and raw
chunk boundaries do not correspond one-to-one to parsed objects. RPC timestamps
mark object receipt after framing, not the timestamp of each contributing byte.
