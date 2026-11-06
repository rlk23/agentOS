from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentos_core.contracts import TaskStatus
from agentos_core.events import EventType
from agentos_core.models import Task, TaskEvent
from agentos_core.queue import TaskQueue
from agentos_core.state_machine import require_transition

SessionFactory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True)
class TaskClaim:
    id: UUID
    token: UUID
    attempt: int
    prompt: str
    repository: str
    max_runtime_seconds: int
    execution_mode: str = "demo"


async def dispatch_once(
    sessions: SessionFactory,
    queue: TaskQueue,
    *,
    batch_size: int = 50,
    redispatch_seconds: int = 30,
) -> int:
    """Re-publish queued tasks until claimed; delivery need not be exactly once."""
    async with sessions.begin() as session:
        tasks = list(
            await session.scalars(
                select(Task)
                .where(Task.status == TaskStatus.QUEUED, Task.dispatch_after <= func.now())
                .order_by(Task.dispatch_after, Task.id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        for task in tasks:
            # Publish before postponing dispatch. A crash here can produce a duplicate,
            # which the claim predicate handles. Redis loss is healed on the next scan.
            await queue.enqueue(task.id)
            task.dispatch_after = func.now() + timedelta(seconds=redispatch_seconds)
        return len(tasks)


async def claim_task(sessions: SessionFactory, task_id: UUID, worker_id: str) -> TaskClaim | None:
    require_transition(TaskStatus.QUEUED, TaskStatus.RUNNING)
    token = uuid4()
    async with sessions.begin() as session:
        task = await session.scalar(
            update(Task)
            .where(Task.id == task_id, Task.status == TaskStatus.QUEUED)
            .values(
                status=TaskStatus.RUNNING,
                worker_id=worker_id,
                execution_token=token,
                attempts=Task.attempts + 1,
                started_at=func.now(),
                completed_at=None,
                result=None,
                error=None,
            )
            .returning(Task)
        )
        if task is None:
            return None
        session.add(
            TaskEvent(
                task_id=task.id,
                type=EventType.STARTED,
                attempt=task.attempts,
                message="Worker claimed task",
                data={"worker_id": worker_id},
            )
        )
        return TaskClaim(
            task.id,
            token,
            task.attempts,
            task.prompt,
            task.repository,
            task.max_runtime_seconds,
            task.execution_mode,
        )


async def record_progress(
    sessions: SessionFactory,
    claim: TaskClaim,
    message: str,
    *,
    event_type: EventType = EventType.PROGRESS,
    data: dict | None = None,
) -> bool:
    async with sessions.begin() as session:
        task = await session.scalar(
            select(Task)
            .where(
                Task.id == claim.id,
                Task.status == TaskStatus.RUNNING,
                Task.execution_token == claim.token,
            )
            .with_for_update()
        )
        if task is None:
            return False
        session.add(
            TaskEvent(
                task_id=claim.id,
                type=event_type,
                attempt=claim.attempt,
                message=message,
                data=data or {},
            )
        )
        return True


async def finish_task(
    sessions: SessionFactory,
    claim: TaskClaim,
    status: TaskStatus,
    *,
    result: dict | None = None,
    error: str | None = None,
) -> bool:
    require_transition(TaskStatus.RUNNING, status)
    async with sessions.begin() as session:
        task_id = await session.scalar(
            update(Task)
            .where(
                Task.id == claim.id,
                Task.status == TaskStatus.RUNNING,
                Task.execution_token == claim.token,
            )
            .values(status=status, result=result, error=error, completed_at=func.now())
            .returning(Task.id)
        )
        if task_id is None:
            return False
        session.add(
            TaskEvent(
                task_id=claim.id,
                type=status.value,
                attempt=claim.attempt,
                message=(
                    "Task execution completed"
                    if status == TaskStatus.SUCCEEDED
                    else error or "Task execution ended"
                ),
                data={},
            )
        )
        return True
