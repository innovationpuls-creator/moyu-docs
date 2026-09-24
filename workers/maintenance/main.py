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

from app_core.operations.task import CreateTask
from app_core.resource.purge import PurgeResource
from app_core.webhook.application import DeliverWebhook
from app_core.workspace.application.purge import PurgeWorkspace
from app_infra.postgres.audit.audit_repository import PostgresAuditRepository
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
from app_infra.postgres.search_repository import PostgresSearchRepository
from app_infra.postgres.task.effect_repository import PostgresTaskEffectRepository
from app_infra.postgres.task.task_repository import PostgresTaskRepository
from app_infra.postgres.webhook_repository import PostgresWebhookSubscriptionRepository
from app_infra.postgres.webhook_retention import PostgresWebhookRetention
from app_infra.postgres.webhook_transporter import PostgresWebhookTransporter
from app_infra.postgres.workspace_purge_repository import (
    PostgresWorkspacePurgeRepository,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from task_runtime.registry import HandlerRegistry, HandlerSpec
from task_runtime.runtime import WorkerHost

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


def build_registry(session: AsyncSession) -> HandlerRegistry:
    registry = HandlerRegistry()
    effects = PostgresTaskEffectRepository(session)
    journal = PostgresJournalRepository(session)
    checkpoints = PostgresCheckpointRepository(session)
    resources = PostgresResourceRepository(session)
    projects = PostgresProjectRepository(session)

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
                PurgeResource(PostgresResourcePurgeRepository(session)),
                effects,  # type: ignore[arg-type]
                audit=PostgresAuditRepository(session),
            ),
        )
    )
    webhook_handler = WebhookDeliverHandler(
        DeliverWebhook(
            PostgresWebhookSubscriptionRepository(session),
            PostgresWebhookTransporter(),
        )
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


async def sweep(session: AsyncSession) -> int:
    create = CreateTask(PostgresTaskRepository(session))
    async with session.begin():
        checkpoint = await PostgresResourceCheckpointEnqueuer(session, create).enqueue(
            threshold=1
        )
    async with session.begin():
        purge = await PostgresResourcePurgeEnqueuer(session, create).enqueue()
    async with session.begin():
        retained = await PostgresWebhookRetention(session).run()
    return checkpoint + purge + retained


async def run_daemon(
    session: AsyncSession,
    *,
    interval: float = 5.0,
    max_ticks: int | None = None,
) -> int:
    """Periodic scheduler daemon: claim cycles every `interval` seconds; with
    max_ticks (tests) it stops after that many claims."""
    worker = WorkerHost(
        PostgresTaskRepository(session),
        build_registry(session),
        worker_id="maintenance-daemon",
        heartbeat_seconds=60,
    )
    ticks = 0
    worked = 0
    while max_ticks is None or ticks < max_ticks:
        if await worker.run_once():
            worked += 1
        ticks += 1
        if max_ticks is None:
            await asyncio.sleep(interval)
    return worked


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
    session = factory()
    try:
        if args.daemon:
            await run_daemon(session, interval=args.interval)
            return
        if args.sweep:
            await sweep(session)
        worker = WorkerHost(
            PostgresTaskRepository(session),
            build_registry(session),
            worker_id="maintenance-dev",
            heartbeat_seconds=60,
        )
        await worker.run_once()
    finally:
        await session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
