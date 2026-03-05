"""Parallel process composition."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from stbass.process import Process, ProcessContext
from stbass.result import ProcessResult, Failure, FailurePolicy

__all__ = ["PAR"]


@dataclass
class PARResult:
    """Result of a parallel process composition."""

    results: list[ProcessResult] = field(default_factory=list)

    @property
    def is_ok(self) -> bool:
        return all(r.is_ok for r in self.results)

    @property
    def failures(self) -> list[Failure]:
        return [r.failure for r in self.results if r.is_fail]

    @property
    def successes(self) -> list[ProcessResult]:
        return [r for r in self.results if r.is_ok]

    @property
    def value(self) -> list:
        return [r.value for r in self.results if r.is_ok]


class PAR:
    """Composes processes to run in parallel, completing when all finish."""

    def __init__(
        self,
        *processes: Process,
        on_failure: FailurePolicy = FailurePolicy.HALT,
        deadline: Any = None,
    ):
        self._processes = list(processes)
        self._on_failure = on_failure
        self._deadline = deadline

    def _get_deadline_seconds(self) -> float | None:
        if self._deadline is None:
            return None
        if isinstance(self._deadline, (int, float)):
            return float(self._deadline)
        return None

    async def run(self) -> PARResult:
        if not self._processes:
            return PARResult(results=[])

        results: list[ProcessResult | None] = [None] * len(self._processes)

        async def execute_one(idx: int, proc: Process) -> None:
            ctx = ProcessContext(process_name=proc.name)
            try:
                results[idx] = await proc.execute(ctx)
            except asyncio.CancelledError:
                results[idx] = ProcessResult.fail(
                    RuntimeError("Process cancelled"),
                    process_name=proc.name,
                )

        tasks = [
            asyncio.create_task(execute_one(i, proc))
            for i, proc in enumerate(self._processes)
        ]

        deadline_seconds = self._get_deadline_seconds()

        if self._on_failure == FailurePolicy.HALT:
            await self._run_halt(tasks, results, deadline_seconds)
        else:
            await self._run_collect(tasks, results, deadline_seconds)

        # Fill any remaining None results
        for i in range(len(results)):
            if results[i] is None:
                results[i] = ProcessResult.fail(
                    RuntimeError("Process did not complete"),
                    process_name=self._processes[i].name,
                )

        return PARResult(results=results)

    async def _run_halt(
        self,
        tasks: list[asyncio.Task],
        results: list[ProcessResult | None],
        deadline_seconds: float | None,
    ) -> None:
        pending = set(tasks)
        task_to_idx = {task: i for i, task in enumerate(tasks)}
        loop = asyncio.get_running_loop()
        start_time = loop.time()

        while pending:
            timeout = None
            if deadline_seconds is not None:
                elapsed = loop.time() - start_time
                timeout = max(0.0, deadline_seconds - elapsed)

            done, pending = await asyncio.wait(
                pending,
                return_when=asyncio.FIRST_COMPLETED,
                timeout=timeout,
            )

            if not done:
                # Deadline hit with no completions
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                pending = set()
                break

            should_halt = False
            for task in done:
                idx = task_to_idx[task]
                if results[idx] is not None and results[idx].is_fail:
                    if not getattr(self._processes[idx], '_is_optional', False):
                        should_halt = True

            if should_halt and pending:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                pending = set()
                break

    async def _run_collect(
        self,
        tasks: list[asyncio.Task],
        results: list[ProcessResult | None],
        deadline_seconds: float | None,
    ) -> None:
        if deadline_seconds is not None:
            done, pending = await asyncio.wait(tasks, timeout=deadline_seconds)
            if pending:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        else:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def __aenter__(self) -> PAR:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        return False
