# Limitations and trade-offs

What TierForge doesn't do (yet), the trade-offs behind its design, and where it could go next. The design itself is in [architecture.md](architecture.md).

## Known limitations

### The enrichment API's rate limit sets the pace

- The API allows **5 calls/s across all callers**, and has no batch endpoint. So 5,000 stores need at least 1,000 s (~17 min) however the system is built. At our 4.5 calls/s it's ~18.5 min (measured: 18 min 35 s).
- **More workers don't make it faster.** Each worker process has its own in-memory rate limiter. Two workers would send ~9 calls/s together, causing 429s and, since rejected calls still count against the API's window, possibly slower runs. Today, **run one worker**.
- **Several jobs at once share that one worker's rate,** so each job takes longer; there's no per-job fairness or priority.

### Draft 1 has no recovery

- **One attempt per store.** About 12% of stores fail on every run (the API's ~10% 500s and ~2% hangs), although nearly all would succeed on a retry.
- **A 429 fails the store,** although it only means "try again later". With the limiter at 4.5/s none occurred in the live run.
- **A worker stopped mid-call** (Ctrl+C, deploy, crash) leaves its claimed tasks `in_progress` forever. SQS redelivers their events, but the claim then refuses them, so the job stays `running`. The same happens if recording an outcome fails, e.g. the database is briefly unreachable.
- **No circuit breaker.** If the API is down, every store fails once and the job ends `completed_with_failures`, rather than stopping early with a clear `failed` state.
- **No resuming of stuck jobs,** and no way to retry a finished job's failed stores, other than uploading the file again.

All of these are draft 2's job (retries with backoff, leases, a circuit breaker), see [architecture.md §2](architecture.md#2-draft-2-retry-with-backoff).

### Other limitations

- **The upload waits until every event is sent** (~1 s per 5,000 stores). Much larger files would slow the request down; see future scope.
- **Scoring needs a finished job.** The tiers can't be previewed while enrichment runs.
- **Scoring keeps only the latest run.** Re-scoring replaces the previous scores and settings, so runs can't be compared. Two people scoring the same job at once: the last to commit wins, silently.
- **Progress is polled.** There's no push (server-sent events or websockets) when a job advances.
- **Revenue is returned as a string** (e.g. `"400000.00"`), to keep it exact; clients must convert it.
- **No CORS configuration yet,** so a browser frontend on another origin can't call the API until it's added.
- **Validation errors are plain strings** (`"body.weights: …"`), not structured by field.
- **The store list's order is fixed by its filter** (score, recent failure, or `store_id`); there's no user-chosen sort, search, or city/state filter.
- **The SQS dead-letter queue isn't monitored.** A message that lands there leaves its task unfinished.

## Trade-offs considered

| Decision | Chosen | Alternative | Why |
| --- | --- | --- | --- |
| Unit of work on SQS | one event per store | one event per job (`{job_id}`), or chunks of N stores | Per-store events give per-store delivery, redelivery and dead-lettering from SQS, and let several workers share a job. A job event means fewer messages and a faster upload, but the worker must then schedule stores itself, and one worker owns a whole job. |
| Work queue | SQS, with state in Postgres | Postgres as the queue (`SELECT … FOR UPDATE SKIP LOCKED`) | SQS already delivers and redelivers work; using Postgres as well would give two sources of "what to run next". |
| Sending events | in the upload request, after commit | return first and send in the background (or a transactional outbox) | Simple, and a 201 guarantees every store is queued, at the cost of ~1 s per 5,000 stores in the request. |
| Rate | 4.5 calls/s, capacity 1 | 5/s, or bursts | Evenly spaced calls with a margin avoid 429s against the API's fixed windows; ~4.8/s is worth trying, since the live run had no 429s at 4.5. |
| Rate limiter | in-process | shared (e.g. Redis) | Correct for one worker and no extra infrastructure; several workers would need a shared one. |
| Results | columns on the task row | a separate results table | A task has at most one result. |
| Scores | own table, rewritten per run | columns on the task | Re-scoring can never touch enrichment results. |
| Scoring computation | Python, one read plus one bulk write | one SQL `INSERT … SELECT` with `CASE` | The formula is one unit-tested function; still ~0.2 s for 5,000 stores. |
| Scoring concurrency | lock the job row; last writer wins | optimistic version check (409 on a stale version) | Prevents collisions and mixed results simply; a version check matters only with several concurrent users. |
| Scoring history | latest only (on `jobs`) | a table of every run | Simpler; the brief only needs the current breakdown. |
| When scoring is allowed | finished jobs only | any time, scoring what has succeeded so far | Tier counts always describe the job's final set of stores. |
| Failures endpoint | the store list, filtered by `status=failed` | a separate `/failures` endpoint | One endpoint, one query, one row shape for every view of a job's stores. |
| Pagination | `page` / `page_size`, returning `total_count` | `offset` / `limit`, or cursors | Matches a numbered-page table; at most 5,000 rows per job. |
| Statuses | `TEXT` with `StrEnum`s in code | Postgres enum types or check constraints | Adding a value needs no migration; the database doesn't reject unknown values. |
| Read endpoints | in `EnrichmentJobService` | a separate read-only service | One service per resource; reads get an unused SQS client injected. |

## Future scope

**Resilience (draft 2):**
- retries with exponential backoff and jitter, up to a cap;
- 429s retried without using up a store's attempts;
- leases, so stuck `in_progress` work is reclaimed and the job resumes after a restart;
- a fenced result write, so a late answer is ignored;
- a circuit breaker that stops a broken run with a `failed` job.

**Throughput and scale:**
- **Reuse results** for stores already enriched recently (the API is deterministic per `store_id`). Re-uploading a known file would then take seconds instead of minutes.
- A **shared rate limiter** (e.g. Redis), so several workers can run safely.
- Sending events **in the background or through an outbox** for much larger uploads.
- Tuning the rate towards ~4.8 calls/s.

**API and frontend:**
- the frontend itself;
- CORS, and field-level validation errors;
- push updates for progress;
- search, sorting, and city/state filters on the store list;
- progress on the job list, and an estimated time left;
- scoring history, to compare runs;
- restarting a failed job, or retrying only its failed stores.

**Operations:**
- metrics and alerts (calls/s, error rates, queue depth, dead-letter queue);
- structured logs;
- containerising the API and worker;
- Terraform for the queue and IAM roles.

## Intentionally left out

- **Authentication and user management.** There's no sign-up, login or roles, and no ownership of jobs: anyone who can reach the API can see, and score, every job.
- **Multi-tenancy and data retention:** no tenants, no deleting jobs or uploads, no cleanup of old data.
- **Deployment:** no Docker images or infrastructure for the app itself; Docker is used only for local Postgres and LocalStack.
- **Changing the enrichment API:** it's treated as a third-party dependency (no batch endpoint, no higher limit).
- **The brief's bonus items:**
  - several jobs sharing one limit across several workers;
  - full resume after a restart, which comes with draft 2's leases.
