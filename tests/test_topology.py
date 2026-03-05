import pytest
import asyncio
from stbass import Chan, Process, ProcessResult
from stbass.channel import ChannelClosedError
from stbass.topology import ChanArray, Distributor, Collector
from stbass.process import ProcessContext


class TestChanArray:
    def test_creation(self):
        arr = ChanArray(int, 5)
        assert len(arr) == 5
        assert arr.count == 5
        assert arr.type_spec is int

    def test_iteration(self):
        arr = ChanArray(str, 3, name_prefix="test")
        channels = list(arr)
        assert len(channels) == 3
        assert all(isinstance(ch, Chan) for ch in channels)

    def test_indexing(self):
        arr = ChanArray(int, 4)
        ch = arr[2]
        assert isinstance(ch, Chan)

    def test_channel_names(self):
        arr = ChanArray(int, 3, name_prefix="worker")
        assert "worker[0]" in arr[0].name
        assert "worker[1]" in arr[1].name
        assert "worker[2]" in arr[2].name

    def test_type_spec_propagated(self):
        arr = ChanArray(str, 2)
        for ch in arr:
            assert ch.type_spec is str


class TestDistributorRoundRobin:
    @pytest.mark.asyncio
    async def test_round_robin_distribution(self):
        source = Chan(int, name="source")
        targets = ChanArray(int, 3, name_prefix="target")

        dist = Distributor(source, targets, strategy="round_robin")

        collected = {0: [], 1: [], 2: []}

        async def feed():
            for i in range(6):
                await source.send(i)
            source.close()

        async def drain(idx, ch):
            try:
                while True:
                    val = await ch.recv()
                    collected[idx].append(val)
            except ChannelClosedError:
                pass

        ctx = ProcessContext(process_name="dist")
        feed_task = asyncio.create_task(feed())
        drain_tasks = [asyncio.create_task(drain(i, targets[i])) for i in range(3)]
        await dist.run(ctx)
        await feed_task
        await asyncio.gather(*drain_tasks)

        assert sorted(collected[0]) == [0, 3]
        assert sorted(collected[1]) == [1, 4]
        assert sorted(collected[2]) == [2, 5]


class TestDistributorBroadcast:
    @pytest.mark.asyncio
    async def test_broadcast(self):
        source = Chan(int, name="source")
        targets = ChanArray(int, 3, name_prefix="target")

        dist = Distributor(source, targets, strategy="broadcast")

        collected = {0: [], 1: [], 2: []}

        async def feed():
            for i in range(3):
                await source.send(i)
            source.close()

        async def drain(idx, ch):
            try:
                while True:
                    val = await ch.recv()
                    collected[idx].append(val)
            except ChannelClosedError:
                pass

        ctx = ProcessContext(process_name="dist")
        feed_task = asyncio.create_task(feed())
        drain_tasks = [asyncio.create_task(drain(i, targets[i])) for i in range(3)]
        await dist.run(ctx)
        await feed_task
        await asyncio.gather(*drain_tasks)

        # Each target should get all values
        for idx in range(3):
            assert sorted(collected[idx]) == [0, 1, 2]


class TestCollector:
    @pytest.mark.asyncio
    async def test_unordered_collection(self):
        sources = ChanArray(int, 3, name_prefix="src")
        sink = Chan(int, name="sink")

        collector = Collector(sources, sink, ordered=False)

        collected = []

        async def feed(ch, values):
            for v in values:
                await ch.send(v)
            ch.close()

        async def drain():
            try:
                while True:
                    val = await sink.recv()
                    collected.append(val)
            except ChannelClosedError:
                pass

        ctx = ProcessContext(process_name="collector")
        feed_tasks = [
            asyncio.create_task(feed(sources[0], [10, 20])),
            asyncio.create_task(feed(sources[1], [30, 40])),
            asyncio.create_task(feed(sources[2], [50, 60])),
        ]
        drain_task = asyncio.create_task(drain())
        await collector.run(ctx)
        await asyncio.gather(*feed_tasks)
        await drain_task

        assert sorted(collected) == [10, 20, 30, 40, 50, 60]


class TestChanArrayIndependence:
    @pytest.mark.asyncio
    async def test_channels_are_independent(self):
        arr = ChanArray(int, 3)

        async def send_recv(ch, val):
            task = asyncio.create_task(ch.send(val))
            result = await ch.recv()
            await task
            return result

        results = await asyncio.gather(
            send_recv(arr[0], 100),
            send_recv(arr[1], 200),
            send_recv(arr[2], 300),
        )
        assert sorted(results) == [100, 200, 300]
