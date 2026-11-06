# Task lifecycle

This milestone only creates and reads `QUEUED` tasks. Clients cannot supply status,
attempt count, IDs, or timestamps. PostgreSQL constrains status to the shared enum values.
Transition enforcement will be implemented before worker execution is enabled.

Planned transitions:

- `QUEUED → RUNNING` after an atomic worker claim.
- `RUNNING → SUCCEEDED` after successful execution.
- `RUNNING → RETRY_WAIT → QUEUED` for eligible failures within the retry budget.
- `RUNNING → FAILED` for permanent failures or an exhausted retry budget.
- `RUNNING → TIMED_OUT` when execution exceeds its limit.
- Nonterminal states may reach `CANCELLED` after the cancellation protocol is satisfied.

`SUCCEEDED`, `FAILED`, `CANCELLED`, and `TIMED_OUT` are terminal. Future conditional state
updates must check both the expected state and attempt ownership. Lease expiry and stale
worker handling need explicit recovery rules; a late result must not overwrite a newer
attempt or terminal outcome. Persist cancellation intent separately from confirmed termination.

The persisted runtime is currently declarative. Retry policy, leases, heartbeats, ownership
tokens, and checkpoint semantics are deferred to the worker milestones.
