"""Base process class for defining composable concurrent units of work."""

from __future__ import annotations

import copy
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Awaitable

from stbass.result import ProcessResult, Failure
from stbass.channel import Chan

__all__ = ["Process", "ProcessContext"]


@dataclass
class ProcessContext:
    """Runtime context passed to every process."""

    process_name: str
    process_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    channels: dict[str, Chan] = field(default_factory=dict)
    parent: str | None = None
    placement: Any | None = None
    deadline: datetime | None = None
    _checkpoints: list[Any] = field(default_factory=list)

    async def recv(self, channel_name: str) -> Any:
        return await self.get_channel(channel_name).recv()

    async def send(self, channel_name: str, value: Any) -> None:
        await self.get_channel(channel_name).send(value)

    def checkpoint(self, value: Any) -> None:
        self._checkpoints.append(value)

    def get_channel(self, name: str) -> Chan:
        if name not in self.channels:
            raise KeyError(f"Channel '{name}' not found in context")
        return self.channels[name]


class Process:
    """Base class for all stbass processes. Also usable as a decorator."""

    _func: Callable[..., Awaitable[ProcessResult]] | None
    _name: str | None
    _is_optional: bool
    _bound_channels: dict[str, Chan]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        # If Process itself is being used (not a subclass), act as decorator
        if cls is Process:
            if args and callable(args[0]) and not kwargs:
                # @Process with no arguments: @Process applied directly to a function
                return _FuncProcess(args[0])
            if not args and kwargs:
                # @Process(name="...") with keyword arguments: returns a decorator
                return _decorator_factory(**kwargs)
            if args and not callable(args[0]):
                # Positional non-callable arg — shouldn't happen in normal use
                return super().__new__(cls)
        # Subclass instantiation — normal __new__
        instance = super().__new__(cls)
        instance._func = None
        instance._name = None
        instance._is_optional = False
        instance._bound_channels = {}
        return instance

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Skip init for decorator usage (handled by _FuncProcess)
        if type(self) is Process:
            return
        if not hasattr(self, '_func'):
            self._func = None
        if not hasattr(self, '_name'):
            self._name = None
        if not hasattr(self, '_is_optional'):
            self._is_optional = False
        if not hasattr(self, '_bound_channels'):
            self._bound_channels = {}

    @property
    def name(self) -> str:
        if self._name:
            return self._name
        return type(self).__name__

    @property
    def process_id(self) -> str:
        return str(uuid.uuid4())

    async def run(self, ctx: ProcessContext) -> ProcessResult:
        raise NotImplementedError("Subclasses must implement run()")

    async def execute(self, ctx: ProcessContext) -> ProcessResult:
        started_at = datetime.now()
        try:
            result = await self.run(ctx)
            return result
        except Exception as e:
            failed_at = datetime.now()
            tb_str = traceback.format_exc()
            failure = Failure(
                error=e,
                process_name=ctx.process_name,
                process_id=ctx.process_id,
                started_at=started_at,
                failed_at=failed_at,
                parent_process=ctx.parent,
                placement=ctx.placement,
                checkpoint=ctx._checkpoints[-1] if ctx._checkpoints else None,
                traceback_str=tb_str,
            )
            return ProcessResult(
                _ok=False,
                _failure=failure,
            )

    def optional(self) -> Process:
        wrapped = copy.copy(self)
        wrapped._is_optional = True
        return wrapped

    def with_channels(self, **channels: Chan) -> Process:
        wrapped = copy.copy(self)
        wrapped._bound_channels = {**getattr(self, '_bound_channels', {}), **channels}
        return wrapped

    def with_name(self, name: str) -> Process:
        wrapped = copy.copy(self)
        wrapped._name = name
        return wrapped


class _FuncProcess(Process):
    """A Process wrapping an async function."""

    def __init__(self, func: Callable[..., Awaitable[ProcessResult]], name: str | None = None, placement: Any | None = None):
        self._func = func
        self._name = name or func.__name__
        self._is_optional = False
        self._bound_channels = {}
        self._placement = placement

    @property
    def name(self) -> str:
        return self._name

    async def run(self, ctx: ProcessContext) -> ProcessResult:
        return await self._func(ctx)


def _decorator_factory(**kwargs: Any) -> Callable:
    """Returns a decorator that wraps an async function as a Process."""
    def decorator(func: Callable[..., Awaitable[ProcessResult]]) -> _FuncProcess:
        return _FuncProcess(func, **kwargs)
    return decorator
