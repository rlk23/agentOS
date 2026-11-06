# AgentOS

A monorepo for submitting coding tasks, executing them in isolated workers, and recovering from failures.

The first milestone implements the FastAPI control plane and durable PostgreSQL task persistence.
Tasks remain `QUEUED` until the worker milestone. There is no agent execution yet.

## Local setup

Requirements: Python 3.12+, uv, and Docker with Compose. Run commands from the repository root.

```bash
make install
cp .env.example .env
make db
make migrate
make dev
```

The API listens on http://127.0.0.1:8000; interactive documentation is at
http://127.0.0.1:8000/docs. Configuration is read from environment variables or `.env`.
The PostgreSQL credentials in Compose are for local development only. The API has no
authentication yet and should remain bound to localhost.

## First milestone

```bash
curl --fail http://127.0.0.1:8000/health

curl --fail -i http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Run the tests and identify failing cases","repository":"https://github.com/example/demo","max_runtime_seconds":300}'
```

Creation returns HTTP 201, a `Location` header, and:

```json
{"task_id":"<UUID>","status":"QUEUED"}
```

Retrieve the task with `GET /tasks/<UUID>`. List tasks with `GET /tasks?limit=50&offset=0`.
Lists are newest first, with UUID as a tie breaker. Limits must be between 1 and 100.
`GET /health` checks PostgreSQL connectivity and returns HTTP 503 if the database is unavailable;
it does not check migration readiness.

Prompts must contain 1–50,000 characters after trimming. Repository URLs must be HTTP(S).
Runtime defaults to 300 seconds and must be between 1 and 86,400 seconds. These are stored
execution settings; this milestone never clones repositories or runs commands. Runtime limits
will be enforced by the worker. Invalid requests return 422; missing tasks return 404.

Routes currently use `/tasks`, following the first milestone. `/api/v1` versioning, event
history, and cancellation are deferred. Repeated POSTs create separate tasks; submission
idempotency will be added with scheduling.

## Verification

```bash
make test
make lint
```

`make test` starts a separate PostgreSQL container on port 55433 and runs all tests.
Each integration test creates a unique schema, applies the actual Alembic migration,
and removes only that schema afterward. Tests cover committed data surviving an API
restart, pagination, validation, missing IDs, health behavior, and migration roundtrips.
They fail if PostgreSQL is unavailable rather than silently skipping persistence checks.

For an existing test server, export `TEST_DATABASE_URL` and run `uv run pytest -q`.
The test database user needs permission to create schemas. This test override is read
from the shell environment, not `.env`.

`make stop` stops the project containers without removing the development database volume.
The test database uses ephemeral storage. `uv.lock` pins the dependency versions.

## Layout

- `apps/api/app`: routes, configuration, models, schemas, and task services.
- `packages/agentos_core`: shared task status contract.
- `infra`: PostgreSQL Compose services and Alembic migrations.
- `tests`: unit and real PostgreSQL integration tests.
- `docs`: architecture, lifecycle, and roadmap decisions.

Worker and Next.js applications will be introduced in their respective milestones.

## Roadmap — 3/7 complete

- [x] Create FastAPI app and verify the health endpoint locally.
- [x] Create PostgreSQL task model and migrations.
- [x] Implement task creation, listing, and retrieval with integration tests.
- [ ] Add Redis delivery and a worker for deterministic jobs.
- [ ] Integrate an LLM agent with controlled tools and isolated execution.
- [ ] Add crash recovery, leases, retries, and fault injection tests.
- [ ] Build the Next.js task and log dashboard.

Before any agent-generated command runs, introduce isolated, resource-limited containers.
Do not execute untrusted commands on the host. Durable dispatch must be included when Redis
is introduced so a crash between committing a task and delivering it cannot lose work.
