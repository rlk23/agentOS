from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models.task import Task
from apps.api.app.schemas.task import TaskCreate


async def create_task(session: AsyncSession, payload: TaskCreate) -> Task:
    task = Task(
        prompt=payload.prompt,
        repository=str(payload.repository),
        max_runtime_seconds=payload.max_runtime_seconds,
    )
    session.add(task)
    await session.commit()
    return task


async def get_task(session: AsyncSession, task_id: UUID) -> Task | None:
    return await session.get(Task, task_id)


async def list_tasks(session: AsyncSession, limit: int, offset: int) -> list[Task]:
    result = await session.scalars(
        select(Task).order_by(Task.created_at.desc(), Task.id.desc()).limit(limit).offset(offset)
    )
    return list(result)
