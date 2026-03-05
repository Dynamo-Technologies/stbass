"""Timer and deadline primitives for time-bounded operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

__all__ = ["TIMER", "DEADLINE", "TimerExpired"]


@dataclass(frozen=True)
class TimerExpired:
    """Value produced when a timer or deadline fires."""

    started_at: datetime
    deadline: datetime
    elapsed: timedelta
    timer_name: str = ""
    last_checkpoint: Any | None = None


class TIMER:
    """A timer that fires after a specified duration."""

    def __init__(self, *, seconds: float, name: str | None = None):
        self.seconds = seconds
        self.name = name or f"timer_{uuid.uuid4().hex[:8]}"
        self.is_expired = False


class DEADLINE:
    """A deadline that fires at a specific point in time."""

    def __init__(self, target: datetime, *, name: str | None = None):
        self.target = target
        self.name = name or f"deadline_{uuid.uuid4().hex[:8]}"
        self.is_expired = False

    @property
    def remaining(self) -> timedelta:
        return self.target - datetime.now()

    @property
    def seconds(self) -> float:
        """Remaining seconds until deadline (for ALT integration)."""
        return max(0.0, self.remaining.total_seconds())
