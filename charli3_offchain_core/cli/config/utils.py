"""CLI utility functions and decorators."""

import asyncio
import logging
from functools import wraps


def setup_logging(verbose: bool) -> None:
    """Configure logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def async_command(f) -> callable:
    """Decorator to run async click commands."""

    @wraps(f)
    def wrapper(*args, **kwargs) -> None:

        return asyncio.run(f(*args, **kwargs))

    return wrapper
