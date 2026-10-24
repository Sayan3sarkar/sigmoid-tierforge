# TierForge

TierForge scores and tiers a large list of stores. A user uploads a CSV of stores. A background job then enriches each store with three metrics (monthly footfall, monthly revenue, store size) from a slow, rate-limited and unreliable third-party API: the provided simulator, at most 5 calls/s. Once enrichment finishes, the user sets a bar and a weight per metric plus tier thresholds, and TierForge scores every enriched store and sorts it into **Large**, **Medium** or **Small**. Scoring uses only the saved metrics, so it's fast and can be re-run any time.

The backend is a FastAPI API and a separate SQS worker, sharing a PostgreSQL database. The frontend is a React single-page app over the API.

## Documentation

| Document                                                                 | What's in it                                                                      |
| ------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| [Requirements](documentation/REQUIREMENTS.md)                            | What the system must do: backend and frontend                                     |
| [Architecture](documentation/architecture.md)                            | High-level design: components, flows, key decisions                               |
| [Frontend architecture](documentation/FE_Architecture.md)                | Frontend stack, layers, directory structure, testing                              |
| [Data stores](documentation/datastores.md)                               | Every table, column, constraint and index                                         |
| [Limitations and trade-offs](documentation/limitations-and-tradeoffs.md) | Known limitations, design trade-offs, future scope, what's intentionally left out |

## Repository layout

```
sigmoid-tierforge/
├── backend/                  FastAPI API and SQS worker (one Poetry project)
│   ├── api/                  routes, services, repositories, models, schemas
│   ├── worker/               SQS consumer and rate limiter
│   ├── config/               settings (pydantic-settings, reads backend/.env)
│   ├── migrations/           Alembic migrations
│   ├── scripts/              database and LocalStack setup scripts
│   └── tests/                pytest suite (settings in tests/.test.env)
├── frontend/                 React + TypeScript single-page app (npm project)
│   └── src/                  api/, hooks/, components/, pages/, utils/, test/
├── documentation/            requirements, architecture, data stores, limitations
├── enrichment_simulator.zip  the provided enrichment API (unzip; don't modify)
└── stores_5000.csv           sample upload with 5,000 stores
```

## Getting started

### Prerequisites

