import pytest
import asyncio
from stbass import Chan, Guard, ALT, PRI_ALT, ProcessResult
from stbass.alt import SKIP, AllGuardsDisabledError
from stbass.timer import TIMER

class TestALTBasic:
    @pytest.mark.asyncio
    async def test_single_guard(self):
        ch = Chan(str)
        async def writer():
            await asyncio.sleep(0.01)
            await ch.send("hello")
        task = asyncio.create_task(writer())
        result = await ALT(
            Guard(ch, handler=lambda v: f"got: {v}")
        )
        assert result == "got: hello"
        await task

    @pytest.mark.asyncio
    async def test_two_guards_one_ready(self):
        ch1 = Chan(str, name="ch1")
        ch2 = Chan(str, name="ch2")
        async def send_ch2():
            await asyncio.sleep(0.01)
            await ch2.send("from_ch2")
        task = asyncio.create_task(send_ch2())
        result = await ALT(
            Guard(ch1, handler=lambda v: f"ch1: {v}"),
            Guard(ch2, handler=lambda v: f"ch2: {v}"),
        )
        assert result == "ch2: from_ch2"
        await task

    @pytest.mark.asyncio
    async def test_precondition_false_skips_guard(self):
        ch1 = Chan(str, name="ch1")
        ch2 = Chan(str, name="ch2")
        async def send_both():
            await asyncio.sleep(0.01)
            await ch2.send("from_ch2")
        task = asyncio.create_task(send_both())
        result = await ALT(
            Guard(ch1, precondition=False, handler=lambda v: "ch1"),
            Guard(ch2, precondition=True, handler=lambda v: "ch2"),
        )
        assert result == "ch2"
        await task

    @pytest.mark.asyncio
    async def test_callable_precondition(self):
        ch = Chan(str)
        flag = False
        async def delayed_send():
            nonlocal flag
            await asyncio.sleep(0.01)
            flag = True
            await ch.send("ready")
        task = asyncio.create_task(delayed_send())
        result = await ALT(
            Guard(ch, precondition=lambda: flag, handler=lambda v: v),
        )
        assert result == "ready"
        await task

class TestPRI_ALT:
    @pytest.mark.asyncio
    async def test_priority_order(self):
        """When both channels are ready, PRI_ALT picks first declared."""
        ch1 = Chan(str, name="priority")
        ch2 = Chan(str, name="secondary")
        async def send_both():
            await ch1.send("first")
        async def send_ch2():
            await ch2.send("second")
        t1 = asyncio.create_task(send_both())
        t2 = asyncio.create_task(send_ch2())
        await asyncio.sleep(0.02)  # let both sends start
        result = await PRI_ALT(
            Guard(ch1, handler=lambda v: f"pri: {v}"),
            Guard(ch2, handler=lambda v: f"sec: {v}"),
        )
        assert result == "pri: first"
        # clean up ch2
        t2.cancel()
        try:
            await t1
            await t2
        except (asyncio.CancelledError, Exception):
            pass

class TestSKIP:
    @pytest.mark.asyncio
    async def test_skip_fires_when_nothing_ready(self):
        ch = Chan(str)
        # ch has no pending send, so SKIP should fire
        result = await ALT(
            Guard(ch, handler=lambda v: "ch"),
            Guard(SKIP, handler=lambda: "skipped"),
        )
        assert result == "skipped"

class TestALTWithTimer:
    @pytest.mark.asyncio
    async def test_timer_fires_after_delay(self):
        ch = Chan(str)
        # ch never gets a send, so timer should win
        result = await ALT(
            Guard(ch, handler=lambda v: "channel"),
            Guard(TIMER(seconds=0.05), handler=lambda v: "timeout"),
        )
        assert result == "timeout"

class TestALTErrors:
    @pytest.mark.asyncio
    async def test_all_guards_disabled(self):
        ch = Chan(str)
        with pytest.raises(AllGuardsDisabledError):
            await asyncio.wait_for(
                ALT(Guard(ch, precondition=False)),
                timeout=0.5
            )

class TestALTNoHandler:
    @pytest.mark.asyncio
    async def test_no_handler_returns_raw_value(self):
        ch = Chan(int)
        task = asyncio.create_task(ch.send(42))
        result = await ALT(Guard(ch))
        assert result == 42
        await task
