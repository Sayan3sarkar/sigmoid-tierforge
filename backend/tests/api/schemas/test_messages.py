from datetime import UTC, datetime, timedelta
from json import loads

from pydantic import ValidationError
from pytest import raises

from api.schemas.messages import (
    EVENT_VERSION,
    EnrichmentEvent,
    EnrichStorePayload,
    SQSEvent,
)


class TestSQSEvent:
    def test_defaults_to_current_version_and_utc_timestamp(self):
        event = EnrichmentEvent(payload=EnrichStorePayload(job_id=7, task_id=42))

        assert event.version == EVENT_VERSION
        assert event.timestamp.tzinfo is not None
        assert datetime.now(UTC) - event.timestamp < timedelta(seconds=5)

    def test_serialises_to_the_documented_json_shape(self):
        event = EnrichmentEvent(payload=EnrichStorePayload(job_id=7, task_id=42))

        body = loads(event.model_dump_json())

        assert set(body) == {"version", "timestamp", "payload"}
        assert body["version"] == EVENT_VERSION
        assert body["payload"] == {"job_id": 7, "task_id": 42}

    def test_round_trips_through_json_with_a_typed_payload(self):
        event = EnrichmentEvent(payload=EnrichStorePayload(job_id=7, task_id=42))

        parsed = EnrichmentEvent.model_validate_json(event.model_dump_json())

        assert parsed == event
        assert isinstance(parsed.payload, EnrichStorePayload)

    def test_rejects_a_payload_that_does_not_match_its_type(self):
        with raises(ValidationError):
            EnrichmentEvent.model_validate_json(
                '{"version": 1, "timestamp": "2026-10-23T10:00:00Z",'
                ' "payload": {"job_id": 7}}'
            )

    def test_payload_type_is_a_parameter(self):
        class OtherPayload(EnrichStorePayload):
            note: str

        event = SQSEvent[OtherPayload](
            payload=OtherPayload(job_id=1, task_id=2, note="hi")
        )

        assert loads(event.model_dump_json())["payload"]["note"] == "hi"
