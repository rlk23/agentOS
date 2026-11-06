from datetime import datetime
from typing import Annotated
from uuid import UUID

from agentos_core.contracts import TaskStatus
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50000)]
    repository: HttpUrl = Field(max_length=2048)
    max_runtime_seconds: int = Field(default=300, ge=1, le=86400, strict=True)


class TaskCreated(BaseModel):
    task_id: UUID
    status: TaskStatus


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    prompt: str
    repository: str
    max_runtime_seconds: int
    status: TaskStatus
    attempts: int
    worker_id: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
