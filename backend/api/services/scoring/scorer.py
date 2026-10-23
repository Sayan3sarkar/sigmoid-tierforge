from decimal import Decimal

from api.models import Tier
from api.schemas.scoring import ScoringConfig, TierThresholds


class StoreScorer:
    """The scoring formula: static methods, no database or I/O.

    score = w_footfall * [footfall >= bar_footfall]
          + w_revenue  * [revenue  >= bar_revenue]
          + w_size     * [size     >= bar_size]

    tier  = Large if score >= large_min, else Medium if score >= medium_min,
            else Small
    """

    @staticmethod
    def score_store(
        footfall: int, revenue: Decimal, size_sqft: int, config: ScoringConfig
    ) -> int:
        """The sum of the weights of every bar the store meets. A value exactly
        equal to its bar meets it."""
        bars, weights = config.bars, config.weights
        return (
            (weights.footfall if footfall >= bars.footfall else 0)
            + (weights.revenue if revenue >= bars.revenue else 0)
            + (weights.size_sqft if size_sqft >= bars.size_sqft else 0)
        )

    @staticmethod
    def tier_for(score: int, tiers: TierThresholds) -> Tier:
        """The tier for a score. A score exactly at a threshold is in that
        tier."""
        if score >= tiers.large_min:
            return Tier.LARGE
        if score >= tiers.medium_min:
            return Tier.MEDIUM
        return Tier.SMALL
