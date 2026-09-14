# API reference

Import `PiClient` or `AsyncPiClient` from `pi_coding_agent_client`. Both expose
the same command arguments and return values. Await command methods on the async
client; call them directly on the synchronous client. Types named below are
defined in `pi_coding_agent_client.types`.

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
| `run(message, *, images=None, timeout=None, command_timeout=DEFAULT_TIMEOUT)` | `RunResult` after an observed run settles; final model failure raises `PiRunError` with a partial result |
| `stream(message, *, images=None, timeout=None, command_timeout=DEFAULT_TIMEOUT)` | Context-managed owned run with an event iterator and `result()` |
| `events()` | Context-managed future-event subscription; it does not own the conversation |
| `request(command_type, *, timeout=DEFAULT_TIMEOUT, **fields)` | Checked raw response envelope; assigns ID and enforces normal ownership rules |

`start()` is single-use; construct a new client for another process. Repeated
close calls are safe. Use `with` / `async with` for lifecycle management.
`stream()` and `events()` return their context objects directly, even on the async
client: use `async with pi.stream(...)`, without awaiting its construction.

Within a stream context, iterate and then call `result()`, or call `result()`
alone to drain. Await it for async streams. An active iterator and a simultaneous
result drain are mutually exclusive. Contexts are single-use.

| Property | Meaning |
|---|---|
| `running` | Child is running and initial readiness has completed |
| `busy` | A high-level run/stream currently owns the conversation; not a global Pi idle indicator |
| `session` | Cached `SessionInfo`; use `get_state()` for an authoritative refresh |
| `pi_version` | Recognized version string, or `None` |
| `compatibility` | `unchecked` before startup, then `tested`, `untested`, or `unknown` |
| `stderr_tail` | Explicit diagnostic text; empty by default because retention is disabled |
| `limits` | The configured `Limits` object |

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
| `prompt(message, *, images=None, streaming_behavior=None)` | `AcceptanceReceipt` | Acknowledgement envelope with `id`, `command="prompt"`, and `success=True`; not proof of an agent start |
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
| `cycle_thinking_level()` | `ThinkingLevel` or `None` | Next level, or no available cycle result |
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
| `set_session_name(name)` | `None` | Update the current name and refresh cached identity |
| `get_messages()` | `list[AgentMessage]` | Current conversation messages |
| `get_session_stats()` | `SessionStats` | Message/tool counts, token totals, cost, and optional context usage |
| `export_html(*, output_path=None)` | `str` | Path of Pi's generated HTML export |

The client refreshes session identity after successful session mutations and
before finalizing run results. `cancelled=True` is a normal return value; it is
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

`RunResult.messages` retains finalized messages for the owned run. Event buffer
limits do not bound the memory required to retain that result. Usage is observed
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

`bash`, `compact`, `new_session`, `switch_session`, `fork`, `clone`, and
`export_html` have no default command execution deadline. A numeric `timeout=`
overrides that. `run(timeout=...)` bounds the whole run, including preflight;
`command_timeout=` separately selects its prompt-acknowledgement deadline.
The internal `DEFAULT_TIMEOUT` sentinel means “use configured defaults”; normal
callers obtain that behavior by omitting the argument.

Response deadlines begin after the separately bounded write completes. A
numeric response timeout is therefore not a maximum wall time for the entire
call. See [failure semantics](errors.md) before retrying an uncertain operation.
