"""Opt-in process output delivery; storage and forwarding belong to callers."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Literal

from ._events import _Subscription
from .errors import PiSubscriptionOverflow
from .types import Limits


@dataclass(frozen=True)
class ProcessOutput:
    """Original bytes received from the RPC child (never the version probe)."""

    source: Literal["stderr"]
    time_ns: int
    data: bytes = field(repr=False)


@dataclass(frozen=True)
class ObservationStatus:
    """Delivery coverage, independent of RPC success and consumer storage."""

    started_at_ns: int | None = None
    ended_at_ns: int | None = None
    from_start: bool = False
    complete: bool = False
    lost: bool = False
    stderr_eof: bool = False
    error: Exception | None = field(default=None, repr=False)


class ProcessObservation(_Subscription[ProcessOutput]):
    """Bounded output iterator. Check status after draining to detect incomplete output."""

    def __init__(
        self,
        limits: Limits,
        register: Callable[[ProcessObservation], None],
        unregister: Callable[[ProcessObservation], None],
    ) -> None:
        super().__init__(limits, lambda: register(self), lambda: unregister(self))
        self._status = ObservationStatus()

    @property
    def status(self) -> ObservationStatus:
        return self._status

    def _finish(self, error: Exception | None = None) -> None:
        if not self._closed and self._status.ended_at_ns is None:
            self._status = ObservationStatus(
                started_at_ns=self._status.started_at_ns,
                ended_at_ns=time.time_ns(),
                from_start=self._status.from_start,
                lost=self._status.lost or isinstance(error, PiSubscriptionOverflow),
                error=error,
            )
        super()._finish(error)

    def _discard(self) -> None:
        if self._records:
            self._status = replace(self._status, complete=False, lost=True)
        super()._discard()
