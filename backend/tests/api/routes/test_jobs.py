from json import loads

from pytest import fixture, mark

HEADER = "store_id,store_name,address,city,state,country"
# The brief's worked example (A, B, C), plus D, whose enrichment failed.
STORES = {
    "ST000001": (40_000, 400_000, 18_000),  # A: all three bars -> 100, Large
    "ST000002": (20_000, 100_000, 5_000),  # B: footfall -> 50, Medium
    "ST000003": (2_000, 20_000, 9_000),  # C: size -> 20, Small
    "ST000004": None,  # D: failed, so never scored
}
CONFIG = {
    "bars": {"footfall": 15000, "revenue": 150000, "size_sqft": 8000},
    "weights": {"footfall": 50, "revenue": 30, "size_sqft": 20},
    "tiers": {"large_min": 70, "medium_min": 40},
}


@fixture
def finished_job(client, test_database) -> int:
    """Upload the four stores, then finish enrichment as the worker would:
    A, B and C succeed with their metrics, D fails, and the job completes."""
    rows = "\n".join(
        f"{store_id},Store {store_id},1 Main Street,New Delhi,Delhi,India"
        for store_id in STORES
    )
    job_id = client.post(
        "/api/uploads",
        files={"file": ("stores.csv", f"{HEADER}\n{rows}\n", "text/csv")},
    ).json()["job_id"]

    for store_id, metrics in STORES.items():
        if metrics is None:
            update = "status = 'failed', last_error = 'upstream error (500)'"
        else:
            footfall, revenue, size_sqft = metrics
            update = (
                "status = 'succeeded',"
                f" estimated_monthly_footfall = {footfall},"
                f" estimated_monthly_revenue = {revenue},"
                f" store_size_sqft = {size_sqft}"
            )
        test_database.fetch_value(
            f"UPDATE enrichment_tasks SET {update} FROM stores"
            " WHERE enrichment_tasks.store_id = stores.id"
            " AND enrichment_tasks.job_id = $1 AND stores.store_id = $2",
            job_id,
            store_id,
        )
    set_job_status(test_database, job_id, "completed_with_failures")
    return job_id


def set_job_status(test_database, job_id: int, status: str) -> None:
    test_database.fetch_value(
        "UPDATE jobs SET status = $2 WHERE id = $1", job_id, status
    )


def tiers_by_store(test_database, job_id: int) -> dict[str, tuple[int, str]]:
    rows = test_database.fetch_value(
        "SELECT json_object_agg(stores.store_id, json_build_array(score, tier))"
        " FROM store_scores"
        " JOIN enrichment_tasks ON enrichment_tasks.id = store_scores.task_id"
        " JOIN stores ON stores.id = enrichment_tasks.store_id"
        " WHERE store_scores.job_id = $1",
        job_id,
    )
    return {store_id: tuple(value) for store_id, value in loads(rows or "{}").items()}


class TestScoreJob:
    def test_scores_the_worked_example(self, client, test_database, finished_job):
        response = client.post(f"/api/jobs/{finished_job}/scoring", json=CONFIG)

        body = response.json()
        assert response.status_code == 200
        assert body["job_id"] == finished_job
        assert body["scored_count"] == 3
        assert body["tiers"] == {"large": 1, "medium": 1, "small": 1}
        assert body["config"] == CONFIG
        assert tiers_by_store(test_database, finished_job) == {
            "ST000001": (100, "large"),
            "ST000002": (50, "medium"),
            "ST000003": (20, "small"),
        }

    def test_saves_the_config_on_the_job(self, client, test_database, finished_job):
        client.post(f"/api/jobs/{finished_job}/scoring", json=CONFIG)

        saved = test_database.fetch_value(
            "SELECT scoring_config::text FROM jobs WHERE id = $1", finished_job
        )
        assert loads(saved) == CONFIG

    def test_rescoring_with_new_settings_changes_the_tiers(
        self, client, test_database, finished_job
    ):
        client.post(f"/api/jobs/{finished_job}/scoring", json=CONFIG)
        # Only size matters now: A (18,000) and C (9,000) meet the 8,000 bar.
        size_only = {
            **CONFIG,
            "weights": {"footfall": 0, "revenue": 0, "size_sqft": 100},
        }

        body = client.post(f"/api/jobs/{finished_job}/scoring", json=size_only).json()

        assert body["tiers"] == {"large": 2, "medium": 0, "small": 1}
        assert tiers_by_store(test_database, finished_job) == {
            "ST000001": (100, "large"),
            "ST000002": (0, "small"),
            "ST000003": (100, "large"),
        }

    def test_scoring_twice_with_the_same_settings_gives_the_same_result(
        self, client, test_database, finished_job
    ):
        first = client.post(f"/api/jobs/{finished_job}/scoring", json=CONFIG).json()
        scores = tiers_by_store(test_database, finished_job)

        second = client.post(f"/api/jobs/{finished_job}/scoring", json=CONFIG).json()

        assert second["tiers"] == first["tiers"]
        assert tiers_by_store(test_database, finished_job) == scores

    def test_failed_stores_get_no_score(self, client, test_database, finished_job):
        client.post(f"/api/jobs/{finished_job}/scoring", json=CONFIG)

        assert "ST000004" not in tiers_by_store(test_database, finished_job)


class TestScoreJobRejections:
    def test_unknown_job_returns_404(self, client):
        response = client.post("/api/jobs/999999/scoring", json=CONFIG)

        assert response.status_code == 404
        assert response.json()["detail"] == "Job 999999 not found."

    @mark.parametrize("status", ["pending", "running", "failed"])
    def test_unfinished_or_failed_job_returns_409(
        self, client, test_database, finished_job, status
    ):
        set_job_status(test_database, finished_job, status)

        response = client.post(f"/api/jobs/{finished_job}/scoring", json=CONFIG)

        assert response.status_code == 409
        assert f"is {status}" in response.json()["detail"]
        assert tiers_by_store(test_database, finished_job) == {}

    def test_invalid_settings_return_422_and_change_nothing(
        self, client, test_database, finished_job
    ):
        client.post(f"/api/jobs/{finished_job}/scoring", json=CONFIG)
        bad = {**CONFIG, "weights": {"footfall": 50, "revenue": 30, "size_sqft": 30}}

        response = client.post(f"/api/jobs/{finished_job}/scoring", json=bad)

        assert response.status_code == 422
        assert "add up to 100, not 110" in response.text
        assert len(tiers_by_store(test_database, finished_job)) == 3
