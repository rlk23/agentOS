"""Create durable tasks.

Revision ID: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

task_status = sa.Enum(
    "QUEUED",
    "RUNNING",
    "RETRY_WAIT",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
    "TIMED_OUT",
    name="task_status",
)


def upgrade():
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("repository", sa.Text(), nullable=False),
        sa.Column("max_runtime_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("status", task_status, nullable=False, server_default="QUEUED"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("worker_id", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(trim(prompt)) > 0", name="ck_tasks_prompt_nonempty"),
        sa.CheckConstraint("max_runtime_seconds BETWEEN 1 AND 86400", name="ck_tasks_runtime"),
        sa.CheckConstraint("attempts >= 0", name="ck_tasks_attempts"),
    )
    op.create_index("ix_tasks_created_at_id", "tasks", ["created_at", "id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])


def downgrade():
    op.drop_table("tasks")
    task_status.drop(op.get_bind(), checkfirst=True)
