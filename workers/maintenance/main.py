"""Maintenance worker runner (arch 25: task consumers as a process).

Assembles real infrastructure adapters into the task runtime and exposes
`run_once()` (one claim cycle) and `sweep()` (run the maintenance enqueuers,
then one claim cycle). The dev runner refuses to operate against non-isolated
databases: DATABASE_URL must target the guarded test database.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app_core.history.application import RestoreAtVersion
from app_core.import_export.application import (
    ExpireImportExportSessions,
    ExportResourceSnapshot,
)
from app_core.import_export.domain import EXPORT_TASK_TYPE, IMPORT_TASK_TYPE
from app_core.import_export.ports import TemporaryAssetStore
from app_core.operations.task import CreateTask
from app_core.resource.application import ImportResource
from app_core.resource.purge import PurgeResource
from app_core.webhook.application import DeliverWebhook
from app_core.webhook.ports import WebhookTransporter
from app_core.workspace.application.purge import PurgeWorkspace
from app_infra.postgres.audit.audit_repository import PostgresAuditRepository
from app_infra.postgres.history.history_repository import PostgresHistoryRepository
from app_infra.postgres.import_export_repository import (
    PostgresImportExportSessionRepository,
    PostgresResourceExportSnapshotRepository,
)
from app_infra.postgres.import_export_storage import (
    ImportExportTemporaryAssetStore,
    configured_asset_store,
)
from app_infra.postgres.ops_alerts import PostgresOpsAlerts
from app_infra.postgres.permission_resource_cleanup_repository import (
    PostgresPermissionResourceCleanupRepository,
)
from app_infra.postgres.permission_workspace_repository import (
    PostgresWorkspaceMembershipRepository,
)
from app_infra.postgres.project_repository import PostgresProjectRepository
from app_infra.postgres.resource.checkpoint_repository import (
    PostgresCheckpointRepository,
)
from app_infra.postgres.resource.journal_repository import PostgresJournalRepository
from app_infra.postgres.resource.resource_checkpoint_enqueuer import (
    PostgresResourceCheckpointEnqueuer,
)
from app_infra.postgres.resource.resource_purge_enqueuer import (
    PostgresResourcePurgeEnqueuer,
)
from app_infra.postgres.resource.resource_purge_repository import (
    PostgresResourcePurgeRepository,
)
from app_infra.postgres.resource.resource_repository import (
    PostgresResourceRepository,
)
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)
from app_infra.postgres.search_repository import PostgresSearchRepository
from app_infra.postgres.task.effect_repository import PostgresTaskEffectRepository
from app_infra.postgres.task.task_repository import PostgresTaskRepository
from app_infra.postgres.webhook_repository import (
    PostgresWebhookSubscriptionLoader,
    PostgresWebhookSubscriptionRepository,
)
from app_infra.postgres.webhook_retention import PostgresWebhookRetention
from app_infra.postgres.webhook_transporter import PostgresWebhookTransporter
from app_infra.postgres.workspace_purge_repository import (
    PostgresWorkspacePurgeRepository,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from task_runtime.registry import HandlerRegistry, HandlerSpec
from task_runtime.runtime import (
    TaskRuntimeRepository,
    WorkerExecutionScope,
    WorkerHost,
)

from workers.maintenance.task_handlers.history_restore import (
    TASK_TYPE as HISTORY_RESTORE_TASK_TYPE,
)
from workers.maintenance.task_handlers.history_restore import (
    HistoryRestoreHandler,
    apply_history_op,
)
from workers.maintenance.task_handlers.import_export import (
    ExportResourceTaskHandler,
    ImportResourceTaskHandler,
)
from workers.maintenance.task_handlers.lifecycle_purge import LifecyclePurgeHandler
from workers.maintenance.task_handlers.resource_checkpoint import (
    ResourceCheckpointHandler,
)
from workers.maintenance.task_handlers.resource_purge import ResourcePurgeHandler
from workers.maintenance.task_handlers.webhook_deliver import (
    TASK_TYPE as WEBHOOK_TASK_TYPE,
)
from workers.maintenance.task_handlers.webhook_deliver import WebhookDeliverHandler


def require_isolated(url: str) -> str:
    if not url.endswith("/dom_workspace_lifecycle_test"):
        raise RuntimeError(
            "maintenance worker dev runner requires the isolated test database"
        )
    return url


class _ExecutionTransaction:
    """Caller-owned transaction with a release/resume seam for external I/O."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._transaction: Any | None = None

    async def begin(self) -> None:
        self._transaction = await self._session.begin()

    async def release_before_external_io(self) -> None:
        transaction = self._transaction
        if transaction is not None and transaction.is_active:
            await transaction.commit()
        self._transaction = None

    async def resume_after_external_io(self) -> None:
        if self._transaction is None:
            self._transaction = await self._session.begin()

    async def commit(self) -> None:
        transaction = self._transaction
        if transaction is not None and transaction.is_active:
            await transaction.commit()
        self._transaction = None

    async def rollback(self) -> None:
        transaction = self._transaction
        if transaction is not None and transaction.is_active:
            await transaction.rollback()
        self._transaction = None


