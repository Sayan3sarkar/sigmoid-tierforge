from pathlib import Path
from uuid import UUID

from pytest import fixture, mark

from config import get_config
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
        assert count_stores(first["upload_id"]) == 1
        assert count_stores(second["upload_id"]) == 1

    @mark.skipif(not SAMPLE_CSV.exists(), reason="stores_5000.csv not in repo root")
    def test_accepts_the_provided_5000_row_sample(self, client, count_stores):
        response = client.post(
            "/api/uploads", files=csv_file(SAMPLE_CSV.read_bytes(), SAMPLE_CSV.name)
        )

        body = response.json()
        assert response.status_code == 201
        assert body["row_count"] == 5000
        assert count_stores(body["upload_id"]) == 5000


class TestUploadEndpointRejections:
    def test_rejects_invalid_header_with_422_and_saves_nothing(
        self, client, test_database
    ):
        before = test_database.fetch_value("SELECT count(*) FROM stores")

        response = client.post(
            "/api/uploads", files=csv_file(f"store_id,name\n{ROW_1}\n")
        )

        body = response.json()
        assert response.status_code == 422
        assert body["detail"].startswith("Invalid header")
        assert "Unexpected columns: name" in body["errors"]
        assert test_database.fetch_value("SELECT count(*) FROM stores") == before

    def test_rejects_whole_file_when_one_row_is_invalid(self, client, test_database):
        before = test_database.fetch_value("SELECT count(*) FROM stores")

        response = client.post(
            "/api/uploads", files=csv_file(f"{HEADER}\n{ROW_1}\n{ROW_2}\n{ROW_1}\n")
        )

        assert response.status_code == 422
        assert response.json()["errors"] == [
            "Row 4: duplicate store_id ST000001 (first seen in row 2)"
        ]
        assert test_database.fetch_value("SELECT count(*) FROM stores") == before

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
