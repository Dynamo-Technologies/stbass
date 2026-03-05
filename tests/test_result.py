import pytest
from datetime import datetime, timedelta
from stbass import ProcessResult, Failure, FailurePolicy, FailureReport
from stbass.result import RetryPolicy

class TestProcessResult:
    def test_ok_result(self):
        r = ProcessResult.ok(42)
        assert r.is_ok is True
        assert r.is_fail is False
        assert r.value == 42

    def test_fail_result(self):
        err = ValueError("something broke")
        r = ProcessResult.fail(err, process_name="test_proc")
        assert r.is_fail is True
        assert r.is_ok is False
        assert r.failure.error is err
        assert r.failure.process_name == "test_proc"

    def test_value_raises_on_failure(self):
        r = ProcessResult.fail(RuntimeError("bad"))
        with pytest.raises(RuntimeError):
            _ = r.value

    def test_failure_raises_on_success(self):
        r = ProcessResult.ok("good")
        with pytest.raises(AttributeError):
            _ = r.failure

    def test_ok_with_none_value(self):
        r = ProcessResult.ok(None)
        assert r.is_ok is True
        assert r.value is None

    def test_immutability(self):
        r = ProcessResult.ok(42)
        with pytest.raises((AttributeError, TypeError)):
            r.is_ok = False

class TestFailure:
    def test_auto_generated_id(self):
        f = Failure(error=ValueError("x"))
        assert f.process_id is not None
        assert len(f.process_id) > 0

    def test_elapsed_computed(self):
        start = datetime(2026, 1, 1, 12, 0, 0)
        end = datetime(2026, 1, 1, 12, 0, 30)
        f = Failure(error=ValueError("x"), started_at=start, failed_at=end)
        assert f.elapsed == timedelta(seconds=30)

    def test_elapsed_none_without_start(self):
        f = Failure(error=ValueError("x"))
        assert f.elapsed is None or isinstance(f.elapsed, timedelta)

    def test_summary_is_oneliner(self):
        f = Failure(error=ValueError("oops"), process_name="agent_a")
        assert "agent_a" in f.summary
        assert "oops" in f.summary
        assert "\n" not in f.summary

    def test_detailed_is_multiline(self):
        f = Failure(
            error=ValueError("oops"),
            process_name="agent_a",
            parent_process="orchestrator",
        )
        detailed = f.detailed
        assert "\n" in detailed
        assert "agent_a" in detailed

    def test_traceback_captured(self):
        try:
            raise ValueError("capture me")
        except ValueError as e:
            import traceback
            tb = traceback.format_exc()
            f = Failure(error=e, traceback_str=tb)
            assert "capture me" in f.traceback_str

class TestFailurePolicy:
    def test_halt_exists(self):
        assert FailurePolicy.HALT is not None

    def test_collect_exists(self):
        assert FailurePolicy.COLLECT is not None

    def test_retry_returns_policy(self):
        rp = FailurePolicy.retry(max_attempts=3, backoff="exponential")
        assert isinstance(rp, RetryPolicy)
        assert rp.max_attempts == 3

class TestRetryPolicy:
    def test_exponential_backoff(self):
        rp = RetryPolicy(max_attempts=5, backoff="exponential", base_delay=1.0)
        assert rp.delay_for(0) == 1.0
        assert rp.delay_for(1) == 2.0
        assert rp.delay_for(2) == 4.0
        assert rp.delay_for(3) == 8.0

    def test_linear_backoff(self):
        rp = RetryPolicy(max_attempts=5, backoff="linear", base_delay=2.0)
        assert rp.delay_for(0) == 2.0
        assert rp.delay_for(1) == 4.0
        assert rp.delay_for(2) == 6.0

    def test_constant_backoff(self):
        rp = RetryPolicy(max_attempts=5, backoff="constant", base_delay=3.0)
        assert rp.delay_for(0) == 3.0
        assert rp.delay_for(1) == 3.0
        assert rp.delay_for(5) == 3.0

class TestFailureReport:
    def test_empty_report(self):
        fr = FailureReport()
        assert fr.total_processes == 0
        assert fr.failure_rate == 0.0

    def test_add_success(self):
        fr = FailureReport()
        fr.add(ProcessResult.ok("good"))
        assert fr.total_processes == 1
        assert fr.succeeded == 1
        assert fr.failed == 0

    def test_add_failure(self):
        fr = FailureReport()
        fr.add(ProcessResult.fail(ValueError("bad"), process_name="p1"))
        assert fr.total_processes == 1
        assert fr.failed == 1
        assert fr.failure_rate == 1.0

    def test_mixed_results(self):
        fr = FailureReport()
        fr.add(ProcessResult.ok("a"))
        fr.add(ProcessResult.ok("b"))
        fr.add(ProcessResult.fail(ValueError("c")))
        assert fr.total_processes == 3
        assert fr.succeeded == 2
        assert fr.failed == 1
        assert abs(fr.failure_rate - 1/3) < 0.01

    def test_common_failure_types(self):
        fr = FailureReport()
        fr.add(ProcessResult.fail(ValueError("a")))
        fr.add(ProcessResult.fail(ValueError("b")))
        fr.add(ProcessResult.fail(TypeError("c")))
        types = fr.common_failure_types
        assert types["ValueError"] == 2
        assert types["TypeError"] == 1

    def test_summary_is_string(self):
        fr = FailureReport()
        fr.add(ProcessResult.ok("x"))
        fr.add(ProcessResult.fail(RuntimeError("y")))
        s = fr.summary()
        assert isinstance(s, str)
        assert "2" in s  # total
        assert "1" in s  # at least one count
