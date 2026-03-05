"""Result types for process execution outcomes."""

from __future__ import annotations

import uuid
import traceback as tb_module
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

__all__ = ["ProcessResult", "Failure", "FailurePolicy", "FailureReport", "RetryPolicy"]


@dataclass(frozen=True)
class Failure:
    """Represents a failed process execution with full diagnostic context."""

    error: Exception
    process_name: str = "unknown"
    process_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime | None = None
    failed_at: datetime = field(default_factory=datetime.now)
    placement: Any | None = None
    parent_process: str | None = None
    channel_state: dict = field(default_factory=dict)
    checkpoint: Any | None = None
    traceback_str: str = ""

    @property
    def elapsed(self) -> timedelta | None:
        if self.started_at is not None:
            return self.failed_at - self.started_at
        return None

    @property
    def summary(self) -> str:
        err_type = type(self.error).__name__
        return f"[{self.process_name}] {err_type}: {self.error}"

    @property
    def detailed(self) -> str:
        lines = [
            f"Process: {self.process_name} ({self.process_id})",
            f"Error: {type(self.error).__name__}: {self.error}",
            f"Failed at: {self.failed_at}",
        ]
        if self.started_at:
            lines.append(f"Started at: {self.started_at}")
            lines.append(f"Elapsed: {self.elapsed}")
        if self.parent_process:
            lines.append(f"Parent: {self.parent_process}")
        if self.placement:
            lines.append(f"Placement: {self.placement}")
        if self.channel_state:
            lines.append(f"Channel state: {self.channel_state}")
        if self.checkpoint:
            lines.append(f"Checkpoint: {self.checkpoint}")
        if self.traceback_str:
            lines.append(f"Traceback:\n{self.traceback_str}")
        return "\n".join(lines)


@dataclass(frozen=True)
class ProcessResult:
    """Represents the outcome of a process execution."""

    _ok: bool
    _value: Any = None
    _failure: Failure | None = None

    @classmethod
    def ok(cls, value: Any = None) -> ProcessResult:
        return cls(_ok=True, _value=value)

    @classmethod
    def fail(cls, error: Exception, **context: Any) -> ProcessResult:
        if "traceback_str" not in context:
            context["traceback_str"] = tb_module.format_exc()
        failure = Failure(error=error, **context)
        return cls(_ok=False, _failure=failure)

    @property
    def is_ok(self) -> bool:
        return self._ok

    @property
    def is_fail(self) -> bool:
        return not self._ok

    @property
    def value(self) -> Any:
        if self.is_fail:
            raise self._failure.error
        return self._value

    @property
    def failure(self) -> Failure:
        if self.is_ok:
            raise AttributeError("Cannot access failure on a successful result")
        return self._failure


@dataclass
class RetryPolicy:
    """Configuration for retry behavior."""

    max_attempts: int
    backoff: str = "exponential"
    base_delay: float = 1.0

    def delay_for(self, attempt: int) -> float:
        if self.backoff == "exponential":
            return self.base_delay * (2 ** attempt)
        elif self.backoff == "linear":
            return self.base_delay * (attempt + 1)
        else:  # constant
            return self.base_delay


class FailurePolicy(Enum):
    """Defines how failures in child processes are handled."""

    HALT = "halt"
    COLLECT = "collect"

    @classmethod
    def retry(
        cls,
        max_attempts: int,
        backoff: str = "exponential",
        base_delay: float = 1.0,
    ) -> RetryPolicy:
        return RetryPolicy(
            max_attempts=max_attempts,
            backoff=backoff,
            base_delay=base_delay,
        )


