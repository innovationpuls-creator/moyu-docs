# Realtime Service

The WebSocket gateway authenticates a connection from the `dom_session` Session cache entry. Each Resource subscription is separately authorized through the API before the connection can receive or publish Resource data.

After an authorized subscription, the gateway creates an in-memory Awareness participant for that connection and Resource. The account ID comes from the verified Session; the client cannot choose its participant ID, display name, or color. A participant is tracked per connection and subscription, so closing one tab does not remove another tab's cursor. New subscribers receive current participants and cursor states. Awareness updates are coalesced to the latest state at an 80 ms trailing interval and cleared at unsubscribe or connection close.

Awareness payloads contain only the cursor selection. They are size-bounded, validated, and accepted only when the current `subscriptionId` matches an authorized Resource subscription. They are not written to the Yjs backlog, Valkey roster store, or database.

Canonical behavior: `docs/architecture/05-Realtime-Collaboration-Protocol-Design.md` §§9–14, 27–29, 40–42; Resource boundary: `docs/architecture/03-Resource-Collaboration-Design.md` §4.
