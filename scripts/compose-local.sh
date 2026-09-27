#!/bin/sh
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE="$REPO_ROOT/.env.docker.local"
cd "$REPO_ROOT"

if [ ! -f "$ENV_FILE" ]; then
	command -v openssl >/dev/null 2>&1 || {
		printf '%s\n' "openssl is required to create local-only Compose secrets." >&2
		exit 1
	}
	tmp_file="$ENV_FILE.tmp.$$"
	trap 'rm -f "$tmp_file"' EXIT HUP INT TERM
	{
		printf 'POSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 32)"
		printf 'MINIO_ROOT_USER=%s\n' 'dom_local'
		printf 'MINIO_ROOT_PASSWORD=%s\n' "$(openssl rand -hex 32)"
		printf 'INVITATION_IDEMPOTENCY_ENCRYPTION_KEY=%s\n' "$(openssl rand -base64 32 | tr -d '\n')"
		printf 'SHARE_LINK_IDEMPOTENCY_ENCRYPTION_KEY=%s\n' "$(openssl rand -base64 32 | tr -d '\n')"
	} > "$tmp_file"
	chmod 600 "$tmp_file"
	mv "$tmp_file" "$ENV_FILE"
	trap - EXIT HUP INT TERM
	printf '%s\n' 'Created ignored .env.docker.local with local-only credentials.'
fi

if [ "$#" -eq 0 ]; then
	set -- up --detach --build
fi

exec docker compose --project-name dom-local --env-file "$ENV_FILE" -f compose.yaml "$@"
