from pydantic import BaseModel, ConfigDict


class StoreRow(BaseModel):
    """One validated store from an uploaded CSV, before it is saved."""

    model_config = ConfigDict(frozen=True)

    store_id: str
    store_name: str
    address: str
    city: str
    state: str
    country: str
