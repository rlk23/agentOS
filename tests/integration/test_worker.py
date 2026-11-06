import asyncio
from dataclasses import replace
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from agentos_core.contracts import TaskStatus
from agentos_core.scheduler import claim_task, dispatch_once, finish_task, record_progress
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from apps.worker.app.executor import execute_demo
from apps.worker.app.runner import Worker

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

PAYLOAD = {"prompt": "Run the tests", "repository": "https://github.com/example/demo"}


async def submit(client, **overrides):
    response = await client.post("/tasks", json={**PAYLOAD, **overrides})
    assert response.status_code == 201
    return UUID(response.json()["task_id"])


async def test_submit_dispatch_execute_and_read_history(client, sessions, queue):
    task_id = await submit(client)
    assert (await client.get(f"/tasks/{task_id}")).json()["status"] == "QUEUED"
    assert await dispatch_once(sessions, queue) == 1
    assert await Worker(sessions, queue, "test-worker").run_once()
    response = await client.get(f"/tasks/{task_id}")
    task = response.json()
    assert task["status"] == "SUCCEEDED"
    assert task["attempts"] == 1
    assert task["worker_id"] == "test-worker"
    assert task["started_at"] and task["completed_at"]
    assert task["error"] is None
    assert task["result"] == {
        "job": "deterministic_demo",
        "prompt_sha256": sha256(PAYLOAD["prompt"].encode()).hexdigest(),
        "word_count": 3,
        "character_count": 13,
        "repository": PAYLOAD["repository"],
    }
    assert "execution_token" not in task
    events = (await client.get(f"/tasks/{task_id}/events")).json()
    assert [event["type"] for event in events] == [
        "QUEUED",
        "STARTED",
        "PROGRESS",
        "PROGRESS",
        "SUCCEEDED",
    ]
    assert [event["attempt"] for event in events] == [0, 1, 1, 1, 1]
    assert events[1]["data"] == {"worker_id": "test-worker"}
    assert all(event["task_id"] == str(task_id) for event in events)
    first_page = (await client.get(f"/tasks/{task_id}/events?limit=2")).json()
    second_page = (
        await client.get(f"/tasks/{task_id}/events", params={"after_id": first_page[-1]["id"]})
    ).json()
    assert first_page + second_page == events
    assert await dispatch_once(sessions, queue) == 0


async def test_events_validate_task_and_pagination(client):
    task_id = await submit(client)
    assert (await client.get(f"/tasks/{uuid4()}/events")).status_code == 404
    assert (await client.get("/tasks/invalid/events")).status_code == 422
    assert (await client.get(f"/tasks/{task_id}/events?after_id=-1")).status_code == 422
    assert (await client.get(f"/tasks/{task_id}/events?limit=101")).status_code == 422


async def test_concurrent_workers_claim_exactly_once(client, sessions):
    task_id = await submit(client)
    claims = await asyncio.gather(*(claim_task(sessions, task_id, f"worker-{i}") for i in range(8)))
    winners = [claim for claim in claims if claim is not None]
    assert len(winners) == 1
    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["status"] == "RUNNING"
    assert task["attempts"] == 1
    assert task["completed_at"] is None
    assert [event["type"] for event in (await client.get(f"/tasks/{task_id}/events")).json()] == [
        "QUEUED",
        "STARTED",
    ]


async def test_duplicate_delivery_during_and_after_execution(client, sessions, queue):
    task_id = await submit(client)
    entered = asyncio.Event()
    release = asyncio.Event()
    executions = []

    async def slow_job(claim, report):
        executions.append(claim.id)
        entered.set()
        await release.wait()
        return await execute_demo(claim, report)

    await queue.enqueue(task_id)
    worker = Worker(sessions, queue, "worker-1", executor=slow_job)
    running = asyncio.create_task(worker.run_once())
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        await queue.enqueue(task_id)
        assert await Worker(sessions, queue, "worker-2", executor=slow_job).run_once(block=False)
    finally:
        release.set()
        await running
    await queue.enqueue(task_id)
    assert await worker.run_once(block=False)
    assert executions == [task_id]
    assert (await client.get(f"/tasks/{task_id}")).json()["attempts"] == 1


