import asyncio
from uuid import UUID

import pytest
from agentos_core.models import Task
from agentos_core.scheduler import dispatch_once
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select, update

from apps.worker.app.runner import Worker

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def submit(client):
    response = await client.post(
        "/tasks", json={"prompt": "Test delivery", "repository": "https://github.com/example/demo"}
    )
    assert response.status_code == 201
    return UUID(response.json()["task_id"])


async def make_due(sessions, task_id):
    # Advance the durable dispatch deadline without slowing the test down by 30 seconds.
    async with sessions.begin() as session:
        await session.execute(
            update(Task).where(Task.id == task_id).values(dispatch_after=func.now())
        )


async def test_redis_failure_does_not_lose_accepted_task(client, sessions, queue, monkeypatch):
    task_id = await submit(client)

    async def unavailable(task_id):
        raise RedisConnectionError("simulated outage")

    with monkeypatch.context() as patch:
        patch.setattr(queue, "enqueue", unavailable)
        with pytest.raises(RedisConnectionError):
            await dispatch_once(sessions, queue)
    assert (await client.get(f"/tasks/{task_id}")).json()["status"] == "QUEUED"
    assert await dispatch_once(sessions, queue) == 1
    await Worker(sessions, queue, "worker").run_once(block=False)
    assert (await client.get(f"/tasks/{task_id}")).json()["status"] == "SUCCEEDED"


async def test_crash_after_publish_before_db_commit_is_replayable(
    client, sessions, queue, monkeypatch
):
    task_id = await submit(client)
    enqueue = queue.enqueue

    async def publish_then_crash(task_id):
        await enqueue(task_id)
        raise RuntimeError("simulated dispatcher crash")

    with monkeypatch.context() as patch:
        patch.setattr(queue, "enqueue", publish_then_crash)
        with pytest.raises(RuntimeError):
            await dispatch_once(sessions, queue)
    # The real Redis publication happened but the database transaction rolled back.
    assert await queue.redis.zcard(queue.key) == 1
    assert await dispatch_once(sessions, queue) == 1
    assert await queue.redis.zcard(queue.key) == 1
    await Worker(sessions, queue, "worker").run_once(block=False)
    assert (await client.get(f"/tasks/{task_id}")).json()["attempts"] == 1


@pytest.mark.parametrize("lost_delivery", ["redis_loss", "worker_dies_before_claim"])
async def test_lost_redis_delivery_is_rebuilt_from_postgres(client, sessions, queue, lost_delivery):
    task_id = await submit(client)
    assert await dispatch_once(sessions, queue) == 1
    if lost_delivery == "redis_loss":
        await queue.redis.delete(queue.key)
    else:
        assert await queue.dequeue(block=False) == task_id
    assert await dispatch_once(sessions, queue) == 0
    await make_due(sessions, task_id)
    assert await dispatch_once(sessions, queue) == 1
    await Worker(sessions, queue, "worker").run_once(block=False)
    assert (await client.get(f"/tasks/{task_id}")).json()["status"] == "SUCCEEDED"


async def test_multiple_dispatchers_do_not_wait_on_locked_tasks(client, sessions, queue):
    first = await submit(client)
    second = await submit(client)
    async with sessions.begin() as session:
        await session.scalar(select(Task).where(Task.id == first).with_for_update())
        assert await asyncio.wait_for(dispatch_once(sessions, queue), timeout=5) == 1
        assert await queue.dequeue(block=False) == second
    assert await dispatch_once(sessions, queue) == 1
    assert await queue.dequeue(block=False) == first


async def test_redis_queue_stays_bounded_when_workers_are_offline(client, sessions, queue):
    task_id = await submit(client)
    for _ in range(3):
        await make_due(sessions, task_id)
        assert await dispatch_once(sessions, queue) == 1
    assert await queue.redis.zcard(queue.key) == 1
