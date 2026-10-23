from decimal import Decimal

from pytest import mark

from api.models import Tier
from api.schemas.scoring import ScoringConfig, TierThresholds
from api.services.scoring.scorer import StoreScorer

# The brief's worked example settings.
CONFIG = ScoringConfig.model_validate(
    {
        "bars": {"footfall": 15000, "revenue": 150000, "size_sqft": 8000},
        "weights": {"footfall": 50, "revenue": 30, "size_sqft": 20},
        "tiers": {"large_min": 70, "medium_min": 40},
    }
)


class TestStoreScorerWorkedExample:
    @mark.parametrize(
        "store, footfall, revenue, size_sqft, score, tier",
        [
            ("A", 40_000, Decimal("400000"), 18_000, 100, Tier.LARGE),
            ("B", 20_000, Decimal("100000"), 5_000, 50, Tier.MEDIUM),
            ("C", 2_000, Decimal("20000"), 9_000, 20, Tier.SMALL),
        ],
    )
    def test_store(self, store, footfall, revenue, size_sqft, score, tier):
        actual = StoreScorer.score_store(footfall, revenue, size_sqft, CONFIG)

        assert actual == score
        assert StoreScorer.tier_for(actual, CONFIG.tiers) == tier


class TestStoreScorerScoreStore:
    def test_a_value_exactly_at_its_bar_meets_it(self):
        assert (
            StoreScorer.score_store(15_000, Decimal("150000.00"), 8_000, CONFIG) == 100
        )

    def test_a_value_just_below_its_bar_does_not(self):
        assert StoreScorer.score_store(14_999, Decimal("149999.99"), 7_999, CONFIG) == 0

    def test_a_zero_weight_adds_nothing_even_when_its_bar_is_met(self):
        config = CONFIG.model_copy(
            update={
                "weights": CONFIG.weights.model_copy(
                    update={"footfall": 70, "revenue": 30, "size_sqft": 0}
                )
            }
        )

        assert StoreScorer.score_store(0, Decimal("0"), 50_000, config) == 0
        assert StoreScorer.score_store(20_000, Decimal("0"), 50_000, config) == 70

    def test_bars_of_zero_are_met_by_every_store(self):
        config = CONFIG.model_copy(
            update={
                "bars": CONFIG.bars.model_copy(
                    update={"footfall": 0, "revenue": 0, "size_sqft": 0}
                )
            }
        )

        assert StoreScorer.score_store(0, Decimal("0"), 0, config) == 100


class TestStoreScorerTierFor:
    TIERS = TierThresholds(large_min=70, medium_min=40)

    @mark.parametrize(
        "score, tier",
        [
            (100, Tier.LARGE),
            (70, Tier.LARGE),
            (69, Tier.MEDIUM),
            (40, Tier.MEDIUM),
            (39, Tier.SMALL),
            (0, Tier.SMALL),
        ],
    )
    def test_boundaries(self, score, tier):
        assert StoreScorer.tier_for(score, self.TIERS) == tier

    def test_equal_thresholds_leave_no_medium_tier(self):
        tiers = TierThresholds(large_min=50, medium_min=50)

        assert StoreScorer.tier_for(50, tiers) == Tier.LARGE
        assert StoreScorer.tier_for(49, tiers) == Tier.SMALL

    def test_thresholds_of_zero_make_every_store_large(self):
        assert (
            StoreScorer.tier_for(0, TierThresholds(large_min=0, medium_min=0))
            == Tier.LARGE
        )
