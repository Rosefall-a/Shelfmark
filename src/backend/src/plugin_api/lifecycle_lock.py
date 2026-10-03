"""Serialize host package transactions and startup recovery within an event loop."""

import asyncio
from functools import wraps
from typing import Awaitable, Callable, ParamSpec, TypeVar
from weakref import WeakKeyDictionary

_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = WeakKeyDictionary()
_P = ParamSpec("_P")
_R = TypeVar("_R")


def serialized_lifecycle(function: Callable[_P, Awaitable[_R]]) -> Callable[_P, Awaitable[_R]]:
    """Recovery cannot mistake an in-flight installation for an abandoned one."""

    @wraps(function)
    async def serialized(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        loop = asyncio.get_running_loop()
        lock = _locks.setdefault(loop, asyncio.Lock())
        async with lock:
            return await function(*args, **kwargs)

    return serialized
