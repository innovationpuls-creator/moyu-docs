from __future__ import annotations

from uuid import UUID, uuid4

from app_core.history.domain import NamedVersion, VersionKind, VersionNode
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresHistoryRepository:
    """Merged history view: checkpoints (auto/restore) + named versions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_nodes(
        self, resource_id: UUID, *, limit: int = 100
    ) -> list[VersionNode]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT * FROM ("
                        "SELECT c.base_journal_seq AS ord, c.resource_id, "
                        "'Checkpoint' AS src, c.base_journal_seq, c.created_at, "
                        "NULL::varchar AS label, c.created_by, "
                        "(SELECT update_bytes FROM collab.resource_update_journal j "
                        "WHERE j.resource_id=c.resource_id "
                        "AND j.journal_seq=c.base_journal_seq LIMIT 1) AS op_bytes, "
                        "(SELECT mutation_kind FROM "
                        "collab.resource_update_journal j "
                        "WHERE j.resource_id=c.resource_id AND "
                        "j.journal_seq=c.base_journal_seq LIMIT 1) AS mutation_kind, "
                        "(SELECT restore_target_seq FROM "
                        "collab.resource_update_journal j "
                        "WHERE j.resource_id=c.resource_id AND "
                        "j.journal_seq=c.base_journal_seq LIMIT 1) AS "
                        "restore_target_seq "
                        "FROM collab.resource_checkpoints c "
                        "WHERE c.resource_id=:rid "
                        "UNION ALL "
                        "SELECT n.base_journal_seq AS ord, n.resource_id, "
                        "'Named' AS src, n.base_journal_seq, n.created_at, "
                        "n.label, n.created_by, NULL::bytea, NULL::varchar, "
                        "NULL::bigint "
                        "FROM collab.resource_named_versions n "
                        "WHERE n.resource_id=:rid"
                        ") merged ORDER BY ord DESC LIMIT :lim"
                    ),
                    {"rid": resource_id, "lim": limit},
                )
            )
            .mappings()
            .all()
        )
        nodes: list[VersionNode] = []
        for row in rows:
            kind = (
                VersionKind.NAMED
                if row["src"] == "Named"
                else (
                    VersionKind.RESTORE
                    if row["mutation_kind"] == "history-restore"
                    or (
                        row["op_bytes"] is not None
                        and bytes(row["op_bytes"]).startswith(b"restore@")
                    )
                    else VersionKind.AUTOMATIC
                )
            )
            nodes.append(
                VersionNode(
                    node_id=uuid4(),
                    resource_id=row["resource_id"],
                    kind=kind,
                    label=(
                        f"restore to v{row['restore_target_seq']}"
                        if row["mutation_kind"] == "history-restore"
                        and row["restore_target_seq"] is not None
                        else row["label"]
                    ),
                    author=row["created_by"],
                    occurred_at=row["created_at"],
                    base_journal_seq=row["base_journal_seq"],
                )
            )
        return nodes

    async def create_named_version(
        self,
        resource_id: UUID,
        label: str,
        base_journal_seq: int,
        created_by: UUID | None,
    ) -> NamedVersion:
        version_id = uuid4()
        row = (
            (
                await self._session.execute(
                    text(
                        "INSERT INTO collab.resource_named_versions "
                        "(version_id,resource_id,label,base_journal_seq,created_by) "
                        "VALUES (:vid,:rid,:label,:seq,:by) RETURNING *"
                    ),
                    {
                        "vid": version_id,
                        "rid": resource_id,
                        "label": label,
                        "seq": base_journal_seq,
                        "by": created_by,
                    },
                )
            )
            .mappings()
            .one()
        )
        return NamedVersion(
            version_id=row["version_id"],
            resource_id=row["resource_id"],
            label=row["label"],
            base_journal_seq=row["base_journal_seq"],
            created_by=row["created_by"],
            created_at=row["created_at"],
        )

    async def named_label_exists(self, resource_id: UUID, label: str) -> bool:
        value = await self._session.scalar(
            text(
                "SELECT 1 FROM collab.resource_named_versions "
                "WHERE resource_id=:rid AND label=:label LIMIT 1"
            ),
            {"rid": resource_id, "label": label},
        )
        return value is not None
