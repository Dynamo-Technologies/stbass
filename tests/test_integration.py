import pytest
import asyncio
from stbass import (
    Process, ProcessResult, Chan,
    PAR, SEQ, ALT, PRI_ALT, Guard,
    FailurePolicy, FailureReport,
)
from stbass.replicator import PAR_FOR, SEQ_FOR
from stbass.topology import ChanArray, Distributor, Collector
from stbass.placement import Placement, PLACED_PAR
from stbass.timer import TIMER, TimerExpired
from stbass.process import ProcessContext

class TestSEQIntoPAR:
    """SEQ pipeline that includes a PAR stage."""

    @pytest.mark.asyncio
    async def test_seq_with_par_stage(self):
        @Process
        async def prepare(ctx: ProcessContext) -> ProcessResult:
            val = await ctx.recv("input")
            return ProcessResult.ok([val, val + 1, val + 2])

        @Process
        async def parallel_process(ctx: ProcessContext) -> ProcessResult:
            items = await ctx.recv("input")
            results = []
            result = await PAR_FOR(
                count=len(items),
                factory=lambda i, c: square(i, items[i], c),
            ).run()
            return ProcessResult.ok([r.value for r in result.results])

        async def square(idx, val, ctx):
            return ProcessResult.ok(val ** 2)

        @Process
        async def aggregate(ctx: ProcessContext) -> ProcessResult:
            items = await ctx.recv("input")
            return ProcessResult.ok(sum(items))

        result = await SEQ(prepare, parallel_process, aggregate).run(input_value=10)
        assert result.is_ok
        # 10^2 + 11^2 + 12^2 = 100 + 121 + 144 = 365
        assert result.value == 365

class TestPARWithALTFallback:
    """PAR where each process uses ALT with timer fallback."""

    @pytest.mark.asyncio
    async def test_par_processes_with_alt_timeouts(self):
        @Process
        async def agent_with_fallback(ctx: ProcessContext) -> ProcessResult:
            ch = Chan(str)
            # Channel never gets data, so timer fires
            result = await PRI_ALT(
                Guard(ch, handler=lambda v: v),
                Guard(TIMER(seconds=0.05), handler=lambda v: "timed_out"),
            )
            return ProcessResult.ok(result)

        result = await PAR(
            agent_with_fallback, agent_with_fallback, agent_with_fallback,
        ).run()
        assert result.is_ok
        for r in result.results:
            assert r.value == "timed_out"

class TestDynamicSubagentSpawning:
    """Simulates agents that spawn subagents that spawn more subagents."""

    @pytest.mark.asyncio
    async def test_three_level_nesting(self):
        leaf_count = 0

        async def level_3(idx, ctx):
            nonlocal leaf_count
            leaf_count += 1
            return ProcessResult.ok(f"leaf_{idx}")

        async def level_2(idx, ctx):
            r = await PAR_FOR(count=2, factory=level_3).run()
            return ProcessResult.ok(f"mid_{idx}")

        async def level_1(idx, ctx):
            r = await PAR_FOR(count=3, factory=level_2).run()
            return ProcessResult.ok(f"top_{idx}")

        result = await PAR_FOR(count=2, factory=level_1).run()
        assert result.is_ok
        assert leaf_count == 12  # 2 * 3 * 2

class TestFailureIsolation:
    """Failures in one PAR branch don't corrupt other branches."""

    @pytest.mark.asyncio
    async def test_collect_isolates_failures(self):
        @Process
        async def good_agent(ctx: ProcessContext) -> ProcessResult:
            await asyncio.sleep(0.05)
            return ProcessResult.ok("good")

        @Process
        async def bad_agent(ctx: ProcessContext) -> ProcessResult:
            raise ValueError("corrupted")

        result = await PAR(
            good_agent, bad_agent, good_agent,
            on_failure=FailurePolicy.COLLECT
        ).run()
        assert len(result.successes) == 2
        assert len(result.failures) == 1
        for s in result.successes:
            assert s.value == "good"  # not corrupted

class TestChannelTypeSafety:
    """Type mismatches caught at boundaries, not downstream."""

    @pytest.mark.asyncio
    async def test_type_error_immediate(self):
        from stbass.channel import ChannelTypeError
        ch = Chan(int, name="typed_ch")

        with pytest.raises(ChannelTypeError):
            await asyncio.wait_for(ch.send("not_an_int"), timeout=0.5)

class TestPLACED_PARWithFailureReport:
    """Placed processes carry placement info through failure reports."""

    @pytest.mark.asyncio
    async def test_placement_in_report(self):
        opus = Placement(model="opus", endpoint="anthropic")
        haiku = Placement(model="haiku", endpoint="anthropic")

        @Process
        async def opus_fails(ctx: ProcessContext) -> ProcessResult:
            raise RuntimeError("opus error")

        @Process
        async def haiku_ok(ctx: ProcessContext) -> ProcessResult:
            return ProcessResult.ok("classified")

        result = await PLACED_PAR(
            (opus_fails, opus),
            (haiku_ok, haiku),
            on_failure=FailurePolicy.COLLECT,
        ).run()

        report = FailureReport()
        for r in result.results:
            report.add(r)

        assert report.failed == 1
        assert report.succeeded == 1

class TestEndToEndResearchPipeline:
    """Simulates the research pipeline from the design spec."""

    @pytest.mark.asyncio
    async def test_research_pipeline(self):
        @Process
        async def plan(ctx: ProcessContext) -> ProcessResult:
            query = await ctx.recv("input")
            return ProcessResult.ok(["subtopic_a", "subtopic_b", "subtopic_c"])

        @Process
        async def research_all(ctx: ProcessContext) -> ProcessResult:
            subtopics = await ctx.recv("input")
            async def research_one(idx, c):
                return ProcessResult.ok({"topic": subtopics[idx], "finding": f"result_{idx}"})
            result = await PAR_FOR(
                count=len(subtopics), factory=research_one,
                on_failure=FailurePolicy.COLLECT,
                deadline=5.0,
            ).run()
            return ProcessResult.ok([r.value for r in result.successes])

        @Process
        async def synthesize(ctx: ProcessContext) -> ProcessResult:
            findings = await ctx.recv("input")
            return ProcessResult.ok(f"Report with {len(findings)} findings")

        result = await SEQ(plan, research_all, synthesize).run(
            input_value="AI safety research"
        )
        assert result.is_ok
        assert "3 findings" in result.value
