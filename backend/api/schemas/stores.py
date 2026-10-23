from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoreRow:
    """One validated store from an uploaded CSV, before it is saved."""

    store_id: str
    store_name: str
    address: str
    city: str
    state: str
    country: str
