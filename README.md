# AgentOS

A monorepo for submitting coding tasks, executing them in isolated workers, and recovering from failures.

The control plane and basic worker milestones are implemented. Submit a task, deliver its ID
through Redis, and run a deterministic demo job with durable status, progress events, and results.
The worker summarizes the prompt as text; it does not execute the requested coding task yet.

## Local setup

Requirements: Python 3.12+, uv, and Docker with Compose. Run commands from the repository root.

```bash
make install
cp .env.example .env
make db
make migrate
make dev
```

In two additional terminals, from the repository root:

```bash
make dispatcher
```

```bash
make worker
```

Existing installations should run `make install`, `make db`, and `make migrate` before
restarting the API and starting the dispatcher and worker. Existing queued tasks are preserved
and will be picked up automatically. Development PostgreSQL uses port 55432; Redis uses 56379.

The API listens on http://127.0.0.1:8000; interactive documentation is at
http://127.0.0.1:8000/docs. Configuration is read from environment variables or `.env`.
The PostgreSQL credentials in Compose are for local development only. The API has no
authentication yet and should remain bound to localhost.

## Try task execution

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
With the dispatcher and worker running, the task moves `QUEUED → RUNNING → SUCCEEDED`.
The demo is fast; you may see `SUCCEEDED` on the first read. Execution history still records
each stage. The result contains `job: deterministic_demo`, a SHA-256 hash of the prompt,
character and word counts, and the supplied repository URL. It does not contain test results
or code changes. Executor exceptions produce `FAILED`; exceeding the runtime produces `TIMED_OUT`.

Use `GET /tasks/<UUID>/events` to read submission, start, progress, and completion events.
Events are oldest first. Poll with `?after_id=<last_event_id>&limit=50` to retrieve new events;
the limit can be 1–100. Task details include `result`, `error`, worker ID, attempt count,
and execution timestamps. Clients cannot set task state or ownership.

`GET /health` checks PostgreSQL connectivity and returns HTTP 503 if the database is unavailable;
it does not check migration readiness.

Prompts must contain 1–50,000 characters after trimming. Repository URLs must be HTTP(S).
Runtime defaults to 300 seconds and must be between 1 and 86,400 seconds. The worker applies
an asynchronous timeout around the trusted demo executor. This is cooperative cancellation,
not a sandbox or a hard resource limit. This milestone never clones repositories or runs
commands. Invalid requests return 422; missing tasks return 404.

Routes currently use `/tasks`. `/api/v1` versioning and cancellation are deferred.
Repeated POSTs create separate tasks; client submission idempotency is not implemented.

## Delivery guarantees and current limits

PostgreSQL owns task state. The API commits a task and its submission event together,
without contacting Redis. A separate dispatcher scans eligible `QUEUED` rows every second,
publishes IDs, and postpones their next dispatch by 30 seconds. Queued tasks remain eligible
for redispatch until claimed, including tasks created before the dispatcher started.

The Redis sorted set holds at most one waiting entry per task ID. A worker atomically claims
`QUEUED` tasks in PostgreSQL and persists its start event in the same transaction. Duplicate
messages cannot execute an already claimed task. Result writes require the current execution
token and `RUNNING` state, and commit together with their completion event.

Redis outages do not prevent task submission. Lost queue entries and a worker crash before
claiming are repaired by a later dispatch scan. A dispatcher crash between Redis publication
and database commit can replay a message safely. Redis persistence is deliberately disabled
locally to keep the database's recovery responsibility explicit.

**A worker crash after claiming can leave a task `RUNNING`.** Lost database connectivity
during finalization can do the same. Leases, heartbeats, retry budgets, and recovery of running
attempts belong to the later recovery milestone. Do not assume exactly-once external side
effects. This worker has no external execution effects.

Stop API, dispatcher, and worker with Ctrl+C in their terminals. The worker finishes its active
demo before exiting on SIGINT/SIGTERM. `make stop` stops only the infrastructure containers.

## Verification

```bash
make test
make lint
```

`make test` starts separate PostgreSQL (55433) and Redis (56380) containers and runs all tests.
Each integration test creates a unique schema, applies the actual Alembic migration,
and removes only that schema afterward. Redis tests use unique keys and never flush shared data.
Tests cover persistence, the full API-to-worker flow, competing claims, duplicate deliveries,
stale result rejection, progress pagination, executor failures, runtime limits, migration of
existing tasks, and delivery failure injection. Tests fail if their required services are unavailable.

For existing test servers, export `TEST_DATABASE_URL` and `TEST_REDIS_URL`, then run `uv run pytest -q`.
The test database user needs permission to create schemas. This test override is read
from the shell environment, not `.env`.

`make stop` stops the project containers without removing the development database volume.
The test database uses ephemeral storage. `uv.lock` pins the dependency versions.

## Layout

- `apps/api/app`: routes, configuration, models, schemas, and task services.
- `apps/worker/app`: dispatcher/worker entry point, runner, and trusted demo executor.
- `packages/agentos_core`: shared models, contracts, state transitions, scheduling, and Redis delivery.
- `infra`: PostgreSQL and Redis Compose services, plus Alembic migrations.
- `tests`: unit, real-service integration, and delivery fault injection tests.
- `docs`: architecture, lifecycle, and roadmap decisions.

The Next.js dashboard will be introduced in its own milestone.

## Roadmap — 4/7 complete

- [x] Create FastAPI app and verify the health endpoint locally.
- [x] Create PostgreSQL task model and migrations.
- [x] Implement task creation, listing, and retrieval with integration tests.
- [x] Add Redis delivery and a worker for deterministic jobs.
- [ ] Integrate an LLM agent with controlled tools and isolated execution.
- [ ] Add crash recovery, leases, retries, and fault injection tests.
- [ ] Build the Next.js task and log dashboard.

Before any agent-generated command runs, introduce isolated, resource-limited containers.
Do not execute untrusted commands on the host. The current trusted text-summary job is not
an isolation boundary and must not be replaced by a shell or LLM tool executor without one.
