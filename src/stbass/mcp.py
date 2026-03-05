"""MCP (Model Context Protocol) integration for agentic process orchestration."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import httpx

from stbass.process import Process, ProcessContext
from stbass.result import ProcessResult
from stbass.placement import ExecutionBackend

__all__ = ["MCPProcess", "MCPServer", "MCPBackend"]


class MCPProcess(Process):
    """Wraps a single MCP tool as an stbass Process."""

    def __init__(self, server_url: str, tool_name: str, *, timeout: float = 30.0):
        self._server_url = server_url
        self._tool_name = tool_name
        self._timeout = timeout
        self._name = f"mcp:{tool_name}"
        self._is_optional = False
        self._bound_channels = {}
        self._func = None

    @property
    def name(self) -> str:
        return self._name

    async def _call_tool(self, arguments: Any = None) -> Any:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                self._server_url,
                json={"tool": self._tool_name, "arguments": arguments or {}},
            )
            response.raise_for_status()
            return response.json()

    async def run(self, ctx: ProcessContext) -> ProcessResult:
        try:
            result = await asyncio.wait_for(
                self._call_tool(),
                timeout=self._timeout,
            )
            return ProcessResult.ok(result)
        except asyncio.TimeoutError:
            return ProcessResult.fail(
                TimeoutError(f"MCP tool '{self._tool_name}' timed out after {self._timeout}s"),
                process_name=ctx.process_name,
            )
        except Exception as e:
            return ProcessResult.fail(e, process_name=ctx.process_name)


class MCPServer:
    """Represents a connected MCP server."""

    def __init__(self, url: str, *, name: str | None = None):
        self._url = url
        self._name = name or url

    @property
    def url(self) -> str:
        return self._url

    @property
    def name(self) -> str:
        return self._name

    def tool(self, tool_name: str, *, timeout: float = 30.0) -> MCPProcess:
        return MCPProcess(self._url, tool_name, timeout=timeout)

    async def _ping(self) -> bool:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(self._url)
            return response.status_code == 200

    async def health(self) -> bool:
        try:
            return await self._ping()
        except Exception:
            return False

    async def tools(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._url}/tools")
                response.raise_for_status()
                return response.json().get("tools", [])
        except Exception:
            return []


class MCPBackend(ExecutionBackend):
    """Execution backend that routes processes to an MCP server."""

    def __init__(self, server_url: str):
        self._server_url = server_url

    async def execute(self, process: Process, ctx: ProcessContext) -> ProcessResult:
        return await process.execute(ctx)

    async def health_check(self) -> bool:
        server = MCPServer(self._server_url)
        return await server.health()

    @property
    def concurrency_limit(self) -> int:
        return sys.maxsize

    @property
    def name(self) -> str:
        return f"mcp:{self._server_url}"
