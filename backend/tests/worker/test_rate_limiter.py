from asyncio import gather

from pytest import approx, fixture, raises

from worker.rate_limiter import TokenBucket


class FakeTime:
    """A clock that only moves when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


class TestTokenBucket:
    @fixture
    def time(self):
        return FakeTime()

    def bucket(self, time: FakeTime, rate: float, capacity: int = 1) -> TokenBucket:
        return TokenBucket(
            rate, capacity=capacity, clock=time.clock, sleeper=time.sleep
        )

    async def acquire_times(self, bucket: TokenBucket, time: FakeTime, count: int):
        """Acquire `count` tokens one after another; returns when each was granted."""
        granted = []
        for _ in range(count):
            await bucket.acquire()
            granted.append(time.now)
        return granted

    async def test_first_call_goes_out_immediately(self, time):
        await self.bucket(time, rate=4.5).acquire()

        assert time.now == 0

    async def test_calls_are_spaced_evenly_at_the_rate(self, time):
        granted = await self.acquire_times(self.bucket(time, rate=4.5), time, 10)

        gaps = [later - earlier for earlier, later in zip(granted, granted[1:])]
        assert gaps == approx([1 / 4.5] * 9)

    async def test_no_one_second_span_holds_more_than_five_calls_at_4_5_per_second(
        self, time
    ):
        # The enrichment API's limit: 5 calls in any of its 1-second windows.
        granted = await self.acquire_times(self.bucket(time, rate=4.5), time, 50)

        for start in granted:
            in_window = [t for t in granted if start <= t < start + 1]
            assert len(in_window) <= 5

    async def test_idle_time_does_not_build_up_a_burst(self, time):
        bucket = self.bucket(time, rate=4.5)
        await bucket.acquire()
        time.now += 60  # idle for a minute

        granted = await self.acquire_times(bucket, time, 3)

        assert granted == approx([60, 60 + 1 / 4.5, 60 + 2 / 4.5])

    async def test_a_larger_capacity_allows_that_burst_then_paces(self, time):
        granted = await self.acquire_times(
            self.bucket(time, rate=2, capacity=3), time, 5
        )

        assert granted == approx([0, 0, 0, 0.5, 1.0])

    async def test_concurrent_waiters_are_served_one_token_each(self, time):
        bucket = self.bucket(time, rate=4)
        granted = []

        async def call() -> None:
            await bucket.acquire()
            granted.append(time.now)

        await gather(*(call() for _ in range(5)))

        assert granted == approx([0, 0.25, 0.5, 0.75, 1.0])

    def test_rejects_a_rate_that_is_not_positive(self):
        with raises(ValueError, match="rate"):
            TokenBucket(0)

    def test_rejects_a_capacity_below_one(self):
        with raises(ValueError, match="capacity"):
            TokenBucket(4.5, capacity=0)
