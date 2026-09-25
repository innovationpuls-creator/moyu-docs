"""Add Permission-owned member, project, resource and invitation state."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_members",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("membership_kind", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("project_id", "account_id"),
        sa.ForeignKeyConstraint(["project_id"], ["core.projects.project_id"]),
        sa.ForeignKeyConstraint(["account_id"], ["auth.accounts.account_id"]),
        sa.CheckConstraint(
            "role IN ('Owner', 'Manage', 'Edit', 'Comment', 'Read')",
            name="ck_project_members_role",
        ),
        sa.CheckConstraint(
            "membership_kind IN ('Owner', 'Member')",
            name="ck_project_members_kind",
        ),
        sa.CheckConstraint(
            "(role = 'Owner') = (membership_kind = 'Owner')",
            name="ck_project_members_role_kind",
        ),
        schema="core",
    )
    op.create_index(
        "ix_project_members_account_project",
        "project_members",
        ["account_id", "project_id"],
        schema="core",
    )

    op.create_table(
        "resource_permissions",
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("resource_id", "account_id"),
        sa.ForeignKeyConstraint(["resource_id"], ["core.resources.resource_id"]),
        sa.ForeignKeyConstraint(["account_id"], ["auth.accounts.account_id"]),
        sa.CheckConstraint(
            "role IN ('Owner', 'Manage', 'Edit', 'Comment', 'Read')",
            name="ck_resource_permissions_role",
        ),
        schema="core",
    )
    op.create_index(
        "ix_resource_permissions_account_resource",
        "resource_permissions",
        ["account_id", "resource_id"],
        schema="core",
    )

    op.create_table(
        "invitations",
        sa.Column("invitation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_email", sa.String(255), nullable=False),
        sa.Column("target_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="Pending"),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["core.workspaces.workspace_id"]),
        sa.ForeignKeyConstraint(["project_id"], ["core.projects.project_id"]),
        sa.ForeignKeyConstraint(["resource_id"], ["core.resources.resource_id"]),
        sa.ForeignKeyConstraint(["target_account_id"], ["auth.accounts.account_id"]),
        sa.ForeignKeyConstraint(["created_by"], ["auth.accounts.account_id"]),
        sa.CheckConstraint(
            "state IN ('Pending', 'Accepted', 'Expired', 'Revoked')",
            name="ck_invitations_state",
        ),
        sa.CheckConstraint(
            "role IN ('Member', 'Owner', 'Manage', 'Edit', 'Comment', 'Read')",
            name="ck_invitations_role",
        ),
        sa.CheckConstraint(
            "project_id IS NULL OR resource_id IS NULL",
            name="ck_invitations_one_scope",
        ),
        sa.CheckConstraint(
            "(project_id IS NULL AND resource_id IS NULL AND role = 'Member') OR "
            "((project_id IS NOT NULL OR resource_id IS NOT NULL) AND "
            "role IN ('Owner', 'Manage', 'Edit', 'Comment', 'Read'))",
            name="ck_invitations_scope_role",
        ),
        sa.CheckConstraint(
            "(state = 'Accepted') = (accepted_at IS NOT NULL)",
            name="ck_invitations_accepted_at",
        ),
        sa.CheckConstraint(
            "(state = 'Revoked') = (revoked_at IS NOT NULL)",
            name="ck_invitations_revoked_at",
        ),
        schema="core",
    )
    op.create_index(
        "ix_invitations_workspace_state_expiry",
        "invitations",
        ["workspace_id", "state", "expires_at"],
        schema="core",
    )
    op.create_index(
        "uq_invitations_pending_workspace_email",
        "invitations",
        ["workspace_id", "target_email"],
        unique=True,
        schema="core",
        postgresql_where=sa.text(
            "state = 'Pending' AND project_id IS NULL AND resource_id IS NULL"
        ),
    )

    op.execute(
        """
        INSERT INTO core.project_members
            (project_id, account_id, role, membership_kind)
        SELECT p.project_id, COALESCE(active_creator.account_id, owner.account_id),
               'Owner', 'Owner'
          FROM core.projects AS p
          JOIN core.workspace_members AS owner
            ON owner.workspace_id = p.workspace_id
           AND owner.membership_kind = 'Owner'
          LEFT JOIN auth.accounts AS active_creator
            ON active_creator.account_id = p.created_by
           AND active_creator.status = 'Active'
        ON CONFLICT (project_id, account_id) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE FUNCTION core.lock_project_membership_parent() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE target_project uuid;
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.project_id <> OLD.project_id THEN
                RAISE EXCEPTION 'Project membership cannot move between Projects'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_project_members_project_immutable';
            END IF;
            target_project := CASE WHEN TG_OP = 'DELETE' THEN OLD.project_id
                                   ELSE NEW.project_id END;
            PERFORM 1 FROM core.projects
             WHERE project_id = target_project FOR UPDATE;
            RETURN COALESCE(NEW, OLD);
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_project_membership_parent_lock
        BEFORE INSERT OR UPDATE OR DELETE ON core.project_members
        FOR EACH ROW EXECUTE FUNCTION core.lock_project_membership_parent()
        """
    )
    op.execute(
        """
        CREATE FUNCTION core.enforce_project_owner_invariant() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE target_project uuid;
        DECLARE owner_count bigint;
        BEGIN
            target_project := COALESCE(NEW.project_id, OLD.project_id);
            PERFORM 1 FROM core.projects
             WHERE project_id = target_project FOR UPDATE;
            IF NOT FOUND THEN RETURN NULL; END IF;
            SELECT count(*) INTO owner_count FROM core.project_members
             WHERE project_id = target_project AND role = 'Owner';
            IF owner_count < 1 THEN
                RAISE EXCEPTION 'Project must have at least one Owner'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_project_members_at_least_one_owner';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_project_owner_membership_invariant
        AFTER INSERT OR UPDATE OR DELETE ON core.project_members
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION core.enforce_project_owner_invariant()
        """
    )
    op.execute(
        """
        CREATE FUNCTION core.seed_initial_project_owner() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE initial_owner uuid;
        BEGIN
            SELECT account_id INTO initial_owner FROM auth.accounts
             WHERE account_id = NEW.created_by AND status = 'Active';
            IF initial_owner IS NULL THEN
                SELECT account_id INTO initial_owner FROM core.workspace_members
                 WHERE workspace_id = NEW.workspace_id
                   AND membership_kind = 'Owner';
            END IF;
            IF initial_owner IS NULL THEN
                RAISE EXCEPTION 'New Project requires an active initial Owner'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_project_members_initial_owner';
            END IF;
            INSERT INTO core.project_members
                (project_id, account_id, role, membership_kind)
            VALUES (NEW.project_id, initial_owner, 'Owner', 'Owner');
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_projects_seed_initial_owner
        AFTER INSERT ON core.projects
        FOR EACH ROW EXECUTE FUNCTION core.seed_initial_project_owner()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_projects_seed_initial_owner ON core.projects"
    )
    op.execute("DROP FUNCTION IF EXISTS core.seed_initial_project_owner()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_project_owner_membership_invariant "
        "ON core.project_members"
    )
    op.execute("DROP FUNCTION IF EXISTS core.enforce_project_owner_invariant()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_project_membership_parent_lock "
        "ON core.project_members"
    )
    op.execute("DROP FUNCTION IF EXISTS core.lock_project_membership_parent()")
    op.drop_index(
        "uq_invitations_pending_workspace_email",
        table_name="invitations",
        schema="core",
    )
    op.drop_index(
        "ix_invitations_workspace_state_expiry",
        table_name="invitations",
        schema="core",
    )
    op.drop_table("invitations", schema="core")
    op.drop_index(
        "ix_resource_permissions_account_resource",
        table_name="resource_permissions",
        schema="core",
    )
    op.drop_table("resource_permissions", schema="core")
    op.drop_index(
        "ix_project_members_account_project",
        table_name="project_members",
        schema="core",
    )
    op.drop_table("project_members", schema="core")
