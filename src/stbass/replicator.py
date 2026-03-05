"""Replicated process constructors for dynamic fan-out."""

from __future__ import annotations

from typing import Any, Callable

from stbass.process import Process, ProcessContext
from stbass.result import ProcessResult, FailurePolicy
from stbass.par import PAR
from stbass.seq import SEQResult

__all__ = ["PAR_FOR", "SEQ_FOR"]


class _ReplicaProcess(Process):
    """A process wrapping a factory function call for a specific index."""

    def __init__(self, factory: Callable, index: int, name: str):
        self._factory = factory
        self._index = index
        self._name = name
        self._is_optional = False
        self._bound_channels = {}

    @property
    def name(self) -> str:
        return self._name

    async def run(self, ctx: ProcessContext) -> ProcessResult:
        return await self._factory(self._index, ctx)


class PAR_FOR:
    """Replicates a process template in parallel over an iterable."""

    def __init__(
        self,
        count: int | Callable[[], int],
        factory: Callable,
        *,
        on_failure: FailurePolicy = FailurePolicy.HALT,
        deadline: Any = None,
    ):
        self._count = count
        self._factory = factory
        self._on_failure = on_failure
        self._deadline = deadline

    async def run(self) -> Any:
        n = self._count() if callable(self._count) else self._count
        factory_name = getattr(self._factory, '__name__', 'replica')
        processes = [
            _ReplicaProcess(self._factory, i, f"{factory_name}[{i}]")
            for i in range(n)
        ]
        return await PAR(
            *processes,
            on_failure=self._on_failure,
            deadline=self._deadline,
        ).run()


class SEQ_FOR:
    """Replicates a process template sequentially over an iterable."""

    def __init__(
        self,
        count: int | Callable[[], int],
        factory: Callable,
        *,
        on_failure: FailurePolicy = FailurePolicy.HALT,
    ):
        self._count = count
        self._factory = factory
        self._on_failure = on_failure

    async def run(self) -> SEQResult:
        n = self._count() if callable(self._count) else self._count
        factory_name = getattr(self._factory, '__name__', 'replica')
        results: list[ProcessResult] = []

        for i in range(n):
            proc = _ReplicaProcess(self._factory, i, f"{factory_name}[{i}]")
            ctx = ProcessContext(process_name=proc.name)
            result = await proc.execute(ctx)
            results.append(result)

            if result.is_fail and self._on_failure == FailurePolicy.HALT:
                break

        return SEQResult(results=results)
