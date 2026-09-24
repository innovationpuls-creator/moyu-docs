"""Create Permission-owned Workspace membership authority."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_kind", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "account_id", name="pk_workspace_members"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["core.workspaces.workspace_id"],
            name="fk_workspace_members_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["auth.accounts.account_id"],
            name="fk_workspace_members_account",
        ),
        sa.CheckConstraint(
            "membership_kind IN ('Owner', 'Member')", name="ck_workspace_members_kind"
        ),
        schema="core",
    )
    op.create_index(
        "uq_workspace_members_one_owner",
        "workspace_members",
        ["workspace_id"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("membership_kind = 'Owner'"),
    )
    op.create_index(
        "ix_workspace_members_account_kind_workspace",
        "workspace_members",
        ["account_id", "membership_kind", "workspace_id"],
        schema="core",
    )
    op.execute(
        """
        CREATE FUNCTION core.lock_workspace_membership_parent() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE target_workspace uuid;
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.workspace_id <> OLD.workspace_id THEN
                RAISE EXCEPTION 'Workspace membership cannot move between Workspaces'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_workspace_members_workspace_immutable';
            END IF;
            target_workspace := CASE
                WHEN TG_OP = 'DELETE' THEN OLD.workspace_id
                ELSE NEW.workspace_id
            END;
            PERFORM 1 FROM core.workspaces
             WHERE workspace_id = target_workspace FOR UPDATE;
            RETURN COALESCE(NEW, OLD);
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_workspace_membership_parent_lock
        BEFORE INSERT OR UPDATE OR DELETE ON core.workspace_members
        FOR EACH ROW EXECUTE FUNCTION core.lock_workspace_membership_parent()
        """
    )
    op.execute(
        """
        CREATE FUNCTION core.enforce_workspace_owner_invariant() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            target_workspace uuid;
            current_status text;
            owner_count bigint;
        BEGIN
            target_workspace := COALESCE(NEW.workspace_id, OLD.workspace_id);
            SELECT status INTO current_status FROM core.workspaces
             WHERE workspace_id = target_workspace FOR UPDATE;
            IF NOT FOUND OR current_status = 'Deleted' THEN
                RETURN NULL;
            END IF;
            SELECT count(*) INTO owner_count FROM core.workspace_members
             WHERE workspace_id = target_workspace AND membership_kind = 'Owner';
            IF owner_count <> 1 THEN
                RAISE EXCEPTION 'non-Deleted workspace must have exactly one Owner'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_workspace_exactly_one_owner';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_workspace_owner_membership_invariant
        AFTER INSERT OR UPDATE OR DELETE ON core.workspace_members
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION core.enforce_workspace_owner_invariant()
        """
    )
    op.execute(
        """
        CREATE FUNCTION core.lock_workspace_status_parent() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM 1 FROM core.workspaces
             WHERE workspace_id = NEW.workspace_id FOR UPDATE;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_workspace_status_parent_lock
        BEFORE UPDATE OF status ON core.workspaces
        FOR EACH ROW EXECUTE FUNCTION core.lock_workspace_status_parent()
        """
    )
    op.execute(
        """
        CREATE FUNCTION core.enforce_workspace_status_owner_invariant() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE owner_count bigint;
        BEGIN
            IF NEW.status <> 'Deleted' THEN
                SELECT count(*) INTO owner_count FROM core.workspace_members
                 WHERE workspace_id = NEW.workspace_id AND membership_kind = 'Owner';
                IF owner_count <> 1 THEN
                    RAISE EXCEPTION 'non-Deleted workspace must have exactly one Owner'
                        USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_workspace_exactly_one_owner';
                END IF;
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_workspace_status_owner_invariant
        AFTER INSERT OR UPDATE ON core.workspaces
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION core.enforce_workspace_status_owner_invariant()
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS core.uq_workspace_members_one_owner")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_workspace_membership_parent_lock "
        "ON core.workspace_members"
    )
    op.execute("DROP FUNCTION IF EXISTS core.lock_workspace_membership_parent()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_workspace_status_owner_invariant ON core.workspaces"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_workspace_status_parent_lock ON core.workspaces"
    )
    op.execute("DROP FUNCTION IF EXISTS core.lock_workspace_status_parent()")
    op.execute(
        "DROP FUNCTION IF EXISTS core.enforce_workspace_status_owner_invariant()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_workspace_owner_membership_invariant "
        "ON core.workspace_members"
    )
    op.execute("DROP FUNCTION IF EXISTS core.enforce_workspace_owner_invariant()")
    op.drop_index(
        "ix_workspace_members_account_kind_workspace",
        table_name="workspace_members",
        schema="core",
    )
    op.drop_table("workspace_members", schema="core")
