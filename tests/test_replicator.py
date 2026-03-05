import pytest
import asyncio
from stbass import Process, ProcessResult, FailurePolicy
from stbass.replicator import PAR_FOR, SEQ_FOR
from stbass.process import ProcessContext

class TestPAR_FOR:
    @pytest.mark.asyncio
    async def test_basic_replication(self):
        results_collector = []

        async def worker(index: int, ctx: ProcessContext):
            results_collector.append(index)
            return ProcessResult.ok(index * 10)

        result = await PAR_FOR(count=5, factory=worker).run()
        assert result.is_ok
        assert len(result.results) == 5
        assert sorted(results_collector) == [0, 1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_dynamic_count(self):
        items = [1, 2, 3, 4, 5, 6, 7]

        async def process_item(index: int, ctx: ProcessContext):
            return ProcessResult.ok(items[index] ** 2)

        result = await PAR_FOR(count=lambda: len(items), factory=process_item).run()
        assert result.is_ok
        assert len(result.results) == 7
        values = sorted([r.value for r in result.results])
        assert values == [1, 4, 9, 16, 25, 36, 49]

    @pytest.mark.asyncio
    async def test_truly_parallel(self):
        import time
        start = time.monotonic()

        async def sleep_worker(index: int, ctx: ProcessContext):
            await asyncio.sleep(0.1)
            return ProcessResult.ok(index)

        result = await PAR_FOR(count=10, factory=sleep_worker).run()
        elapsed = time.monotonic() - start
        assert result.is_ok
        assert elapsed < 0.5  # 10 * 0.1s parallel, not 1.0s sequential

    @pytest.mark.asyncio
    async def test_failure_halt(self):
        async def sometimes_fails(index: int, ctx: ProcessContext):
            if index == 2:
                raise ValueError(f"worker {index} failed")
            await asyncio.sleep(0.05)
            return ProcessResult.ok(index)

        result = await PAR_FOR(
            count=5, factory=sometimes_fails,
            on_failure=FailurePolicy.HALT
        ).run()
        assert result.is_ok is False

    @pytest.mark.asyncio
    async def test_failure_collect(self):
        async def sometimes_fails(index: int, ctx: ProcessContext):
            if index == 2:
                raise ValueError(f"worker {index} failed")
            return ProcessResult.ok(index)

        result = await PAR_FOR(
            count=5, factory=sometimes_fails,
            on_failure=FailurePolicy.COLLECT
        ).run()
        assert result.is_ok is False
        assert len(result.successes) == 4
        assert len(result.failures) == 1

    @pytest.mark.asyncio
    async def test_deadline(self):
        async def slow_worker(index: int, ctx: ProcessContext):
            await asyncio.sleep(100)
            return ProcessResult.ok(index)

        result = await PAR_FOR(
            count=3, factory=slow_worker,
            on_failure=FailurePolicy.COLLECT,
            deadline=0.1
        ).run()
        assert len(result.failures) == 3

    @pytest.mark.asyncio
    async def test_zero_count(self):
        async def worker(index: int, ctx: ProcessContext):
            return ProcessResult.ok(index)

        result = await PAR_FOR(count=0, factory=worker).run()
        assert result.is_ok
        assert len(result.results) == 0

class TestSEQ_FOR:
    @pytest.mark.asyncio
    async def test_basic_sequential(self):
        execution_order = []

        async def worker(index: int, ctx: ProcessContext):
            execution_order.append(index)
            return ProcessResult.ok(index)

        result = await SEQ_FOR(count=5, factory=worker).run()
        assert result.is_ok
        assert execution_order == [0, 1, 2, 3, 4]  # must be in order

    @pytest.mark.asyncio
    async def test_sequential_is_actually_sequential(self):
        timestamps = []
        import time

        async def timed_worker(index: int, ctx: ProcessContext):
            timestamps.append(time.monotonic())
            await asyncio.sleep(0.02)
            return ProcessResult.ok(index)

        result = await SEQ_FOR(count=3, factory=timed_worker).run()
        assert result.is_ok
        # Each should start after previous finished
        for i in range(1, len(timestamps)):
            assert timestamps[i] - timestamps[i-1] >= 0.015

class TestNestedReplication:
    @pytest.mark.asyncio
    async def test_par_for_inside_par_for(self):
        """Subagents spawning subagents."""
        leaf_results = []

        async def outer(index: int, ctx: ProcessContext):
            inner_result = await PAR_FOR(
                count=3,
                factory=lambda j, ctx: inner_worker(index, j, ctx),
            ).run()
            return ProcessResult.ok(f"outer_{index}_done")

        async def inner_worker(outer_idx, inner_idx, ctx: ProcessContext):
            leaf_results.append((outer_idx, inner_idx))
            return ProcessResult.ok(f"{outer_idx}_{inner_idx}")

        result = await PAR_FOR(count=2, factory=outer).run()
        assert result.is_ok
        assert len(leaf_results) == 6  # 2 outer * 3 inner
