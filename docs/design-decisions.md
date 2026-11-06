# Initial decisions

- Start with the control plane and persistence, before the dashboard or LLM integration.
- Use Python 3.12+, FastAPI, async SQLAlchemy, asyncpg, and Alembic.
- Use PostgreSQL in integration tests; SQLite would not exercise PostgreSQL migrations and types.
- Keep PostgreSQL authoritative. Use due `QUEUED` rows as a durable dispatch backlog.
- Use `/tasks` for the first milestone, matching the latest API examples. Defer route versioning.
- Return a compact creation receipt and a full task representation on retrieval.
- Use offset pagination for the initial dashboard; reconsider cursor pagination as volume grows.
- Keep development services on localhost. Authentication is required before shared deployment.
- Enforce worker transitions with expected status and execution tokens. Expose progress via events.
- Use Redis sorted-set delivery so repeated dispatch does not accumulate waiting duplicates.
  Periodic database redispatch repairs lost notifications until a task is claimed.
- Keep the API independent of Redis availability. Events and state changes share transactions.
- Run only a fixed, trusted text-summary job in this milestone. Hard sandboxing precedes LLM tools.
- Defer running-attempt recovery to the leases and retries milestone; document stuck-RUNNING behavior.

Implementation references:

- [SQLAlchemy async sessions](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [FastAPI async tests](https://fastapi.tiangolo.com/advanced/async-tests/)
- [FastAPI lifespan testing](https://fastapi.tiangolo.com/advanced/testing-events/)
- [Redis ZADD](https://redis.io/docs/latest/commands/zadd/)
- [Redis BZPOPMIN](https://redis.io/docs/latest/commands/bzpopmin/)
- [SQLAlchemy row locking](https://docs.sqlalchemy.org/en/20/core/selectable.html)
