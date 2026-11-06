from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from agentos_core.contracts import TaskStatus
from agentos_core.events import EventType
from agentos_core.repositories import github_repository
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50000)]
    repository: HttpUrl = Field(max_length=2048)
    execution_mode: Literal["demo", "agent"] = "demo"
    max_runtime_seconds: int = Field(default=300, ge=1, le=86400, strict=True)

    @model_validator(mode="after")
    def validate_agent_repository(self):
        if self.execution_mode == "agent":
            github_repository(str(self.repository))
            if self.max_runtime_seconds > 600:
                raise ValueError("Agent tasks currently support at most 600 seconds")
        return self


class TaskCreated(BaseModel):
    task_id: UUID
    status: TaskStatus


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    prompt: str
    repository: str
    execution_mode: Literal["demo", "agent"]
    max_runtime_seconds: int
    status: TaskStatus
    attempts: int
    worker_id: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    result: dict | None
    error: str | None


class TaskEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: UUID
    type: EventType
    attempt: int
    message: str
    data: dict
    created_at: datetime
