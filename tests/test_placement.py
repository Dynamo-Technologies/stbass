import pytest
import asyncio
from stbass import Process, ProcessResult, FailurePolicy
from stbass.placement import (
    Placement, PLACED_PAR, BackendRegistry,
    ExecutionBackend, LocalBackend
)
from stbass.process import ProcessContext

class TestPlacement:
    def test_creation(self):
        p = Placement(model="claude-opus-4-5-20250414", endpoint="anthropic")
        assert p.model == "claude-opus-4-5-20250414"
        assert p.endpoint == "anthropic"

    def test_summary(self):
        p = Placement(model="haiku", endpoint="anthropic")
        s = p.summary
        assert "haiku" in s
        assert "anthropic" in s

    def test_config(self):
        p = Placement(model="local", config={"temperature": 0.7})
        assert p.config["temperature"] == 0.7

class TestBackendRegistry:
    def test_register_and_get(self):
        reg = BackendRegistry()
        backend = LocalBackend()
        reg.register("local", backend)
        assert reg.get(Placement(endpoint="local")) is backend

    def test_default_backend(self):
        reg = BackendRegistry()
        assert reg.default is not None

class TestLocalBackend:
    @pytest.mark.asyncio
    async def test_executes_process(self):
        backend = LocalBackend()

        @Process
        async def simple(ctx: ProcessContext) -> ProcessResult:
            return ProcessResult.ok("local_result")

        ctx = ProcessContext(process_name="simple")
        result = await backend.execute(simple, ctx)
        assert result.is_ok
        assert result.value == "local_result"

class TestPLACED_PAR:
    @pytest.mark.asyncio
    async def test_basic_placed_par(self):
        opus = Placement(model="claude-opus-4-5-20250414", endpoint="anthropic")
        haiku = Placement(model="claude-haiku-4-5-20250414", endpoint="anthropic")

        @Process
        async def reasoning(ctx: ProcessContext) -> ProcessResult:
            return ProcessResult.ok("deep_thought")

        @Process
        async def classification(ctx: ProcessContext) -> ProcessResult:
            return ProcessResult.ok("category_a")

        # Both will use LocalBackend (no real backends registered)
        # but the placement metadata should be tracked
        result = await PLACED_PAR(
            (reasoning, opus),
            (classification, haiku),
        ).run()
        assert result.is_ok
        assert len(result.results) == 2

    @pytest.mark.asyncio
    async def test_placement_in_failure_context(self):
        opus = Placement(model="opus", endpoint="anthropic")

        @Process
        async def failing(ctx: ProcessContext) -> ProcessResult:
            raise RuntimeError("placed failure")

        result = await PLACED_PAR(
            (failing, opus),
            on_failure=FailurePolicy.COLLECT,
        ).run()
        assert result.is_ok is False
        failure = result.failures[0]
        assert failure.placement is not None
        assert failure.placement.model == "opus"

    @pytest.mark.asyncio
    async def test_placed_par_with_deadline(self):
        slow_placement = Placement(model="slow", endpoint="local")

        @Process
        async def never_done(ctx: ProcessContext) -> ProcessResult:
            await asyncio.sleep(100)
            return ProcessResult.ok("impossible")

        result = await PLACED_PAR(
            (never_done, slow_placement),
            on_failure=FailurePolicy.COLLECT,
            deadline=0.1,
        ).run()
        assert result.is_ok is False

class TestProcessWithPlacement:
    @pytest.mark.asyncio
    async def test_decorator_placement(self):
        opus = Placement(model="opus")

        @Process(placement=opus)
        async def placed_agent(ctx: ProcessContext) -> ProcessResult:
            return ProcessResult.ok("placed")

        # Placement should be accessible
        assert placed_agent._placement is not None or hasattr(placed_agent, 'placement')
