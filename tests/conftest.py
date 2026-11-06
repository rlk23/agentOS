import os
from pathlib import Path
from uuid import uuid4

import pytest
from agentos_core.queue import TaskQueue
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from apps.api.app.main import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def database():
    url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://agentos:agentos@127.0.0.1:55433/agentos_test",
    )
    # Every test owns a randomly named schema. Never drop shared or public tables.
    schema = f"test_{uuid4().hex}"
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    created = False
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True

        def migrate(connection):
            config = Config(str(ROOT / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        async with engine.begin() as connection:
            await connection.run_sync(migrate)
        yield engine
    finally:
        await engine.dispose()
        if created:
            async with admin.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@pytest.fixture
async def client(database):
    app = create_app(engine=database)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


@pytest.fixture
def sessions(database):
    return async_sessionmaker(database, expire_on_commit=False)


@pytest.fixture
async def queue():
    redis = Redis.from_url(
        os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:56380/0"),
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=3,
    )
    queue = TaskQueue(redis, key=f"agentos:test:{uuid4().hex}")
    try:
        await redis.ping()
        yield queue
    finally:
        # Only remove this test's unique key, never shared Redis data.
        await redis.delete(queue.key)
        await redis.aclose()
