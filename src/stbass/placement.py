"""Placement-aware parallel composition for distributed execution."""

from __future__ import annotations

import abc
import asyncio
import sys
from dataclasses import dataclass, field
from typing import Any

from stbass.process import Process, ProcessContext
from stbass.result import ProcessResult, Failure, FailurePolicy

__all__ = ["Placement", "PLACED_PAR", "BackendRegistry", "ExecutionBackend", "LocalBackend"]


@dataclass
class Placement:
    """Describes where a process should execute."""

    model: str | None = None
    endpoint: str | None = None
    config: dict | None = None

    @property
    def summary(self) -> str:
        parts = []
        if self.model:
            parts.append(f"model={self.model}")
        if self.endpoint:
            parts.append(f"endpoint={self.endpoint}")
        return ", ".join(parts) if parts else "unspecified"


class ExecutionBackend(abc.ABC):
    """Protocol for process execution backends."""

    @abc.abstractmethod
    async def execute(self, process: Process, ctx: ProcessContext) -> ProcessResult:
        ...

    @abc.abstractmethod
    async def health_check(self) -> bool:
        ...

    @property
    @abc.abstractmethod
    def concurrency_limit(self) -> int:
        ...

    @property
    @abc.abstractmethod
    def name(self) -> str:
        ...


class LocalBackend(ExecutionBackend):
    """Default backend — runs process coroutines directly."""

    async def execute(self, process: Process, ctx: ProcessContext) -> ProcessResult:
        return await process.execute(ctx)

    async def health_check(self) -> bool:
        return True

    @property
    def concurrency_limit(self) -> int:
        return sys.maxsize

    @property
    def name(self) -> str:
        return "local"


class BackendRegistry:
    """Maps placement specs to execution backends."""

    def __init__(self) -> None:
        self._backends: dict[str, ExecutionBackend] = {}
        self._default = LocalBackend()

    def register(self, name: str, backend: ExecutionBackend) -> None:
        self._backends[name] = backend

    def get(self, placement: Placement) -> ExecutionBackend:
        if placement.endpoint and placement.endpoint in self._backends:
            return self._backends[placement.endpoint]
        if placement.model and placement.model in self._backends:
            return self._backends[placement.model]
        return self._default

    @property
    def default(self) -> ExecutionBackend:
        return self._default


# Global registry instance
_global_registry = BackendRegistry()


class PLACED_PAR:
    """Composes processes to run in parallel with explicit placement directives."""

    def __init__(
        self,
        *pairs: tuple[Process, Placement],
        on_failure: FailurePolicy = FailurePolicy.HALT,
        deadline: Any = None,
        registry: BackendRegistry | None = None,
    ):
        self._pairs = list(pairs)
        self._on_failure = on_failure
        self._deadline = deadline
        self._registry = registry or _global_registry

    def _get_deadline_seconds(self) -> float | None:
        if self._deadline is None:
            return None
        if isinstance(self._deadline, (int, float)):
            return float(self._deadline)
        return None

    async def run(self) -> Any:
        from stbass.par import PARResult

        if not self._pairs:
            return PARResult(results=[])

        results: list[ProcessResult | None] = [None] * len(self._pairs)

        async def execute_one(idx: int, proc: Process, placement: Placement) -> None:
            backend = self._registry.get(placement)
            ctx = ProcessContext(process_name=proc.name, placement=placement)
            try:
                results[idx] = await backend.execute(proc, ctx)
            except asyncio.CancelledError:
                results[idx] = ProcessResult.fail(
                    RuntimeError("Process cancelled"),
                    process_name=proc.name,
                    placement=placement,
                )

        tasks = [
            asyncio.create_task(execute_one(i, proc, placement))
            for i, (proc, placement) in enumerate(self._pairs)
        ]

        deadline_seconds = self._get_deadline_seconds()

        if self._on_failure == FailurePolicy.HALT:
            await self._run_halt(tasks, results, deadline_seconds)
        else:
            await self._run_collect(tasks, results, deadline_seconds)

        for i in range(len(results)):
            if results[i] is None:
                proc, placement = self._pairs[i]
                results[i] = ProcessResult.fail(
                    RuntimeError("Process did not complete"),
                    process_name=proc.name,
                    placement=placement,
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
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                pending = set()
                break

            should_halt = False
            for task in done:
                idx = task_to_idx[task]
                if results[idx] is not None and results[idx].is_fail:
                    proc = self._pairs[idx][0]
                    if not getattr(proc, '_is_optional', False):
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
