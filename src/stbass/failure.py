"""Failure aggregation and retry utilities for process compositions."""

from __future__ import annotations

import asyncio
from typing import Any

from stbass.process import Process, ProcessContext
from stbass.result import FailurePolicy, FailureReport, ProcessResult, RetryPolicy, Failure

__all__ = ["FailurePolicy", "FailureReport", "FailureAggregator", "retry_process"]


class FailureAggregator:
    """Collects FailureReports across multiple runs for ongoing analysis."""

    def __init__(self) -> None:
        self._reports: list[FailureReport] = []

    def add_report(self, report: FailureReport) -> None:
        self._reports.append(report)

    def overall_summary(self) -> str:
        total = sum(r.total_processes for r in self._reports)
        succeeded = sum(r.succeeded for r in self._reports)
        failed = sum(r.failed for r in self._reports)
        return (
            f"Across {len(self._reports)} reports: "
            f"{total} processes, {succeeded} succeeded, {failed} failed"
        )

    def worst_processes(self, n: int = 5) -> list[str]:
        process_failures: dict[str, int] = {}
        for report in self._reports:
            for f in report.failures:
                pname = f.process_name
                process_failures[pname] = process_failures.get(pname, 0) + 1
        sorted_procs = sorted(
            process_failures.keys(),
            key=lambda p: process_failures[p],
            reverse=True,
        )
        return sorted_procs[:n]


async def retry_process(
    process: Process,
    ctx: ProcessContext,
    policy: RetryPolicy,
) -> ProcessResult:
    """Retry a process according to the given policy."""
    result = None
    for attempt in range(policy.max_attempts):
        result = await process.execute(ctx)
        if result.is_ok:
            return result
        if attempt < policy.max_attempts - 1:
            delay = policy.delay_for(attempt)
            await asyncio.sleep(delay)
    return result