| Tool                                 | Version                                  |
| ------------------------------------ | ---------------------------------------- |
| Python                               | 3.12 or 3.13                             |
| [Poetry](https://python-poetry.org/) | 2.x                                      |
| Docker                               | any recent                               |
| Node.js / npm                        | 22.x / 10.x                              |
| AWS CLI                              | v2 (used by the LocalStack setup script) |

### 1. Start Postgres and LocalStack

```bash
docker run -d --name tierforge-postgres \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 postgres:16

docker run -d --name tierforge-localstack \
  -e SERVICES=sqs \
  -p 4566:4566 localstack/localstack
```

If your LocalStack version asks for an auth token, add `-e LOCALSTACK_AUTH_TOKEN=<token>`. If you already run Postgres on `localhost:5432` or LocalStack on `localhost:4566`, skip that container.

### 2. Unzip the enrichment simulator

From the repository root:

```bash
unzip enrichment_simulator.zip -x "__MACOSX/*"
```

This creates `enrichment_simulator/` next to `backend/`. It's git-ignored and must not be modified. Its dependencies are already in the backend environment.

### 3. Install and configure the backend

```bash
cd backend
poetry install
cp .env.example .env
```

The defaults in `.env` match the containers above. `tests/.test.env` is committed and needs no copy.

### 4. Create the SQS queues, the database and its tables

From `backend/`:

```bash
poetry run poe localstack_init   # SQS queue + dead-letter queue in LocalStack (safe to re-run)
poetry run poe db_create         # the database in DATABASE_URL, if it doesn't exist
poetry run poe db_upgrade        # run all Alembic migrations
```

`poetry run poe setup` runs all three in one go.

### 5. Run the backend

Run each process in its own terminal, from `backend/`:

```bash
poetry run poe simulator   # enrichment API on http://localhost:8000
poetry run poe api         # TierForge API on http://localhost:8001 (interactive docs at /docs)
poetry run poe worker      # SQS worker
```

Running `eval $(poetry env activate)` once per shell lets you drop the `poetry run` prefix.

### 6. Run the frontend

In another terminal, from `frontend/`:

```bash
npm install
cp .env.example .env    # VITE_API_BASE_URL=http://localhost:8001
npm run dev             # http://localhost:5173
```

Open http://localhost:5173, upload `stores_5000.csv`, follow the job's progress, and score it once enrichment has finished.

### 7. Or try the API directly

```bash
# Upload the sample file: returns the job_id
curl -F "file=@../stores_5000.csv;type=text/csv" http://localhost:8001/api/uploads

# Watch progress (enriching 5,000 stores takes ~18.5 minutes)
curl http://localhost:8001/api/jobs/1

# Once the job is completed (or completed_with_failures), score it
curl -H "Content-Type: application/json" http://localhost:8001/api/jobs/1/scoring -d '{
  "bars":    {"footfall": 15000, "revenue": 150000, "size_sqft": 8000},
  "weights": {"footfall": 50,    "revenue": 30,     "size_sqft": 20},
  "tiers":   {"large_min": 70, "medium_min": 40}}'

# Tier counts, the Large stores, and the failed stores with reasons
curl http://localhost:8001/api/jobs/1/summary
curl "http://localhost:8001/api/jobs/1/stores?tier=large"
curl "http://localhost:8001/api/jobs/1/stores?status=failed"
```

### 8. Run the tests

**Backend,** from `backend/`, with Postgres running:

```bash
poetry run poe test
```

Each run creates its own temporary database (`tierforge_test_<random>`), migrates it, and drops it at the end. SQS and the enrichment API are mocked, so LocalStack and the simulator don't need to be running.

**Frontend,** from `frontend/`:

```bash
npm test
```

Every API call is mocked (Mock Service Worker), so no backend needs to be running.

## Frontend scripts

Run them from `frontend/`.

| Script                               | What it does                                                               |
| ------------------------------------ | -------------------------------------------------------------------------- |
| `npm run dev`                        | Dev server on http://localhost:5173                                        |
| `npm run build` / `npm run preview`  | Production build in `dist/` / serve that build locally                     |
| `npm test` / `npm run test:watch`    | Run the tests once / in watch mode                                         |
| `npm run typecheck` / `npm run lint` | TypeScript check / oxlint                                                  |
| `npm run api:types`                  | Regenerate `src/api/schema.d.ts` from the running backend's OpenAPI schema |

## Poe tasks

Run them from `backend/`; every task reads `backend/.env`. `poetry run poe --help` lists them all.

| Task                                                        | What it does                                                             |
| ----------------------------------------------------------- | ------------------------------------------------------------------------ |
| `poe api` / `poe worker` / `poe simulator`                  | Run the API (auto-reload), the worker, or the simulator                  |
| `poe setup`                                                 | `db_create`, `db_upgrade` and `localstack_init` in one go                |
| `poe localstack_init`                                       | Create the SQS queue and its dead-letter queue in LocalStack             |
| `poe db_create`                                             | Create the database in `DATABASE_URL` if it doesn't exist                |
| `poe db_upgrade [revision]` / `poe db_downgrade [revision]` | Apply migrations (default `head`) / roll back (default one step)         |
| `poe db_create_migration -m "message"`                      | Autogenerate a migration from the models                                 |
| `poe db_current` / `poe db_history`                         | Show the current revision / list all migrations                          |
| `poe test`                                                  | Run the test suite                                                       |
| `poe format` / `poe check`                                  | Format (isort, black) / lint and check formatting (flake8, isort, black) |

## Configuration

Settings live in `backend/.env`, read by `Config` in [backend/config/settings.py](backend/config/settings.py). [backend/.env.example](backend/.env.example) documents every variable, including the enrichment rate (`ENRICHMENT_RATE_PER_SECOND`, default 4.5), timeout (10 s) and number of handlers (8).

**CORS:** `ALLOWED_ORIGINS` lists the origins a browser frontend may call the API from, comma-separated (e.g. `http://localhost:5173,https://app.example.com`). The default, `*`, allows any origin; set explicit origins outside local development.

**SQS:** the app never creates queues; it uses the existing queue at `SQS_ENRICHMENT_QUEUE_URL`.

- **Locally,** `poe localstack_init` creates it in LocalStack (`000000000000` in the URL is LocalStack's default account ID).
- **In AWS,** it's provisioned with Terraform. Leave `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` unset, so the real endpoint and the IAM role are used.
- **At startup,** the worker checks the queue is reachable and refuses to start if not. If SQS is down while the API runs, uploads return 503 and everything else keeps working.
- **IAM:** the API needs `sqs:SendMessage`; the worker needs `sqs:GetQueueAttributes`, `sqs:ReceiveMessage` and `sqs:DeleteMessage`.
