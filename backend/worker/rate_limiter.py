from asyncio import Lock, sleep
from collections.abc import Awaitable, Callable
from time import monotonic

# Float slack: a sleep of exactly the missing time can refill to 0.9999...
# tokens, and the tiny remaining sleep may not move the clock at all.
_EPSILON = 1e-9


class TokenBucket:
    """In-process async rate limiter: at most `rate` acquisitions per second.

    The bucket holds up to `capacity` tokens and refills continuously at `rate`
    tokens per second; each `acquire()` takes one token, waiting if none is left.
    Waiters are served in arrival order.

    With the default capacity of 1 there are no bursts: calls are spaced evenly,
    1 / `rate` seconds apart. That matters for the enrichment API, which counts
    calls in fixed 1-second windows that don't line up with ours: a burst at the
    end of one of its windows plus calls at the start of the next could exceed
    its limit. Evenly spaced at 4.5/s, any 1-second span holds at most 5 calls.

    One bucket per worker process. It doesn't coordinate across processes; a
    shared limiter (e.g. Redis) is future scope.
    """

    def __init__(
        self,
        rate: float,
        capacity: int = 1,
        clock: Callable[[], float] = monotonic,
        sleeper: Callable[[float], Awaitable[None]] = sleep,
    ) -> None:
        """`clock` and `sleeper` let tests replace real time with a fake one."""
        if rate <= 0:
            raise ValueError("rate must be positive")
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.rate = rate
        self.capacity = capacity
        self._clock = clock
        self._sleep = sleeper
        # Starts full, so the first `capacity` calls go out immediately.
        self._tokens = float(capacity)
        self._updated_at = clock()
        # Held while waiting for a token, so waiters queue up in arrival order.
        self._lock = Lock()

    async def acquire(self) -> None:
        """Take one token, waiting until one is available."""
        async with self._lock:
            self._refill()
            while self._tokens < 1 - _EPSILON:
                # Sleep exactly until the missing part of a token has refilled.
                await self._sleep((1 - self._tokens) / self.rate)
                self._refill()
            self._tokens -= 1

    def _refill(self) -> None:
        """Add the tokens earned since the last refill, up to `capacity`."""
        now = self._clock()
        self._tokens = min(
            self.capacity, self._tokens + (now - self._updated_at) * self.rate
        )
        self._updated_at = now
