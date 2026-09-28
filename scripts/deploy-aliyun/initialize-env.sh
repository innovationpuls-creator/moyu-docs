#!/bin/sh
# 在部署服务器（compose.yaml 所在目录）生成本地 .env（mode 600），密钥不入仓库。
# 用法:  scripts/deploy-aliyun/initialize-env.sh <公网IPv4>
# 已存在 .env 时拒绝覆盖（密钥轮换请手工编辑）。
set -eu

PUBLIC_IP=${1:-}
if ! printf '%s\n' "$PUBLIC_IP" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; then
	printf '%s\n' '用法: scripts/deploy-aliyun/initialize-env.sh <server-public-ipv4>' >&2
	exit 2
fi
for octet in $(printf '%s\n' "$PUBLIC_IP" | tr '.' ' '); do
	if [ "$octet" -gt 255 ]; then
		printf '%s\n' '服务器地址必须是合法 IPv4。' >&2
		exit 2
	fi
done

if [ -e .env ]; then
	printf '%s\n' '.env 已存在，拒绝覆盖服务器凭据（如需轮换请手工编辑）。' >&2
	exit 1
fi

command -v openssl >/dev/null 2>&1 || {
	printf '%s\n' '需要 openssl 生成服务器凭据。' >&2
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

printf '%s\n' "已生成服务器本地凭据 .env（mode 600）。公开入口: https://$PUBLIC_IP"
printf '%s\n' '可选：追加 SMTP_* 启用真实邮件，或 CORS_ALLOW_ORIGINS 配置跨域来源。'