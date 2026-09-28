#!/bin/sh
# certbot 容器入口：短期 IP 证书（Let's Encrypt，约 6 天有效期）签发/续期循环。
# 每 6 小时跑一轮：
#  - 无证书：certonly 签发（首次签发失败不退出，下轮自动重试，等待 80 端口可达）；
#  - 有证书：用 certbot 自身的到期判断（VALID: N days）按剩余有效期决定是否重签，
#    剩余 < 2 天才 renew（6 天证书提前 1/3 续期），平时跳过——避免默认 30 天阈值
#    对短证书每轮都重签而触发 Let's Encrypt 速率限制。
# 续期/签发成功经 --deploy-hook 触发 nginx reload 加载新证书。
set -eu

PUBLIC_IP=${PUBLIC_IP:?PUBLIC_IP is required}
DEPLOY_DIR=/opt/dom/deploy
CERT_DIR="/etc/letsencrypt/live/${PUBLIC_IP}"
RENEW_THRESHOLD_DAYS=2

# 从 `certbot certificates` 的 "(VALID: N days)" 提取剩余天数；
# 到期不足 1 天时显示小时数不匹配模式，按 0 处理（视为需要续期）。
remaining_days() {
	certbot certificates --cert-name "${PUBLIC_IP}" 2>/dev/null |
		sed -n 's/.*(VALID: *\([0-9][0-9]*\) *days).*/\1/p' |
		head -1
}

while :; do
	if [ ! -s "${CERT_DIR}/fullchain.pem" ] || [ ! -s "${CERT_DIR}/privkey.pem" ]; then
		# --ip-address + --preferred-profile shortlived：IP 证书必须用短期 profile。
		if certbot certonly \
			--non-interactive \
			--agree-tos \
			--register-unsafely-without-email \
			--preferred-profile shortlived \
			--webroot \
			--webroot-path /var/www/certbot \
			--ip-address "${PUBLIC_IP}" \
			--deploy-hook "${DEPLOY_DIR}/reload-nginx.sh"; then
			"${DEPLOY_DIR}/reload-nginx.sh"
		fi
	else
		days=$(remaining_days)
		[ -n "$days" ] || days=0
		if [ "$days" -lt "$RENEW_THRESHOLD_DAYS" ]; then
			certbot renew --non-interactive --quiet --deploy-hook "${DEPLOY_DIR}/reload-nginx.sh" || true
		else
			echo "[certbot-loop] valid for ${days}d; skip renewal (threshold ${RENEW_THRESHOLD_DAYS}d)"
		fi
	fi
	sleep 21600 # 6 小时
done