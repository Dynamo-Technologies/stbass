"""Alternation constructs for guarded choice over channels."""

from __future__ import annotations

import asyncio
import inspect
import random
from typing import Any, Callable

__all__ = ["ALT", "PRI_ALT", "Guard", "SKIP", "AllGuardsDisabledError"]


class AllGuardsDisabledError(Exception):
    """Raised when all guards in an ALT have false preconditions."""
    pass


class _SkipSentinel:
    """Sentinel for the SKIP guard — always ready."""
    pass


SKIP = _SkipSentinel()


class Guard:
    """A guard condition on a channel for use in ALT constructs."""

    def __init__(self, channel: Any, *, precondition: bool | Callable[[], bool] = True, handler: Callable | None = None):
        self.channel = channel
        self._precondition = precondition
        self.handler = handler

    @property
    def is_eligible(self) -> bool:
        if callable(self._precondition):
            return self._precondition()
        return bool(self._precondition)


async def ALT(*guards: Guard) -> Any:
    """Wait for one of several guarded channel operations, choosing fairly."""
    return await _alt_impl(guards, fair=True)


async def PRI_ALT(*guards: Guard) -> Any:
    """Wait for one of several guarded channel operations, by priority."""
    return await _alt_impl(guards, fair=False)


def _is_timer_like(channel: Any) -> bool:
    from stbass.timer import TIMER, DEADLINE
    return isinstance(channel, (TIMER, DEADLINE))


def _is_guard_ready(guard: Guard, timer_events: dict) -> bool:
    if isinstance(guard.channel, _SkipSentinel):
        return True
    elif _is_timer_like(guard.channel):
        event = timer_events.get(id(guard))
        return event is not None and event.is_set()
    else:
        return not guard.channel._queue.empty()


def _call_handler(handler: Callable, value: Any) -> Any:
    """Call handler with value, or without args if it accepts none."""
    sig = inspect.signature(handler)
    if len(sig.parameters) == 0:
        return handler()
    return handler(value)


async def _fire_guard(guard: Guard, timer_events: dict, started_at: Any = None) -> Any:
    from stbass.timer import TimerExpired

    if isinstance(guard.channel, _SkipSentinel):
        if guard.handler:
            return _call_handler(guard.handler, None)
        return None
    elif _is_timer_like(guard.channel):
        from datetime import datetime, timedelta
        now = datetime.now()
        sa = started_at or now
        value = TimerExpired(
            started_at=sa,
            deadline=sa + timedelta(seconds=guard.channel.seconds) if not hasattr(guard.channel, 'target') else guard.channel.target,
            elapsed=now - sa,
            timer_name=guard.channel.name,
        )
        guard.channel.is_expired = True
        if guard.handler:
            return _call_handler(guard.handler, value)
        return value
    else:
        value = await guard.channel.recv()
        if guard.handler:
            return guard.handler(value)
        return value


async def _alt_impl(guards: tuple[Guard, ...], fair: bool) -> Any:
    from datetime import datetime

    has_dynamic = any(callable(g._precondition) for g in guards)
    started_at = datetime.now()

    # Start timer tasks
    timer_events: dict[int, asyncio.Event] = {}
    timer_tasks: list[asyncio.Task] = []
    for g in guards:
        if _is_timer_like(g.channel):
            event = asyncio.Event()

            async def fire_timer(ev: asyncio.Event, secs: float) -> None:
                await asyncio.sleep(secs)
                ev.set()

            task = asyncio.create_task(fire_timer(event, g.channel.seconds))
            timer_events[id(g)] = event
            timer_tasks.append(task)

    try:
        while True:
            eligible = [g for g in guards if g.is_eligible]

            if not eligible:
                if not has_dynamic:
                    raise AllGuardsDisabledError("All guards have false preconditions")
                await asyncio.sleep(0)
                continue

            # Find ready guards (preserving declaration order)
            ready = [g for g in eligible if _is_guard_ready(g, timer_events)]

            if not ready:
                await asyncio.sleep(0)
                continue

            # Select winner
            if fair:
                # ALT: prefer non-SKIP guards, random among them
                non_skip = [g for g in ready if not isinstance(g.channel, _SkipSentinel)]
                if non_skip:
                    winner = random.choice(non_skip)
                else:
                    winner = ready[0]
            else:
                # PRI_ALT: first ready in declaration order
                winner = ready[0]

            return await _fire_guard(winner, timer_events, started_at=started_at)
    finally:
        for task in timer_tasks:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
