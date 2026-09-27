#!/bin/sh
set -eu

# Avoid packing macOS AppleDouble sidecars and resource-fork metadata into the
# Linux deployment archive.
COPYFILE_DISABLE=1
export COPYFILE_DISABLE

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE="$REPO_ROOT/deploy/tencent-cvm/server.env"
OUTPUT_DIR="$REPO_ROOT/dist"
COMMIT=$(git -C "$REPO_ROOT" rev-parse --short HEAD)

if [ ! -f "$ENV_FILE" ]; then
	command -v openssl >/dev/null 2>&1 || {
		printf '%s\n' 'openssl is required to generate server-only credentials.' >&2
		exit 1
	}
	TMP_ENV="$ENV_FILE.tmp.$$"
	trap 'rm -f "$TMP_ENV"' EXIT HUP INT TERM
	{
		printf 'POSTGRES_USER=%s\n' 'dom_app'
		printf 'POSTGRES_DB=%s\n' 'dom'
		printf 'POSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 32)"
		printf 'MINIO_ROOT_USER=%s\n' 'dom_storage_admin'
		printf 'MINIO_ROOT_PASSWORD=%s\n' "$(openssl rand -hex 32)"
		printf 'INVITATION_IDEMPOTENCY_ENCRYPTION_KEY=%s\n' "$(openssl rand -base64 32 | tr -d '\n')"
		printf 'SHARE_LINK_IDEMPOTENCY_ENCRYPTION_KEY=%s\n' "$(openssl rand -base64 32 | tr -d '\n')"
	} > "$TMP_ENV"
	chmod 600 "$TMP_ENV"
	mv "$TMP_ENV" "$ENV_FILE"
	trap - EXIT HUP INT TERM
	chmod 600 "$ENV_FILE"
	printf '%s\n' "Generated private database, object storage, and application keys in $ENV_FILE."
fi

if [ -n "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)" ]; then
	printf '%s\n' 'Commit or remove non-ignored workspace changes before packaging the deployment bundle.' >&2
	exit 1
fi

for required in POSTGRES_USER POSTGRES_DB POSTGRES_PASSWORD MINIO_ROOT_USER MINIO_ROOT_PASSWORD INVITATION_IDEMPOTENCY_ENCRYPTION_KEY SHARE_LINK_IDEMPOTENCY_ENCRYPTION_KEY; do
	if ! grep -Eq "^$required=.+$" "$ENV_FILE"; then
		printf '%s\n' "Missing required value: $required" >&2
		exit 1
	fi
done

chmod 600 "$ENV_FILE"
TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/dom-cvm-deploy.XXXXXX")
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

git -C "$REPO_ROOT" archive --format=tar HEAD -- . \
	':(glob,exclude)**/README*' \
	':(glob,exclude)**/AGENTS.md' \
	':(exclude)docs/**' \
	':(exclude)tests/**' \
	':(top,exclude)index.html' \
	':(top,exclude)dom-architecture.html' \
	':(top,exclude)df-contracts.html' \
	':(top,exclude)lc-task.html' \
	':(top,exclude)seq-keystroke.html' \
	':(exclude).vscode/**' \
	':(exclude).superpowers/**' \
	':(exclude).dsh/**' \
	':(exclude).workbuddy/**' | tar -xf - -C "$TMP_DIR"
install -m 600 "$ENV_FILE" "$TMP_DIR/.env"
install -m 644 "$TMP_DIR/compose.server.yaml" "$TMP_DIR/compose.yaml"
mkdir -p "$OUTPUT_DIR"
PACKAGE="$OUTPUT_DIR/tencent-cvm-deploy-$COMMIT.tar.gz"
tar -czf "$PACKAGE" -C "$TMP_DIR" .
chmod 600 "$PACKAGE"

printf '%s\n' "Created $PACKAGE"