class _TransactionReleasingWebhookTransporter:
    def __init__(
        self,
        transporter: WebhookTransporter,
        transaction: _ExecutionTransaction,
    ) -> None:
        self._transporter = transporter
        self._transaction = transaction

    async def post(self, url: str, payload: bytes, headers: dict[str, str]) -> int:
        await self._transaction.release_before_external_io()
        try:
            return await self._transporter.post(url, payload, headers)
        finally:
            await self._transaction.resume_after_external_io()


class _TransactionReleasingTemporaryAssetStore:
    def __init__(
        self,
        store: TemporaryAssetStore,
        transaction: _ExecutionTransaction,
    ) -> None:
        self._store = store
        self._transaction = transaction

    async def put_import_source(self, asset_id: UUID, data: bytes) -> None:
        await self._run(self._store.put_import_source, asset_id, data)

    async def get_import_source(self, asset_id: UUID) -> bytes:
        return await self._run(self._store.get_import_source, asset_id)

    async def delete_import_source(self, asset_id: UUID) -> None:
        await self._run(self._store.delete_import_source, asset_id)

    async def put_export_result(self, asset_id: UUID, data: bytes) -> None:
        await self._run(self._store.put_export_result, asset_id, data)

    async def get_export_result(self, asset_id: UUID) -> bytes:
        return await self._run(self._store.get_export_result, asset_id)

    async def delete_export_result(self, asset_id: UUID) -> None:
        await self._run(self._store.delete_export_result, asset_id)

    async def _run(self, operation: Any, *args: Any) -> Any:
        await self._transaction.release_before_external_io()
        try:
            return await operation(*args)
        finally:
            await self._transaction.resume_after_external_io()


def build_registry(
    session: AsyncSession,
    *,
    webhook_session_factory: async_sessionmaker[AsyncSession] | None = None,
    execution_transaction: _ExecutionTransaction | None = None,
    temporary_assets: TemporaryAssetStore | None = None,
) -> HandlerRegistry:
    registry = HandlerRegistry()
    effects = PostgresTaskEffectRepository(session)
    journal = PostgresJournalRepository(session)
    checkpoints = PostgresCheckpointRepository(session)
    resources = PostgresResourceRepository(session)
    projects = PostgresProjectRepository(session)
    ownership = PostgresResourceOwnershipRepository(session)
    import_export_sessions = PostgresImportExportSessionRepository(session)
    temporary_assets = temporary_assets or ImportExportTemporaryAssetStore(
        configured_asset_store()
    )
    if execution_transaction is not None:
        temporary_assets = _TransactionReleasingTemporaryAssetStore(
            temporary_assets, execution_transaction
        )

    registry.register(
        HandlerSpec(
            "resource.checkpoint",
            ResourceCheckpointHandler(
                journal,
                checkpoints,
                effects,  # type: ignore[arg-type]
                search_index=PostgresSearchRepository(session),
                resources=resources,
                projects=projects,
            ),
        )
    )
    registry.register(
        HandlerSpec(
            "resource.purge",
            ResourcePurgeHandler(
                PurgeResource(
                    PostgresResourcePurgeRepository(
                        session, PostgresPermissionResourceCleanupRepository(session)
                    )
                ),
                effects,  # type: ignore[arg-type]
                audit=PostgresAuditRepository(session),
            ),
        )
    )
    registry.register(
        HandlerSpec(
            HISTORY_RESTORE_TASK_TYPE,
            HistoryRestoreHandler(
                resources,
                ownership,
                journal,
                RestoreAtVersion(
                    PostgresHistoryRepository(session),
                    resources,
                    journal,
                    checkpoints,
                    apply_history_op,
                ),
            ),
        )
    )
    registry.register(
        HandlerSpec(
            IMPORT_TASK_TYPE,
            ImportResourceTaskHandler(
                import_export_sessions,
                temporary_assets,
                resources,
                projects,
                ownership,
                ImportResource(resources, journal, checkpoints, ownership),
            ),
        )
    )
    registry.register(
        HandlerSpec(
            EXPORT_TASK_TYPE,
            ExportResourceTaskHandler(
                import_export_sessions,
                temporary_assets,
                resources,
                projects,
                ownership,
                ExportResourceSnapshot(
                    PostgresResourceExportSnapshotRepository(session), ownership
                ),
            ),
        )
    )
    webhook_loader = (
        PostgresWebhookSubscriptionLoader(webhook_session_factory)
        if webhook_session_factory is not None
        else PostgresWebhookSubscriptionRepository(session)
    )
    webhook_transporter: WebhookTransporter = PostgresWebhookTransporter()
    if execution_transaction is not None:
        webhook_transporter = _TransactionReleasingWebhookTransporter(
            webhook_transporter, execution_transaction
        )
    webhook_handler = WebhookDeliverHandler(
        DeliverWebhook(webhook_loader, webhook_transporter)
    )
    registry.register(
        HandlerSpec(
            WEBHOOK_TASK_TYPE,
            webhook_handler,
        )
    )
    registry.register(
        HandlerSpec(
            "lifecycle.purge",
            LifecyclePurgeHandler(
                PurgeWorkspace(
                    PostgresWorkspacePurgeRepository(
                        session, PostgresWorkspaceMembershipRepository(session)
                    ),
                    PostgresWorkspaceMembershipRepository(session),
                ),
                effects,  # type: ignore[arg-type]
            ),
        )
    )
    return registry


