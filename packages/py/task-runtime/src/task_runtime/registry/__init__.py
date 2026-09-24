from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from task_runtime.domain import RetryPolicy


class UnknownTaskTypeError(LookupError):
    pass


class UnsupportedTaskVersionError(ValueError):
    pass


class TaskHandler(Protocol):
    async def execute(self, context: Any) -> Any: ...


@dataclass(frozen=True)
class HandlerSpec:
    task_type: str
    handler: TaskHandler
    handler_version: str = "1.0.0"
    schema_version: str = "1.0.0"
    retry_policy: RetryPolicy = RetryPolicy()
    priority_hint: str = "Normal"
    cancellable: bool = True


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, HandlerSpec] = {}

    def register(self, spec: HandlerSpec) -> None:
        self._handlers[spec.task_type] = spec

    def resolve(self, task_type: str, schema_version: str) -> HandlerSpec:
        spec = self._handlers.get(task_type)
        if spec is None:
            raise UnknownTaskTypeError(task_type)
        if spec.schema_version != schema_version:
            raise UnsupportedTaskVersionError(
                f"{task_type}: expected {spec.schema_version}, got {schema_version}"
            )
        return spec

    def __contains__(self, task_type: str) -> bool:
        return task_type in self._handlers
