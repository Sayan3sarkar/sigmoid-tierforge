# Requirements

What TierForge must do, for both the backend and the frontend. How it's built is in [architecture.md](architecture.md); what's deliberately left out or limited is in [limitations-and-tradeoffs.md](limitations-and-tradeoffs.md).

## Summary

A user uploads a CSV of stores. TierForge enriches every store with three business metrics from a slow, rate-limited and unreliable third-party API. The user then sets scoring rules, and TierForge scores every enriched store and sorts it into **Large**, **Medium** or **Small**.

Enrichment (slow, unreliable) and scoring (fast, local) are separate: scoring only uses metrics already saved, never calls the API, and can be re-run as often as the user likes.

## What we're given

### The enrichment API (`enrichment_simulator/`)

A provided local service that behaves like a third-party dependency we don't control. It must not be modified.

- `POST /enrich` takes one store (`store_id`, `store_name`, `address`, `city`, `state`; no `country`) and returns `estimated_monthly_footfall`, `estimated_monthly_revenue` and `store_size_sqft`. There is no batch endpoint: one call per store.
- `GET /health` returns `{"status": "ok"}`.
- Results are deterministic: the same `store_id` always gets the same metrics.

| Behaviour | How often |
| --- | --- |
| Success (200) in 0.2–0.5 s | ~88% of calls |
| 429 rate limited | whenever more than **5 calls/s arrive across all callers**; rejected calls still count toward the limit |
| 500 transient error (retryable) | ~10% of calls |
| Hangs 45–60 s, then succeeds | ~2% of calls |

Because of the global 5 calls/s limit, 5,000 stores take at least ~17 minutes to enrich, so enrichment must run in the background.

### Sample data

`stores_5000.csv`: 5,000 stores with columns `store_id, store_name, address, city, state, country`.

## User flow

1. **Upload** a CSV of stores. Enrichment starts automatically.
2. **Watch progress** while stores are enriched, and see why any store failed.
3. **Score**: set the scoring rules and see the tier breakdown. Repeat with different rules as often as needed.
4. **Browse** the scored stores, filtered by tier.

## Backend requirements

### 1. Upload

- Accept a CSV upload (max 10 MB).
- **Validate before accepting:**
  - the header has exactly the columns `store_id, store_name, address, city, state, country`, in any order, with none missing and no extras;
  - no blank values, no duplicate `store_id`, valid UTF-8.
- **All or nothing:** any invalid row rejects the whole file. Every problem is listed in the error.
- Save each row as a store, and start an enrichment job for the upload automatically.
- Respond quickly with the upload's ID and the new job's ID and status; don't wait for enrichment.

### 2. Enrichment job

- Enrich every store of the upload in the background, one call per store attempt.
- Stay under the API's 5 calls/s global limit.
- Give up on a call after 10 s.
- Track every store's state (`pending`, `in_progress`, `succeeded`, `failed`), its metrics if it succeeded, and its reason if it failed.
- Never lose track of a store, and never count one twice, even if a message is delivered twice.
- When every store has finished, the job is finished: `completed` (all succeeded) or `completed_with_failures` (some failed). If the job can't be started, it's `failed` with the reason.

**Draft 1 (implemented):** one attempt per store. Any 429, 500, timeout or connection error fails that store with its reason.

**Draft 2 (to do):**
- **Retries:** retry transient failures (500s, timeouts, connection errors) with exponential backoff and jitter, up to a cap on attempts, then fail the store with the reason.
- **429s:** a 429 is retried after a short wait without using up the store's attempts.
- **Stuck work:** work that never comes back (a hung call, a dead worker) is reclaimed and retried. A late answer from the original attempt must not corrupt anything or be double-counted.
- **Broken runs:** a run that fails across the board (e.g. the API is down) stops after a bounded number of failures, with a clear terminal `failed` state, instead of looping forever.

### 3. Scoring and tiering

The user sends, in one request:
- a **bar** per metric (footfall, revenue, size): the minimum value that counts as strong;
- a **weight** per metric (0–100): the points for meeting that bar;
- the **tier thresholds**: the minimum score for Large and for Medium.

