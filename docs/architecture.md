# Architecture

PostgreSQL is the source of truth for tasks. FastAPI commits a new task before returning
HTTP 201. Each request receives its own SQLAlchemy async session. Alembic owns schema
changes; API startup never creates tables automatically.

Current flow: client → FastAPI → PostgreSQL → dispatcher → Redis → worker → PostgreSQL.
The API commits submission state and its event in one transaction. Shared models live in
`agentos_core`; the API model module re-exports them for compatibility. Workers do not import
the API application.

The database-backed dispatcher selects due `QUEUED` tasks with `FOR UPDATE SKIP LOCKED`,
publishes their IDs, and postpones dispatch by a configurable interval (default 30 seconds).
Redis failures roll back the postponement. A crash after publication but before commit can
cause redelivery, which is safe. Even after a successful dispatch, a still-queued task is
eligible again at its deadline, so losing Redis contents or dying before claim cannot strand it.

Redis uses a sorted set with task IDs as unique members (`ZADD NX` and `BZPOPMIN`). This bounds
waiting entries to one per task even if workers are offline. Queue ordering is approximate;
there is no strict FIFO or priority guarantee. Queue messages carry no prompt or repository data.

Workers use `UPDATE ... WHERE status = 'QUEUED' RETURNING ...` to claim tasks and issue an
execution token. Start state and its event commit atomically. Progress and completion require
`RUNNING` state plus the token. Completion status, result, and terminal event share a transaction.
This guards current ownership and terminal states; it does not implement worker leases.

The deterministic executor computes a prompt summary and hash. It accesses no repository and
launches no subprocess. Runtime cancellation is cooperative, appropriate only to this bounded,
trusted executor. Worker exceptions are recorded without arbitrary exception messages.

Graceful shutdown finishes an active demo. A hard crash after claim or lost database connectivity
during finalization may leave `RUNNING` tasks stuck. Heartbeats, leases, retries, and checkpoint
recovery remain a separate milestone. There is no claim of exactly-once external effects.

Before enabling LLM tools, isolate execution from the host and control CPU, memory, runtime,
filesystem access, network access, and credentials. A disposable working directory alone
is not an isolation boundary.

The dashboard will use HTTP APIs. Events are exposed in ID order with an `after_id` cursor;
polling is sufficient initially. Cancellation, subprocess logs, and execution artifacts are deferred.
