from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from apps.api.app.core.database import Base
from apps.api.app.main import create_app

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

PAYLOAD = {
    "prompt": "Run the tests and identify failing cases",
    "repository": "https://github.com/example/demo",
    "max_runtime_seconds": 300,
}


async def test_create_and_read_survives_api_restart(database):
    app = create_app(engine=database)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/tasks", json=PAYLOAD)
            assert response.status_code == 201
            task_id = response.json()["task_id"]
            assert UUID(task_id)
            assert response.json()["status"] == "QUEUED"
            assert response.headers["location"] == f"/tasks/{task_id}"

    # Read through an independent database connection to prove the transaction committed.
    async with database.connect() as connection:
        row = (
            await connection.execute(
                text("SELECT prompt, status, attempts FROM tasks WHERE id = :id"),
                {"id": UUID(task_id)},
            )
        ).one()
        assert tuple(row) == (PAYLOAD["prompt"], "QUEUED", 0)

    restarted = create_app(engine=database)
    async with restarted.router.lifespan_context(restarted):
        async with AsyncClient(
            transport=ASGITransport(app=restarted), base_url="http://test"
        ) as client:
            response = await client.get(f"/tasks/{task_id}")
            assert response.status_code == 200
            task = response.json()
            assert task["id"] == task_id
            assert task["prompt"] == PAYLOAD["prompt"]
            assert task["repository"] == PAYLOAD["repository"]
            assert task["max_runtime_seconds"] == 300
            assert task["status"] == "QUEUED"
            assert task["attempts"] == 0
            assert task["created_at"]
            assert task["worker_id"] is None
            assert task["started_at"] is None
            assert task["completed_at"] is None


async def test_list_is_paginated_and_newest_first(client):
    assert (await client.get("/tasks")).json() == []
    ids = []
    for i in range(3):
        response = await client.post("/tasks", json={**PAYLOAD, "prompt": f"Task {i}"})
        assert response.status_code == 201
        ids.append(response.json()["task_id"])
    response = await client.get("/tasks", params={"limit": 2})
    assert response.status_code == 200
    assert [task["id"] for task in response.json()] == ids[::-1][:2]
    response = await client.get("/tasks", params={"limit": 2, "offset": 2})
    assert [task["id"] for task in response.json()] == [ids[0]]
    assert (await client.get("/tasks?limit=101")).status_code == 422
    assert (await client.get("/tasks?offset=-1")).status_code == 422


async def test_missing_or_invalid_task_id(client):
    response = await client.get(f"/tasks/{uuid4()}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Task not found"}
    assert (await client.get("/tasks/not-a-uuid")).status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"prompt": "   "},
        {"prompt": "x" * 50001},
        {"repository": "file:///etc/passwd"},
        {"repository": "not-a-url"},
        {"max_runtime_seconds": 0},
        {"max_runtime_seconds": 86401},
        {"max_runtime_seconds": True},
        {"status": "SUCCEEDED"},
    ],
)
async def test_invalid_input_is_not_persisted(client, changes):
    assert (await client.post("/tasks", json={**PAYLOAD, **changes})).status_code == 422
    assert (await client.get("/tasks")).json() == []


async def test_runtime_defaults_and_prompt_is_trimmed(client):
    response = await client.post(
        "/tasks", json={"prompt": "  Run tests  ", "repository": PAYLOAD["repository"]}
    )
    task = (await client.get(response.headers["location"])).json()
    assert task["prompt"] == "Run tests"
    assert task["max_runtime_seconds"] == 300


async def test_health_checks_postgres(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_migration_matches_model_and_roundtrips(database):
    def check_and_roundtrip(connection):
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
        assert connection.scalar(text("SELECT to_regclass('tasks')")) is None
        command.upgrade(config, "head")
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []

    async with database.begin() as connection:
        await connection.run_sync(check_and_roundtrip)