Rules:
- **Score** = the sum of the weights of every bar the store meets. A value equal to its bar meets it (≥).
- **Tier** = Large if score ≥ the Large threshold; else Medium if score ≥ the Medium threshold; else Small.
- **Validation** (reject with a clear error):
  - each weight is 0–100 and the three add up to exactly 100;
  - each bar is ≥ 0;
  - 0 ≤ Medium threshold ≤ Large threshold ≤ 100.
- **Which stores:** only stores that were enriched successfully are scored. Failed stores appear in the failure list, not in the tier counts.
- **When:** only once the job's enrichment has finished (`completed` or `completed_with_failures`).
- **Re-runnable:** each run replaces the job's previous scores completely, and the same rules always give the same result. Only the latest rules are kept.
- **Fast and local:** it uses saved metrics only and never calls the enrichment API.

**Worked example** (from the brief): bars 15,000 / 150,000 / 8,000; weights 50 / 30 / 20; Large ≥ 70, Medium ≥ 40.

| Store | Footfall | Revenue | Size (sqft) | Bars met | Score | Tier |
| --- | --- | --- | --- | --- | --- | --- |
| A | 40,000 | 400,000 | 18,000 | all three | 100 | Large |
| B | 20,000 | 100,000 | 5,000 | footfall | 50 | Medium |
| C | 2,000 | 20,000 | 9,000 | size | 20 | Small |

### 4. Reading jobs and results

| Need | Endpoint |
| --- | --- |
| List jobs, newest first | `GET /api/jobs` |
| A job's status and progress (pending / in progress / succeeded / failed counts) | `GET /api/jobs/{id}` |
| Progress plus the latest scoring: rules used, when, and Large / Medium / Small counts | `GET /api/jobs/{id}/summary` |
| A job's stores with status, metrics, failure reason, score and tier; filter by status and/or tier; paginated | `GET /api/jobs/{id}/stores?status=&tier=&page=&page_size=` |
| Why stores failed | `GET /api/jobs/{id}/stores?status=failed` |

All errors return the same shape, `{"detail": "...", "errors": [{"field": ..., "message": "..."}]}`, with every problem listed and, where it applies, the input it's about.

### Endpoint list

| Method + path | Does |
| --- | --- |
| `POST /api/uploads` | Upload a CSV and start its enrichment job |
| `GET /api/jobs` | List jobs |
| `GET /api/jobs/{id}` | Job status and progress |
| `GET /api/jobs/{id}/summary` | Progress and latest scoring |
| `GET /api/jobs/{id}/stores` | A job's stores, filterable and paginated |
| `POST /api/jobs/{id}/scoring` | Set the scoring rules and score the job |
| `GET /api/health` | Health of the API and its database |

## Frontend requirements

Not built yet. The backend above provides everything these screens need.

1. **Upload screen**
   - Pick and upload a CSV.
   - On failure, show every validation problem (missing column, bad row, file too large).
   - On success, go to the new job's page.
2. **Job progress**
   - Show the job's status and counts of succeeded, failed and pending stores, updating while the job runs (polling).
   - Show when the job finished, or why it failed.
3. **Failures**
   - List the stores that failed, with the reason and the number of attempts.
4. **Scoring form**
   - Inputs for a bar and a weight per metric, plus the Large and Medium thresholds.
   - Prefill with the job's last-used rules.
   - Show each validation error next to its input (weights not adding up to 100, Medium above Large).
   - Available only once enrichment has finished.
5. **Tier breakdown**
   - Counts of Large, Medium and Small stores from the latest scoring, and when it ran.
6. **Store list**
   - A table of stores with name, location, the three metrics, score and tier.
   - Filterable by tier (and by status), with pagination.

## Out of scope

- User accounts, sign-up, login, or restricting who can see which jobs.
- Deployment and containerising the app itself (Docker is used only for local Postgres and LocalStack).
- Building our own enrichment API, or changing the provided one.
- **Bonus items, only if time allows:**
  - several jobs running at once while sharing one 5 calls/s limit;
  - resuming a job after a restart without redoing finished stores.

## Testing

Tests are optional but expected, runnable with one command. They should cover:
- the scoring formula and tier boundaries (the worked example, plus a value exactly at a bar, a score exactly at a threshold, a weight of 0);
- CSV validation;
- for draft 2: backoff delays and attempt caps, a 429 not using up attempts, a late answer not double-counting, and the circuit breaker leaving the job `failed`.
