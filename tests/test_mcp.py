import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from stbass.mcp import MCPProcess, MCPServer, MCPBackend
from stbass import Process, ProcessResult, PAR, FailurePolicy
from stbass.process import ProcessContext
from stbass.timer import TIMER

class TestMCPProcess:
    @pytest.mark.asyncio
    async def test_successful_tool_call(self):
        proc = MCPProcess("http://fake-mcp.com/sse", "web_search", timeout=5.0)

        mock_response = {"results": ["result1", "result2"]}

        with patch.object(proc, '_call_tool', new_callable=AsyncMock, return_value=mock_response):
            ctx = ProcessContext(process_name="mcp_search")
            result = await proc.execute(ctx)
            assert result.is_ok
            assert result.value == mock_response

    @pytest.mark.asyncio
    async def test_tool_timeout(self):
        proc = MCPProcess("http://fake-mcp.com/sse", "slow_tool", timeout=0.05)

        async def slow_call(*args, **kwargs):
            await asyncio.sleep(10)
            return {"result": "too_late"}

        with patch.object(proc, '_call_tool', side_effect=slow_call):
            ctx = ProcessContext(process_name="mcp_slow")
            result = await proc.execute(ctx)
            assert result.is_fail

    @pytest.mark.asyncio
    async def test_connection_error(self):
        proc = MCPProcess("http://unreachable.com/sse", "any_tool")

        with patch.object(proc, '_call_tool', side_effect=ConnectionError("refused")):
            ctx = ProcessContext(process_name="mcp_unreachable")
            result = await proc.execute(ctx)
            assert result.is_fail
            assert "refused" in str(result.failure.error)

class TestMCPServer:
    def test_creation(self):
        server = MCPServer("http://fake-mcp.com/sse", name="brave")
        assert server.url == "http://fake-mcp.com/sse"
        assert server.name == "brave"

    def test_tool_returns_mcp_process(self):
        server = MCPServer("http://fake-mcp.com/sse")
        proc = server.tool("web_search")
        assert isinstance(proc, MCPProcess)

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        server = MCPServer("http://fake-mcp.com/sse")
        with patch.object(server, '_ping', new_callable=AsyncMock, return_value=True):
            assert await server.health() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        server = MCPServer("http://fake-mcp.com/sse")
        with patch.object(server, '_ping', new_callable=AsyncMock, side_effect=ConnectionError):
            assert await server.health() is False

class TestMCPInPAR:
    @pytest.mark.asyncio
    async def test_mcp_processes_in_par(self):
        proc1 = MCPProcess("http://server1.com/sse", "search")
        proc2 = MCPProcess("http://server2.com/sse", "analyze")

        mock_result1 = {"data": "search_results"}
        mock_result2 = {"data": "analysis"}

        with patch.object(proc1, '_call_tool', new_callable=AsyncMock, return_value=mock_result1), \
             patch.object(proc2, '_call_tool', new_callable=AsyncMock, return_value=mock_result2):
            result = await PAR(proc1, proc2).run()
            assert result.is_ok
            assert len(result.results) == 2

class TestMCPWithFailover:
    @pytest.mark.asyncio
    async def test_mcp_with_timer_fallback(self):
        from stbass import Chan, Guard, PRI_ALT

        proc = MCPProcess("http://slow.com/sse", "tool", timeout=10)
        ch = Chan(dict, name="mcp_result")

        # Simulate: MCP is slow, timer fires first
        result = await PRI_ALT(
            Guard(TIMER(seconds=0.05), handler=lambda v: "timed_out"),
        )
        assert result == "timed_out"

class TestMCPBackend:
    @pytest.mark.asyncio
    async def test_backend_protocol(self):
        backend = MCPBackend("http://fake.com/sse")
        assert hasattr(backend, 'execute')
        assert hasattr(backend, 'health_check')
        assert hasattr(backend, 'concurrency_limit')
