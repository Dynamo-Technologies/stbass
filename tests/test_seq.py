import pytest
import asyncio
from stbass import Process, ProcessResult, SEQ, FailurePolicy, Chan
from stbass.process import ProcessContext

@Process
async def add_ten(ctx: ProcessContext) -> ProcessResult:
    val = await ctx.recv("input")
    result = val + 10
    await ctx.send("output", result)
    return ProcessResult.ok(result)

@Process
async def double(ctx: ProcessContext) -> ProcessResult:
    val = await ctx.recv("input")
    result = val * 2
    await ctx.send("output", result)
    return ProcessResult.ok(result)

@Process
async def to_string(ctx: ProcessContext) -> ProcessResult:
    val = await ctx.recv("input")
    result = f"Result: {val}"
    await ctx.send("output", result)
    return ProcessResult.ok(result)

@Process
async def explode(ctx: ProcessContext) -> ProcessResult:
    await ctx.recv("input")
    raise ValueError("boom")

class TestSEQBasic:
    @pytest.mark.asyncio
    async def test_single_process(self):
        result = await SEQ(add_ten).run(input_value=5)
        assert result.is_ok
        assert result.value == 15

    @pytest.mark.asyncio
    async def test_two_processes(self):
        result = await SEQ(add_ten, double).run(input_value=5)
        assert result.is_ok
        assert result.value == 30  # (5 + 10) * 2

    @pytest.mark.asyncio
    async def test_three_processes(self):
        result = await SEQ(add_ten, double, to_string).run(input_value=5)
        assert result.is_ok
        assert result.value == "Result: 30"

    @pytest.mark.asyncio
    async def test_results_list(self):
        result = await SEQ(add_ten, double).run(input_value=5)
        assert len(result.results) == 2
        assert result.results[0].value == 15
        assert result.results[1].value == 30

class TestSEQContextManager:
    @pytest.mark.asyncio
    async def test_context_manager_usage(self):
        async with SEQ(add_ten, double) as pipeline:
            result = await pipeline.run(input_value=3)
        assert result.is_ok
        assert result.value == 26  # (3 + 10) * 2

class TestSEQFailure:
    @pytest.mark.asyncio
    async def test_halt_on_failure(self):
        result = await SEQ(
            add_ten, explode, double,
            on_failure=FailurePolicy.HALT
        ).run(input_value=5)
        assert result.is_ok is False
        assert len(result.failures) == 1
        assert result.results[0].is_ok  # add_ten succeeded
        assert result.results[1].is_fail  # explode failed
        assert len(result.results) == 2  # double never ran

    @pytest.mark.asyncio
    async def test_collect_past_failure(self):
        result = await SEQ(
            add_ten, explode, double,
            on_failure=FailurePolicy.COLLECT
        ).run(input_value=5)
        assert result.is_ok is False
        assert len(result.results) == 3  # all three ran (or attempted)
        assert result.results[0].is_ok
        assert result.results[1].is_fail

class TestSEQEmpty:
    @pytest.mark.asyncio
    async def test_empty_seq(self):
        result = await SEQ().run(input_value="passthrough")
        assert result.is_ok
        assert result.value == "passthrough"
