from datetime import datetime
from uuid import UUID, uuid4

from agentos_core.contracts import TaskStatus
from sqlalchemy import CheckConstraint, DateTime, Enum, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.core.database import Base


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("length(trim(prompt)) > 0", name="ck_tasks_prompt_nonempty"),
        CheckConstraint("max_runtime_seconds BETWEEN 1 AND 86400", name="ck_tasks_runtime"),
        CheckConstraint("attempts >= 0", name="ck_tasks_attempts"),
        Index("ix_tasks_created_at_id", "created_at", "id"),
        Index("ix_tasks_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    prompt: Mapped[str] = mapped_column(Text)
    repository: Mapped[str] = mapped_column(Text)
    max_runtime_seconds: Mapped[int] = mapped_column(default=300, server_default="300")
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"), default=TaskStatus.QUEUED, server_default="QUEUED"
    )
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    worker_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