async def test_stale_claim_and_terminal_updates_rejected(client, sessions):
    task_id = await submit(client)
    claim = await claim_task(sessions, task_id, "owner")
    stale = replace(claim, token=uuid4())
    assert not await record_progress(sessions, stale, "Stale progress")
    assert not await finish_task(sessions, stale, TaskStatus.SUCCEEDED, result={"bad": True})
    assert await finish_task(sessions, claim, TaskStatus.SUCCEEDED, result={"ok": True})
    assert not await finish_task(sessions, claim, TaskStatus.FAILED, error="Late failure")
    assert not await record_progress(sessions, claim, "Late progress")
    assert await claim_task(sessions, task_id, "late-worker") is None
    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["status"] == "SUCCEEDED" and task["result"] == {"ok": True}
    assert [event["type"] for event in (await client.get(f"/tasks/{task_id}/events")).json()] == [
        "QUEUED",
        "STARTED",
        "SUCCEEDED",
    ]


async def test_executor_failure_is_recorded_and_worker_can_continue(client, sessions, queue):
    async def failing_job(claim, report):
        raise ValueError("secret-value-not-for-event-history")

    failed_id = await submit(client)
    await queue.enqueue(failed_id)
    worker = Worker(sessions, queue, "worker", executor=failing_job)
    assert await worker.run_once(block=False)
    task = (await client.get(f"/tasks/{failed_id}")).json()
    assert task["status"] == "FAILED"
    assert task["error"] == "Task execution failed (ValueError)"
    assert task["result"] is None and task["completed_at"]
    history = (await client.get(f"/tasks/{failed_id}/events")).json()
    assert history[-1]["type"] == "FAILED"
    assert "secret-value" not in str(history)
    worker.executor = execute_demo
    next_id = await submit(client)
    await queue.enqueue(next_id)
    assert await worker.run_once(block=False)
    assert (await client.get(f"/tasks/{next_id}")).json()["status"] == "SUCCEEDED"


async def test_runtime_limit_marks_task_timed_out(client, sessions, queue):
    async def waiting_job(claim, report):
        await asyncio.Event().wait()

    task_id = await submit(client, max_runtime_seconds=1)
    await queue.enqueue(task_id)
    assert await Worker(sessions, queue, "worker", executor=waiting_job).run_once(block=False)
    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["status"] == "TIMED_OUT"
    assert task["error"] == "Task runtime limit exceeded"
    assert (await client.get(f"/tasks/{task_id}/events")).json()[-1]["type"] == "TIMED_OUT"


async def test_executor_timeout_error_is_not_misreported_as_runtime_limit(client, sessions, queue):
    async def failing_job(claim, report):
        raise TimeoutError("An internal operation timed out")

    task_id = await submit(client)
    await queue.enqueue(task_id)
    await Worker(sessions, queue, "worker", executor=failing_job).run_once(block=False)
    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["status"] == "FAILED"
    assert task["error"] == "Task execution failed (TimeoutError)"


async def test_prompt_is_data_not_a_command(client, sessions, queue, tmp_path):
    marker = tmp_path / "must-not-exist"
    task_id = await submit(client, prompt=f"touch {marker}")
    await queue.enqueue(task_id)
    await Worker(sessions, queue, "worker").run_once(block=False)
    assert not marker.exists()
    assert (await client.get(f"/tasks/{task_id}")).json()["result"]["job"] == "deterministic_demo"


async def test_queue_deduplicates_waiting_ids_and_ignores_invalid_messages(queue):
    task_id = uuid4()
    await queue.enqueue(task_id)
    await queue.enqueue(task_id)
    assert await queue.redis.zcard(queue.key) == 1
    assert await queue.dequeue(block=False) == task_id
    assert await queue.dequeue(block=False) is None
    await queue.redis.zadd(queue.key, {"invalid": 0})
    assert await queue.dequeue(block=False) is None
    await queue.enqueue(task_id)
    assert await queue.dequeue() == task_id


async def test_migration_preserves_existing_queued_tasks(database, client, sessions, queue):
    task_id = uuid4()

    def upgrade_existing(connection):
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.downgrade(config, "0001")
        connection.execute(
            text("INSERT INTO tasks (id, prompt, repository) VALUES (:id, :prompt, :repository)"),
            {"id": task_id, **PAYLOAD},
        )
        command.upgrade(config, "head")

    async with database.begin() as connection:
        await connection.run_sync(upgrade_existing)
    events = (await client.get(f"/tasks/{task_id}/events")).json()
    assert len(events) == 1 and events[0]["type"] == "QUEUED"
    assert await dispatch_once(sessions, queue) == 1
    await Worker(sessions, queue, "worker").run_once(block=False)
    assert (await client.get(f"/tasks/{task_id}")).json()["status"] == "SUCCEEDED"
