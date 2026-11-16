"""Durable protocol v0 wire dictionaries and results; upstream data stays opaque."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, NotRequired, TypedDict

ConversationId = int
SubmissionId = int
WhenBusy = Literal["followUp", "steer", "reject"]


@dataclass(frozen=True)
class SettledSubmission:
    status: Literal["done", "unanswered"]
    reason: str | None
    raw: dict[str, Any] = field(repr=False)

    @property
    def answer_id(self) -> int | None:
        """The settled answer's opaque entry ID, or None if no answer is present."""
        value = self.raw.get("answer")
        return value if isinstance(value, int) and not isinstance(value, bool) else None


def entry_text(entry: Mapping[str, Any]) -> str:
    """Read text from an entry's model messages without changing the entry.

    String content and text blocks are joined in order. Thinking, images,
    tool calls and malformed/unknown parts are ignored; no text yields "".
    """
    messages = entry.get("model")
    if not isinstance(messages, list):
        return ""
    text: list[str] = []
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        content = message.get("content")
        if isinstance(content, str):
            text.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, Mapping) and part.get("type") == "text":
                    value = part.get("text")
                    if isinstance(value, str):
                        text.append(value)
    return "".join(text)


@dataclass(frozen=True)
class WatchUpdate:
    entries: list[dict[str, Any]] = field(repr=False)
    live: dict[str, Any] | None = field(repr=False)
    gap: bool
    snapshot: bool
    raw: dict[str, Any] = field(repr=False)


class HelloFields(TypedDict):
    pass


class HelloData(TypedDict):
    protocol: int
    piDurable: str
    pid: int


class Storage(TypedDict):
    kind: Literal["sqlite", "memory"]
    path: NotRequired[str]


class OpenFields(TypedDict):
    storage: Storage
    codingTools: NotRequired[bool]
    models: NotRequired[Literal["pi", "builtin"]]
    piAgentDir: NotRequired[str]
    settings: NotRequired[dict[str, Any]]
    maxRecordBytes: NotRequired[int]
    faux: NotRequired[list[str | dict[str, Any]]]
    fauxTokensPerSecond: NotRequired[float]


class EmptyData(TypedDict):
    pass


OpenData = EmptyData
AbortData = EmptyData
WatchData = EmptyData
UnwatchData = EmptyData


class AgentOptions(TypedDict, total=False):
    model: dict[str, str]
    cwd: str
    thinkingLevel: str


class RootFields(TypedDict, total=False):
    agent: AgentOptions


class RootData(TypedDict):
    conversationId: ConversationId


class SubmitFields(TypedDict):
    conversationId: ConversationId
    content: str
    requestId: str
    whenBusy: NotRequired[WhenBusy]


class SubmitData(TypedDict):
    submissionId: SubmissionId


class WaitFields(TypedDict):
    submissionId: SubmissionId


class WaitData(TypedDict):
    submission: dict[str, Any]


class EntriesFields(TypedDict):
    conversationId: ConversationId
    limit: NotRequired[int]


class EntriesData(TypedDict):
    entries: list[dict[str, Any]]


class AbortFields(TypedDict):
    conversationId: ConversationId


class WatchFields(TypedDict):
    conversationId: ConversationId
    watchId: str


class UnwatchFields(TypedDict):
    watchId: str


class WatchEvent(TypedDict):
    type: Literal["durable_watch"]
    watchId: str
    entries: list[dict[str, Any]]
    live: dict[str, Any] | None
    gap: bool
    snapshot: bool


class WatchEndEvent(TypedDict):
    type: Literal["durable_watch_end"]
    watchId: str
    kind: str


class ReportEvent(TypedDict):
    type: Literal["durable_report"]
    report: dict[str, Any]


class ProtocolErrorEvent(TypedDict):
    type: Literal["durable_protocol_error"]
    code: str
    message: str
