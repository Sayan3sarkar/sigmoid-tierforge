# Limitations and trade-offs

The architectural limits of TierForge's design, the trade-offs behind it, and where the architecture could go next. The design itself is in [architecture.md](architecture.md).

## Known limitations

### Throughput is capped by the enrichment API, and scaling out doesn't help

- The API allows **5 calls/s across all callers** and has no batch endpoint, so 5,000 stores need at least ~17 min however the system is built. Measured: 18 min 35 s with one call per store (draft 1); 5,660 calls and ~21 min with draft 2's retries, every store enriched.
- **The rate limiter lives in the worker process.** Two workers would each send 4.5 calls/s, causing 429s, and since rejected calls still count against the API's window, possibly slower runs. So the system runs **one worker**, and adding workers is not a way to scale.
- **Jobs share one queue in arrival order,** with no fairness or priority: a second job's events wait behind the first job's thousands.

### Uploads: the API does everything in one request, and can leave a job stranded

- The whole file (up to 10 MB) is read into the API's memory, then validated, saved and queued within the request (~1.7 s for 5,000 stores). Much larger files would hold memory and the request open, and hit proxy and timeout limits.
- **Saving and queueing are two separate writes** (Postgres, then SQS) with no outbox between them. If sending fails, the job is marked `failed`; but if the API process dies between the commit and the last event, the job stays `pending` with some of its stores never queued, and nothing notices.
- **The source CSV isn't kept,** only its parsed rows, so a file can't be audited or re-processed later.

### Postgres and SQS can drift apart, and nothing reconciles them

Postgres holds every task's state, and SQS holds the work still to be done. The design relies on each unfinished task always having a message on the queue. When that breaks, the task is stuck, and its job never finishes:
- a message dead-lettered after 5 deliveries that each crashed the worker, or found the database unreachable, leaves its task `in_progress` and its job `running`. The dead-letter queue isn't monitored or redriven;
- the upload case above: a job whose events were never sent.

There's no sweeper that looks for unfinished tasks with no live lease and no message, so no way to detect or repair either case.

### Retries ride on the queue, so they're scheduled only roughly

- **A backoff is a minimum, not a schedule.** A retry is a new event that SQS releases after the delay, but it then queues behind everything else. On a big job, most retries run at the end: on 5,000 stores, in the last ~3 minutes.
- **A retry can come early.** Events don't carry the attempt number, so a duplicate or stale copy of an old event can claim a `retrying` task before its backoff is up. Nothing is corrupted or double-counted; one wait is skipped.
- **A worker crash doesn't use up an attempt,** since no outcome is recorded. A store that crashes the worker every time is only stopped by the dead-letter queue (see above).
- **The lease must stay below the queue's visibility timeout,** and the two are configured in different places (the app's env and the queue's settings). The worker checks this at startup, but the coupling remains.

### Failure handling is all or nothing at the job level

- **The circuit breaker is a kill switch.** It fails the job after 20 failed calls in a row (~5 s with the API down) and doesn't wait to see whether the API comes back, so a short outage ends a job that would have recovered.
- **A job can't be resumed or partly re-run.** There's no way to retry a finished job's failed stores, or to restart a `failed` job; the file has to be uploaded again, and every store is enriched again.

### Every upload re-enriches every store

Stores belong to an upload, and results belong to a job. Although the API is deterministic per `store_id`, uploading the same stores again calls the API for each one again, spending ~20 minutes of a shared, rate-limited budget on results the system already has.

### Scoring is synchronous and keeps only the latest run

- Scoring runs inside the request: one read, the computation in Python, one bulk write (~0.2 s for 5,000 stores). That cost grows with the job, so much larger jobs would need it moved out of the request, or into SQL.
- Re-scoring replaces the previous scores and settings, so runs can't be compared. Concurrent scorings of one job run one after the other, and the last silently wins.

### Progress is polled

Clients poll a running job (the frontend every 3 s); there's no push channel, such as server-sent events or websockets.

## Trade-offs considered

