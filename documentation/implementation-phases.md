# Implementation phases

TierForge's backend is built in small phases. Each phase ends with something you can run and check on its own, and is committed separately. Requirements: [REQUIREMENTS.md](../REQUIREMENTS.md). Flow and SQS event format: [architecture.md](architecture.md). Tables: [datastores.md](datastores.md).

| # | Phase | Status | You can check it by |
| --- | --- | --- | --- |
| 0 | Scaffolding | Done (`6ba595d`) | `poe api`, `poe worker` and `poe test` run; `GET /api/health` returns 200 |
| 1 | Store CSV upload | Done (`b6f2fdb`, `f180f90`) | Uploading `stores_5000.csv` saves 5,000 rows; a bad file returns 422 with reasons |
| 2 | Upload starts an enrichment job | Done (`89a6459`) | Uploading 5,000 stores creates a running job, 5,000 tasks and 5,000 SQS events; the worker claims every task |
| 3 | Worker enrichment | Built (live run pending) | Progress climbs to ~88% succeeded / ~12% failed; the job finishes |
| 4 | Scoring and tiering | Planned | Re-scoring with new settings changes the tier counts |
| 5 | Dashboard reads | Planned | Failures, tier summary and a filterable store list |
| 6 | Resilience (draft 2) | Later | Retries, backoff, reclaiming hung work, circuit breaker |

Phases 2–5 make up draft 1: every store gets exactly one enrichment call, and a failed call marks the store failed with its reason. Phase 6 adds the recovery the brief requires.

## Phase 0: Scaffolding (done)

FastAPI app and worker in one Poetry project, with Postgres, Alembic, LocalStack SQS, Poe tasks, pytest, and a health check (server and Postgres).

## Phase 1: Store CSV upload (done)

- **Table:** `stores`.
- **Endpoint:** `POST /api/uploads`, a multipart CSV upload. It returns `201 {upload_id, row_count}`, or 422 or 413 with every problem listed.
- **Rules:** the six required columns in any order and nothing else, no blank values, no duplicate `store_id`, UTF-8. All or nothing: any bad row rejects the whole file.

## Phase 2: Upload starts an enrichment job (done)

**Goal:** a successful upload automatically starts enrichment. It creates a job with one unit of work per store and puts one SQS event per store on the queue; the worker picks them up one by one. The worker does **not** call the enrichment API yet. Details: [architecture.md](architecture.md).

**Tables:**
- `jobs`: one row per enrichment run.
- `enrichment_tasks`: one row per store in a job; it tracks that store's status.

**Upload (`POST /api/uploads`):** after validating the CSV, it:
1. Saves the stores, a `pending` job and one `pending` task per store, then commits.
2. Sends one `EnrichmentEvent` per task with `SendMessageBatch` (10 per call, several calls at once).
3. Marks the job `running`.
4. Returns `201 {upload_id, row_count, job_id, job_status}`.

If sending fails, the job is marked `failed` with the reason and the upload returns 503. The stores stay saved.

**Event:** `SQSEvent[EnrichStorePayload]` = `{version, timestamp, payload: {job_id, task_id}}`.

**Worker:** for each event, it checks the version, claims the task (`pending` → `in_progress`, only if its job hasn't failed), logs it, and deletes the event.

**Checked:**
- The real `stores_5000.csv` upload returned in 1.2 s: 5,000 stores, one `running` job, 5,000 tasks, and 5,000 events sent in about 1 s.
- The worker claimed all 5,000 tasks in about 24 s, with none skipped and no errors, and the queue ended empty.
- 59 tests pass.

**Not in this phase:** `GET /api/jobs/{job_id}` (progress) moves to phase 5. Until then, progress can be read from `enrichment_tasks` grouped by status. Running several jobs at once is allowed: one worker serves them all, so they share its rate limit.

## Phase 3: Worker enrichment

**Goal:** the worker enriches each store with one call to the simulator.

- **Per message:**
    1. Take a rate-limiter slot (in-process, about 4.5 calls/s).
    2. Call `POST /enrich` with a 10 s timeout.
    3. On 200: save footfall, revenue and size on the task and mark it `SUCCEEDED`.
    4. On 429, 500, timeout or connection error: mark the task `FAILED` with the reason.
    5. Delete the message either way.
- **Guarded update:** a task that's already `SUCCEEDED` or `FAILED` is never overwritten, so a duplicate SQS delivery is harmless.
- **Job completion:** when the last task finishes, the job becomes `COMPLETED` or `COMPLETED_WITH_FAILURES`.
- **Done when:** a 5,000-store job finishes in about 18–19 minutes with about 88% of tasks succeeded, and every failed task shows a reason.

**Built:** details in [architecture.md](architecture.md#worker-enrichment).

| Piece | Where |
| --- | --- |
| Result columns on `enrichment_tasks` (footfall, revenue, size, `finished_at`) | migration `b7783ebb251d` |
| Settings: `ENRICHMENT_TIMEOUT_SECONDS` (10), `ENRICHMENT_RATE_PER_SECOND` (4.5), `ENRICHMENT_CONCURRENCY` (8) | `config/settings.py` |
| Token-bucket rate limiter, capacity 1 (evenly spaced calls) | `worker/rate_limiter.py` |
| Enrichment client: one `POST /enrich` per call; typed errors whose message is the saved reason | `api/dependencies/enrichment.py` |
| Claim with store, record success / failure, finish the job once | `EnrichmentTaskService`, `EnrichmentJobService.finish_if_complete` |
| One receiver plus 8 handler tasks sharing the limiter | `worker/worker.py` |

The client uses `aiohttp`, already installed with `aiobotocore` and now declared as a runtime dependency. Its tests run against a local aiohttp test server.

**Checked so far:** 127 tests pass. Three real calls to the simulator through the client returned parsed metrics. The live 5,000-store run is still to do.

## Phase 4: Scoring and tiering

- **Table:** `store_scores`. The job row also keeps the latest scoring settings.
- **Endpoint:** `POST /api/jobs/{job_id}/scoring` with bars, weights and tier thresholds. It validates them (weights add up to 100; Medium ≤ Large threshold), computes a score and tier for every succeeded store from the saved metrics, and replaces the job's previous scores in one transaction. It never calls the simulator.
- **Done when:** the brief's worked example produces the expected tiers in tests, and re-scoring with different settings changes the tier counts.

## Phase 5: Dashboard reads

- `GET /api/jobs/{job_id}`: job status plus task counts by status (progress).
- `GET /api/jobs/{job_id}/failures`: each failed store with its reason.
- `GET /api/jobs/{job_id}/summary`: job counts plus Large / Medium / Small counts.
- `GET /api/jobs/{job_id}/stores?tier=&page=&page_size=`: stores with metrics, score and tier, filterable by tier and paginated.

## Phase 6: Resilience (draft 2, later)

- Retries with backoff, up to an attempt limit.
- A 429 is retried without using up the store's attempts.
- Hung or abandoned work is taken back.
- A circuit breaker stops a broken run with a terminal `FAILED` job state.
- Optional: a shared Redis rate limiter, and resuming after a restart.

These build on the phase 2–3 tables with added columns rather than new tables. Covered in detail when we get there.