@dataclass
class FailureReport:
    """Aggregated analysis of process execution results."""

    total_processes: int = 0
    succeeded: int = 0
    failed: int = 0
    failures: list[Failure] = field(default_factory=list)

    @property
    def failure_rate(self) -> float:
        if self.total_processes == 0:
            return 0.0
        return self.failed / self.total_processes

    @property
    def common_failure_types(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.failures:
            name = type(f.error).__name__
            counts[name] = counts.get(name, 0) + 1
        return counts

    @property
    def slowest_failure(self) -> Failure | None:
        with_elapsed = [f for f in self.failures if f.elapsed is not None]
        if not with_elapsed:
            return None
        return max(with_elapsed, key=lambda f: f.elapsed)

    def add(self, result: ProcessResult) -> None:
        self.total_processes += 1
        if result.is_ok:
            self.succeeded += 1
        else:
            self.failed += 1
            self.failures.append(result.failure)

    def _add_failure(self, failure: Failure) -> None:
        self.total_processes += 1
        self.failed += 1
        self.failures.append(failure)

    def pattern_analysis(self) -> dict:
        from stbass.timer import TimerExpired

        # repeat_timeouts: processes with multiple TimerExpired failures
        timeout_counts: dict[str, int] = {}
        for f in self.failures:
            if isinstance(f.error, TimerExpired):
                timeout_counts[f.process_name] = timeout_counts.get(f.process_name, 0) + 1
        repeat_timeouts = [pname for pname, count in timeout_counts.items() if count >= 2]

        # repeat_errors: (process_name, error_type) pairs occurring >= 2 times
        error_counts: dict[tuple[str, str], int] = {}
        for f in self.failures:
            key = (f.process_name, type(f.error).__name__)
            error_counts[key] = error_counts.get(key, 0) + 1
        repeat_errors = [key for key, count in error_counts.items() if count >= 2]

        # cascade_failures: consecutive failures < 100ms apart
        cascade = False
        if len(self.failures) >= 2:
            sorted_failures = sorted(self.failures, key=lambda f: f.failed_at)
            for i in range(1, len(sorted_failures)):
                delta = sorted_failures[i].failed_at - sorted_failures[i - 1].failed_at
                if delta.total_seconds() < 0.1:
                    cascade = True
                    break

        return {
            "repeat_timeouts": repeat_timeouts,
            "repeat_errors": repeat_errors,
            "cascade_failures": cascade,
        }

    def recommendations(self) -> list[str]:
        from stbass.timer import TimerExpired

        recs: list[str] = []
        patterns = self.pattern_analysis()

        # Timeout recommendations
        timeout_counts: dict[str, int] = {}
        for f in self.failures:
            if isinstance(f.error, TimerExpired):
                timeout_counts[f.process_name] = timeout_counts.get(f.process_name, 0) + 1
        for pname, count in timeout_counts.items():
            recs.append(
                f"Process '{pname}' timeout {count}/{self.total_processes} runs "
                f"— consider increasing deadline or optimizing"
            )

        # Repeated error recommendations
        error_counts: dict[tuple[str, str], int] = {}
        for f in self.failures:
            if not isinstance(f.error, TimerExpired):
                key = (f.process_name, type(f.error).__name__)
                error_counts[key] = error_counts.get(key, 0) + 1
        for (pname, etype), count in error_counts.items():
            if count >= 2:
                recs.append(
                    f"Process '{pname}' consistently fails with {etype} — check input validation"
                )

        # Cascade recommendation
        if patterns["cascade_failures"]:
            recs.append(
                "Cascade failure detected — consider adding FailurePolicy.COLLECT to isolate"
            )

        return recs

    def to_dict(self) -> dict:
        return {
            "total_processes": self.total_processes,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "failure_rate": self.failure_rate,
            "failures": [
                {
                    "process_name": f.process_name,
                    "error_type": type(f.error).__name__,
                    "error_message": str(f.error),
                }
                for f in self.failures
            ],
        }

    def summary(self) -> str:
        lines = [
            f"Total: {self.total_processes}, Succeeded: {self.succeeded}, Failed: {self.failed}",
            f"Failure rate: {self.failure_rate:.1%}",
        ]
        if self.failures:
            lines.append("Failure types: " + ", ".join(
                f"{k}={v}" for k, v in self.common_failure_types.items()
            ))
        return "\n".join(lines)