| Decision | Chosen | Alternative | Why |
| --- | --- | --- | --- |
| Unit of work on SQS | one event per store | one event per job, or chunks of N stores | Per-store events give per-store delivery, redelivery and dead-lettering from SQS, and let several workers share a job. A job event means fewer messages and a faster upload, but the worker must then schedule stores itself, and one worker owns a whole job. |
| Work queue | SQS, with state in Postgres | Postgres as the queue (`SELECT … FOR UPDATE SKIP LOCKED`) | SQS already delivers and redelivers work; using Postgres as well would give two sources of "what to run next". The price is the drift described above. |
| Upload path | multipart upload to the API, validated in the request | presigned S3 upload, validated by a worker on the S3 event | Errors come back in the same response, and no extra infrastructure is needed; enough for files up to 10 MB. |
| Sending events | in the upload request, after commit | a transactional outbox, sent in the background | Simple, and a 201 means every store is queued; the cost is the stranded-job case above, and ~1 s per 5,000 stores in the request. |
| Rate limit | in-process token bucket, 4.5 calls/s, capacity 1 | a shared limiter (e.g. Redis); 5/s or bursts | Evenly spaced calls with a margin avoid 429s against the API's fixed windows, with no extra infrastructure. Correct for one worker only. |
| Where a task waits for its retry | a new event on the same queue, held back by SQS (`DelaySeconds` = the backoff) | the same message with its visibility pushed out; Postgres plus a separate retry-scheduler process; sleeping in the handler | No new infrastructure, and SQS stays the only source of "what to run next". Pushing visibility out would tie retries to the dead-letter queue's receive count; a scheduler is a third process for the same result; sleeping ties up handlers and overruns the visibility timeout. |
| Attempts per store | 5 calls in total; a 429 doesn't count | more attempts, or counting 429s | With ~12% of calls failing independently, a store fails all 5 with probability ~2.5 × 10⁻⁵. A 429 means "too fast", not that the store's call failed. |
| Recovering a dead worker's tasks | a 25 s lease on each claim, taken over on redelivery; the lease is also the fencing token for the outcome | reset every `in_progress` task to `pending` when a worker starts | Works without a restart and with several workers; a reset on start would steal tasks other workers are still working on. |
| Circuit breaker | per job, 20 failed calls in a row, counted in Postgres; tripping fails the job straight away | pause, then fail (closed / open / half-open); a failure rate over a window; counting in the worker's memory | Simple, and what the brief asks for. Counting in Postgres survives restarts and works across workers. The price is that a short outage fails the job. |
| Results | columns on the task row | a separate results table | A task has at most one result. |
| Scores | own table, rewritten per run | columns on the task | Re-scoring can never touch enrichment results. |
| Scoring computation | Python, one read plus one bulk write, in the request | one SQL `INSERT … SELECT` with `CASE`; an asynchronous scoring job | The formula is one unit-tested function, and ~0.2 s for 5,000 stores. |
| Scoring concurrency | lock the job row; last writer wins | optimistic version check (409 on a stale version) | Prevents collisions and mixed results simply; a version check matters only with several concurrent users. |
| When scoring is allowed | finished jobs only | any time, scoring what has succeeded so far | Tier counts always describe the job's final set of stores. |
| Statuses | `TEXT`, with `StrEnum`s in code | Postgres enum types or check constraints | Adding a value (as draft 2 added `retrying`) needs no migration; the database doesn't reject unknown values. |

## Future scope

**Scaling out the worker:**
- a **shared rate limiter** (e.g. a Redis token bucket), so several workers can run within the API's limit;
- **per-job fairness:** interleave jobs' work (e.g. a queue per job, or a scheduler that hands out the rate limit across running jobs) instead of first in, first out.

**Reliable hand-off between Postgres and SQS:**
- a **transactional outbox:** the upload writes its events to a table in the same transaction as the job, and a relay sends them. No stranded jobs, and a faster upload response;
- a **reconciler (sweeper):** periodically finds unfinished tasks with no live lease and no recent activity, and re-queues them; together with **dead-letter queue alerts and redrive**, this closes the drift between the two stores.

**Resilience, beyond draft 2:**
- a **"pause, then fail" circuit breaker:** stop calling the API for a cool-down, let one test call through, and fail the job only if the API stays down;
- **re-driving jobs:** an endpoint to retry a finished job's failed stores, or to resume a `failed` job, by resetting those tasks and re-queueing them;
- the **attempt number in each event,** so a stale copy of an old event can't start a retry early.

**Reusing enrichment results:**
- cache results by `store_id`, with a freshness window, and skip the API for stores enriched recently. Re-uploading known stores would then take seconds, and the rate limit would only be spent on new ones.

**Uploads at scale: S3 with presigned URLs:**
1. `POST /api/uploads` returns an `upload_id` and a short-lived **presigned S3 URL**; the client uploads the CSV **straight to S3**.
2. An **S3 event notification** goes to an SQS queue, and a **validation worker** streams the file, validates it, then saves the stores, creates the job and queues its events (through the outbox), or records the problems.
3. The client follows the upload's state (`validating`, then `rejected` with every problem, or `accepted` with its `job_id`).

This removes the size limit and the in-memory file, keeps the source CSV (with a lifecycle rule), and makes validation retryable; the costs are asynchronous validation errors, and a bucket, an event notification, a second queue and worker, and an upload-state table.

**Scoring at scale:**
- compute scores in SQL, or as an asynchronous job for very large jobs;
- keep **every scoring run** (a runs table), so runs can be compared, with optimistic concurrency if several people score at once.

**Progress and observability:**
- **push progress** to clients (server-sent events) instead of polling;
- **metrics and alerts:** calls/s, error and 429 rates, retries, breaker trips, queue depth and age, dead-letter queue size.

## Intentionally left out

- **Authentication, authorisation and multi-tenancy:** anyone who can reach the API can see and score every job; there's no ownership, tenant isolation or data retention policy.
- **Deployment:** no container images or infrastructure as code for the app; locally, Docker runs only Postgres and LocalStack, and in AWS the queues and IAM would come from Terraform.
- **Changing the enrichment API:** it's treated as a third-party dependency (no batch endpoint, no higher limit).
- **The brief's bonus item of several jobs sharing one limit across several workers:** it needs the shared rate limiter above. The other bonus item, resuming after a restart without redoing finished work, comes with draft 2: finished stores stay finished, waiting events stay on the queue, and a stopped worker's claimed tasks are taken over once their lease expires.
