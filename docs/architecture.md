# Architecture

PostgreSQL is the source of truth for tasks. FastAPI commits a new task before returning
HTTP 201. Each request receives its own SQLAlchemy async session. Alembic owns schema
changes; API startup never creates tables automatically.

Current flow: client → FastAPI → PostgreSQL. The API accepts tasks and reads their state.
UUID identifiers and timezone-aware timestamps are persisted with prompt, repository,
runtime limit, status, attempt count, and optional worker and lifecycle timestamps.

Next: add a database-backed dispatcher or transactional outbox to deliver queued task IDs
to Redis. Redis provides coordination and delivery, not authoritative state. Workers must
claim tasks atomically in PostgreSQL and tolerate duplicate delivery. Existing queued
tasks must be discoverable by the dispatcher when it starts.

Before enabling LLM tools, isolate execution from the host and control CPU, memory, runtime,
filesystem access, network access, and credentials. A disposable working directory alone
is not an isolation boundary.

The dashboard will use HTTP APIs. Polling is sufficient initially. Events, logs, cancellation,
and execution artifacts will be added alongside worker execution.
