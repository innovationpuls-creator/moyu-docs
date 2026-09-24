"""Create generic asynchronous task runtime tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def _timestamp() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS work")
    op.create_table(
        "tasks",
        sa.Column("task_id", _uuid(), primary_key=True),
        sa.Column("task_type", sa.String(120), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(120)),
        sa.Column("priority", sa.String(32), nullable=False, server_default="Normal"),
        sa.Column("actor_account_id", _uuid()),
        sa.Column("workspace_id", _uuid()),
        sa.Column("resource_id", _uuid()),
        sa.Column("input_ref", sa.Text()),
        sa.Column("result_ref", sa.Text()),
        sa.Column("retry_of_task_id", _uuid()),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", _timestamp()),
        sa.Column("cancel_requested_at", _timestamp()),
        sa.Column(
            "created_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("queued_at", _timestamp()),
        sa.Column("started_at", _timestamp()),
        sa.Column("finished_at", _timestamp()),
        sa.Column("failure_code", sa.String(120)),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("current_attempt_id", _uuid()),
        sa.Column(
            "execution_epoch", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.CheckConstraint(
            "state IN ('Created','Queued','Running','WaitingForUser','Retrying',"
            "'Succeeded','PartialSucceeded','Failed','Cancelled')",
            name="ck_tasks_state",
        ),
        sa.CheckConstraint(
            "priority IN ('Interactive','Normal','Background','Maintenance')",
            name="ck_tasks_priority",
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["auth.accounts.account_id"], name="fk_tasks_actor"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["core.workspaces.workspace_id"],
            name="fk_tasks_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["retry_of_task_id"], ["work.tasks.task_id"], name="fk_tasks_retry_of"
        ),
        schema="work",
    )
    op.create_index(
        "ix_tasks_state_priority_next",
        "tasks",
        ["state", "priority", "next_attempt_at"],
        schema="work",
    )
    op.create_index(
        "ix_tasks_type_state", "tasks", ["task_type", "state"], schema="work"
    )
    op.create_index(
        "ix_tasks_workspace_state", "tasks", ["workspace_id", "state"], schema="work"
    )
    op.create_index("ix_tasks_created_at", "tasks", ["created_at"], schema="work")

    op.create_table(
        "task_attempts",
        sa.Column("attempt_id", _uuid(), primary_key=True),
        sa.Column("task_id", _uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(200), nullable=False),
        sa.Column("execution_epoch", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("claimed_at", _timestamp(), nullable=False),
        sa.Column("lease_until", _timestamp(), nullable=False),
        sa.Column("heartbeat_at", _timestamp(), nullable=False),
        sa.Column("finished_at", _timestamp()),
        sa.Column("error_code", sa.String(120)),
        sa.ForeignKeyConstraint(
            ["task_id"], ["work.tasks.task_id"], name="fk_task_attempts_task"
        ),
        sa.UniqueConstraint(
            "task_id", "attempt_number", name="uq_task_attempts_number"
        ),
        sa.CheckConstraint(
            "state IN ('Running','Succeeded','Failed','Cancelled')",
            name="ck_task_attempts_state",
        ),
        schema="work",
    )
    op.create_index(
        "ix_task_attempts_task", "task_attempts", ["task_id"], schema="work"
    )

    op.create_table(
        "task_effects",
        sa.Column("effect_id", _uuid(), primary_key=True),
        sa.Column("task_id", _uuid(), nullable=False),
        sa.Column("effect_key", sa.String(300), nullable=False),
        sa.Column("effect_type", sa.String(120), nullable=False),
        sa.Column("target_ref", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider_ref", sa.String(300)),
        sa.Column(
            "created_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", _timestamp()),
        sa.ForeignKeyConstraint(
            ["task_id"], ["work.tasks.task_id"], name="fk_task_effects_task"
        ),
        sa.UniqueConstraint("effect_key", name="uq_task_effects_key"),
        schema="work",
    )
    op.create_index("ix_task_effects_task", "task_effects", ["task_id"], schema="work")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE IF EXISTS work.tasks "
        "DROP CONSTRAINT IF EXISTS fk_tasks_current_attempt"
    )
    op.drop_index("ix_task_effects_task", table_name="task_effects", schema="work")
    op.drop_table("task_effects", schema="work")
    op.drop_index("ix_task_attempts_task", table_name="task_attempts", schema="work")
    op.drop_table("task_attempts", schema="work")
    op.drop_index("ix_tasks_created_at", table_name="tasks", schema="work")
    op.drop_index("ix_tasks_workspace_state", table_name="tasks", schema="work")
    op.drop_index("ix_tasks_type_state", table_name="tasks", schema="work")
    op.drop_index("ix_tasks_state_priority_next", table_name="tasks", schema="work")
    op.drop_table("tasks", schema="work")
    op.execute("DROP SCHEMA IF EXISTS work")
