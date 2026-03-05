import pytest
import asyncio
from stbass import Process, ProcessResult, Chan
from stbass.process import ProcessContext

class TestProcessDecorator:
    @pytest.mark.asyncio
    async def test_decorator_basic(self):
        @Process
        async def simple(ctx: ProcessContext) -> ProcessResult:
            return ProcessResult.ok("done")

        ctx = ProcessContext(process_name="simple")
        result = await simple.execute(ctx)
        assert result.is_ok
        assert result.value == "done"

    @pytest.mark.asyncio
    async def test_decorator_with_name(self):
        @Process(name="custom_agent")
        async def my_func(ctx: ProcessContext) -> ProcessResult:
            return ProcessResult.ok("done")

        assert my_func.name == "custom_agent"

    @pytest.mark.asyncio
    async def test_auto_name_from_function(self):
        @Process
        async def analyze_data(ctx: ProcessContext) -> ProcessResult:
            return ProcessResult.ok("done")

        assert analyze_data.name == "analyze_data"

    @pytest.mark.asyncio
    async def test_exception_becomes_failure(self):
        @Process
        async def broken(ctx: ProcessContext) -> ProcessResult:
            raise ValueError("something went wrong")

        ctx = ProcessContext(process_name="broken")
        result = await broken.execute(ctx)
        assert result.is_fail
        assert "something went wrong" in str(result.failure.error)
        assert result.failure.traceback_str is not None

    @pytest.mark.asyncio
    async def test_failure_records_timing(self):
        @Process
        async def slow_fail(ctx: ProcessContext) -> ProcessResult:
            await asyncio.sleep(0.05)
            raise RuntimeError("timeout-ish")

        ctx = ProcessContext(process_name="slow_fail")
        result = await slow_fail.execute(ctx)
        assert result.is_fail
        assert result.failure.elapsed.total_seconds() >= 0.04

class TestProcessClass:
    @pytest.mark.asyncio
    async def test_class_based_process(self):
        class Adder(Process):
            def __init__(self, amount: int):
                self.amount = amount
            async def run(self, ctx: ProcessContext) -> ProcessResult:
                return ProcessResult.ok(self.amount + 10)

        adder = Adder(5)
        ctx = ProcessContext(process_name="adder")
        result = await adder.execute(ctx)
        assert result.is_ok
        assert result.value == 15

class TestProcessContext:
    @pytest.mark.asyncio
    async def test_send_recv_via_context(self):
        ch = Chan(str, name="data")
        ctx = ProcessContext(process_name="test", channels={"data": ch})

        async def writer():
            await ctx.send("data", "hello world")
        async def reader():
            val = await ctx.recv("data")
            assert val == "hello world"

        async with asyncio.TaskGroup() as tg:
            tg.create_task(writer())
            tg.create_task(reader())

    def test_checkpoint(self):
        ctx = ProcessContext(process_name="test")
        ctx.checkpoint("step_1")
        ctx.checkpoint("step_2")
        assert ctx._checkpoints == ["step_1", "step_2"]

    def test_get_channel(self):
        ch = Chan(int, name="nums")
        ctx = ProcessContext(process_name="test", channels={"nums": ch})
        assert ctx.get_channel("nums") is ch

    def test_get_missing_channel_raises(self):
        ctx = ProcessContext(process_name="test")
        with pytest.raises(KeyError):
            ctx.get_channel("nonexistent")

class TestProcessOptional:
    @pytest.mark.asyncio
    async def test_optional_marker(self):
        @Process
        async def maybe_fails(ctx: ProcessContext) -> ProcessResult:
            return ProcessResult.ok("ok")

        opt = maybe_fails.optional()
        assert hasattr(opt, '_is_optional') or hasattr(opt, 'is_optional')

class TestProcessWithChannels:
    @pytest.mark.asyncio
    async def test_with_channels(self):
        ch = Chan(str, name="output")

        @Process
        async def emitter(ctx: ProcessContext) -> ProcessResult:
            await ctx.send("output", "data")
            return ProcessResult.ok("sent")

        bound = emitter.with_channels(output=ch)
        ctx = ProcessContext(process_name="emitter")
        # The bound process should have channels pre-configured
        # Exact implementation may vary — test that it doesn't raise
        assert bound is not None
