# Task lifecycle

Clients cannot supply status, attempt count, IDs, or timestamps. PostgreSQL constrains status
to the shared enum values. The worker enforces allowed transitions and performs conditional
database updates; clients have no status-mutation endpoint.

Implemented transitions:

- `QUEUED → RUNNING` after an atomic worker claim.
- `RUNNING → SUCCEEDED` after successful execution.
- `RUNNING → FAILED` for executor exceptions.
- `RUNNING → TIMED_OUT` when execution exceeds its limit.

Retry (`RUNNING → RETRY_WAIT → QUEUED`) and cancellation are reserved but not implemented.

`SUCCEEDED`, `FAILED`, `CANCELLED`, and `TIMED_OUT` are terminal. Claiming increments attempts,
sets a worker ID and execution token, and records the start timestamp. Progress and finalization
check the token and `RUNNING` state; late writes cannot overwrite terminal outcomes.
Finalization records the completion timestamp and result or error. State changes and their
corresponding events commit atomically.

Queued tasks can be redispatched after lost delivery. Running tasks are never automatically
reclaimed in this milestone; a hard worker crash after claim can leave them stuck. Retry policy,
leases, heartbeats, and checkpoint semantics remain deferred. Future cancellation must persist
intent separately from confirmed termination.
