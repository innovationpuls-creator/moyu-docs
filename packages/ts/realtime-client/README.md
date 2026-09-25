# Realtime Client

This package owns the browser WebSocket connection and Resource subscriptions. Features use `ResourceRealtimeClient`; they do not create sockets or construct routing frames.

`subscribeResource(resourceId, handlers)` subscribes to one Resource. The client routes binary Yjs updates and typed roster/Awareness events to that subscription. `onResourceEvent(resourceId, listener)` observes registered comment event frames for that Resource without creating another socket or replacing its Yjs subscription. `publishAwareness(resourceId, { cursor })` sends only the current selection offsets; the server supplies participant identity and presentation metadata. The cursor is ephemeral and is not document content.

Awareness events are delivered as `update` or `remove`. An update includes the server-issued `participantId`, display name, stable color, and latest cursor. A `remove` event identifies the participant to clear from the editor. Reconnect sends the last local Awareness state after the new Resource subscription is accepted.

Canonical behavior: `docs/architecture/05-Realtime-Collaboration-Protocol-Design.md` §§7, 9, 12, 14, 27–29.
