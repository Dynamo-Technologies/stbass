"""Channel topology patterns for common communication structures."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from stbass.channel import Chan, ChannelClosedError
from stbass.process import Process, ProcessContext
from stbass.result import ProcessResult

__all__ = ["ChanArray", "Distributor", "Collector"]


class ChanArray:
    """An indexed array of channels for structured communication."""

    def __init__(self, type_spec: Any, count: int, *, name_prefix: str | None = None):
        prefix = name_prefix or f"chan_array_{uuid.uuid4().hex[:8]}"
        self._type_spec = type_spec
        self._channels = [Chan(type_spec, name=f"{prefix}[{i}]") for i in range(count)]

    @property
    def count(self) -> int:
        return len(self._channels)

    @property
    def type_spec(self) -> Any:
        return self._type_spec

    @property
    def channels(self) -> list[Chan]:
        return self._channels

    def __getitem__(self, index: int) -> Chan:
        return self._channels[index]

    def __iter__(self):
        return iter(self._channels)

    def __len__(self) -> int:
        return len(self._channels)


class Distributor(Process):
    """Fan-out pattern that distributes values from one channel to many."""

    def __init__(self, source: Chan, targets: ChanArray | list[Chan], *, strategy: str = "round_robin"):
        self._source = source
        self._targets = targets.channels if isinstance(targets, ChanArray) else list(targets)
        self._strategy = strategy

    async def run(self, ctx: ProcessContext) -> ProcessResult:
        if self._strategy == "round_robin":
            return await self._run_round_robin()
        elif self._strategy == "broadcast":
            return await self._run_broadcast()
        elif self._strategy == "ready_first":
            return await self._run_ready_first()
        return ProcessResult.fail(ValueError(f"Unknown strategy: {self._strategy}"))

    async def _run_round_robin(self) -> ProcessResult:
        idx = 0
        n = len(self._targets)
        count = 0
        try:
            while True:
                value = await self._source.recv()
                await self._targets[idx % n].send(value)
                idx += 1
                count += 1
        except (ChannelClosedError, Exception):
            pass
        for ch in self._targets:
            ch.close()
        return ProcessResult.ok(count)

    async def _run_broadcast(self) -> ProcessResult:
        count = 0
        try:
            while True:
                value = await self._source.recv()
                for ch in self._targets:
                    await ch.send(value)
                count += 1
        except (ChannelClosedError, Exception):
            pass
        for ch in self._targets:
            ch.close()
        return ProcessResult.ok(count)

    async def _run_ready_first(self) -> ProcessResult:
        count = 0
        try:
            while True:
                value = await self._source.recv()
                # Send to whichever target is ready first
                tasks = {
                    asyncio.create_task(ch.send(value)): ch
                    for ch in self._targets
                }
                done, pending = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                count += 1
        except (ChannelClosedError, Exception):
            pass
        for ch in self._targets:
            ch.close()
        return ProcessResult.ok(count)


class Collector(Process):
    """Fan-in pattern that collects values from many channels into one."""

    def __init__(self, sources: ChanArray | list[Chan], sink: Chan, *, ordered: bool = False):
        self._sources = sources.channels if isinstance(sources, ChanArray) else list(sources)
        self._sink = sink
        self._ordered = ordered

    async def run(self, ctx: ProcessContext) -> ProcessResult:
        if self._ordered:
            return await self._run_ordered()
        return await self._run_unordered()

    async def _run_unordered(self) -> ProcessResult:
        results_queue: asyncio.Queue = asyncio.Queue()
        active_count = len(self._sources)

        async def reader(ch: Chan, idx: int) -> None:
            try:
                while True:
                    value = await ch.recv()
                    await results_queue.put(("value", value))
            except Exception:
                pass
            results_queue.put_nowait(("closed", idx))

        tasks = [asyncio.create_task(reader(ch, i)) for i, ch in enumerate(self._sources)]

        closed_count = 0
        collected = 0
        try:
            while closed_count < active_count:
                msg_type, data = await results_queue.get()
                if msg_type == "closed":
                    closed_count += 1
                else:
                    await self._sink.send(data)
                    collected += 1
        except Exception:
            pass
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._sink.close()

        return ProcessResult.ok(collected)

    async def _run_ordered(self) -> ProcessResult:
        collected = 0
        try:
            for ch in self._sources:
                try:
                    while True:
                        value = await ch.recv()
                        await self._sink.send(value)
                        collected += 1
                except ChannelClosedError:
                    continue
        except Exception:
            pass
        finally:
            self._sink.close()
        return ProcessResult.ok(collected)
