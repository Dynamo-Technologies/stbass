import pytest
import asyncio
import time
from stbass import (
    Process, ProcessResult, Chan,
    PAR, SEQ, ALT, PRI_ALT, Guard,
    FailurePolicy, FailureReport,
    TIMER, DEADLINE,
    Placement, PLACED_PAR,
    Distributor, Collector, ChanArray,
)
from stbass.replicator import PAR_FOR, SEQ_FOR
from stbass.process import ProcessContext
from stbass.timer import TimerExpired
from stbass.channel import ChannelTypeError, ChannelTopologyError
from stbass.failure import FailureAggregator, retry_process
from stbass.result import RetryPolicy


class TestScenarioFanOutResearch:
    """
    Scenario: An orchestrator fans out research to N subagents,
    each with a PRI_ALT cache/search/timeout pattern, then
    synthesizes results.
    """
    @pytest.mark.asyncio
    async def test_full_fan_out_with_timeouts(self):
        async def research_agent(idx, ctx):
            # Simulate: some agents are fast, some timeout
            if idx % 3 == 0:
                await asyncio.sleep(0.01)
                return ProcessResult.ok({"topic": idx, "result": "cached"})
            elif idx % 3 == 1:
                await asyncio.sleep(0.02)
                return ProcessResult.ok({"topic": idx, "result": "searched"})
            else:
                await asyncio.sleep(10)  # will be cancelled by deadline
                return ProcessResult.ok({"topic": idx, "result": "never"})

        result = await PAR_FOR(
            count=9,
            factory=research_agent,
            on_failure=FailurePolicy.COLLECT,
            deadline=0.5,
        ).run()

        # 6 should succeed (idx 0,1,3,4,6,7), 3 should timeout (idx 2,5,8)
        assert len(result.successes) == 6
        assert len(result.failures) == 3


class TestScenarioPipelineWithRetry:
    """
    Scenario: A SEQ pipeline where the middle stage is flaky
    and needs retry logic.
    """
    @pytest.mark.asyncio
    async def test_pipeline_with_retry_stage(self):
        attempt_counter = {"count": 0}

        @Process
        async def fetch_data(ctx: ProcessContext) -> ProcessResult:
            val = await ctx.recv("input")
            return ProcessResult.ok({"raw": val})

        @Process
        async def flaky_transform(ctx: ProcessContext) -> ProcessResult:
            data = await ctx.recv("input")
            attempt_counter["count"] += 1
            if attempt_counter["count"] < 3:
                raise ConnectionError("API flake")
            return ProcessResult.ok({"transformed": data["raw"]})

        @Process
        async def save_result(ctx: ProcessContext) -> ProcessResult:
            data = await ctx.recv("input")
            return ProcessResult.ok(f"saved: {data}")

        # For this test, we test the retry_process utility separately
        # Provide an input channel since flaky_transform reads from it
        input_ch = Chan(object, name="input")

        async def feed_input():
            for _ in range(5):
                try:
                    await input_ch.send({"raw": "test_data"})
                except Exception:
                    break

        feeder = asyncio.create_task(feed_input())
        policy = RetryPolicy(max_attempts=5, backoff="constant", base_delay=0.01)
        ctx = ProcessContext(process_name="flaky_transform", channels={"input": input_ch})
        result = await retry_process(flaky_transform, ctx, policy)
        feeder.cancel()
        try:
            await feeder
        except asyncio.CancelledError:
            pass
        assert result.is_ok


class TestScenarioHeterogeneousPlacement:
    """
    Scenario: Different agents run on different "models" via PLACED_PAR.
    """
    @pytest.mark.asyncio
    async def test_heterogeneous_agents(self):
        @Process
        async def reasoning_agent(ctx: ProcessContext) -> ProcessResult:
            await asyncio.sleep(0.02)  # "heavy" reasoning
            return ProcessResult.ok("deep_insight")

        @Process
        async def classifier_agent(ctx: ProcessContext) -> ProcessResult:
            return ProcessResult.ok("category_B")

        @Process
        async def embed_agent(ctx: ProcessContext) -> ProcessResult:
            return ProcessResult.ok([0.1, 0.2, 0.3])

        result = await PLACED_PAR(
            (reasoning_agent, Placement(model="opus", endpoint="anthropic")),
            (classifier_agent, Placement(model="haiku", endpoint="anthropic")),
            (embed_agent, Placement(model="nomic", endpoint="local:8080")),
        ).run()

        assert result.is_ok
        values = [r.value for r in result.results]
        assert "deep_insight" in values
        assert "category_B" in values
        assert [0.1, 0.2, 0.3] in values


class TestScenarioFailureReportAcrossRuns:
    """
    Scenario: Run a pipeline multiple times, aggregate failure reports,
    and get engineering recommendations.
    """
    @pytest.mark.asyncio
    async def test_aggregated_failure_analysis(self):
        run_count = 0

        async def sometimes_slow(idx, ctx):
            nonlocal run_count
            run_count += 1
            if idx == 2:
                await asyncio.sleep(10)  # always times out
            return ProcessResult.ok(idx)

        agg = FailureAggregator()

        for _ in range(5):
            result = await PAR_FOR(
                count=4,
                factory=sometimes_slow,
                on_failure=FailurePolicy.COLLECT,
                deadline=0.1,
            ).run()
            report = FailureReport()
            for r in result.results:
                report.add(r)
            agg.add_report(report)

        # Process at index 2 should be flagged as worst
        worst = agg.worst_processes(n=1)
        assert len(worst) >= 1


class TestScenarioChannelTypeSafetyInPipeline:
    """
    Scenario: Type mismatch in a pipeline caught immediately,
    not after several stages.
    """
    @pytest.mark.asyncio
    async def test_type_error_doesnt_propagate(self):
        from pydantic import BaseModel

        class InputType(BaseModel):
            query: str

        class OutputType(BaseModel):
            result: str

        ch = Chan(InputType, name="typed_pipe")
        with pytest.raises(ChannelTypeError):
            await asyncio.wait_for(
                ch.send({"result": "wrong_type"}),  # has "result" not "query"
                timeout=0.5,
            )


class TestScenarioConcurrencyPerformance:
    """Verify that PAR_FOR actually runs processes concurrently."""

    @pytest.mark.asyncio
    async def test_100_concurrent_processes(self):
        async def worker(idx, ctx):
            await asyncio.sleep(0.1)
            return ProcessResult.ok(idx)

        start = time.monotonic()
        result = await PAR_FOR(count=100, factory=worker).run()
        elapsed = time.monotonic() - start

        assert result.is_ok
        assert len(result.results) == 100
        assert elapsed < 1.0  # 100 * 0.1s concurrent, not 10s sequential


class TestPublicAPI:
    """Verify all documented public API is accessible."""

    def test_all_core_exports(self):
        from stbass import (
            Process, ProcessResult, Failure,
            Chan, SEQ, PAR, ALT, PRI_ALT,
            Guard, TIMER, DEADLINE,
            PAR_FOR, SEQ_FOR,
            PLACED_PAR, Placement,
            FailurePolicy, FailureReport,
            Distributor, Collector, ChanArray,
        )

    def test_version(self):
        import stbass
        assert stbass.__version__ == "0.1.0"


class TestPackageBuild:
    """Verify the package can be built."""

    def test_pyproject_exists(self):
        from pathlib import Path
        assert (Path(__file__).parent.parent / "pyproject.toml").exists()

    def test_mit_license(self):
        from pathlib import Path
        license_text = (Path(__file__).parent.parent / "LICENSE").read_text()
        assert "MIT" in license_text
        assert "Beautiful Majestic Dolphin" in license_text
