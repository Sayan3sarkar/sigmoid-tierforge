from pytest import mark, raises

from config.settings import EnrichmentConfig
from worker.backoff import Backoff

# random() values giving the lowest (50%) and highest (100%) jitter.
LOWEST, HIGHEST = 0.0, 1.0


def make_backoff(jitter: float, **settings) -> Backoff:
    return Backoff(EnrichmentConfig(_env_file=None, **settings), random=lambda: jitter)


class TestBackoffRetryDelay:
    @mark.parametrize(
        "failed_calls, lowest, highest",
        [(1, 1, 2), (2, 2, 4), (3, 4, 8), (4, 8, 16)],
    )
    def test_doubles_with_each_failed_call(self, failed_calls, lowest, highest):
        assert make_backoff(LOWEST).retry_delay(failed_calls) == lowest
        assert make_backoff(HIGHEST).retry_delay(failed_calls) == highest

    def test_is_capped_at_the_max(self):
        # 2 × 2^5 = 64 s, above the 60 s cap.
        assert make_backoff(HIGHEST).retry_delay(6) == 60
        assert make_backoff(LOWEST).retry_delay(6) == 30

    def test_a_very_late_retry_stays_at_the_cap(self):
        assert make_backoff(HIGHEST).retry_delay(10_000) == 60

    def test_rounds_up_to_whole_seconds(self):
        # 2 s × 75% = 1.5 s, sent as 2 s.
        assert make_backoff(0.5).retry_delay(1) == 2

    def test_is_never_below_one_second(self):
        backoff = make_backoff(LOWEST, backoff_base_seconds=0.1)

        assert backoff.retry_delay(1) == 1

    def test_rejects_a_count_below_one(self):
        with raises(ValueError, match="at least 1"):
            make_backoff(LOWEST).retry_delay(0)


class TestBackoffRateLimitedDelay:
    def test_waits_about_a_second_by_default(self):
        assert make_backoff(LOWEST).rate_limited_delay() == 1
        assert make_backoff(HIGHEST).rate_limited_delay() == 1

    def test_is_jittered_like_a_retry(self):
        backoff = make_backoff(LOWEST, rate_limited_delay_seconds=4)

        assert backoff.rate_limited_delay() == 2
