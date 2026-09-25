# Assets

`domain.py` owns immutable Asset metadata. `application.py` coordinates upload,
download, and Resource-scoped listing through the ports in `ports.py`.
Infrastructure owns binary storage and persistence adapters; this module does
not import API or storage implementations.

Upload retries pass a stable idempotency key and a fingerprint of the actor,
Resource, file bytes, MIME type, and original name. The adapter replays the
first Asset for a matching key and raises `IDEMPOTENCY_KEY_CONFLICT` when the
key is reused for another request.
