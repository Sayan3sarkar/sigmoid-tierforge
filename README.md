# TierForge

TierForge reads a CSV of stores and enriches each store with metrics from a slow, flaky third-party API (the provided simulator). It then scores each store and sorts it into Large, Medium or Small.

What the system must do: [REQUIREMENTS.md](REQUIREMENTS.md)

## Repository layout

```
sigmoid-tierforge/
├── backend/                     Python backend (Poetry project)
│   ├── api/                     FastAPI app
│   │   ├── main.py              App factory + lifespan (DB engine, SQS client)
│   │   ├── routes/              HTTP routes, all under /api
│   │   ├── services/            Business logic, injected as FastAPI dependencies
│   │   ├── repositories/        DB access, injected as FastAPI dependencies
│   │   ├── models/              SQLAlchemy models (shared with the worker)
│   │   ├── schemas/             Pydantic request/response and message schemas
│   │   ├── dependencies/        DB session and SQS dependencies
│   │   └── aws/sqs.py           Async SQS client (aiobotocore)
│   ├── worker/worker.py         SQS consumer
│   ├── config/                  Config class (pydantic-settings, reads .env)
│   ├── migrations/              Alembic migrations
│   ├── scripts/                 Database and LocalStack setup scripts
│   ├── tests/                   pytest suite (settings in tests/.test.env)
│   ├── make.toml                Poe tasks: app, tests, formatting, checks
│   └── db.toml                  Poe tasks: database and migrations
├── enrichment_simulator/        Provided enrichment API (not in git; do not modify)
└── frontend/                    (later)
```

## Prerequisites

| Tool                                        | Version | Used for                            |
| ------------------------------------------- | ------- | ----------------------------------- |
| Python                                      | 3.12    | Backend and simulator               |
| [Poetry](https://python-poetry.org/)        | 2.x     | Dependencies and virtualenv         |
| Docker                                      | any     | Postgres and LocalStack containers  |
| AWS CLI                                     | v2      | Used by the LocalStack setup script |

### Postgres and LocalStack containers

Skip these if you already have Postgres on `localhost:5432` and LocalStack on `localhost:4566`.

```bash
# Postgres 16 on localhost:5432 (user postgres / password postgres)
docker run -d --name tierforge-postgres \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 postgres:16

# LocalStack (SQS) on localhost:4566
docker run -d --name tierforge-localstack \
  -e SERVICES=sqs \
  -p 4566:4566 localstack/localstack
```

If your LocalStack version asks for an auth token, add `-e LOCALSTACK_AUTH_TOKEN=<your token>` to the LocalStack command.

## First-time setup

```bash
cd backend

# 1. Install dependencies (creates the virtualenv)
poetry install

# 2. Create your env file, then adjust values if your setup differs
cp .env.example .env

# 3. Create the database, run migrations and create the SQS queues
poetry run poe setup
```

The provided simulator must be extracted to `enrichment_simulator/` at the repo root, next to `backend/`. Don't modify it. Its dependencies (FastAPI, Uvicorn) are already in the backend environment.

## Running

Each command runs in its own terminal, from `backend/`:

```bash
poetry run poe simulator   # enrichment simulator on http://localhost:8000
poetry run poe api         # API on http://localhost:8001 (docs at /docs)
poetry run poe worker      # SQS consumer
```

To drop the `poetry run` prefix, activate the virtualenv once per shell with `eval $(poetry env activate)`, then run `poe api`, `poe worker`, and so on.

## Poe tasks

Run `poe --help` for the full list. Every task reads `backend/.env`.

| Task                                 | What it does                                                        |
| ------------------------------------ | ------------------------------------------------------------------- |
| `poe api`                            | Run the FastAPI server with auto-reload                             |
| `poe worker`                         | Run the SQS consumer                                                |
| `poe simulator`                      | Run the provided enrichment simulator                               |
| `poe setup`                          | One-time setup: `db_create`, `db_upgrade`, `localstack_init`        |
| `poe localstack_init`                | Create the SQS queue and its dead-letter queue (safe to re-run)     |
| `poe test`                           | Run the tests (settings from `tests/.test.env`)                     |
| `poe format`                         | Sort imports (isort) and format code (black, 88 characters)         |
| `poe check`                          | flake8, plus isort and black checks without changing files          |
| `poe db_create`                      | Create the database in `DATABASE_URL` if it doesn't exist           |
| `poe db_create_migration -m "msg"`   | Autogenerate a migration from the models                            |
| `poe db_upgrade [revision]`          | Apply migrations (default: `head`)                                  |
| `poe db_downgrade [revision]`        | Roll back migrations (default: one step, `-1`)                      |
| `poe db_current` / `poe db_history`  | Show the current revision / list all migrations                     |

## Configuration

Settings live in `backend/.env` and are read by the `Config` class in [backend/config/settings.py](backend/config/settings.py). See [backend/.env.example](backend/.env.example) for every variable. `.env` is git-ignored; `.env.example` and `tests/.test.env` are committed.

### SQS

The app never creates queues; it only connects to an existing one through `SQS_ENRICHMENT_QUEUE_URL`.

- **Locally:** `poe localstack_init` creates the queue in LocalStack, named after the last part of that URL (plus a `-dlq` dead-letter queue). `000000000000` in the URL is LocalStack's default account ID.
- **In AWS:** the queue is provisioned with Terraform. Set `SQS_ENRICHMENT_QUEUE_URL` to its URL and leave `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` unset, so the client uses the real AWS endpoint and the IAM role.
