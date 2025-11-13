import asyncio
import functools
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


def async_retry(
    tries: int = 3, delay: int = 1
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Retry decorator for async functions."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            for attempt in range(tries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < tries - 1:
                        await asyncio.sleep(delay)
            raise last_exception

        return wrapper

    return decorator
