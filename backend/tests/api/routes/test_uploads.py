from pathlib import Path
from uuid import UUID

from pytest import fixture, mark

from api.exceptions import SQSSendError
from api.schemas.messages import EVENT_VERSION
from config import cfg, get_config
from config.settings import UploadConfig

SAMPLE_CSV = Path(__file__).resolve().parents[4] / "stores_5000.csv"  # repo root
HEADER = "store_id,store_name,address,city,state,country"
ROW_1 = "ST000001,Fresh Supermarket #1,71 Church Street,New Delhi,Delhi,India"
ROW_2 = "ST000002,City Pharmacy #2,27 Hill Street,New Delhi,Delhi,India"


def csv_file(content: bytes | str, name: str = "stores.csv") -> dict:
    if isinstance(content, str):
        content = content.encode()
    return {"file": (name, content, "text/csv")}


class TestUploadEndpointSuccess:
    @fixture
    def count_stores(self, test_database):
        def count(upload_id: str) -> int:
            return test_database.fetch_value(
                "SELECT count(*) FROM stores WHERE upload_id = $1", UUID(upload_id)
            )

        return count

    def test_saves_every_row_and_returns_upload_id(self, client, count_stores):
        response = client.post(
            "/api/uploads", files=csv_file(f"{HEADER}\n{ROW_1}\n{ROW_2}\n")
        )

        body = response.json()
        assert response.status_code == 201
        assert body["row_count"] == 2
        assert count_stores(body["upload_id"]) == 2

    def test_each_upload_gets_its_own_upload_id(self, client, count_stores):
        content = f"{HEADER}\n{ROW_1}\n"

        first = client.post("/api/uploads", files=csv_file(content)).json()
        second = client.post("/api/uploads", files=csv_file(content)).json()

        assert first["upload_id"] != second["upload_id"]
        assert first["job_id"] != second["job_id"]
        assert count_stores(first["upload_id"]) == 1
        assert count_stores(second["upload_id"]) == 1

    @mark.skipif(not SAMPLE_CSV.exists(), reason="stores_5000.csv not in repo root")
    def test_accepts_the_provided_5000_row_sample(
        self, client, count_stores, test_database, sqs_client
    ):
        response = client.post(
            "/api/uploads", files=csv_file(SAMPLE_CSV.read_bytes(), SAMPLE_CSV.name)
        )

        body = response.json()
        assert response.status_code == 201
        assert body["row_count"] == 5000
        assert count_stores(body["upload_id"]) == 5000
        assert (
            test_database.fetch_value(
                "SELECT count(*) FROM enrichment_tasks WHERE job_id = $1",
                body["job_id"],
            )
            == 5000
        )
        _, events = sqs_client.send_messages.await_args.args
        assert len(events) == 5000


class TestUploadStartsEnrichmentJob:
    def test_creates_a_running_job_with_one_pending_task_per_store(
        self, client, test_database
    ):
        response = client.post(
            "/api/uploads", files=csv_file(f"{HEADER}\n{ROW_1}\n{ROW_2}\n")
        )

        body = response.json()
        assert response.status_code == 201
        assert body["job_status"] == "running"
        job_id = body["job_id"]
        assert test_database.fetch_value(
            "SELECT status FROM jobs WHERE id = $1", job_id
        ) == ("running")
        assert (
            test_database.fetch_value(
                "SELECT total_tasks FROM jobs WHERE id = $1", job_id
            )
            == 2
        )
        assert (
            test_database.fetch_value(
                "SELECT count(*) FROM enrichment_tasks"
                " WHERE job_id = $1 AND status = 'pending'",
                job_id,
            )
            == 2
        )

    def test_sends_one_event_per_task_to_the_enrichment_queue(
        self, client, test_database, sqs_client
    ):
        body = client.post(
            "/api/uploads", files=csv_file(f"{HEADER}\n{ROW_1}\n{ROW_2}\n")
        ).json()

        sqs_client.send_messages.assert_awaited_once()
        queue_url, events = sqs_client.send_messages.await_args.args
        task_ids = test_database.fetch_value(
            "SELECT array_agg(id ORDER BY id) FROM enrichment_tasks WHERE job_id = $1",
            body["job_id"],
        )
        assert queue_url == cfg.sqs.enrichment_queue_url
        assert sorted(event.payload.task_id for event in events) == task_ids
        assert all(event.payload.job_id == body["job_id"] for event in events)
        assert all(event.version == EVENT_VERSION for event in events)

    def test_returns_503_and_fails_the_job_when_events_cannot_be_sent(
        self, client, test_database, sqs_client
    ):
        sqs_client.send_messages.side_effect = SQSSendError("SQS is down")

        response = client.post(
            "/api/uploads", files=csv_file(f"{HEADER}\n{ROW_1}\n{ROW_2}\n")
        )

        assert response.status_code == 503
        assert "could not be started" in response.json()["detail"]
        job = test_database.fetch_value(
            "SELECT row(id, upload_id, status, error) FROM jobs"
            " ORDER BY id DESC LIMIT 1"
        )
        job_id, upload_id, status, error = job
        assert status == "failed"
        assert "SQS is down" in error
        # The stores stay saved; only the job failed.
        assert (
            test_database.fetch_value(
                "SELECT count(*) FROM stores WHERE upload_id = $1", upload_id
            )
            == 2
        )


class TestUploadEndpointRejections:
    @fixture
    def counts(self, test_database):
        def count() -> tuple[int, int]:
            return (
                test_database.fetch_value("SELECT count(*) FROM stores"),
                test_database.fetch_value("SELECT count(*) FROM jobs"),
            )

        return count

    def test_rejects_invalid_header_with_422_and_saves_nothing(
        self, client, counts, sqs_client
    ):
        before = counts()

        response = client.post(
            "/api/uploads", files=csv_file(f"store_id,name\n{ROW_1}\n")
        )

        body = response.json()
        assert response.status_code == 422
        assert body["detail"].startswith("Invalid header")
        assert {"field": None, "message": "Unexpected columns: name"} in body["errors"]
        assert counts() == before
        sqs_client.send_messages.assert_not_awaited()

    def test_rejects_whole_file_when_one_row_is_invalid(
        self, client, counts, sqs_client
    ):
        before = counts()

        response = client.post(
            "/api/uploads", files=csv_file(f"{HEADER}\n{ROW_1}\n{ROW_2}\n{ROW_1}\n")
        )

        assert response.status_code == 422
        assert response.json()["errors"] == [
            {
                "field": None,
                "message": "Row 4: duplicate store_id ST000001 (first seen in row 2)",
            }
        ]
        assert counts() == before
        sqs_client.send_messages.assert_not_awaited()

    def test_rejects_non_csv_file_name(self, client):
        response = client.post(
            "/api/uploads", files=csv_file(f"{HEADER}\n{ROW_1}\n", "stores.xlsx")
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "Upload a .csv file."

    def test_rejects_file_over_the_size_limit_with_413(self, app, client):
        small_limit = get_config().model_copy(
            update={"upload": UploadConfig(max_size_bytes=50)}
        )
        app.dependency_overrides[get_config] = lambda: small_limit

        response = client.post(
            "/api/uploads", files=csv_file(f"{HEADER}\n{ROW_1}\n{ROW_2}\n")
        )

        assert response.status_code == 413
        assert response.json()["detail"].startswith("The file is larger than")

    def test_requires_a_file_field(self, client):
        response = client.post("/api/uploads")

        assert response.status_code == 422
