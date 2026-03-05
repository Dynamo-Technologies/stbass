import pytest
import asyncio
from datetime import datetime, timedelta
from stbass import ProcessResult, Failure, FailurePolicy, FailureReport, Process
from stbass.result import RetryPolicy
from stbass.failure import FailureAggregator, retry_process
from stbass.process import ProcessContext
from stbass.timer import TimerExpired

class TestFailureReportPatterns:
    def test_repeat_timeouts(self):
        fr = FailureReport()
        for i in range(5):
            te = TimerExpired(
                started_at=datetime.now(),
                deadline=datetime.now(),
                elapsed=timedelta(seconds=30),
                timer_name="timeout",
            )
            fr.add(ProcessResult.fail(te, process_name="slow_agent"))
        patterns = fr.pattern_analysis()
        assert "slow_agent" in patterns["repeat_timeouts"]

    def test_repeat_errors(self):
        fr = FailureReport()
        for _ in range(3):
            fr.add(ProcessResult.fail(ValueError("bad input"), process_name="parser"))
        fr.add(ProcessResult.ok("good"))
        patterns = fr.pattern_analysis()
        assert ("parser", "ValueError") in patterns["repeat_errors"]

    def test_cascade_detection(self):
        fr = FailureReport()
        now = datetime.now()
        for i in range(3):
            f = Failure(
                error=RuntimeError("cascade"),
                process_name=f"proc_{i}",
                failed_at=now + timedelta(milliseconds=i * 10),
            )
            fr._add_failure(f)
        patterns = fr.pattern_analysis()
        assert patterns["cascade_failures"] is True

class TestFailureReportRecommendations:
    def test_timeout_recommendation(self):
        fr = FailureReport()
        te = TimerExpired(
            started_at=datetime.now(), deadline=datetime.now(),
            elapsed=timedelta(seconds=30), timer_name="t",
        )
        for _ in range(3):
            fr.add(ProcessResult.fail(te, process_name="slow"))
        fr.add(ProcessResult.ok("x"))
        fr.add(ProcessResult.ok("y"))
        recs = fr.recommendations()
        assert any("slow" in r and "timeout" in r.lower() for r in recs)

    def test_to_dict(self):
        fr = FailureReport()
        fr.add(ProcessResult.ok("a"))
        fr.add(ProcessResult.fail(ValueError("b")))
        d = fr.to_dict()
        assert d["total_processes"] == 2
        assert d["succeeded"] == 1
        assert d["failed"] == 1

class TestFailureAggregator:
    def test_add_reports(self):
        agg = FailureAggregator()
        fr1 = FailureReport()
        fr1.add(ProcessResult.fail(ValueError("x"), process_name="proc_a"))
        fr2 = FailureReport()
        fr2.add(ProcessResult.fail(ValueError("y"), process_name="proc_a"))
        agg.add_report(fr1)
        agg.add_report(fr2)
        worst = agg.worst_processes(n=1)
        assert "proc_a" in worst

    def test_overall_summary(self):
        agg = FailureAggregator()
        fr = FailureReport()
        fr.add(ProcessResult.ok("x"))
        agg.add_report(fr)
        s = agg.overall_summary()
        assert isinstance(s, str)

class TestRetryProcess:
    @pytest.mark.asyncio
    async def test_retry_succeeds_eventually(self):
        attempt_count = 0

        @Process
        async def flaky(ctx: ProcessContext) -> ProcessResult:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise ValueError("not yet")
            return ProcessResult.ok("finally")

        policy = RetryPolicy(max_attempts=5, backoff="constant", base_delay=0.01)
        ctx = ProcessContext(process_name="flaky")
        result = await retry_process(flaky, ctx, policy)
        assert result.is_ok
        assert result.value == "finally"
        assert attempt_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        @Process
        async def always_fails(ctx: ProcessContext) -> ProcessResult:
            raise RuntimeError("permanent")

        policy = RetryPolicy(max_attempts=3, backoff="constant", base_delay=0.01)
        ctx = ProcessContext(process_name="always_fails")
        result = await retry_process(always_fails, ctx, policy)
        assert result.is_fail
        assert "permanent" in str(result.failure.error)

    @pytest.mark.asyncio
    async def test_exponential_backoff_timing(self):
        import time
        timestamps = []

        @Process
        async def timed_fail(ctx: ProcessContext) -> ProcessResult:
            timestamps.append(time.monotonic())
            raise ValueError("fail")

        policy = RetryPolicy(max_attempts=3, backoff="exponential", base_delay=0.05)
        ctx = ProcessContext(process_name="timed_fail")
        await retry_process(timed_fail, ctx, policy)

        # Should have 3 timestamps with increasing delays
        assert len(timestamps) == 3
        delay_1 = timestamps[1] - timestamps[0]
        delay_2 = timestamps[2] - timestamps[1]
        assert delay_2 > delay_1  # exponential grows
