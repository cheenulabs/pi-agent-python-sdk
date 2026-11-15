"""Blocking Durable methods delegated to the async client on the shared bridge."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

from .._sync_bridge import _SyncBridge
from ..client import DEFAULT_TIMEOUT, Timeout
from ..types import Limits
from .client import AsyncDurableClient
from .types import ConversationId, SettledSubmission, SubmissionId, WhenBusy


class DurableClient(_SyncBridge[AsyncDurableClient]):
    """Single-use synchronous Durable facade; use a context or start/close.

    Construction starts neither a thread nor a process. All protocol behavior
    lives in AsyncDurableClient. Blocking calls from the loop thread are rejected.
    """

    def __init__(
        self,
        storage_path: str | os.PathLike[str] | None,
        *,
        host_command: Sequence[str] | None = None,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str | None] | None = None,
        inherit_env: bool = True,
        limits: Limits | None = None,
        coding_tools: bool = True,
        settings: Mapping[str, Any] | None = None,
        faux: Sequence[str | Mapping[str, Any]] | None = None,
        faux_tokens_per_second: float | None = None,
    ) -> None:
        super().__init__(
            AsyncDurableClient(
                storage_path,
                host_command=host_command,
                cwd=cwd,
                env=env,
                inherit_env=inherit_env,
                limits=limits,
                coding_tools=coding_tools,
                settings=settings,
                faux=faux,
                faux_tokens_per_second=faux_tokens_per_second,
            )
        )

    @property
    def limits(self) -> Limits:
        return self._client.limits

    @property
    def running(self) -> bool:
        return self._client.running

    @property
    def host_pid(self) -> int | None:
        return self._client.host_pid

    @property
    def pi_durable_version(self) -> str | None:
        return self._client.pi_durable_version

    @property
    def stderr_tail(self) -> str:
        return self._client.stderr_tail

    def root(
        self,
        *,
        model: Mapping[str, str] | None = None,
        cwd: str | None = None,
        thinking_level: str | None = None,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> ConversationId:
        """Get/create the root; options apply only on its first creation."""
        return self._call(
            lambda: self._client.root(
                model=model, cwd=cwd, thinking_level=thinking_level, timeout=timeout
            )
        )

    def submit(
        self,
        conversation_id: ConversationId,
        content: str,
        *,
        request_id: str,
        when_busy: WhenBusy | None = None,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> SubmissionId:
        """Submit idempotently with a non-empty key scoped to the conversation."""
        return self._call(
            lambda: self._client.submit(
                conversation_id,
                content,
                request_id=request_id,
                when_busy=when_busy,
                timeout=timeout,
            )
        )

    def wait(
        self, submission_id: SubmissionId, *, timeout: float | None = None
    ) -> SettledSubmission:
        """Block for settlement; local timeout does not abort upstream work."""
        return self._call(lambda: self._client.wait(submission_id, timeout=timeout))

    def entries(
        self,
        conversation_id: ConversationId,
        *,
        limit: int = 50,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> list[dict[str, Any]]:
        """Read newest entries in oldest-to-newest order, preserving unknown fields."""
        return self._call(
            lambda: self._client.entries(conversation_id, limit=limit, timeout=timeout)
        )

    def abort(self, conversation_id: ConversationId, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
        """Abort upstream work and block until the conversation is idle."""
        self._call(lambda: self._client.abort(conversation_id, timeout=timeout))
