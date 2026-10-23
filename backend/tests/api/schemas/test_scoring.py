from pydantic import ValidationError
from pytest import mark, raises

from api.schemas.scoring import ScoringConfig

VALID = {
    "bars": {"footfall": 15000, "revenue": 150000, "size_sqft": 8000},
    "weights": {"footfall": 50, "revenue": 30, "size_sqft": 20},
    "tiers": {"large_min": 70, "medium_min": 40},
}


def with_changes(section: str, **values) -> dict:
    """The valid config with some values of one section replaced."""
    return {**VALID, section: {**VALID[section], **values}}


class TestScoringConfigAccepts:
    def test_the_briefs_example(self):
        config = ScoringConfig.model_validate(VALID)

        assert config.bars.revenue == 150000
        assert config.weights.footfall == 50
        assert config.tiers.large_min == 70

    @mark.parametrize(
        "section, values",
        [
            ("weights", {"footfall": 100, "revenue": 0, "size_sqft": 0}),
            ("bars", {"footfall": 0, "revenue": 0, "size_sqft": 0}),
            ("bars", {"revenue": 149999.99}),
            ("tiers", {"large_min": 40, "medium_min": 40}),
            ("tiers", {"large_min": 0, "medium_min": 0}),
            ("tiers", {"large_min": 100, "medium_min": 100}),
        ],
    )
    def test_edge_values(self, section, values):
        ScoringConfig.model_validate(with_changes(section, **values))


class TestScoringConfigRejects:
    @mark.parametrize(
        "section, values, message",
        [
            ("weights", {"footfall": 49}, "add up to 100, not 99"),
            ("weights", {"footfall": 51}, "add up to 100, not 101"),
            ("weights", {"footfall": -10, "revenue": 90}, "greater than or equal"),
            ("weights", {"footfall": 101, "revenue": -1}, "less than or equal"),
            ("bars", {"footfall": -1}, "greater than or equal"),
            ("bars", {"revenue": -0.01}, "greater than or equal"),
            ("tiers", {"medium_min": 71}, "must not be above large_min"),
            ("tiers", {"large_min": 101}, "less than or equal"),
            ("tiers", {"medium_min": -1}, "greater than or equal"),
        ],
    )
    def test_invalid_values(self, section, values, message):
        with raises(ValidationError, match=message):
            ScoringConfig.model_validate(with_changes(section, **values))

    @mark.parametrize("section", ["bars", "weights", "tiers"])
    def test_a_missing_section(self, section):
        config = {key: value for key, value in VALID.items() if key != section}

        with raises(ValidationError, match="Field required"):
            ScoringConfig.model_validate(config)

    def test_a_missing_metric(self):
        bars = {"footfall": 15000, "revenue": 150000}

        with raises(ValidationError, match="size_sqft"):
            ScoringConfig.model_validate({**VALID, "bars": bars})

    def test_an_unknown_key(self):
        # Catches typos such as "revnue" instead of silently ignoring them.
        with raises(ValidationError, match="Extra inputs are not permitted"):
            ScoringConfig.model_validate(with_changes("bars", revnue=1))
