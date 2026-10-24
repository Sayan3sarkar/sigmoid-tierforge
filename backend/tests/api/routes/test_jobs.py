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


class TestListJobs:
    def test_lists_the_newest_job_first(self, client, finished_job):
        response = client.get("/api/jobs", params={"page_size": 1})

        body = response.json()
        assert response.status_code == 200
        assert [item["job_id"] for item in body["items"]] == [finished_job]
        assert body["items"][0]["status"] == "completed_with_failures"
        assert body["items"][0]["total_tasks"] == 4
        assert set(body) == {"items", "total_count"}
        assert body["total_count"] >= 1

    def test_rejects_a_page_size_above_the_limit(self, client):
        response = client.get("/api/jobs", params={"page_size": 201})

        assert response.status_code == 422
        assert response.json() == {
            "detail": "Invalid request.",
            "errors": [
                {
                    "field": "page_size",
                    "message": "Input should be less than or equal to 200",
                }
            ],
        }


class TestGetJob:
    def test_returns_the_job_with_its_task_counts(self, client, finished_job):
        response = client.get(f"/api/jobs/{finished_job}")

        body = response.json()
        assert response.status_code == 200
        assert body["job_id"] == finished_job
        assert body["status"] == "completed_with_failures"
        assert body["total_tasks"] == 4
        assert body["tasks"] == {
            "pending": 0,
            "in_progress": 0,
            "retrying": 0,
            "succeeded": 3,
            "failed": 1,
        }
        assert body["error"] is None

    def test_counts_and_filters_tasks_waiting_for_a_retry(
        self, client, finished_job, test_database
    ):
        test_database.fetch_value(
            "UPDATE enrichment_tasks SET status = 'retrying'"
            " WHERE job_id = $1 AND status = 'failed'",
            finished_job,
        )

        tasks = client.get(f"/api/jobs/{finished_job}").json()["tasks"]
        stores = client.get(
            f"/api/jobs/{finished_job}/stores", params={"status": "retrying"}
        ).json()

        assert (tasks["retrying"], tasks["failed"]) == (1, 0)
        assert [store["store_id"] for store in stores["items"]] == ["ST000004"]

    def test_unknown_job_returns_404(self, client):
        response = client.get("/api/jobs/999999")

        assert response.status_code == 404
        assert response.json() == {"detail": "Job 999999 not found.", "errors": []}


class TestGetJobSummary:
    def test_an_unscored_job_has_no_scoring(self, client, finished_job):
        body = client.get(f"/api/jobs/{finished_job}/summary").json()

        assert body["tasks"]["succeeded"] == 3
        assert body["scoring"] is None

    def test_a_scored_job_has_its_latest_scoring(self, client, finished_job):
        scored = client.post(f"/api/jobs/{finished_job}/scoring", json=CONFIG).json()

        body = client.get(f"/api/jobs/{finished_job}/summary").json()

        assert body["scoring"] == {
            "scored_at": scored["scored_at"],
            "config": CONFIG,
            "tiers": {"large": 1, "medium": 1, "small": 1},
        }

    def test_unknown_job_returns_404(self, client):
        assert client.get("/api/jobs/999999/summary").status_code == 404


class TestListJobStores:
    @fixture
    def scored_job(self, client, finished_job) -> int:
        client.post(f"/api/jobs/{finished_job}/scoring", json=CONFIG)
        return finished_job

    @staticmethod
    def store_ids(response) -> list[str]:
        return [item["store_id"] for item in response.json()["items"]]

    def test_lists_every_store_by_store_id(self, client, scored_job):
        response = client.get(f"/api/jobs/{scored_job}/stores")

        assert response.status_code == 200
        assert self.store_ids(response) == list(STORES)
        assert response.json()["total_count"] == 4

    def test_a_store_carries_its_metrics_score_and_tier(self, client, scored_job):
        response = client.get(
            f"/api/jobs/{scored_job}/stores", params={"tier": "large"}
        )

        [store] = response.json()["items"]
        assert store["store_id"] == "ST000001"
        assert store["status"] == "succeeded"
        assert store["estimated_monthly_footfall"] == 40000
        assert store["estimated_monthly_revenue"] == "400000.00"
        assert store["store_size_sqft"] == 18000
        assert (store["score"], store["tier"]) == (100, "large")
        assert store["last_error"] is None

    def test_failed_stores_carry_their_reason(self, client, scored_job):
        response = client.get(
            f"/api/jobs/{scored_job}/stores", params={"status": "failed"}
        )

        [store] = response.json()["items"]
        assert store["store_id"] == "ST000004"
        assert store["last_error"] == "upstream error (500)"
        assert (store["score"], store["tier"]) == (None, None)

    def test_succeeded_stores_come_highest_score_first(self, client, scored_job):
        response = client.get(
            f"/api/jobs/{scored_job}/stores", params={"status": "succeeded"}
        )

        assert self.store_ids(response) == ["ST000001", "ST000002", "ST000003"]

    def test_combines_filters_with_pagination(self, client, scored_job):
        # Filters and pagination are separate query models; neither may reject
        # the other's parameters.
        response = client.get(
            f"/api/jobs/{scored_job}/stores",
            params={"status": "succeeded", "page": 2, "page_size": 2},
        )

        body = response.json()
        assert response.status_code == 200
        assert self.store_ids(response) == ["ST000003"]
        assert body["total_count"] == 3

    def test_unscored_stores_have_no_score_or_tier(self, client, finished_job):
        response = client.get(f"/api/jobs/{finished_job}/stores")

        assert {(i["score"], i["tier"]) for i in response.json()["items"]} == {
            (None, None)
        }

    def test_rejects_an_unknown_tier(self, client, scored_job):
        response = client.get(f"/api/jobs/{scored_job}/stores", params={"tier": "huge"})

        assert response.status_code == 422
        assert response.json() == {
            "detail": "Invalid request.",
            "errors": [
                {
                    "field": "tier",
                    "message": "Input should be 'large', 'medium' or 'small'",
                }
            ],
        }

    def test_unknown_job_returns_404(self, client):
        assert client.get("/api/jobs/999999/stores").status_code == 404


class TestValidationErrorFormat:
    def test_body_errors_use_the_common_error_shape(self, client, finished_job):
        bad = {
            **CONFIG,
            "weights": {"footfall": 50, "revenue": 30, "size_sqft": 30},
            "tiers": {"large_min": 40, "medium_min": 70},
        }

        response = client.post(f"/api/jobs/{finished_job}/scoring", json=bad)

        assert response.status_code == 422
        assert response.json() == {
            "detail": "Invalid request.",
            "errors": [
                {
                    "field": "weights",
                    "message": "weights must add up to 100, not 110",
                },
                {
                    "field": "tiers",
                    "message": "medium_min (70) must not be above large_min (40)",
                },
            ],
        }

    def test_a_nested_field_is_named_by_its_dotted_path(self, client, finished_job):
        bad = {**CONFIG, "bars": {**CONFIG["bars"], "revenue": -1}}

        response = client.post(f"/api/jobs/{finished_job}/scoring", json=bad)

        [error] = response.json()["errors"]
        assert error["field"] == "bars.revenue"
        assert "greater than or equal to 0" in error["message"]

    def test_path_errors_use_the_common_error_shape(self, client):
        response = client.get("/api/jobs/abc")

        assert response.status_code == 422
        assert response.json()["detail"] == "Invalid request."
        [error] = response.json()["errors"]
        assert error["field"] == "job_id"
        assert error["message"].startswith("Input should be a valid integer")
