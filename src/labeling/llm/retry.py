import logging
import re
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


def _extract_retry_seconds(error_message: str) -> float:
    match = re.search(r"try again in (\d+)ms", error_message, flags=re.IGNORECASE)
    if not match:
        return 1.0
    milliseconds = int(match.group(1))
    return max(0.1, milliseconds / 1000.0)


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return type(exc).__name__ == "RateLimitError" or ("rate" in text and "limit" in text)


def _call_with_rate_limit_retry(
    *,
    run_id: str,
    hypothesis_id: str,
    location: str,
    call: Callable[[], _T],
    max_attempts: int = 8,
) -> _T:
    attempt = 0
    while True:
        attempt += 1
        try:
            return call()
        except Exception as exc:
            if not _is_rate_limit_error(exc) or attempt >= max_attempts:
                logger.warning(
                    "LLM call failed without retry recovery: location=%s attempt=%s error_type=%s",
                    location,
                    attempt,
                    type(exc).__name__,
                )
                raise
            retry_in = _extract_retry_seconds(str(exc))
            logger.info(
                "LLM rate limit retry: location=%s attempt=%s sleep=%.3fs",
                location,
                attempt,
                retry_in,
            )
            time.sleep(retry_in)
