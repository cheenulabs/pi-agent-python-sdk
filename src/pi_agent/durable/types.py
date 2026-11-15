"""Durable protocol v0 wire dictionaries and results; upstream data stays opaque."""

from __future__ import annotations

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


@dataclass(frozen=True)
class WatchUpdate:
    entries: list[dict[str, Any]]
    live: dict[str, Any] | None
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
