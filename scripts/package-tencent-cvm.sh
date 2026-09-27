#!/bin/sh
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE="$REPO_ROOT/deploy/tencent-cvm/server.env"
ENV_TEMPLATE="$REPO_ROOT/deploy/tencent-cvm/server.env.example"
OUTPUT_DIR="$REPO_ROOT/dist"
COMMIT=$(git -C "$REPO_ROOT" rev-parse --short HEAD)

if [ ! -f "$ENV_FILE" ]; then
	cp "$ENV_TEMPLATE" "$ENV_FILE"
	chmod 600 "$ENV_FILE"
	printf '%s\n' "Created $ENV_FILE from the template. Fill in the Tencent Cloud values, then run this command again."
	exit 2
fi

if [ -n "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)" ]; then
	printf '%s\n' 'Commit or remove non-ignored workspace changes before packaging the deployment bundle.' >&2
	exit 1
fi

if grep -Eq 'REPLACE_ME|REPLACE_WITH|example\.com|private\.example' "$ENV_FILE"; then
	printf '%s\n' 'Replace the example values in deploy/tencent-cvm/server.env before packaging.' >&2
	exit 1
fi

for required in DOMAIN DATABASE_URL REALTIME_DATABASE_URL S3_ASSET_ENDPOINT S3_ASSET_REGION S3_ASSET_BUCKET S3_ASSET_ACCESS_KEY S3_ASSET_SECRET_KEY INVITATION_IDEMPOTENCY_ENCRYPTION_KEY SHARE_LINK_IDEMPOTENCY_ENCRYPTION_KEY SMTP_HOST SMTP_FROM; do
	if ! grep -Eq "^${required}=.+$" "$ENV_FILE"; then
		printf '%s\n' "Missing required value: $required" >&2
		exit 1
	fi
done

chmod 600 "$ENV_FILE"
TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/dom-cvm-deploy.XXXXXX")
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

git -C "$REPO_ROOT" archive --format=tar HEAD | tar -xf - -C "$TMP_DIR"
install -m 600 "$ENV_FILE" "$TMP_DIR/deploy/tencent-cvm/server.env"
mkdir -p "$OUTPUT_DIR"
PACKAGE="$OUTPUT_DIR/tencent-cvm-deploy-$COMMIT.tar.gz"
tar -czf "$PACKAGE" -C "$TMP_DIR" .
chmod 600 "$PACKAGE"

printf '%s\n' "Created $PACKAGE"
