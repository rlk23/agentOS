"""Distinguish demo tasks from isolated coding-agent tasks."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tasks", sa.Column("execution_mode", sa.String(16), nullable=False, server_default="demo")
    )
    op.create_check_constraint(
        "ck_tasks_execution_mode", "tasks", "execution_mode IN ('demo', 'agent')"
    )


def downgrade():
    op.drop_constraint("ck_tasks_execution_mode", "tasks", type_="check")
    op.drop_column("tasks", "execution_mode")
