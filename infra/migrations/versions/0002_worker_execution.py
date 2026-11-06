"""Add durable dispatch, execution results, and task events."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tasks",
        sa.Column(
            "dispatch_after",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column("tasks", sa.Column("execution_token", sa.Uuid(), nullable=True))
    op.add_column("tasks", sa.Column("result", postgresql.JSONB(), nullable=True))
    op.add_column("tasks", sa.Column("error", sa.Text(), nullable=True))
    op.create_index("ix_tasks_status_dispatch_after", "tasks", ["status", "dispatch_after"])
    op.create_table(
        "task_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id", sa.Uuid(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_task_events_task_id_id", "task_events", ["task_id", "id"])
    # Preserve existing tasks and make their original submission visible in history.
    op.execute(
        """INSERT INTO task_events (task_id, type, attempt, message, data, created_at)
        SELECT id, 'QUEUED', 0, 'Task accepted (history backfilled during migration)',
               '{}'::jsonb, created_at
        FROM tasks WHERE status = 'QUEUED' ORDER BY created_at, id"""
    )


def downgrade():
    op.drop_table("task_events")
    op.drop_index("ix_tasks_status_dispatch_after", table_name="tasks")
    op.drop_column("tasks", "error")
    op.drop_column("tasks", "result")
    op.drop_column("tasks", "execution_token")
    op.drop_column("tasks", "dispatch_after")
