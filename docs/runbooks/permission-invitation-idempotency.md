# Permission Invitation Idempotency Key

The API reads `INVITATION_IDEMPOTENCY_ENCRYPTION_KEY` from its process
environment when `api.config.settings` is initialized. Supply a base64 encoded
32-byte key through the deployment secret store; create one with
`openssl rand -base64 32`. The API fails closed when Permission dependencies
are used without a valid key.

All API replicas that serve Permission routes must use the same key so retries
can decrypt the original invitation URL from the idempotency response. Keep the
key stable while matching idempotency records are retained. Do not put the key
in source control, logs, or a checked-in `.env` file.

Tests inject a fresh key fixture directly into the repository or dependency;
there is no development or test default key.
