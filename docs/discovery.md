# Discovery: Pi coding agent Python client

Protocol snapshot: 2026-09-15, Pi 0.85.1. This document records upstream
wire behavior, source references, and compatibility considerations.

## Findings that shape the package

- The installed runtime and npm latest stable both resolve to **0.85.1**.
  There is no baseline-to-latest stable protocol difference at this snapshot.
- The full stdio interface is 33 commands, 23 session event types, extension
  errors/UI requests, and nine UI methods. Some emitted events are missing
  from the RPC documentation's event table.
- Follow the TypeScript client's concepts, but type the serialized wire
  records. In-memory agent events differ from RPC events.
- Command acceptance does not prove an agent run will start. Both extension
  commands and ordinary input handlers can consume input without settlement.
- The existing private Python client has useful lifecycle behavior and tests;
  its launch defaults and extension-specific completion heuristics should not
  become public-library policy.
- A small async core, typed wire dictionaries, and a few convenience
  dataclasses can expose the full surface without porting Pi itself.

## Evidence and provenance

| Evidence | Version / identity | What was done |
|---|---|---|
| Public Pi source | `v0.85.1`, `d981de1229ef899957bbe968bc8dcda02a21f477` | Read pinned RPC declarations, runtime, client, serializer, referenced types, relevant session behavior and test source |
| npm stable registry metadata | `@earendil-works/pi-coding-agent@0.85.1`; same gitHead | Queried latest stable directly |
| Installed Pi | `0.85.1`; requires Node >=22.19.0 | Read package metadata and exercised isolated stdio probes |
| Upstream main | `53816d7dcc5ebe3a0eedec3cd07196c3a66d83fd` at discovery | Recorded only; not substituted for the stable protocol |
| Existing private Python source | `cheenulabs/cheenulabs`, `03f7e3e3fd3c6d2775dc063bcee7ee809c0c9587` | Read RPC implementation, exports, tests, and one application caller |
| Selected distribution name | `pi-agent-python-sdk` | Updated before publication; confirm index availability before release |

The existing client is `pi-agent/cheenulabs_pi_runtime/rpc.py`, with tests at
`pi-agent/tests/test_rpc.py`, in the remote repository. It was absent from the
local checkout. Private provenance is recorded for the owner; public reviewers
cannot independently inspect that private source. No private implementation,
credentials, configuration values, logs, or application data are reproduced here.

Evidence labels used below: **source** means inspected code; **documented**
means upstream documentation; **observed** means a probe executed during this
discovery. Upstream test files were read, not executed. There is no claim that
the future Python package or a platform support matrix has been tested.

