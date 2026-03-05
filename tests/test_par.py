import pytest
import asyncio
from stbass import Process, ProcessResult, PAR, FailurePolicy
from stbass.process import ProcessContext

@Process
async def fast_ok(ctx: ProcessContext) -> ProcessResult:
    await asyncio.sleep(0.01)
    return ProcessResult.ok("fast")

@Process
async def slow_ok(ctx: ProcessContext) -> ProcessResult:
    await asyncio.sleep(0.1)
    return ProcessResult.ok("slow")

@Process
async def instant_ok(ctx: ProcessContext) -> ProcessResult:
    return ProcessResult.ok("instant")

@Process
async def fast_fail(ctx: ProcessContext) -> ProcessResult:
    await asyncio.sleep(0.01)
    raise ValueError("fast failure")

@Process
async def slow_fail(ctx: ProcessContext) -> ProcessResult:
    await asyncio.sleep(0.1)
    raise RuntimeError("slow failure")

class TestPARBasic:
    @pytest.mark.asyncio
    async def test_single_process(self):
        result = await PAR(instant_ok).run()
        assert result.is_ok
        assert len(result.results) == 1

    @pytest.mark.asyncio
    async def test_multiple_processes(self):
        result = await PAR(fast_ok, slow_ok, instant_ok).run()
        assert result.is_ok
        assert len(result.results) == 3
        values = [r.value for r in result.results]
        assert "fast" in values
        assert "slow" in values
        assert "instant" in values

    @pytest.mark.asyncio
    async def test_truly_parallel(self):
        """Three 0.1s processes should complete in ~0.1s, not ~0.3s"""
        @Process
        async def sleep_100ms(ctx: ProcessContext) -> ProcessResult:
            await asyncio.sleep(0.1)
            return ProcessResult.ok("done")

        import time
        start = time.monotonic()
        result = await PAR(sleep_100ms, sleep_100ms, sleep_100ms).run()
        elapsed = time.monotonic() - start
        assert result.is_ok
        assert elapsed < 0.25  # should be ~0.1s, definitely not 0.3s

class TestPARContextManager:
    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with PAR(fast_ok, instant_ok) as parallel:
            result = await parallel.run()
        assert result.is_ok

class TestPARFailureHalt:
    @pytest.mark.asyncio
    async def test_halt_on_failure(self):
        result = await PAR(
            fast_fail, slow_ok,
            on_failure=FailurePolicy.HALT
        ).run()
        assert result.is_ok is False
        assert len(result.failures) >= 1

    @pytest.mark.asyncio
    async def test_halt_cancels_slow_processes(self):
        """Under HALT, fast failure should cancel slow processes"""
        completed = []

        @Process
        async def very_slow(ctx: ProcessContext) -> ProcessResult:
            await asyncio.sleep(5.0)
            completed.append("slow_finished")
            return ProcessResult.ok("slow")

        @Process
        async def quick_crash(ctx: ProcessContext) -> ProcessResult:
            await asyncio.sleep(0.01)
            raise ValueError("crash")

        result = await PAR(
            quick_crash, very_slow,
            on_failure=FailurePolicy.HALT
        ).run()
        assert result.is_ok is False
        assert "slow_finished" not in completed

class TestPARFailureCollect:
    @pytest.mark.asyncio
    async def test_collect_all_results(self):
        result = await PAR(
            fast_ok, fast_fail, slow_ok,
            on_failure=FailurePolicy.COLLECT
        ).run()
        assert result.is_ok is False
        assert len(result.results) == 3
        assert len(result.successes) == 2
        assert len(result.failures) == 1

class TestPAROptional:
    @pytest.mark.asyncio
    async def test_optional_failure_doesnt_halt(self):
        result = await PAR(
            fast_fail.optional(), fast_ok, slow_ok,
            on_failure=FailurePolicy.HALT
        ).run()
        # fast_fail is optional, so HALT should not trigger
        assert len(result.successes) >= 2

class TestPARDeadline:
    @pytest.mark.asyncio
    async def test_deadline_cancels_slow(self):
        @Process
        async def never_finishes(ctx: ProcessContext) -> ProcessResult:
            await asyncio.sleep(100)
            return ProcessResult.ok("impossible")

        result = await PAR(
            fast_ok, never_finishes,
            on_failure=FailurePolicy.COLLECT,
            deadline=0.2  # 200ms deadline
        ).run()
        assert len(result.failures) >= 1

class TestPAREmpty:
    @pytest.mark.asyncio
    async def test_empty_par(self):
        result = await PAR().run()
        assert result.is_ok
        assert len(result.results) == 0
