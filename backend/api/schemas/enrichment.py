from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class EnrichRequest(BaseModel):
    """Body of `POST /enrich`: the store as the enrichment API expects it."""

    model_config = ConfigDict(frozen=True)

    store_id: str
    store_name: str
    address: str
    city: str
    state: str


class EnrichResponse(BaseModel):
    """A successful `POST /enrich` response: the store's estimated metrics."""

    model_config = ConfigDict(frozen=True)

    store_id: str
    estimated_monthly_footfall: int
    # Parsed from the JSON text directly, so no float rounding on the way in.
    estimated_monthly_revenue: Decimal
    store_size_sqft: int
