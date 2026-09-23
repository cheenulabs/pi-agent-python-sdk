"""Pi 0.87.0 wire annotations and small Python conveniences.

Wire fields retain Pi's spelling and remain ordinary dictionaries. These
annotations describe known shapes, not a recursive runtime validator: extensions
and newer runtimes may add fields and discriminators. Provider compatibility
metadata is deliberately opaque JSON. See docs/discovery.md for pinned sources.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from typing import Any, Literal, NotRequired, TypeAlias, TypedDict

from .errors import PiProtocolError

JSONValue: TypeAlias = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject: TypeAlias = dict[str, JSONValue]
RawRecord: TypeAlias = dict[str, Any]
ThinkingLevel: TypeAlias = Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]
QueueMode: TypeAlias = Literal["all", "one-at-a-time"]
StreamingBehavior: TypeAlias = Literal["steer", "followUp"]
CompactionReason: TypeAlias = Literal["manual", "threshold", "overflow"]
StopReason: TypeAlias = Literal[
    "pending", "stop", "length", "toolUse", "error", "aborted", "deferred"
]


class TextContent(TypedDict):
    type: Literal["text"]
    text: str
    textSignature: NotRequired[str]


class ThinkingContent(TypedDict):
    type: Literal["thinking"]
    thinking: str
    thinkingSignature: NotRequired[str]
    redacted: NotRequired[bool]


class ImageContent(TypedDict):
    type: Literal["image"]
    data: str
    mimeType: str


class ToolCall(TypedDict):
    type: Literal["toolCall"]
    id: str
    name: str
    arguments: JSONObject
    thoughtSignature: NotRequired[str]
    namespace: NotRequired[str]


class UsageCost(TypedDict):
    input: float
    output: float
    cacheRead: float
    cacheWrite: float
    total: float


class Usage(TypedDict):
    input: float
    output: float
    cacheRead: float
    cacheWrite: float
    cacheWrite1h: NotRequired[float]
    reasoning: NotRequired[float]
    totalTokens: float
    cost: UsageCost


class DeferredHandle(TypedDict):
    provider: str
    modelId: str
    api: str
    id: str
    expiresAt: NotRequired[float]
    pollAfterMs: NotRequired[float]
    data: NotRequired[JSONValue]


class DiagnosticError(TypedDict):
    message: str
    name: NotRequired[str]
    stack: NotRequired[str]
    code: NotRequired[str | float]


class AssistantMessageDiagnostic(TypedDict):
    type: str
    timestamp: float
    error: NotRequired[DiagnosticError]
    details: NotRequired[JSONObject]


class ToolDefinition(TypedDict):
    name: str
    description: str
    parameters: JSONObject
    constrainedSampling: NotRequired[Literal[False] | JSONObject]


class ToolReference(TypedDict):
    name: str


class SystemMessage(TypedDict):
    role: Literal["system"]
    content: str | list[TextContent]
    sections: NotRequired[dict[str, str | None]]
    toolsAdded: NotRequired[list[ToolDefinition]]
    toolsRemoved: NotRequired[list[ToolReference]]
    timestamp: float


class UserMessage(TypedDict):
    role: Literal["user"]
    content: str | list[TextContent | ImageContent]
    timestamp: float


class AssistantMessage(TypedDict):
    role: Literal["assistant"]
    content: list[TextContent | ThinkingContent | ToolCall]
    api: str
    provider: str
    model: str
    responseModel: NotRequired[str]
    responseId: NotRequired[str]
    providerThinkingLevel: NotRequired[str]
    diagnostics: NotRequired[list[AssistantMessageDiagnostic]]
    usage: Usage
    stopReason: StopReason
    deferred: NotRequired[DeferredHandle]
    errorMessage: NotRequired[str]
    rawStopReason: NotRequired[str]
    endTurn: NotRequired[bool]
    timestamp: float


class ToolResultMessage(TypedDict):
    role: Literal["toolResult"]
    toolCallId: str
    toolName: str
    content: list[TextContent | ImageContent]
    details: NotRequired[JSONValue]
    usage: NotRequired[Usage]
    addedToolNames: NotRequired[list[str]]  # Legacy Pi 0.85.1 field.
    isError: bool
    timestamp: float


class BashExecutionMessage(TypedDict):
    role: Literal["bashExecution"]
    command: str
    output: str
    exitCode: NotRequired[float]
    cancelled: bool
    truncated: bool
    fullOutputPath: NotRequired[str]
    timestamp: float
    excludeFromContext: NotRequired[bool]


class CustomMessage(TypedDict):
    role: Literal["custom"]
    customType: str
    content: str | list[TextContent | ImageContent]
    display: bool
    details: NotRequired[JSONValue]
    timestamp: float


class BranchSummaryMessage(TypedDict):
    role: Literal["branchSummary"]
    summary: str
    fromId: str | None
    timestamp: float


class CompactionSummaryMessage(TypedDict):
    role: Literal["compactionSummary"]
    summary: str
    tokensBefore: float
    timestamp: float


AgentMessage: TypeAlias = (
    SystemMessage
    | UserMessage
    | AssistantMessage
    | ToolResultMessage
    | BashExecutionMessage
    | CustomMessage
    | BranchSummaryMessage
    | CompactionSummaryMessage
)


class ModelCostRates(TypedDict):
    input: float
    output: float
    cacheRead: float
    cacheWrite: float


class ModelCostTier(ModelCostRates):
    inputTokensAbove: float


class ModelCost(ModelCostRates):
    tiers: NotRequired[list[ModelCostTier]]


class ModelPromptCache(TypedDict, total=False):
    short: float
    long: float


class ModelImageResizeOptions(TypedDict, total=False):
    maxWidth: float
    maxHeight: float
    maxBytes: float
    jpegQuality: float


class ModelImageInputLimits(TypedDict, total=False):
    resize: ModelImageResizeOptions
    maxPerMessage: float
    maxPerRequest: float


class ModelInputLimits(TypedDict, total=False):
    maxRequestBytes: float
    images: ModelImageInputLimits


class Model(TypedDict):
    id: str
    name: str
    api: str
    provider: str
    baseUrl: str
    reasoning: bool
    thinkingLevelMap: NotRequired[dict[ThinkingLevel, str | None]]
    input: list[Literal["text", "image"]]
    inputLimits: NotRequired[ModelInputLimits]
    cost: ModelCost
    contextWindow: float
    maxTokens: float
    samplingParams: NotRequired[JSONObject]
    headers: NotRequired[dict[str, str]]
    compat: NotRequired[JSONObject]
    promptCache: NotRequired[ModelPromptCache]


class SessionState(TypedDict):
    model: NotRequired[Model]
    thinkingLevel: ThinkingLevel
    isStreaming: bool
    isCompacting: bool
    steeringMode: QueueMode
    followUpMode: QueueMode
    sessionFile: NotRequired[str]
    sessionId: str
    sessionName: NotRequired[str]
    autoCompactionEnabled: bool
    messageCount: float
    pendingMessageCount: float


class CompactionResult(TypedDict):
    summary: str
    firstKeptEntryId: str
    tokensBefore: float
    estimatedTokensAfter: NotRequired[float]
    usage: NotRequired[Usage]
    details: NotRequired[JSONValue]


class BashResult(TypedDict):
    output: str
    exitCode: NotRequired[float]
    cancelled: bool
    truncated: bool
    fullOutputPath: NotRequired[str]


class ContextUsage(TypedDict):
    tokens: float | None
    contextWindow: float
    percent: float | None


class SessionTokens(TypedDict):
    input: float
    output: float
    cacheRead: float
    cacheWrite: float
    total: float


class SessionStats(TypedDict):
    sessionFile: NotRequired[str]
    sessionId: str
    userMessages: float
    assistantMessages: float
    toolCalls: float
    toolResults: float
    totalMessages: float
    tokens: SessionTokens
    cost: float
    contextUsage: NotRequired[ContextUsage]


class SourceInfo(TypedDict):
    path: str
    source: str
    scope: Literal["user", "project", "temporary"]
    origin: Literal["package", "top-level"]
    baseDir: NotRequired[str]


class SlashCommand(TypedDict):
    name: str
    description: NotRequired[str]
    source: Literal["extension", "prompt", "skill"]
    sourceInfo: SourceInfo


class _EntryBase(TypedDict):
    id: str
    parentId: str | None
    timestamp: str


class MessageEntry(_EntryBase):
    type: Literal["message"]
    message: AgentMessage


class ThinkingLevelChangeEntry(_EntryBase):
    type: Literal["thinking_level_change"]
    thinkingLevel: str


class ModelChangeEntry(_EntryBase):
    type: Literal["model_change"]
    provider: str
    modelId: str


class UsageEntry(_EntryBase):
    type: Literal["usage"]
    kind: str
    provider: str
    model: str
    usage: Usage
    note: NotRequired[str]


class CompactionEntry(_EntryBase):
    type: Literal["compaction"]
    summary: str
    firstKeptEntryId: str
    tokensBefore: float
    details: NotRequired[JSONValue]
    usage: NotRequired[Usage]
    fromHook: NotRequired[bool]
    systemMessage: NotRequired[SystemMessage]


class BranchSummaryEntry(_EntryBase):
    type: Literal["branch_summary"]
    fromId: str
    summary: str
    details: NotRequired[JSONValue]
    usage: NotRequired[Usage]
    fromHook: NotRequired[bool]


class CustomEntry(_EntryBase):
    type: Literal["custom"]
    customType: str
    data: NotRequired[JSONValue]


class CustomMessageEntry(_EntryBase):
    type: Literal["custom_message"]
    customType: str
    content: str | list[TextContent | ImageContent]
    details: NotRequired[JSONValue]
    display: bool


# Keep the list arms separate so typing rejects mixed ToolCall and ImageContent lists.
ContextEditableContent: TypeAlias = (
    str | list[TextContent | ImageContent] | list[TextContent | ThinkingContent | ToolCall]
)


class ContextEditReplacement(TypedDict):
    content: ContextEditableContent


class ContextEditEntry(_EntryBase):
    type: Literal["context_edit"]
    targetId: str
    replacement: ContextEditReplacement | None


class LabelEntry(_EntryBase):
    type: Literal["label"]
    targetId: str
    label: NotRequired[str]


class SessionInfoEntry(_EntryBase):
    type: Literal["session_info"]
    name: NotRequired[str]


SessionEntry: TypeAlias = (
    MessageEntry
    | ThinkingLevelChangeEntry
    | ModelChangeEntry
    | UsageEntry
    | CompactionEntry
    | BranchSummaryEntry
    | CustomEntry
    | CustomMessageEntry
    | ContextEditEntry
    | LabelEntry
    | SessionInfoEntry
)


class SessionTreeNode(TypedDict):
    entry: SessionEntry
    children: list[SessionTreeNode]
    label: NotRequired[str]
    labelTimestamp: NotRequired[str]


class QueueState(TypedDict):
    steering: list[str]
    followUp: list[str]


class SessionChangeResult(TypedDict):
    cancelled: bool


class ForkResult(SessionChangeResult):
    # A veto omits text despite upstream's required-string declaration.
    text: NotRequired[str]


class ModelCycleResult(TypedDict):
    model: Model
    thinkingLevel: ThinkingLevel
    isScoped: bool


class ThinkingLevelCycleResult(TypedDict):
    level: ThinkingLevel


class ExportHtmlResult(TypedDict):
    path: str


class ForkMessage(TypedDict):
    entryId: str
    text: str


class EntriesResult(TypedDict):
    entries: list[SessionEntry]
    leafId: str | None


class TreeResult(TypedDict):
    tree: list[SessionTreeNode]
    leafId: str | None


class _CommandBase(TypedDict):
    id: NotRequired[str]


class PromptCommand(_CommandBase):
    type: Literal["prompt"]
    message: str
    images: NotRequired[list[ImageContent]]
    streamingBehavior: NotRequired[StreamingBehavior]


class QueueMessageCommand(_CommandBase):
    type: Literal["steer", "follow_up"]
    message: str
    images: NotRequired[list[ImageContent]]


class EmptyCommand(_CommandBase):
    """Commands with no arguments beyond the envelope."""

    type: Literal[
        "abort",
        "clear_queue",
        "get_state",
        "cycle_model",
        "get_available_models",
        "cycle_thinking_level",
        "get_available_thinking_levels",
        "abort_retry",
        "abort_bash",
        "get_session_stats",
        "clone",
        "get_fork_messages",
        "get_tree",
        "get_last_assistant_text",
        "get_messages",
        "get_commands",
    ]


class NewSessionCommand(_CommandBase):
    type: Literal["new_session"]
    parentSession: NotRequired[str]


class SetModelCommand(_CommandBase):
    type: Literal["set_model"]
    provider: str
    modelId: str


class SetThinkingLevelCommand(_CommandBase):
    type: Literal["set_thinking_level"]
    level: ThinkingLevel


class SetQueueModeCommand(_CommandBase):
    type: Literal["set_steering_mode", "set_follow_up_mode"]
    mode: QueueMode


class CompactCommand(_CommandBase):
    type: Literal["compact"]
    customInstructions: NotRequired[str]


class SetAutomaticCommand(_CommandBase):
    type: Literal["set_auto_compaction", "set_auto_retry"]
    enabled: bool


class BashCommand(_CommandBase):
    type: Literal["bash"]
    command: str
    excludeFromContext: NotRequired[bool]


class ExportHtmlCommand(_CommandBase):
    type: Literal["export_html"]
    outputPath: NotRequired[str]


class SwitchSessionCommand(_CommandBase):
    type: Literal["switch_session"]
    sessionPath: str


class ForkCommand(_CommandBase):
    type: Literal["fork"]
    entryId: str


class GetEntriesCommand(_CommandBase):
    type: Literal["get_entries"]
    since: NotRequired[str]


class SetSessionNameCommand(_CommandBase):
    type: Literal["set_session_name"]
    name: str


RpcCommand: TypeAlias = (
    PromptCommand
    | QueueMessageCommand
    | EmptyCommand
    | NewSessionCommand
    | SetModelCommand
    | SetThinkingLevelCommand
    | SetQueueModeCommand
    | CompactCommand
    | SetAutomaticCommand
    | BashCommand
    | ExportHtmlCommand
    | SwitchSessionCommand
    | ForkCommand
    | GetEntriesCommand
    | SetSessionNameCommand
)


class RpcSuccessResponse(TypedDict):
    type: Literal["response"]
    id: NotRequired[str]
    command: str
    success: Literal[True]
    data: NotRequired[JSONValue]


class RpcErrorResponse(TypedDict):
    type: Literal["response"]
    id: NotRequired[str]
    command: str
    success: Literal[False]
    error: str


RpcResponse: TypeAlias = RpcSuccessResponse | RpcErrorResponse


class AssistantStartEvent(TypedDict):
    type: Literal["start"]


class ContentStartEvent(TypedDict):
    type: Literal["text_start", "thinking_start"]
    contentIndex: float


class ContentDeltaEvent(TypedDict):
    type: Literal["text_delta", "thinking_delta", "toolcall_delta"]
    contentIndex: float
    delta: str


class ContentEndEvent(TypedDict):
    type: Literal["text_end", "thinking_end"]
    contentIndex: float
    content: str


class ToolCallStartEvent(TypedDict):
    type: Literal["toolcall_start"]
    contentIndex: float
    id: str
    toolName: str


class ToolCallEndEvent(TypedDict):
    type: Literal["toolcall_end"]
    contentIndex: float
    toolCall: ToolCall


class AssistantDoneEvent(TypedDict):
    type: Literal["done"]
    reason: Literal["stop", "length", "toolUse", "deferred"]
    message: AssistantMessage


class AssistantErrorEvent(TypedDict):
    type: Literal["error"]
    reason: Literal["aborted", "error"]
    error: AssistantMessage


AssistantMessageEvent: TypeAlias = (
    AssistantStartEvent
    | ContentStartEvent
    | ContentDeltaEvent
    | ContentEndEvent
    | ToolCallStartEvent
    | ToolCallEndEvent
    | AssistantDoneEvent
    | AssistantErrorEvent
)


class EmptySessionEvent(TypedDict):
    type: Literal["agent_start", "agent_settled", "turn_start", "summarization_retry_finished"]


class AgentEndEvent(TypedDict):
    type: Literal["agent_end"]
    messages: list[AgentMessage]
    willRetry: bool


class TurnEndEvent(TypedDict):
    type: Literal["turn_end"]
    message: AgentMessage
    toolResults: list[ToolResultMessage]


class MessageBoundaryEvent(TypedDict):
    type: Literal["message_start", "message_end"]
    message: AgentMessage


class MessageUpdateEvent(TypedDict):
    """Serialized shape: Pi removes cumulative message/partial snapshots."""

    type: Literal["message_update"]
    usage: Usage
    assistantMessageEvent: AssistantMessageEvent


class ToolExecutionStartEvent(TypedDict):
    type: Literal["tool_execution_start"]
    toolCallId: str
    toolName: str
    args: JSONValue


class ToolExecutionUpdateEvent(TypedDict):
    type: Literal["tool_execution_update"]
    toolCallId: str
    toolName: str
    args: JSONValue
    partialResult: JSONValue


class ToolExecutionEndEvent(TypedDict):
    type: Literal["tool_execution_end"]
    toolCallId: str
    toolName: str
    result: JSONValue
    isError: bool


class QueueUpdateEvent(QueueState):
    type: Literal["queue_update"]


class CompactionStartEvent(TypedDict):
    type: Literal["compaction_start"]
    reason: CompactionReason


class CompactionEndEvent(TypedDict):
    type: Literal["compaction_end"]
    reason: CompactionReason
    result: NotRequired[CompactionResult]
    aborted: bool
    willRetry: bool
    errorMessage: NotRequired[str]


class EntryAppendedEvent(TypedDict):
    type: Literal["entry_appended"]
    entry: SessionEntry


class SessionInfoChangedEvent(TypedDict):
    type: Literal["session_info_changed"]
    name: NotRequired[str]


class ThinkingLevelChangedEvent(TypedDict):
    type: Literal["thinking_level_changed"]
    level: ThinkingLevel


class RetryStartEvent(TypedDict):
    type: Literal["auto_retry_start", "summarization_retry_scheduled"]
    attempt: float
    maxAttempts: float
    delayMs: float
    errorMessage: str


class AutoRetryEndEvent(TypedDict):
    type: Literal["auto_retry_end"]
    success: bool
    attempt: float
    finalError: NotRequired[str]


class CompactionRetryAttemptEvent(TypedDict):
    type: Literal["summarization_retry_attempt_start"]
    source: Literal["compaction"]
    reason: CompactionReason


class BranchRetryAttemptEvent(TypedDict):
    type: Literal["summarization_retry_attempt_start"]
    source: Literal["branchSummary"]


class BashExecutionUpdateEvent(TypedDict):
    type: Literal["bash_execution_update"]
    id: NotRequired[str]
    delta: str


SessionEvent: TypeAlias = (
    EmptySessionEvent
    | AgentEndEvent
    | TurnEndEvent
    | MessageBoundaryEvent
    | MessageUpdateEvent
    | ToolExecutionStartEvent
    | ToolExecutionUpdateEvent
    | ToolExecutionEndEvent
    | QueueUpdateEvent
    | CompactionStartEvent
    | CompactionEndEvent
    | EntryAppendedEvent
    | SessionInfoChangedEvent
    | ThinkingLevelChangedEvent
    | RetryStartEvent
    | AutoRetryEndEvent
    | CompactionRetryAttemptEvent
    | BranchRetryAttemptEvent
    | BashExecutionUpdateEvent
)


class ExtensionErrorEvent(TypedDict):
    type: Literal["extension_error"]
    extensionPath: str
    event: str
    error: str


class _UIRequestBase(TypedDict):
    type: Literal["extension_ui_request"]
    id: str


class UISelectRequest(_UIRequestBase):
    method: Literal["select"]
    title: str
    options: list[str]
    timeout: NotRequired[float]


class UIConfirmRequest(_UIRequestBase):
    method: Literal["confirm"]
    title: str
    message: str
    timeout: NotRequired[float]


class UIInputRequest(_UIRequestBase):
    method: Literal["input"]
    title: str
    placeholder: NotRequired[str]
    timeout: NotRequired[float]


class UIEditorRequest(_UIRequestBase):
    method: Literal["editor"]
    title: str
    prefill: NotRequired[str]


class UINotifyRequest(_UIRequestBase):
    method: Literal["notify"]
    message: str
    notifyType: NotRequired[Literal["info", "warning", "error"]]


class UISetStatusRequest(_UIRequestBase):
    method: Literal["setStatus"]
    statusKey: str
    statusText: NotRequired[str]


class UISetWidgetRequest(_UIRequestBase):
    method: Literal["setWidget"]
    widgetKey: str
    widgetLines: NotRequired[list[str]]
    widgetPlacement: NotRequired[Literal["aboveEditor", "belowEditor"]]


class UISetTitleRequest(_UIRequestBase):
    method: Literal["setTitle"]
    title: str


class UISetEditorTextRequest(_UIRequestBase):
    method: Literal["set_editor_text"]
    text: str


ExtensionUIRequest: TypeAlias = (
    UISelectRequest
    | UIConfirmRequest
    | UIInputRequest
    | UIEditorRequest
    | UINotifyRequest
    | UISetStatusRequest
    | UISetWidgetRequest
    | UISetTitleRequest
    | UISetEditorTextRequest
)


class _UIResponseBase(TypedDict):
    type: Literal["extension_ui_response"]
    id: str


class UIValueResponse(_UIResponseBase):
    value: str


class UIConfirmResponse(_UIResponseBase):
    confirmed: bool


class UICancelResponse(_UIResponseBase):
    cancelled: Literal[True]


ExtensionUIResponse: TypeAlias = UIValueResponse | UIConfirmResponse | UICancelResponse
RpcEvent: TypeAlias = SessionEvent | ExtensionErrorEvent | ExtensionUIRequest


@dataclass(frozen=True)
class Event:
    """An unconverted event; raw preserves unknown fields and is omitted from repr."""

    raw: RawRecord = field(repr=False)

    @property
    def type(self) -> str:
        value = self.raw.get("type")
        return value if isinstance(value, str) else ""

    @property
    def text_delta(self) -> str | None:
        if self.type != "message_update":
            return None
        nested = self.raw.get("assistantMessageEvent")
        if isinstance(nested, dict) and nested.get("type") == "text_delta":
            delta = nested.get("delta")
            if not isinstance(delta, str):
                raise PiProtocolError("text_delta requires a string delta")
            return delta
        return None


@dataclass(frozen=True)
class SessionInfo:
    """Session identity snapshot; paths and names are omitted from repr."""

    session_id: str | None = None
    session_file: str | None = field(default=None, repr=False)
    session_name: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class UsageSummary:
    """Observed assistant usage, not total billing; None means unknown.

    Reasoning is a subset of output_tokens. It must not be added again.
    A field remains unknown if any observed assistant omitted that measurement.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cache_write_1h_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | None = None
    assistant_messages: int = 0


