"""Bounded, context-managed Durable watch subscriptions."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Self

from .._events import _Subscription
from .types import ConversationId, WatchUpdate

if TYPE_CHECKING:
    from .client import AsyncDurableClient


class WatchSubscription(_Subscription[WatchUpdate]):
    """A coalesced window, not a lossless log; recover gaps with entries()."""

    def __init__(self, client: AsyncDurableClient, conversation_id: ConversationId) -> None:
        self._client = client
        self._conversation_id = conversation_id
        self._watch_id = uuid.uuid4().hex
        self._unwatch_task: asyncio.Task[None] | None = None
        super().__init__(client.limits, self._attach, self._detach)

    def _attach(self) -> None:
        self._client._check_loop()
        self._client._watches[self._watch_id] = self

    def _detach(self) -> None:
        if self._client._watches.pop(self._watch_id, None) is self:
            self._unwatch_task = self._client._track_unwatch(self._watch_id)

    async def __aenter__(self) -> Self:
        self._enter()  # Register before writing; snapshot may precede request completion.
        try:
            await self._client._request(
                "watch",
                {"conversationId": self._conversation_id, "watchId": self._watch_id},
                self._client.limits.command_timeout,
            )
        except BaseException:
            # _detach schedules tracked cleanup outside the cancelled request task.
            self._discard()
            raise
        return self

    async def aclose(self) -> None:
        """Unregister immediately and best-effort unwatch, even after host failure."""
        self._discard()
        if self._unwatch_task is not None:
            await asyncio.shield(self._unwatch_task)