Stable sources:
[release](https://github.com/earendil-works/pi/releases/tag/v0.85.1),
[package metadata](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/package.json#L1),
[npm package](https://www.npmjs.com/package/@earendil-works/pi-coding-agent/v/0.85.1),
[RPC documentation](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/rpc.md).

Notation: `?` means the JSON property may be absent; `T|null` means explicit null is allowed. JavaScript `undefined` properties disappear in JSON objects, including fields declared required-but-undefined in TypeScript. `JSON` means recursively arbitrary JSON; number includes integer or float. Optional command arguments should be omitted rather than serialized as null: none of the 33 declared commands accepts a nullable argument. Every command allows optional string `id`; the Python client should always assign one.

## Complete command coverage

Every row is first-release support. Response envelope: `{type:"response", id?:string, command:string, success:true, data?:…}`. Every command can instead produce `{type:"response", id?:string, command:string, success:false, error:string}`. “Absent” means no `data` key. AcceptanceReceipt is a typed mapping of the successful prompt envelope, including its assigned ID; it conveys no run disposition. Proposed Python methods return the data (or unwrap a single list/scalar as noted), raise on unsuccessful responses, and preserve raw responses through the raw-command escape hatch.

Authoritative [command declarations](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-types.ts#L20), [response declarations](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-types.ts#L108), and [runtime dispatch](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-mode.ts#L394).

| Command | Arguments beyond type/id | Success `data` | Proposed Python method / return |
|---|---|---|---|
| prompt | message:string; images?:ImageContent[]; streamingBehavior?:"steer"/"followUp" | Absent | `prompt(message, *, images=None, streaming_behavior=None)` → AcceptanceReceipt |
| steer | message:string; images?:ImageContent[] | Absent | `steer(message, *, images=None)` → None |
| follow_up | message:string; images?:ImageContent[] | Absent | `follow_up(message, *, images=None)` → None |
| abort | None | Absent | `abort()` → None |
| clear_queue | None | {steering:string[], followUp:string[]} | `clear_queue()` → QueueState |
| new_session | parentSession?:string | {cancelled:boolean} | `new_session(*, parent_session=None)` → SessionChangeResult |
| get_state | None | RpcSessionState | `get_state()` → SessionState |
| set_model | provider:string; modelId:string | Model | `set_model(provider, model_id)` → Model |
| cycle_model | None | {model:Model, thinkingLevel:ThinkingLevel, isScoped:boolean} or null | `cycle_model()` → ModelCycleResult or None |
| get_available_models | None | {models:Model[]} | `get_available_models()` → list[Model] |
| set_thinking_level | level:ThinkingLevel | Absent | `set_thinking_level(level)` → None |
| cycle_thinking_level | None | {level:ThinkingLevel} or null | `cycle_thinking_level()` → ThinkingLevel or None |
| get_available_thinking_levels | None | {levels:ThinkingLevel[]} | `get_available_thinking_levels()` → list[ThinkingLevel] |
| set_steering_mode | mode:QueueMode | Absent | `set_steering_mode(mode)` → None |
| set_follow_up_mode | mode:QueueMode | Absent | `set_follow_up_mode(mode)` → None |
| compact | customInstructions?:string | CompactionResult | `compact(*, custom_instructions=None)` → CompactionResult |
| set_auto_compaction | enabled:boolean | Absent | `set_auto_compaction(enabled)` → None |
| set_auto_retry | enabled:boolean | Absent | `set_auto_retry(enabled)` → None |
| abort_retry | None | Absent | `abort_retry()` → None |
| bash | command:string; excludeFromContext?:boolean | BashResult | `bash(command, *, exclude_from_context=None)` → BashResult |
| abort_bash | None | Absent | `abort_bash()` → None |
| get_session_stats | None | SessionStats | `get_session_stats()` → SessionStats |
| export_html | outputPath?:string | {path:string} | `export_html(*, output_path=None)` → str |
| switch_session | sessionPath:string | {cancelled:boolean} | `switch_session(session_path)` → SessionChangeResult |
| fork | entryId:string | {text?:string, cancelled:boolean}; declaration requires text, runtime omits it on veto | `fork(entry_id)` → ForkResult |
| clone | None | {cancelled:boolean} | `clone()` → SessionChangeResult |
| get_fork_messages | None | {messages:[{entryId:string,text:string}]} | `get_fork_messages()` → list[ForkMessage] |
| get_entries | since?:string | {entries:SessionEntry[], leafId:string or null} | `get_entries(*, since=None)` → EntriesResult |
| get_tree | None | {tree:SessionTreeNode[], leafId:string or null} | `get_tree()` → TreeResult |
| get_last_assistant_text | None | {text?:string or null}; declaration requires nullable text, runtime omits it when absent | `get_last_assistant_text()` → str or None |
| set_session_name | name:string | Absent | `set_session_name(name)` → None |
| get_messages | None | {messages:AgentMessage[]} | `get_messages()` → list[AgentMessage] |
| get_commands | None | {commands:RpcSlashCommand[]} | `get_commands()` → list[SlashCommand] |

Behavior qualifiers: prompt success means preflight succeeded, including queueing or immediate extension handling; it does not carry a disposition telling the client whether a run will follow. Bash output has its own events, and an extension may provide the entire result immediately. `get_entries(since=...)` excludes the referenced entry and fails when that ID does not exist. `clone` fails when no leaf is selected. `set_session_name` trims and rejects empty names. `get_commands` enumerates registered extensions, prompt templates and skills, not built-in TUI slash commands. Runtime responses expose full Model values, despite the TS client's narrower ModelInfo return annotations.


### Command-to-event relationships

These are relationships, not one-event-per-response guarantees. Extensions
can emit additional notifications/errors during commands. Agent events are
session-scoped, so a client cannot allocate them to concurrent prompts by ID.
[RPC dispatch](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-mode.ts#L394),
[session event emission](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/agent-session.ts#L600).

| Commands | Related events / completion rule |
|---|---|
| prompt | May emit agent/turn/message/tool events, retries, compaction and eventual agent_settled; may only acknowledge handled input; may request UI before acknowledging |
| steer, follow_up, clear_queue | queue_update when queue state changes; queued input participates in the session's later run events |
| abort | May end retries/compaction/agent work; response waits for session idle; idle abort need not emit agent_settled |
| new_session, switch_session, fork, clone | Rebind session; extensions can veto; response and refreshed get_state establish identity, not an assumed switch event |
| set_model, cycle_model | May append model/thinking entries and emit thinking_level_changed; no public model_select RPC event |
| set_thinking_level, cycle_thinking_level | thinking_level_changed when changed; persistence does not imply an entry_appended event |
| set_session_name | session_info_changed when applied |
| compact | compaction_start/end and possible summarization retries; command response carries result/failure |
| set_auto_compaction, set_auto_retry, set_steering_mode, set_follow_up_mode | Response completes setting change; no required dedicated setting-change event |
| abort_retry | Interrupts retry handling; observe retry/settlement events as applicable, not a promised immediate agent completion |
| bash, abort_bash | bash_execution_update carries command ID; bash response has final result; extension-provided bash result can bypass streaming |
| get_state, get_messages, get_available_models, get_available_thinking_levels, get_session_stats, get_fork_messages, get_entries, get_tree, get_last_assistant_text, get_commands, export_html | Response-driven; do not await agent_settled for these operations |

## Complete output event surface

23 distinct session-event `type` values, plus `extension_error` and `extension_ui_request`. Every row has a required `type` discriminator equal to its event name. Most session events lack request IDs; only bash deltas carry an originating command ID. All are first-release parse/pass-through support; convenience properties should be limited to frequently used values such as text deltas.

Sources: [AgentEvent](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/agent/src/types.ts#L431), [AgentSessionEvent](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/agent-session.ts#L144), [JSON transformation](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/json-event.ts#L1), [extension error emission](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-mode.ts#L348).

| Event | Wire fields beyond type |
|---|---|
| agent_start | None |
| agent_end | messages:AgentMessage[]; willRetry:boolean |
| agent_settled | None |
| turn_start | None |
| turn_end | message:AgentMessage; toolResults:ToolResultMessage[] |
| message_start | message:AgentMessage |
| message_update | usage:Usage; assistantMessageEvent:JsonAssistantMessageEvent |
| message_end | message:AgentMessage |
| tool_execution_start | toolCallId:string; toolName:string; args:JSON |
| tool_execution_update | toolCallId:string; toolName:string; args:JSON; partialResult:JSON |
| tool_execution_end | toolCallId:string; toolName:string; result:JSON; isError:boolean |
| queue_update | steering:string[]; followUp:string[] |
| compaction_start | reason:"manual"/"threshold"/"overflow" |
| compaction_end | reason:CompactionReason; result?:CompactionResult; aborted:boolean; willRetry:boolean; errorMessage?:string |
| entry_appended | entry:SessionEntry |
| session_info_changed | name?:string |
| thinking_level_changed | level:ThinkingLevel |
| auto_retry_start | attempt:number; maxAttempts:number; delayMs:number; errorMessage:string |
| auto_retry_end | success:boolean; attempt:number; finalError?:string |
| summarization_retry_scheduled | attempt:number; maxAttempts:number; delayMs:number; errorMessage:string |
| summarization_retry_attempt_start | source:"branchSummary"; OR source:"compaction" and reason:CompactionReason |
| summarization_retry_finished | None |
| bash_execution_update | id?:string; delta:string |
| extension_error | extensionPath:string; event:string; error:string |
| extension_ui_request | id:string; method and fields in UI table below |

Tool `args`, `partialResult`, and `result` are explicitly `any` upstream. Model them as JSON, retaining the whole payload. The normal AgentToolResult shape is `{content:(TextContent|ImageContent)[], details:JSON, usage?:Usage, addedToolNames?:string[], terminate?:boolean}`, but that must not become a mandatory schema for every extension result. [AgentToolResult](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/agent/src/types.ts#L362).

`entry_appended` is declared with a general SessionEntry payload, but the
pinned runtime emits it from the extension `appendEntry` action. It is not
a complete change feed for all persisted messages, settings, and compactions.
Use `get_entries`/`get_tree` for authoritative session entries.
[Emission site](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/agent-session.ts#L2597).

### Nested assistant events

The in-memory `AssistantMessageEvent` is transformed before RPC serialization. **There is no outer `message` and no nested `partial` on RPC `message_update`.** It carries cumulative `usage`; `message_start` plus indexed deltas can construct live content, and `message_end.message` is authoritative. `toolcall_start` gains `id` and `toolName` from the omitted partial snapshot.

The declared nested union contains 12 variants, but the normal agent loop emits only the nine block events as `message_update`. It translates `start` into outer `message_start` and `done`/`error` into outer `message_end`. Accepting the broader declared union is inexpensive, but only nine should be advertised as normally emitted nested updates. [AssistantMessageEvent declaration](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/ai/src/types.ts#L546), [agent-loop transformation](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/agent/src/agent-loop.ts#L312).

| Nested type | Fields on wire beyond type |
|---|---|
| start | None |
| text_start | contentIndex:number |
| text_delta | contentIndex:number; delta:string |
| text_end | contentIndex:number; content:string |
| thinking_start | contentIndex:number |
| thinking_delta | contentIndex:number; delta:string |
| thinking_end | contentIndex:number; content:string |
| toolcall_start | contentIndex:number; id:string; toolName:string |
| toolcall_delta | contentIndex:number; delta:string |
| toolcall_end | contentIndex:number; toolCall:ToolCall |
| done | reason:"stop"/"length"/"toolUse"/"deferred"; message:AssistantMessage |
| error | reason:"aborted"/"error"; error:AssistantMessage |

### Extension UI

All requests have `type:"extension_ui_request"`, string `id`, and one of nine methods. A method name is wire spelling, not Python naming. Sources: [UI union](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-types.ts#L242), [runtime implementation](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-mode.ts#L132).

| Method | Payload beyond type/id/method | Client response |
|---|---|---|
| select | title:string; options:string[]; timeout?:number (ms) | value:string or cancelled:true |
| confirm | title:string; message:string; timeout?:number (ms) | confirmed:boolean or cancelled:true |
| input | title:string; placeholder?:string; timeout?:number (ms) | value:string or cancelled:true |
| editor | title:string; prefill?:string | value:string or cancelled:true |
| notify | message:string; notifyType?:"info"/"warning"/"error" | None |
| setStatus | statusKey:string; statusText?:string (absence clears) | None |
| setWidget | widgetKey:string; widgetLines?:string[] (absence clears); widgetPlacement?:"aboveEditor"/"belowEditor" | None |
| setTitle | title:string | None |
| set_editor_text | text:string | None |

Responses are separate stdin messages, not RpcCommand variants: `{type:"extension_ui_response",id:string,value:string}`, `{type:"extension_ui_response",id:string,confirmed:boolean}`, or `{type:"extension_ui_response",id:string,cancelled:true}`. Pi sends no normal RPC acknowledgment. Unknown or already expired dialog IDs are ignored. Select/input/confirm can expire or be aborted within Pi without a cancellation event to the client. Editor has no protocol timeout. Default missing-handler policy should cancel four dialog kinds; notification/display requests are delivered to consumers without answering.

Unsupported in Pi RPC, explicitly documented as out of scope for Python: raw terminal input; working message/visibility/indicator customization; hidden-thinking labels; widget component factories; custom header/footer/custom UI/editor components; autocomplete providers; theme discovery/switching; tool expansion. `getEditorText()` returns empty text; `pasteToEditor` becomes `set_editor_text`; theme getter supplies upstream's existing theme but cannot be controlled over RPC. These are runtime limitations, not missing Python features. [Unsupported UI behavior](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-mode.ts#L163).

## Public type inventory

Represent stable result/message shapes with modest dataclasses or typed mappings, preserve raw JSON/unknown fields, and tolerate unknown discriminators. Avoid generating a class hierarchy for every provider-specific field. Numeric timestamps in messages are Unix milliseconds; session-entry timestamps are strings.

### State, enums, results

- `ThinkingLevel`: `off|minimal|low|medium|high|xhigh|max`. Do not confuse pi-ai's ThinkingLevel (excludes off) with agent-core's union (includes off). `QueueMode`: `all|one-at-a-time`. `CompactionReason`: `manual|threshold|overflow`.
- `RpcSessionState`: model?:Model; thinkingLevel:ThinkingLevel; isStreaming:boolean; isCompacting:boolean; steeringMode:QueueMode; followUpMode:QueueMode; sessionFile?:string; sessionId:string; sessionName?:string; autoCompactionEnabled:boolean; messageCount:number; pendingMessageCount:number. There is no auto-retry state or full idle/settled flag. [State](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-types.ts#L89).
- `CompactionResult`: summary:string; firstKeptEntryId:string; tokensBefore:number; estimatedTokensAfter?:number; usage?:Usage; details?:JSON. [Source](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/compaction/compaction.ts#L88).
- `BashResult`: output:string; exitCode?:number; cancelled:boolean; truncated:boolean; fullOutputPath?:string. Exit code is omitted if killed/cancelled, not guaranteed null. [Source](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/bash-executor.ts#L29).
- `SessionStats`: sessionFile?:string; sessionId:string; userMessages:number; assistantMessages:number; toolCalls:number; toolResults:number; totalMessages:number; tokens:{input,output,cacheRead,cacheWrite,total:number}; cost:number; contextUsage?:ContextUsage. `ContextUsage`: tokens:number|null; contextWindow:number; percent:number|null. [Stats](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/agent-session.ts#L270), [ContextUsage](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/extensions/types.ts#L290).
- `RpcSlashCommand`: name:string; description?:string; source:`extension|prompt|skill`; sourceInfo:SourceInfo. `SourceInfo`: path:string; source:string; scope:`user|project|temporary`; origin:`package|top-level`; baseDir?:string. Skill names have `skill:` prefix. [Source metadata](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/source-info.ts#L1).

### Content, usage, messages

Source: [content and message definitions](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/ai/src/types.ts#L351), [coding-agent additions](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/messages.ts#L29), [diagnostics](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/ai/src/utils/diagnostics.ts#L1).

- `TextContent`: type:"text"; text:string; textSignature?:string.
- `ThinkingContent`: type:"thinking"; thinking:string; thinkingSignature?:string; redacted?:boolean.
- `ImageContent`: type:"image"; data:string (base64); mimeType:string.
- `ToolCall`: type:"toolCall"; id:string; name:string; arguments:object of JSON; thoughtSignature?:string; namespace?:string.
- `Usage`: input:number; output:number; cacheRead:number; cacheWrite:number; cacheWrite1h?:number; reasoning?:number; totalTokens:number; cost:{input,output,cacheRead,cacheWrite,total:number}. Reasoning is already included in output; don't double count.
- `StopReason`: `pending|stop|length|toolUse|error|aborted|deferred`.
- `DeferredHandle`: provider:string; modelId:string; api:string; id:string; expiresAt?:number; pollAfterMs?:number; data?:JSON.
- `AssistantMessageDiagnostic`: type:string; timestamp:number; error?:{name?:string,message:string,stack?:string,code?:string|number}; details?:object of JSON.
- `UserMessage`: role:"user"; content:string or (TextContent|ImageContent)[]; timestamp:number.
- `AssistantMessage`: role:"assistant"; content:(TextContent|ThinkingContent|ToolCall)[]; api:string; provider:string; model:string; responseModel?:string; responseId?:string; providerThinkingLevel?:string; diagnostics?:AssistantMessageDiagnostic[]; usage:Usage; stopReason:StopReason; deferred?:DeferredHandle; errorMessage?:string; rawStopReason?:string; endTurn?:boolean; timestamp:number.
- `ToolResultMessage`: role:"toolResult"; toolCallId:string; toolName:string; content:(TextContent|ImageContent)[]; details?:JSON; usage?:Usage; addedToolNames?:string[]; isError:boolean; timestamp:number.
- `BashExecutionMessage`: role:"bashExecution"; command:string; output:string; exitCode?:number; cancelled:boolean; truncated:boolean; fullOutputPath?:string; timestamp:number; excludeFromContext?:boolean.
- `CustomMessage`: role:"custom"; customType:string; content:string or (TextContent|ImageContent)[]; display:boolean; details?:JSON; timestamp:number.
- `BranchSummaryMessage`: role:"branchSummary"; summary:string; fromId:string|null; timestamp:number.
- `CompactionSummaryMessage`: role:"compactionSummary"; summary:string; tokensBefore:number; timestamp:number.

`AgentMessage` is these seven roles at this baseline; agent-core allows declaration merging, so preserve unknown roles too. Provider IDs and API IDs are open strings, not closed enums. Opaque signatures must be preserved unchanged.

### Session entries and tree

[Authoritative session types](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/session-manager.ts#L46). All nine entry variants have `type`, `id:string`, `parentId:string|null`, `timestamp:string` plus:

| Entry type | Additional fields |
|---|---|
| message | message:AgentMessage |
| thinking_level_change | thinkingLevel:string |
| model_change | provider:string; modelId:string |
| compaction | summary:string; firstKeptEntryId:string; tokensBefore:number; details?:JSON; usage?:Usage; fromHook?:boolean |
| branch_summary | fromId:string; summary:string; details?:JSON; usage?:Usage; fromHook?:boolean |
| custom | customType:string; data?:JSON |
| custom_message | customType:string; content:string or (TextContent\|ImageContent)[]; details?:JSON; display:boolean |
| label | targetId:string; label?:string |
| session_info | name?:string |

`SessionTreeNode`: entry:SessionEntry; children:SessionTreeNode[]; label?:string; labelTimestamp?:string. `get_entries` and `get_tree` expose entries, not raw session-file headers. The separate `SessionHeader` (`type:"session",version?:number,id:string,timestamp:string,cwd:string,parentSession?:string`) is not a returned SessionEntry. Do not accidentally require headers or build a session-file parser to satisfy RPC coverage.

### Model and provider metadata

[Model definition](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/ai/src/types.ts#L825): id:string; name:string; api:string; provider:string; baseUrl:string; reasoning:boolean; thinkingLevelMap?:partial map of ThinkingLevel to string|null; input:("text"|"image")[]; cost:ModelCost; contextWindow:number; maxTokens:number; samplingParams?:object of JSON; headers?:map string→string; compat?:provider-specific JSON object.

`ModelCost`: input,output,cacheRead,cacheWrite:number (USD per million tokens); tiers?:[{inputTokensAbove:number,input:number,output:number,cacheRead:number,cacheWrite:number}]. `thinkingLevelMap` missing keys mean provider defaults; null marks unsupported levels. Keep both states distinct.

The complete provider compatibility object should remain accessible as a typed JSON mapping, rather than duplicating Pi's provider implementation. Current declared field inventory follows; every listed field is optional. [Provider compatibility definitions](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/ai/src/types.ts#L568).

- OpenAI completions boolean fields: supportsStore, supportsDeveloperRole, supportsReasoningEffort, supportsUsageInStreaming, supportsFinishReason, requiresToolResultName, requiresAssistantAfterToolResult, requiresThinkingAsText, requiresReasoningContentOnAssistantMessages, zaiToolStream, supportsThinkingTokenBudget, supportsOpenAIGrammarTools, supportsStrictMode, sendSessionAffinityHeaders, supportsLongCacheRetention. Other fields: maxTokensField:`max_completion_tokens|max_tokens`; thinkingFormat:`openai|openrouter|deepseek|together|baseten|zai|qwen|chat-template|qwen-chat-template|string-thinking|ant-ling`; chatTemplateKwargs/chatTemplateArgs: maps of string/number/boolean/null or {$var:`thinking.enabled|thinking.effort|thinking.budget`,omitWhenOff?:boolean}; openRouterRouting:OpenRouterRouting; vercelGatewayRouting:VercelGatewayRouting; thinkingTokenBudgetField:`thinking_token_budget|thinking_budget|thinking_budget_tokens`; cacheControlFormat:"anthropic"; deferredToolsMode:"kimi"; sessionAffinityFormat:`openai|openai-nosession|openrouter`; vllmPriority:number.
- OpenAI responses boolean fields: supportsDeveloperRole, supportsLongCacheRetention, supportsStrictMode, supportsOpenAIGrammarTools, supportsAdditionalTools, supportsToolSearch, supportsExplicitPromptCacheMode, supportsMaxOutputTokens; plus sessionAffinityFormat as above.
- Anthropic boolean fields: supportsEagerToolInputStreaming, supportsLongCacheRetention, sendSessionAffinityHeaders, supportsCacheControlOnTools, supportsTemperature, forceAdaptiveThinking, allowEmptySignature, supportsStrictTools, supportsMidConvoEffort, supportsToolReferences; allowedFallbackModels?:[{provider:string,model:string,cost:ModelCost}] (retain raw JSON; no Python provider logic).
- Bedrock: supportsStrictMode?:boolean.
- OpenRouterRouting: allow_fallbacks?,require_parameters?,zdr?,enforce_distillable_text?:boolean; data_collection?:`deny|allow`; order?,only?,ignore?,quantizations?:string[]; sort?:string or {by?:string,partition?:string|null}; max_price?:{prompt?,completion?,image?,audio?,request?:number|string}; preferred_min_throughput?,preferred_max_latency?:number or {p50?,p75?,p90?,p99?:number}.
- VercelGatewayRouting: only?:string[]; order?:string[].

Raw Model metadata can contain configured headers; never use automatic repr/logging that dumps those mappings. This is directly observable in the declared Model shape, not a need to read private configuration.

## Declaration/documentation mismatches and design consequences

1. In-memory session events differ from JSON `message_update`; use `JsonAgentSessionEvent` as the wire reference. Copying generic AgentEvent types would be wrong.
2. The docs' event table omits `entry_appended`, `session_info_changed`, and `thinking_level_changed`, all emitted via the session subscription. Cover them anyway.
3. The docs' nested-delta table lists nine block events, whereas the declared union includes `start`, `done`, and `error`; the agent loop confirms the nine are the normal emitted subset, not a docs omission.
4. The docs' UserMessage example contains `attachments` and an Attachment section, but current UserMessage and RpcCommand declarations use content blocks/images instead. No Attachment API is required by this pinned protocol. [Doc examples](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/rpc.md#L1431).
5. Docs list only five stop reasons; source also declares `pending` and `deferred`. Example usage omits required `totalTokens`; do not infer schema from that example. The bash message example uses null for an optional path; actual undefined object fields are omitted by JSON serialization.
6. TS client `prompt()` omits supported streamingBehavior; `bash()` omits excludeFromContext; ModelInfo narrows full model response data. Python should cover the actual RPC surface rather than inherit those omissions. [Client methods](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-client.ts#L198).
7. TS event listener type excludes extension UI/error, but handleLine casts arbitrary non-response lines to that type. Python requires explicit UI/error/unknown event handling. [handleLine](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-client.ts#L516).
8. Protocol has no request-ID linkage for agent events, no generic version/capabilities command, no run-disposition response, no session list/tree navigation RPC command, no arbitrary tool registration RPC, and no shutdown RPC. Avoid inventing any of these while claiming upstream parity. Extensions can perform some additional actions internally, but that does not make them generic RPC commands.
9. The `get_commands` documentation examples use old `path`/`location` fields; runtime and declarations use required `sourceInfo`. The Python inventory follows sourceInfo. [Stale documentation section](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/rpc.md#L816).
10. `user_bash` and other extension hooks are internal extension events, not output RPC events. `bash_execution_update` is the streamed bash wire event. No Python `user_bash` subscription should be promised.
11. `get_last_assistant_text` declares required nullable text, but `getLastAssistantText()` returns undefined when there is no usable text; serialization emits `data:{}`. Accept both omission and null and normalize to Python None. Source and isolated probe agree. [Return implementation](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/agent-session.ts#L3473).
12. `fork` declares required text, but a vetoed runtime fork returns no selectedText, so RPC omits text. Model `ForkResult.text` as optional; do not reject a valid veto response. Source and isolated probe agree. [Fork veto](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/agent-session-runtime.ts#L259).

Completion counts to verify in implementation: 33 typed command methods; 23 session event discriminators; extension_error; 9 extension UI methods and 3 response variants; 12 accepted nested assistant variants; 7 known AgentMessage roles; 9 SessionEntry variants. A compact machine-checked coverage manifest is sufficient; no schema-generation framework is needed.


## Lifecycle findings and proposed behavior contract

### Follow the TS client selectively

**Source:** The reference client has one child process, a pending-request map,
event listeners, IDs assigned before writes, and helpers that subscribe before
prompting. These are useful concepts to preserve.

It also uses a 100 ms startup sleep, buffers/prints stderr, ignores parser
exceptions in its event handler, and only checks `success` inside `getData`.
Void methods such as `prompt` await `send` without that check. Its event
waiters depend on events/timeouts, while child exit rejects pending requests.
These observations justify readiness probes, centralized response checking,
explicit parser errors, bounded optional diagnostics, and failure propagation
to both requests and event waiters in Python. They are source observations,
not reproduced bug reports.
[Start](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-client.ts#L74),
[helpers/routing](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-client.ts#L459),
[response checking](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-client.ts#L599).

### Acceptance, run start, and settlement

**Source:** RPC emits a successful prompt response after preflight succeeds.
The session first executes extension commands, then input handlers; either
can handle input and return without starting an agent. An extension command
that throws emits `extension_error` and is still treated as handled.
Normal execution acknowledges before entering `_runAgentPrompt`.
[Prompt handling](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/agent-session.ts#L1159),
[extension error handling](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/agent-session.ts#L1322).

**Source:** The active session run includes automatic retries, compaction
continuations and queued follow-ups. `agent_settled` is emitted after that
loop. `get_state` exposes streaming and compaction flags but no request-linked
run-disposition field. A point-in-time idle response cannot prove that an
extension has not scheduled future work.
[Run loop](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/agent-session.ts#L1105),
[settlement](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/agent-session.ts#L629).

**Decision:** Reserve `prompt` for acceptance. Let `run`/`stream` explicitly
expect a run, subscribe before submission, and use a configurable start
deadline. A missed start deadline reports uncertainty, not a successful
no-op. Close the owned process after this failure to prevent delayed execution
escaping ownership. Users of handled commands use `prompt` plus an event
subscription. The 30-second proposed deadline is library policy, not a Pi
guarantee; review it with the interface.

### Concurrency and cancellation

**Source:** Incoming lines call `handleInputLine` without awaiting the previous
line; request IDs permit interleaving, but most events have no request ID.
Serialize bytes while allowing control requests and UI replies through.
[Input routing](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-mode.ts#L755).

**Source/documented:** `abort` cancels retries, compaction, branch summaries,
and agent execution, then waits for idle; `clear_queue` is separate. Bash has
its own abort command. New/switch/fork operations go through the runtime host
and can be vetoed. Do not assume that a successful command always changes
session identity.
[Abort](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/core/agent-session.ts#L1619),
[session dispatch](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-mode.ts#L599).

**Decision:** One owned high-level run per client. Preserve direct `abort`
semantics. A cancelled owned run explicitly clears queued work and aborts;
hold ownership until bounded cleanup ends, then close on uncertainty. Reject
conflicting session/model changes during owned runs. No automatic replay
after write/response timeout. Invalidate identity on uncertain session changes.

### Framing and process ownership

**Source:** `jsonl.ts` splits only LF, strips trailing CR, decodes fragmented
UTF-8, and accepts a final unterminated complete record at EOF. Match that
framing, while reporting malformed or incomplete JSON instead of hiding it.
[Framer](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/jsonl.ts#L1).

**Source:** stdin EOF disposes the runtime; SIGTERM/SIGHUP have cleanup paths.
There is no shutdown RPC command. Close stdin and wait briefly before
escalating, and fail all pending operations if the child exits unexpectedly.
[Shutdown](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/modes/rpc/rpc-mode.ts#L724).

**Decision:** Use one asyncio subprocess implementation and a sync facade
over a persistent event loop. Windows subprocess support requires a compatible
event loop, and executable-shim behavior needs CI verification. A private
event loop is appropriate for the sync facade; do not use per-call
`asyncio.run`. [Python subprocess reference](https://docs.python.org/3/library/asyncio-subprocess.html).

## Executed discovery probes

**Observed on Linux with Python 3.12 and installed Pi 0.85.1.** An ad-hoc
Python asyncio harness launched a fresh child in a temporary directory with
a temporary `PI_CODING_AGENT_DIR` and a minimal explicit environment containing
only PATH, the temporary configuration path, and NO_COLOR. It disabled tools,
automatic extensions, skills, templates, context files and themes, and loaded
one explicit synthetic extension. No live service was restarted and no model
or external provider call was made.

The extension registered three commands: one notified, one awaited
`ctx.ui.confirm` then notified, and one threw a fixed synthetic error. An
`input` handler returned `{action:"handled"}` for one fixed test message.
A `session_before_fork` handler vetoed the synthetic fork request.
The harness answered confirmation with a matching-ID
`extension_ui_response`, issued `get_state` after prompt responses, and
checked the records through that response. All checks below passed after
correcting one harness assumption about initial session entries.

| Probe | Observed result |
|---|---|
| get_state immediately after spawn | Readiness response succeeded |
| Initial state | sessionFile/sessionName absent; model present in this run |
| Unknown command with assigned ID | Failure preserved the request ID |
| Session name containing U+2028 and U+2029 | Round-tripped intact |
| get_commands with explicit extension | Fields name, description, source, sourceInfo |
| Notification-only extension command | notify request, successful prompt response; no agent start/settled before the following state response |
| Ordinary input consumed by handler | Successful prompt response; no agent start/settled before the following state response |
| Dialog extension command | confirm request before prompt response; matching reply unblocked it; notify then success |
| Throwing extension command | extension_error followed by a successful prompt response |
| Normal prompt without configured credentials | One failed preflight response; no model invocation |
| clear_queue and abort while idle | Both succeeded; empty queue returned |
| new_session followed by get_entries | Initial thinking_level_change entry and non-null leaf; a fresh session is not necessarily entry-free |
| get_last_assistant_text without assistant messages | data:{}; text omitted |
| fork vetoed by a synthetic session_before_fork handler | data:{cancelled:true}; text omitted |
| Closing stdin | Child exited with code 0 |

The first harness run incorrectly asserted that a new session's leaf must be
null; the observed initial thinking-level entry contradicted that assumption.
The corrected check accepts the declared nullable/string leaf and records
entry types. No runtime code was changed.

These probes establish these narrow cases, not a complete integration suite.
The no-start observations have source support above; absence within one
observation window alone would not prove a general no-future-run guarantee.
Live model streaming, retry timing, compaction, cross-platform behavior and
the future client remain untested during this discovery.

### Reproduction recipe

Use Pi 0.85.1, an empty temporary working/configuration directory, a minimal
environment without inherited credentials, and these startup arguments:

```text
pi --mode rpc --no-session --no-tools --no-extensions --no-skills
   --no-prompt-templates --no-context-files --no-themes --no-approve
   --extension <synthetic-extension.ts>
```

Keep stdin open between requests; send one JSON record per LF and assign a
unique ID. Synthetic extension behavior is described above; it needs no
provider implementation. The critical transcript is:

```json
{"type":"prompt","id":"dialog","message":"/discovery-dialog"}
{"type":"extension_ui_request","id":"<dialog-id>","method":"confirm","title":"Fixture","message":"Continue?"}
{"type":"extension_ui_response","id":"<dialog-id>","confirmed":true}
{"type":"extension_ui_request","id":"<notify-id>","method":"notify","message":"fixture-yes","notifyType":"info"}
{"type":"response","id":"dialog","command":"prompt","success":true}
```

The first/third records are sent to stdin; the other records arrive on stdout.
No normal response acknowledges the UI reply itself.

## Existing Python client comparison

**Private source/test-source evidence; not executed here.** The client owns
one persistent subprocess and provides a synchronous context manager,
start, blocking prompt, reset, abort, close, cached session identity, immutable
result/usage types, and distinct command/process/protocol/timeout/busy/turn
errors. One reader routes responses to request queues and events to a shared
queue. It does not expose the full RPC command surface or a public streaming
interface.

The inspected caller uses caller-owned lifetime, fresh sessions between
independent inputs, final text, stop reason, optional usage, elapsed time,
and session identity. Output-schema validation and tracing belong to the
application. The public interface should preserve that separation.

| Retain as independently implemented behavior | Reason |
|---|---|
| get_state readiness and request registration before writes | Avoid startup and immediate-response races |
| Strict byte framing and bounded writes | Correct Unicode and backpressure behavior |
| One active run, explicit abort/close from another thread | Predictable conversation ownership |
| agent_settled completion | Include retries and continuations |
| Identity invalidation/refresh during session changes | Avoid stale attribution after ambiguous failures |
| Result identity/time snapshots and uncertain usage preserved as unknown | Useful application results without fabricated measurements |
| Idempotent shutdown that wakes pending work | Reliable context-manager lifecycle |

Keep these existing policies out of the public defaults: fixed model/provider,
disabled normal Pi discovery, cleared prompts, tool restrictions, ephemeral
sessions, a pinned goal extension, command-name/notification matching, and
a short grace period used to guess extension completion. Keep capture sinks,
raw-process encodings, trace storage and application validation outside the core.

Source-observed weaknesses to address, not reproduced bug claims: unbounded
event accumulation, stale last-answer fallback when a run emits no assistant
message, incomplete general interrupt cleanup, selector-based pipe portability,
no generic dialog handler, potentially blocking duplicate-response dispatch,
and reader failure not immediately guaranteeing process termination.
Retain requirements from existing tests, not their private implementations.

| Existing concept | Public interface |
|---|---|
| PiRpcSession | PiClient / AsyncPiClient |
| Blocking prompt | run |
| reset | new_session |
| PiTurn | RunResult, since settlement may span multiple turns |
| Session/usage/time properties | Result snapshots and explicit current state |
| Abort that clears queues | Separate public abort/clear_queue; explicit owned-run cleanup policy |

## Evidence-to-test map

Test-source references below were inspected, not run. They define useful
scenarios to re-create through the new public Python interface.

| Requirement | Evidence now | Implementation acceptance test |
|---|---|---|
| Framing, CRLF, Unicode separators, final EOF record | Source + Unicode probe + upstream JSONL tests | Fake executable fragments bytes and sends oversized/invalid/EOF records |
| Command acceptance and single authoritative response | Source + preflight/handled-input probes + prompt tests | Success/rejection/queued/handled cases, including events before acknowledgement |
| Full settlement | Source + settlement regression test source | Faux provider retries and queued follow-ups emit one final settled event |
| Compaction interaction | Regression test source | Prompt rejected during manual compaction; abort ends compaction |
| Request IDs and process failure | Probe + unknown-command/process-exit test source | Unknown, duplicate, late IDs and process death wake correct callers |
| Extension UI | Runtime source + confirmation probe | All four dialog methods, cancellation, timeout, late replies and five display methods |
| All command methods/results | Complete declarations and runtime dispatch | Parameter forwarding plus real Pi fixtures for every command; preserve veto/null/omission |
| Message/entry/model types | Referenced source and wire serializer | Fixtures cover all known discriminators and tolerate new metadata |
| No-start uncertainty | Source + handled-input/command probes | Start deadline surfaces acceptance uncertainty and closes process; no guessed result |
| Cancellation and slow consumers | Proposed contract; private test-source precedent | Deterministic blocked writes, overflow, early stream exit, async cancellation and sync Ctrl-C |
| Session identity and usage | Source and private test-source precedent | Failed switches invalidate cache; no stale result fallback or cumulative-delta double counting |
| Sync facade/platform support | Proposed design, not tested | Async/sync parity plus Linux/macOS/Windows subprocess tests |

Pinned test sources:
[JSONL](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/test/rpc-jsonl.test.ts),
[prompt responses](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/test/rpc-prompt-response-semantics.test.ts),
[settlement/retries](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/test/suite/regressions/6363-agent-settled-event.test.ts),
[compaction rejection](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/test/suite/regressions/7150-rpc-prompt-during-compaction.test.ts),
[unknown IDs](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/test/suite/regressions/5868-rpc-unknown-command-id.test.ts),
[process exit](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/test/rpc-client-process-exit.test.ts).

The upstream broad `rpc.test.ts` suite is credential-gated and includes model
calls; it was not executed or treated as an offline validation suite.
[Test setup](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/test/rpc.test.ts#L15).

## Packaging and maintenance decisions

Use standard pyproject/src packaging with typed exports and wheel/sdist
validation. Link package metadata to this actual public repository. Use
GitHub Release-driven PyPI Trusted Publishing after explicit publication
authorization. [Packaging](https://packaging.python.org/en/latest/tutorials/packaging-projects/),
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/).

Pin the real Pi test runtime in a private npm fixture manifest. Dependabot
can then open runtime upgrade PRs using its npm ecosystem support; it cannot
update an unrelated globally installed CLI on its own. Python dev/build
dependencies and Actions get their own entries. A daily latest-stable
integration job provides independent detection. These are proposed workflows,
not active automation. Scheduled public-repository workflows can be delayed
or disabled after inactivity, so include manual dispatch and maintenance
instructions. [Dependabot](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference),
[Actions schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

Stable 0.85.1 equals the inspected baseline today; older compatibility is not
proven. Recent source changelog entries show why drift checks must include the
wire serializer: cumulative message snapshots were removed in 0.84.0, while
the reference docs still contain some old examples. Do not promise arbitrary
historical versions or automatically bless new ones.
[Pinned changelog](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/CHANGELOG.md#L300).

## Design and release considerations

- Review public method/result names, the 30-second expected-start deadline,
  cancellation behavior, and default buffer limits. They are library policy.
- Exact Windows shim resolution and event-loop behavior require implementation
  CI, not assumptions from Linux or the old selector-based client.
- Version metadata is CLI-level; there is no protocol capabilities handshake.
  Define behavior for custom executable wrappers and unknown newer versions.
- No protocol can prove a consumed prompt will never schedule future work.
  Keep submission usable and uncertainty explicit rather than inventing
  per-extension heuristics.
- Package name availability must be rechecked and the owner must choose the
  final license/release settings before publication.
- Source coverage does not prove full runtime correctness. Validate with
  fake-process tests, real-Pi offline integration, and opt-in model smoke tests.
