# Initial decisions

- Start with the control plane and persistence, before the dashboard or LLM integration.
- Use Python 3.12+, FastAPI, async SQLAlchemy, asyncpg, and Alembic.
- Use PostgreSQL in integration tests; SQLite would not exercise PostgreSQL migrations and types.
- Keep PostgreSQL authoritative. Add durable dispatch when Redis is introduced.
- Use `/tasks` for the first milestone, matching the latest API examples. Defer route versioning.
- Return a compact creation receipt and a full task representation on retrieval.
- Use offset pagination for the initial dashboard; reconsider cursor pagination as volume grows.
- Keep development services on localhost. Authentication is required before shared deployment.
- Reserve lifecycle status values now, but do not expose state updates until transition and
  ownership checks exist.

Implementation references:

- [SQLAlchemy async sessions](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [FastAPI async tests](https://fastapi.tiangolo.com/advanced/async-tests/)
- [FastAPI lifespan testing](https://fastapi.tiangolo.com/advanced/testing-events/)
