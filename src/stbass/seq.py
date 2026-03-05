"""Sequential process composition."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from stbass.channel import Chan
from stbass.process import Process, ProcessContext
from stbass.result import ProcessResult, Failure, FailurePolicy

__all__ = ["SEQ"]


@dataclass
class SEQResult:
    """Result of a sequential process composition."""

    results: list[ProcessResult] = field(default_factory=list)
    _input_value: Any = None

    @property
    def is_ok(self) -> bool:
        return all(r.is_ok for r in self.results)

    @property
    def value(self) -> Any:
        if not self.results:
            return self._input_value
        return self.results[-1].value

    @property
    def failures(self) -> list[Failure]:
        return [r.failure for r in self.results if r.is_fail]


class SEQ:
    """Composes processes to run sequentially, one after another."""

    def __init__(self, *processes: Process, on_failure: FailurePolicy = FailurePolicy.HALT):
        self._processes = list(processes)
        self._on_failure = on_failure

    async def run(self, input_value: Any = None) -> SEQResult:
        results: list[ProcessResult] = []
        current_value = input_value

        for proc in self._processes:
            result, output_value = await self._run_single(proc, current_value)
            results.append(result)

            if result.is_fail:
                if self._on_failure == FailurePolicy.HALT:
                    break
                current_value = None
            else:
                current_value = output_value

        return SEQResult(results=results, _input_value=input_value)

    async def _run_single(self, proc: Process, input_value: Any) -> tuple[ProcessResult, Any]:
        input_ch = Chan(object, name=f"{proc.name}_input")
        output_ch = Chan(object, name=f"{proc.name}_output")
        ctx = ProcessContext(
            process_name=proc.name,
            channels={"input": input_ch, "output": output_ch},
        )

        output_value = None

        feed_task = asyncio.create_task(input_ch.send(input_value))
        drain_task = asyncio.create_task(output_ch.recv())

        result = await proc.execute(ctx)

        # Clean up feed task
        if not feed_task.done():
            feed_task.cancel()
        try:
            await feed_task
        except (asyncio.CancelledError, Exception):
            pass

        # Get output or clean up drain task
        if result.is_ok:
            if drain_task.done():
                output_value = drain_task.result()
            else:
                drain_task.cancel()
                try:
                    await drain_task
                except (asyncio.CancelledError, Exception):
                    pass
                output_value = result.value
        else:
            if not drain_task.done():
                drain_task.cancel()
            try:
                await drain_task
            except (asyncio.CancelledError, Exception):
                pass

        return result, output_value

    async def __aenter__(self) -> SEQ:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        return False
