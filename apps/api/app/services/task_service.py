from uuid import UUID

from agentos_core.events import EventType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models.task import Task, TaskEvent
from apps.api.app.schemas.task import TaskCreate


async def create_task(session: AsyncSession, payload: TaskCreate) -> Task:
    task = Task(
        prompt=payload.prompt,
        repository=str(payload.repository),
        execution_mode=payload.execution_mode,
        max_runtime_seconds=payload.max_runtime_seconds,
    )
    session.add(task)
    await session.flush()
    session.add(TaskEvent(task_id=task.id, type=EventType.QUEUED, message="Task accepted", data={}))
    await session.commit()
    return task


async def get_task(session: AsyncSession, task_id: UUID) -> Task | None:
    return await session.get(Task, task_id)


async def list_tasks(session: AsyncSession, limit: int, offset: int) -> list[Task]:
    result = await session.scalars(
        select(Task).order_by(Task.created_at.desc(), Task.id.desc()).limit(limit).offset(offset)
    )
    return list(result)


async def list_events(
    session: AsyncSession, task_id: UUID, after_id: int, limit: int
) -> list[TaskEvent]:
    return list(
        await session.scalars(
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id, TaskEvent.id > after_id)
            .order_by(TaskEvent.id)
            .limit(limit)
        )
    )
