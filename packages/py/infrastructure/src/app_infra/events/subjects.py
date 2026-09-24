"""Canonical event subjects (arch 04, doc 28 §25): single code-side source of
truth mirrored from contracts/registry.yaml. Publishers must use these
constants; the drift guard test pins registry <-> code equality."""

EVENT_SUBJECTS: dict[str, str] = {
    "workspace.created": "event.workspace.created.v1",
    "workspace.project-archived": "event.workspace.project-archived.v1",
    "workspace.project-unarchived": "event.workspace.project-unarchived.v1",
    "workspace.project-trashed": "event.workspace.project-trashed.v1",
    "workspace.project-restored": "event.workspace.project-restored.v1",
    "workspace.folder-created": "event.workspace.folder-created.v1",
    "workspace.folder-renamed": "event.workspace.folder-renamed.v1",
    "workspace.folder-moved": "event.workspace.folder-moved.v1",
    "workspace.folder-trashed": "event.workspace.folder-trashed.v1",
    "workspace.folder-restored": "event.workspace.folder-restored.v1",
    "auth.session-replaced": "event.auth.session-replaced.v1",
    "resource.checkpoint": "resource.checkpoint",
    "rt.broadcast": "rt.broadcast",
}

RESERVED_PREFIXES: tuple[str, ...] = (
    "event.",
    "rt.broadcast",
    "resource.checkpoint",
    "work.",
)
