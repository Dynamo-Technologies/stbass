import pytest
import asyncio
from datetime import datetime, timedelta
from stbass.timer import TIMER, DEADLINE, TimerExpired
from stbass import Chan, Guard, ALT, PRI_ALT, PAR, Process, ProcessResult
from stbass.process import ProcessContext

class TestTIMER:
    @pytest.mark.asyncio
    async def test_timer_fires(self):
        t = TIMER(seconds=0.05)
        # Use in ALT — should fire after 50ms
        result = await ALT(Guard(t, handler=lambda v: v))
        assert isinstance(result, TimerExpired)

    @pytest.mark.asyncio
    async def test_timer_elapsed(self):
        t = TIMER(seconds=0.05)
        result = await ALT(Guard(t, handler=lambda v: v))
        assert result.elapsed.total_seconds() >= 0.04

    @pytest.mark.asyncio
    async def test_timer_name(self):
        t = TIMER(seconds=1.0, name="agent_timeout")
        assert t.name == "agent_timeout"

    @pytest.mark.asyncio
    async def test_timer_loses_to_fast_channel(self):
        ch = Chan(str)
        async def quick_send():
            await asyncio.sleep(0.01)
            await ch.send("fast")
        task = asyncio.create_task(quick_send())
        result = await ALT(
            Guard(ch, handler=lambda v: f"channel: {v}"),
            Guard(TIMER(seconds=1.0), handler=lambda v: "timeout"),
        )
        assert result == "channel: fast"
        await task

    @pytest.mark.asyncio
    async def test_timer_wins_over_slow_channel(self):
        ch = Chan(str)
        # No one sends to ch, so timer wins
        result = await ALT(
            Guard(ch, handler=lambda v: "channel"),
            Guard(TIMER(seconds=0.05), handler=lambda v: "timeout"),
        )
        assert result == "timeout"

class TestDEADLINE:
    @pytest.mark.asyncio
    async def test_deadline_fires(self):
        target = datetime.now() + timedelta(seconds=0.05)
        d = DEADLINE(target)
        result = await ALT(Guard(d, handler=lambda v: v))
        assert isinstance(result, TimerExpired)

    def test_remaining(self):
        target = datetime.now() + timedelta(seconds=10)
        d = DEADLINE(target)
        assert d.remaining.total_seconds() > 8  # roughly

class TestTimerExpired:
    def test_timer_expired_fields(self):
        te = TimerExpired(
            started_at=datetime(2026, 1, 1, 12, 0, 0),
            deadline=datetime(2026, 1, 1, 12, 0, 30),
            elapsed=timedelta(seconds=30),
            timer_name="test_timer",
        )
        assert te.timer_name == "test_timer"
        assert te.elapsed.total_seconds() == 30

class TestTimerInPAR:
    @pytest.mark.asyncio
    async def test_par_deadline_cancels(self):
        @Process
        async def never_done(ctx: ProcessContext) -> ProcessResult:
            await asyncio.sleep(100)
            return ProcessResult.ok("impossible")

        @Process
        async def quick_done(ctx: ProcessContext) -> ProcessResult:
            await asyncio.sleep(0.01)
            return ProcessResult.ok("quick")

        from stbass import FailurePolicy
        result = await PAR(
            quick_done, never_done,
            on_failure=FailurePolicy.COLLECT,
            deadline=0.15
        ).run()

        successes = [r for r in result.results if r.is_ok]
        failures = [r for r in result.results if r.is_fail]
        assert len(successes) >= 1
        assert len(failures) >= 1

class TestTimerInPRI_ALT:
    @pytest.mark.asyncio
    async def test_pri_alt_timer_as_fallback(self):
        ch_high = Chan(str, name="high_priority")
        ch_low = Chan(str, name="low_priority")
        # Neither channel gets data, so timer fires
        result = await PRI_ALT(
            Guard(ch_high, handler=lambda v: "high"),
            Guard(ch_low, handler=lambda v: "low"),
            Guard(TIMER(seconds=0.05), handler=lambda v: "timeout"),
        )
        assert result == "timeout"
