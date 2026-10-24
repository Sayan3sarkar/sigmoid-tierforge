from collections.abc import Callable
from math import ceil
from random import random

from config.settings import EnrichmentConfig

# Exponents above this would only be capped anyway; stops 2^n overflowing a float.
_MAX_EXPONENT = 32


class Backoff:
    """How long a task waits before its next attempt, in whole seconds: the
    `DelaySeconds` its retry event is sent with.

    After the n-th failed call the delay is `backoff_base_seconds × 2^(n − 1)`,
    capped at `backoff_max_seconds`; a 429 waits `rate_limited_delay_seconds`.
    Either is then scaled by a random 50-100% (jitter), so tasks that failed
    together don't all come back at the same moment, and rounded up, since SQS
    only takes whole seconds. The result is never below 1 s.
    """

    def __init__(
        self, config: EnrichmentConfig, random: Callable[[], float] = random
    ) -> None:
        """`random` returns a float in [0, 1); tests pass a fixed one."""
        self._base = config.backoff_base_seconds
        self._max = config.backoff_max_seconds
        self._rate_limited = config.rate_limited_delay_seconds
        self._random = random

    def retry_delay(self, failed_calls: int) -> int:
        """The delay after the task's `failed_calls`-th failed call (1 or more)."""
        if failed_calls < 1:
            raise ValueError("failed_calls must be at least 1")
        exponent = min(failed_calls - 1, _MAX_EXPONENT)
        return self._jittered(min(self._max, self._base * 2**exponent))

    def rate_limited_delay(self) -> int:
        """The delay after a 429."""
        return self._jittered(self._rate_limited)

    def _jittered(self, delay: float) -> int:
        """`delay` scaled by a random 50-100%, rounded up to whole seconds."""
        return max(1, ceil(delay * (0.5 + 0.5 * self._random())))
