from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.database import get_session
from apps.api.app.schemas.task import TaskCreate, TaskCreated, TaskRead
from apps.api.app.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=TaskCreated, status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreate, response: Response, session: Session) -> TaskCreated:
    task = await task_service.create_task(session, payload)
    response.headers["Location"] = f"/tasks/{task.id}"
    return TaskCreated(task_id=task.id, status=task.status)


@router.get("", response_model=list[TaskRead])
async def list_tasks(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return await task_service.list_tasks(session, limit, offset)


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_id: UUID, session: Session):
    task = await task_service.get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