@dataclass(frozen=True)
class RunResult:
    """Finalized messages from one settled run, including partial failed work.

    Session is the identity current at completion, not an attribution of each
    event. Text and messages can contain sensitive content and are not in repr.
    """

    text: str = field(repr=False)
    messages: list[RawRecord] = field(repr=False)
    stop_reason: str | None
    session: SessionInfo
    elapsed_seconds: float
    usage: UsageSummary | None = None


def _validate_timeout(value: object, name: str = "timeout") -> None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        try:
            if math.isfinite(value):
                return
        except OverflowError:
            pass
    raise ValueError(f"{name} must be a positive finite number")


@dataclass(frozen=True)
class Limits:
    """Client deadlines (seconds) and bounded transport/subscription storage."""

    startup_timeout: float = 30.0
    command_timeout: float = 30.0
    run_start_timeout: float = 30.0
    cleanup_timeout: float = 5.0
    max_record_bytes: int = 16 * 1024 * 1024
    event_queue_size: int = 256
    event_queue_bytes: int = 16 * 1024 * 1024
    stderr_tail_bytes: int = 0
    result_message_count: int = 4096
    result_message_bytes: int = 64 * 1024 * 1024
    collection_event_count: int = 16_384
    collection_event_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        for descriptor in fields(self):
            name = descriptor.name
            value = getattr(self, name)
            if name.endswith("timeout"):
                _validate_timeout(value, name)
            elif (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < (0 if name == "stderr_tail_bytes" else 1)
            ):
                minimum = "nonnegative" if name == "stderr_tail_bytes" else "positive"
                raise ValueError(f"{name} must be a {minimum} integer")
