"""Typed channels for inter-process communication."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from pydantic import BaseModel, ValidationError

__all__ = [
    "Chan",
    "ChannelTypeError",
    "ChannelTopologyError",
    "ChannelClosedError",
    "ChannelProtocolError",
    "SequentialProtocol",
    "VariantProtocol",
]


class ChannelTypeError(TypeError):
    """Raised when a value does not match the channel's type specification."""

    def __init__(self, expected: Any, actual: Any, channel_name: str, message: str | None = None):
        self.expected = expected
        self.actual = actual
        self.channel_name = channel_name
        if message is None:
            message = f"Channel '{channel_name}': expected {expected}, got {actual}"
        super().__init__(message)


class ChannelTopologyError(Exception):
    """Raised when channel binding discipline is violated."""

    def __init__(self, channel_name: str, message: str | None = None):
        self.channel_name = channel_name
        if message is None:
            message = f"Topology violation on channel '{channel_name}'"
        super().__init__(message)


class ChannelClosedError(Exception):
    """Raised when operating on a closed channel."""

    def __init__(self, channel_name: str):
        self.channel_name = channel_name
        super().__init__(f"Channel '{channel_name}' is closed")


class ChannelProtocolError(Exception):
    """Raised when a sequential protocol's sequence is exhausted."""

    def __init__(self, channel_name: str, message: str | None = None):
        self.channel_name = channel_name
        if message is None:
            message = f"Protocol sequence exhausted on channel '{channel_name}'"
        super().__init__(message)


class SequentialProtocol:
    """Channel must carry types in this exact order."""

    def __init__(self, *types: type):
        self.types = types
        self._position = 0

    def current_type(self) -> type:
        if self._position >= len(self.types):
            raise IndexError("Sequence exhausted")
        return self.types[self._position]

    def advance(self) -> None:
        self._position += 1

    def reset(self) -> None:
        self._position = 0


class VariantProtocol:
    """Channel accepts any of the specified types."""

    def __init__(self, *types: type):
        self.types = types


def _validate_single(value: Any, type_spec: type, channel_name: str) -> Any:
    """Validate a value against a single type specification."""
    if isinstance(type_spec, type) and issubclass(type_spec, BaseModel):
        if isinstance(value, type_spec):
            return value
        if isinstance(value, dict):
            try:
                return type_spec.model_validate(value)
            except ValidationError as e:
                raise ChannelTypeError(
                    expected=type_spec.__name__,
                    actual=type(value).__name__,
                    channel_name=channel_name,
                    message=f"Channel '{channel_name}': expected {type_spec.__name__}, validation failed: {e}",
                ) from e
        raise ChannelTypeError(
            expected=type_spec.__name__,
            actual=type(value).__name__,
            channel_name=channel_name,
        )

    if not isinstance(value, type_spec):
        raise ChannelTypeError(
            expected=type_spec.__name__,
            actual=type(value).__name__,
            channel_name=channel_name,
        )
    return value


_CLOSED_SENTINEL = object()


class Chan:
    """A typed communication channel between processes with rendezvous semantics."""

    def __init__(self, type_spec: Any, *, name: str | None = None):
        self._type_spec = type_spec
        self._name = name or f"chan_{uuid.uuid4().hex[:8]}"
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._ack = asyncio.Event()
        self._closed = False
        self._writer_id: str | None = None
        self._reader_id: str | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def type_spec(self) -> Any:
        return self._type_spec

    @property
    def writer_attached(self) -> bool:
        return self._writer_id is not None

    @property
    def reader_attached(self) -> bool:
        return self._reader_id is not None

    @property
    def is_bound(self) -> bool:
        return self.writer_attached and self.reader_attached

    def bind_writer(self, process_id: str) -> None:
        if self._writer_id is not None:
            raise ChannelTopologyError(
                self._name,
                f"Channel '{self._name}': writer already bound to '{self._writer_id}', cannot bind '{process_id}'",
            )
        self._writer_id = process_id

    def bind_reader(self, process_id: str) -> None:
        if self._reader_id is not None:
            raise ChannelTopologyError(
                self._name,
                f"Channel '{self._name}': reader already bound to '{self._reader_id}', cannot bind '{process_id}'",
            )
        self._reader_id = process_id

    def unbind_writer(self) -> None:
        self._writer_id = None

    def unbind_reader(self) -> None:
        self._reader_id = None

    def close(self) -> None:
        self._closed = True
        self._ack.set()  # unblock any waiting sender
        try:
            self._queue.put_nowait(_CLOSED_SENTINEL)  # unblock any waiting reader
        except asyncio.QueueFull:
            pass

    def _validate(self, value: Any) -> Any:
        ts = self._type_spec

        if isinstance(ts, SequentialProtocol):
            try:
                current = ts.current_type()
            except IndexError:
                raise ChannelProtocolError(self._name)
            validated = _validate_single(value, current, self._name)
            ts.advance()
            return validated

        if isinstance(ts, VariantProtocol):
            for t in ts.types:
                try:
                    return _validate_single(value, t, self._name)
                except ChannelTypeError:
                    continue
            type_names = ", ".join(t.__name__ for t in ts.types)
            raise ChannelTypeError(
                expected=type_names,
                actual=type(value).__name__,
                channel_name=self._name,
            )

        return _validate_single(value, ts, self._name)

    async def send(self, value: Any) -> None:
        if self._closed:
            raise ChannelClosedError(self._name)
        validated = self._validate(value)
        self._ack.clear()
        await self._queue.put(validated)
        await self._ack.wait()
        if self._closed:
            raise ChannelClosedError(self._name)

    async def recv(self) -> Any:
        if self._closed and self._queue.empty():
            raise ChannelClosedError(self._name)
        value = await self._queue.get()
        if value is _CLOSED_SENTINEL:
            raise ChannelClosedError(self._name)
        self._ack.set()
        return value