class _TransactionalTaskRepository:
    """Open and commit one short session per runtime control operation."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        async with self._factory() as session:
            async with session.begin():
                repository = PostgresTaskRepository(session)
                return await getattr(repository, method)(*args, **kwargs)

    async def claim_next(self, worker_id: str, lease_seconds: int) -> Any | None:
        return await self._call("claim_next", worker_id, lease_seconds)

    async def get(self, task_id: UUID) -> Any | None:
        return await self._call("get", task_id)

    async def heartbeat(
        self, task_id: UUID, attempt_id: UUID, epoch: int, lease_seconds: int
    ) -> bool:
        return await self._call("heartbeat", task_id, attempt_id, epoch, lease_seconds)

    async def finish(
        self,
        task_id: UUID,
        attempt_id: UUID,
        epoch: int,
        succeeded: bool,
        *,
        failure_code: str | None = None,
    ) -> None:
        await self._call(
            "finish",
            task_id,
            attempt_id,
            epoch,
            succeeded,
            failure_code=failure_code,
        )

    async def finish_cancelled(
        self, task_id: UUID, attempt_id: UUID, epoch: int
    ) -> None:
        await self._call("finish_cancelled", task_id, attempt_id, epoch)

    async def update_progress(
        self,
        task_id: UUID,
        attempt_id: UUID,
        execution_epoch: int,
        *,
        stage: str | None,
        message_code: str | None,
        current: int | None,
        total: int | None,
        percentage: Decimal | None,
    ) -> None:
        await self._call(
            "update_progress",
            task_id,
            attempt_id,
            execution_epoch,
            stage=stage,
            message_code=message_code,
            current=current,
            total=total,
            percentage=percentage,
        )

    async def schedule_retry(
        self, task_id: UUID, next_attempt_at: datetime, failure_code: str
    ) -> None:
        await self._call("schedule_retry", task_id, next_attempt_at, failure_code)

    async def find_expired_leases(self, now: datetime) -> list[UUID]:
        return await self._call("find_expired_leases", now)

    async def release_for_recovery(
        self, task_id: UUID, attempt_id: UUID, epoch: int
    ) -> None:
        await self._call("release_for_recovery", task_id, attempt_id, epoch)


@dataclass
class _MaintenanceExecutionScope:
    repository: TaskRuntimeRepository
    registry: HandlerRegistry


@asynccontextmanager
async def _execution_scope(
    factory: async_sessionmaker[AsyncSession],
    temporary_assets: TemporaryAssetStore | None = None,
) -> AsyncIterator[WorkerExecutionScope]:
    async with factory() as session:
        transaction = _ExecutionTransaction(session)
        await transaction.begin()
        try:
            yield _MaintenanceExecutionScope(
                repository=PostgresTaskRepository(session),
                registry=build_registry(
                    session,
                    webhook_session_factory=factory,
                    execution_transaction=transaction,
                    temporary_assets=temporary_assets,
                ),
            )
            await transaction.commit()
        except BaseException:
            await transaction.rollback()
            raise


def _build_worker(
    factory: async_sessionmaker[AsyncSession],
    worker_id: str,
    temporary_assets: TemporaryAssetStore | None = None,
) -> WorkerHost:
    return WorkerHost(
        _TransactionalTaskRepository(factory),
        HandlerRegistry(),  # Handlers are assembled against the execution session.
        worker_id=worker_id,
        heartbeat_seconds=10,
        execution_scope_factory=lambda: _execution_scope(factory, temporary_assets),
    )


async def cleanup_import_export_sessions(
    session: AsyncSession,
    temporary_assets: TemporaryAssetStore | None = None,
) -> int:
    transaction = _ExecutionTransaction(session)
    await transaction.begin()
    try:
        storage = temporary_assets or ImportExportTemporaryAssetStore(
            configured_asset_store()
        )
        cleaned = await ExpireImportExportSessions(
            PostgresImportExportSessionRepository(session),
            _TransactionReleasingTemporaryAssetStore(storage, transaction),
        ).execute()
        await transaction.commit()
        return cleaned
    except BaseException:
        await transaction.rollback()
        raise


async def sweep(
    session: AsyncSession,
    temporary_assets: TemporaryAssetStore | None = None,
) -> int:
    create = CreateTask(PostgresTaskRepository(session))
    async with session.begin():
        checkpoint = await PostgresResourceCheckpointEnqueuer(session, create).enqueue(
            threshold=1
        )
    async with session.begin():
        purge = await PostgresResourcePurgeEnqueuer(session, create).enqueue()
    async with session.begin():
        retained = await PostgresWebhookRetention(session).run()
    async with session.begin():
        alerts = await PostgresOpsAlerts(session).evaluate()
    cleaned = await cleanup_import_export_sessions(session, temporary_assets)
    return checkpoint + purge + retained + len(alerts) + cleaned


async def run_daemon(
    factory: async_sessionmaker[AsyncSession],
    *,
    interval: float = 5.0,
    max_ticks: int | None = None,
    temporary_assets: TemporaryAssetStore | None = None,
) -> int:
    """Periodic scheduler daemon: claim cycles every `interval` seconds; with
    max_ticks (tests) it stops after that many claims."""
    worker = _build_worker(factory, "maintenance-daemon", temporary_assets)
    ticks = 0
    worked = 0
    next_retention = 0.0
    while max_ticks is None or ticks < max_ticks:
        if time.monotonic() >= next_retention:
            async with factory() as session:
                await cleanup_import_export_sessions(session, temporary_assets)
            next_retention = time.monotonic() + 60
        if await worker.run_once():
            worked += 1
        ticks += 1
        if max_ticks is None:
            await asyncio.sleep(interval)
    return worked


async def run_once(
    factory: async_sessionmaker[AsyncSession], *, worker_id: str = "maintenance-dev"
) -> bool:
    """Run one claim through production transaction/session boundaries."""
    return await _build_worker(factory, worker_id).run_once()


async def _main() -> None:
    parser = argparse.ArgumentParser(description="DOM maintenance worker")
    parser.add_argument("--once", action="store_true", help="run one claim cycle")
    parser.add_argument("--sweep", action="store_true", help="enqueue, then one cycle")
    parser.add_argument("--daemon", action="store_true", help="periodic claim loop")
    parser.add_argument("--interval", type=float, default=5.0, help="claim interval")
    args = parser.parse_args()
    url = require_isolated(os.environ.get("DATABASE_URL", ""))
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        if args.daemon:
            temporary_assets = ImportExportTemporaryAssetStore(configured_asset_store())
            await run_daemon(
                factory,
                interval=args.interval,
                temporary_assets=temporary_assets,
            )
            return
        if args.sweep:
            async with factory() as session:
                temporary_assets = ImportExportTemporaryAssetStore(
                    configured_asset_store()
                )
                await sweep(session, temporary_assets)
        await run_once(factory)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
