#!/bin/sh
set -eu

PUBLIC_IP=${1:-}
if ! printf '%s\n' "$PUBLIC_IP" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; then
	printf '%s\n' 'Usage: deploy/aliyun-cvm/initialize-env.sh <server-public-ipv4>' >&2
	exit 2
fi

for octet in $(printf '%s\n' "$PUBLIC_IP" | tr '.' ' '); do
	if [ "$octet" -gt 255 ]; then
		printf '%s\n' 'The server address must be a valid IPv4 address.' >&2
		exit 2
	fi
done

if [ -e .env ]; then
	printf '%s\n' '.env already exists; refusing to replace server credentials.' >&2
	exit 1
fi

command -v openssl >/dev/null 2>&1 || {
	printf '%s\n' 'openssl is required to generate server credentials.' >&2
	exit 1
}

umask 077
TMP_ENV=".env.tmp.$$"
trap 'rm -f "$TMP_ENV"' EXIT HUP INT TERM
{
	printf 'PUBLIC_IP=%s\n' "$PUBLIC_IP"
	printf 'POSTGRES_USER=%s\n' 'dom_app'
	printf 'POSTGRES_DB=%s\n' 'dom'
	printf 'POSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 32)"
	printf 'MINIO_ROOT_USER=%s\n' 'dom_storage_admin'
	printf 'MINIO_ROOT_PASSWORD=%s\n' "$(openssl rand -hex 32)"
	printf 'INVITATION_IDEMPOTENCY_ENCRYPTION_KEY=%s\n' "$(openssl rand -base64 32 | tr -d '\n')"
	printf 'SHARE_LINK_IDEMPOTENCY_ENCRYPTION_KEY=%s\n' "$(openssl rand -base64 32 | tr -d '\n')"
	printf 'MAIL_LINK_BASE_URL=https://%s\n' "$PUBLIC_IP"
} > "$TMP_ENV"
chmod 600 "$TMP_ENV"
mv "$TMP_ENV" .env
trap - EXIT HUP INT TERM

printf '%s\n' 'Generated server-local credentials in .env (mode 600).'
