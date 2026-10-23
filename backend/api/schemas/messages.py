"""SQS event format: one envelope for every event, with a typed payload.

Example body of an enrichment event on the queue:

    {"version": 1,
     "timestamp": "2026-10-23T10:15:30.123456Z",
     "payload": {"job_id": 7, "task_id": 1234}}
"""

from datetime import UTC, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

# Version of the event format (envelope + payload). Bump it when a payload changes
# in a way older consumers can't read; consumers drop events with other versions.
EVENT_VERSION = 1


class EnrichStorePayload(BaseModel):
    """Enrich one store: the task row holds everything else (store, job, status)."""

    model_config = ConfigDict(frozen=True)

    job_id: int
    task_id: int


PayloadT = TypeVar("PayloadT", bound=BaseModel)


class SQSEvent(BaseModel, Generic[PayloadT]):
    """Envelope for every SQS event: version, creation time and a typed payload.

    Always use a parameterised type (e.g. `SQSEvent[EnrichStorePayload]`), so the
    payload is validated and serialised as that model.
    """

    model_config = ConfigDict(frozen=True)

    version: int = EVENT_VERSION
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: PayloadT


EnrichmentEvent = SQSEvent[EnrichStorePayload]
