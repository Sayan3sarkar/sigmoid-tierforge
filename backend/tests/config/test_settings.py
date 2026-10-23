from pydantic import ValidationError
from pytest import mark, raises

from config.settings import EnrichmentConfig


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
