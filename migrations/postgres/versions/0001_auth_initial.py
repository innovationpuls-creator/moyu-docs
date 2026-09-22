"""Create initial auth, audit, and integration schemas."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def _timestamp() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")
    op.execute("CREATE SCHEMA IF NOT EXISTS audit")
    op.execute("CREATE SCHEMA IF NOT EXISTS integration")

    op.create_table(
        "accounts",
        sa.Column("account_id", _uuid(), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("primary_email", sa.String(255)),
        sa.Column("normalized_email", sa.String(255)),
        sa.Column("email_verified_at", _timestamp()),
        sa.Column("auth_epoch", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("deletion_requested_at", _timestamp()),
        sa.Column("pre_deletion_status", sa.String(32)),
        sa.Column(
            "created_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        schema="auth",
    )
    op.create_index(
        "ix_accounts_normalized_email",
        "accounts",
        ["normalized_email"],
        unique=True,
        schema="auth",
    )

    op.create_table(
        "identities",
        sa.Column("identity_id", _uuid(), primary_key=True),
        sa.Column(
            "account_id",
            _uuid(),
            sa.ForeignKey("auth.accounts.account_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_subject", sa.String(255), nullable=False),
        sa.Column("provider_email", sa.String(255)),
        sa.Column(
            "created_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_used_at", _timestamp()),
        sa.UniqueConstraint(
            "provider", "provider_subject", name="uq_identities_provider_subject"
        ),
        schema="auth",
    )

    op.create_table(
        "password_credentials",
        sa.Column(
            "account_id",
            _uuid(),
            sa.ForeignKey("auth.accounts.account_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "algorithm_version",
            sa.String(32),
            nullable=False,
            server_default="argon2id_v1",
        ),
        sa.Column(
            "password_changed_at",
            _timestamp(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="auth",
    )

    op.create_table(
        "sessions",
        sa.Column("session_id", _uuid(), primary_key=True),
        sa.Column(
            "account_id",
            _uuid(),
            sa.ForeignKey("auth.accounts.account_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "session_version", sa.BigInteger(), nullable=False, server_default="1"
        ),
        sa.Column(
            "last_strong_auth_at",
            _timestamp(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "last_seen_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", _timestamp(), nullable=False),
        sa.Column("replaced_at", _timestamp()),
        sa.Column("replaced_by_session_id", _uuid()),
        sa.Column("invalidation_reason", sa.String(64)),
        schema="auth",
    )
    op.create_index(
        "ix_sessions_account_status",
        "sessions",
        ["account_id", "status"],
        schema="auth",
    )
    op.create_index(
        "ix_sessions_account_created",
        "sessions",
        ["account_id", "created_at"],
        schema="auth",
    )

    op.create_table(
        "one_time_tokens",
        sa.Column("token_id", _uuid(), primary_key=True),
        sa.Column(
            "account_id",
            _uuid(),
            sa.ForeignKey("auth.accounts.account_id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("token_type", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", _timestamp(), nullable=False),
        sa.Column("consumed_at", _timestamp()),
        sa.Column(
            "created_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        schema="auth",
    )
    op.create_index("ix_tokens_hash", "one_time_tokens", ["token_hash"], schema="auth")

    op.create_table(
        "account_deletion_requests",
        sa.Column(
            "account_id",
            _uuid(),
            sa.ForeignKey("auth.accounts.account_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column(
            "requested_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("execute_after", _timestamp(), nullable=False),
        sa.Column("cancelled_at", _timestamp()),
        sa.Column("completed_at", _timestamp()),
        schema="auth",
    )

    op.create_table(
        "entries",
        sa.Column("audit_id", _uuid(), primary_key=True),
        sa.Column(
            "occurred_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", _uuid()),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("workspace_id", _uuid()),
        sa.Column("project_id", _uuid()),
        sa.Column("resource_id", _uuid()),
        sa.Column("target_ref", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("request_id", _uuid()),
        sa.Column("trace_id", sa.String(128)),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text())),
        schema="audit",
    )

    op.create_table(
        "outbox_events",
        sa.Column("outbox_id", _uuid(), primary_key=True),
        sa.Column("event_id", _uuid(), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", _uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trace_id", sa.String(128)),
        sa.Column(
            "created_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("published_at", _timestamp()),
        sa.Column("publish_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("event_id", name="uq_outbox_events_event_id"),
        schema="integration",
    )
    op.create_table(
        "idempotency_records",
        sa.Column("idempotency_key", sa.String(255), primary_key=True),
        sa.Column("response", sa.Text()),
        sa.Column(
            "created_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        schema="integration",
    )

    op.create_index(
        "ix_outbox_events_unpublished",
        "outbox_events",
        ["created_at"],
        schema="integration",
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbox_events_unpublished",
        table_name="outbox_events",
        schema="integration",
    )
    op.execute("DROP TABLE IF EXISTS integration.idempotency_records")
    op.drop_table("outbox_events", schema="integration")
    op.drop_table("entries", schema="audit")
    op.drop_table("account_deletion_requests", schema="auth")
    op.drop_index("ix_tokens_hash", table_name="one_time_tokens", schema="auth")
    op.drop_table("one_time_tokens", schema="auth")
    op.drop_index("ix_sessions_account_created", table_name="sessions", schema="auth")
    op.drop_index("ix_sessions_account_status", table_name="sessions", schema="auth")
    op.drop_table("sessions", schema="auth")
    op.drop_table("password_credentials", schema="auth")
    op.drop_table("identities", schema="auth")
    op.drop_index("ix_accounts_normalized_email", table_name="accounts", schema="auth")
    op.drop_table("accounts", schema="auth")
    op.execute("DROP SCHEMA IF EXISTS integration")
    op.execute("DROP SCHEMA IF EXISTS audit")
    op.execute("DROP SCHEMA IF EXISTS auth")
