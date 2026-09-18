"""Incremental assistant accounting for core run results."""

from __future__ import annotations

import math
from typing import Any

from .types import UsageSummary

_TOKENS = {
    "input_tokens": "input",
    "output_tokens": "output",
    "cache_read_tokens": "cacheRead",
    "cache_write_tokens": "cacheWrite",
    "cache_write_1h_tokens": "cacheWrite1h",
    "reasoning_tokens": "reasoning",
    "total_tokens": "totalTokens",
}


class UsageAccumulator:
    """Keep only totals; a missing or invalid measurement stays unknown."""

    def __init__(self) -> None:
        self._totals: dict[str, int | None] = dict.fromkeys(_TOKENS, 0)
        self._cost: float | None = 0.0
        self._count = 0
        self._observed = False

    def add(self, message: dict[str, Any]) -> None:
        if message.get("role") != "assistant":
            return
        self._count += 1
        raw = message.get("usage")
        self._observed |= isinstance(raw, dict)
        usage = raw if isinstance(raw, dict) else {}
        for field, wire in _TOKENS.items():
            value = usage.get(wire)
            count = (
                value
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0
                else None
            )
            if field == "reasoning_tokens" and count is not None:
                output = usage.get("output")
                content = message.get("content")
                thinking = isinstance(content, list) and any(
                    isinstance(block, dict)
                    and block.get("type") == "thinking"
                    and block.get("thinking")
                    for block in content
                )
                valid = (
                    isinstance(output, int)
                    and not isinstance(output, bool)
                    and count <= output
                    and not (count == 0 and thinking)
                )
                if not valid:
                    count = None
            previous = self._totals[field]
            self._totals[field] = (
                previous + count if previous is not None and count is not None else None
            )
        cost = usage.get("cost")
        amount = cost.get("total") if isinstance(cost, dict) else None
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            try:
                amount = float(amount)
            except OverflowError:
                amount = None
        if (
            self._cost is not None
            and isinstance(amount, (int, float))
            and not isinstance(amount, bool)
            and math.isfinite(amount)
            and amount >= 0
        ):
            self._cost += amount
            if not math.isfinite(self._cost):
                self._cost = None
        else:
            self._cost = None

    def snapshot(self) -> UsageSummary | None:
        if not self._observed:
            return None
        return UsageSummary(**self._totals, cost=self._cost, assistant_messages=self._count)
