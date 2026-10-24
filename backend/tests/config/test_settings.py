from pydantic import ValidationError
from pytest import mark, raises

from config.settings import Config, EnrichmentConfig


class TestEnrichmentConfig:
    def test_defaults_stay_below_the_apis_limit(self, monkeypatch):
        for name in (
            "ENRICHMENT_TIMEOUT_SECONDS",
            "ENRICHMENT_RATE_PER_SECOND",
            "ENRICHMENT_CONCURRENCY",
        ):
            monkeypatch.delenv(name, raising=False)

        config = EnrichmentConfig(_env_file=None)

        assert config.timeout_seconds == 10
        assert config.rate_per_second == 4.5  # the API allows 5 calls/s
        assert config.concurrency == 8

    def test_reads_the_environment(self, monkeypatch):
        monkeypatch.setenv("ENRICHMENT_TIMEOUT_SECONDS", "5")
        monkeypatch.setenv("ENRICHMENT_RATE_PER_SECOND", "2.5")
        monkeypatch.setenv("ENRICHMENT_CONCURRENCY", "4")

        config = EnrichmentConfig(_env_file=None)

        assert (config.timeout_seconds, config.rate_per_second, config.concurrency) == (
            5,
            2.5,
            4,
        )

    @mark.parametrize(
        "name, value",
        [
            ("ENRICHMENT_TIMEOUT_SECONDS", "0"),
            ("ENRICHMENT_RATE_PER_SECOND", "0"),
            ("ENRICHMENT_RATE_PER_SECOND", "-1"),
            ("ENRICHMENT_CONCURRENCY", "0"),
        ],
    )
    def test_rejects_values_that_would_stall_the_worker(self, monkeypatch, name, value):
        monkeypatch.setenv(name, value)

        with raises(ValidationError):
            EnrichmentConfig(_env_file=None)

    def test_retry_defaults(self, monkeypatch):
        for name in (
            "ENRICHMENT_MAX_ATTEMPTS",
            "ENRICHMENT_BACKOFF_BASE_SECONDS",
            "ENRICHMENT_BACKOFF_MAX_SECONDS",
            "ENRICHMENT_RATE_LIMITED_DELAY_SECONDS",
            "ENRICHMENT_LEASE_SECONDS",
            "ENRICHMENT_CIRCUIT_BREAKER_THRESHOLD",
        ):
            monkeypatch.delenv(name, raising=False)

        config = EnrichmentConfig(_env_file=None)

        assert config.max_attempts == 5
        assert (config.backoff_base_seconds, config.backoff_max_seconds) == (2, 60)
        assert config.rate_limited_delay_seconds == 1
        assert config.lease_seconds == 25
        assert config.circuit_breaker_threshold == 20

    @mark.parametrize(
        "name, value",
        [
            ("ENRICHMENT_MAX_ATTEMPTS", "0"),
            ("ENRICHMENT_BACKOFF_BASE_SECONDS", "0"),
            ("ENRICHMENT_BACKOFF_MAX_SECONDS", "901"),  # SQS delays up to 900 s
            ("ENRICHMENT_RATE_LIMITED_DELAY_SECONDS", "0"),
            ("ENRICHMENT_LEASE_SECONDS", "0"),
            ("ENRICHMENT_CIRCUIT_BREAKER_THRESHOLD", "0"),
        ],
    )
    def test_rejects_invalid_retry_settings(self, monkeypatch, name, value):
        monkeypatch.setenv(name, value)

        with raises(ValidationError):
            EnrichmentConfig(_env_file=None)

    def test_rejects_a_backoff_base_above_its_max(self):
        with raises(ValidationError, match="must not exceed backoff_max_seconds"):
            EnrichmentConfig(
                _env_file=None, backoff_base_seconds=90, backoff_max_seconds=60
            )

    def test_rejects_a_lease_no_longer_than_a_call(self):
        # A live call could then outlast its lease and lose its task.
        with raises(ValidationError, match="longer than timeout_seconds"):
            EnrichmentConfig(_env_file=None, timeout_seconds=10, lease_seconds=10)


class TestConfigAllowedOrigins:
    def test_defaults_to_any_origin(self, monkeypatch):
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)

        assert Config(_env_file=None).allowed_origins == ["*"]

    @mark.parametrize(
        "value, origins",
        [
            ("*", ["*"]),
            ("http://localhost:5173", ["http://localhost:5173"]),
            (
                "http://localhost:5173, https://app.example.com",
                ["http://localhost:5173", "https://app.example.com"],
            ),
            ("http://localhost:5173,,", ["http://localhost:5173"]),
        ],
    )
    def test_reads_a_comma_separated_list(self, monkeypatch, value, origins):
        monkeypatch.setenv("ALLOWED_ORIGINS", value)

        assert Config(_env_file=None).allowed_origins == origins
