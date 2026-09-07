"""
TRACES Automation — Retry Decorator

Configurable retry with exponential backoff for safe-retryable operations.
"""

import functools
import time
from typing import Any, Callable, Optional, Tuple, Type

from utils.logger import logger
from config import MAX_RETRIES, RETRY_BACKOFF_FACTOR


def retry(
    max_attempts: int = MAX_RETRIES,
    backoff_factor: float = RETRY_BACKOFF_FACTOR,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_failure: Optional[Callable[..., Any]] = None,
) -> Callable:
    """Decorator that retries a function on specified exceptions.

    Args:
        max_attempts:         Maximum total attempts (including the first).
        backoff_factor:       Multiplier for exponential backoff between retries.
        retryable_exceptions: Tuple of exception classes considered retryable.
        on_failure:           Optional callback(exc, attempt) invoked on each failure.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exception = exc
                    if attempt < max_attempts:
                        wait = backoff_factor ** (attempt - 1)
                        logger.warning(
                            "Retry %d/%d for %s — %s. Waiting %.1fs…",
                            attempt,
                            max_attempts,
                            func.__name__,
                            exc,
                            wait,
                        )
                        if on_failure:
                            on_failure(exc, attempt)
                        time.sleep(wait)
                    else:
                        logger.error(
                            "All %d attempts failed for %s — %s",
                            max_attempts,
                            func.__name__,
                            exc,
                        )
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator
