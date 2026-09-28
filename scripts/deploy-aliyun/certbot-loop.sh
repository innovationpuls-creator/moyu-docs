#!/bin/sh
# certbot 容器入口：短期 IP 证书（Let's Encrypt，约 6 天有效期）签发/续期循环。
# 每 6 小时跑一轮；首次签发失败不退出，6 小时后自动重试（等待 80 端口可达/
# 安全组放行）；续期成功经 --deploy-hook 触发 nginx reload 加载新证书。
set -eu

PUBLIC_IP=${PUBLIC_IP:?PUBLIC_IP is required}
DEPLOY_DIR=/opt/dom/deploy
CERT_DIR="/etc/letsencrypt/live/${PUBLIC_IP}"

while :; do
	if [ ! -s "${CERT_DIR}/fullchain.pem" ] || [ ! -s "${CERT_DIR}/privkey.pem" ]; then
		# --ip-address + --preferred-profile shortlived：IP 证书必须用短期 profile。
		certbot certonly \
			--non-interactive \
			--agree-tos \
			--register-unsafely-without-email \
			--preferred-profile shortlived \
			--webroot \
			--webroot-path /var/www/certbot \
			--ip-address "${PUBLIC_IP}" \
			--deploy-hook "${DEPLOY_DIR}/reload-nginx.sh"
		"${DEPLOY_DIR}/reload-nginx.sh"
	else
		certbot renew --non-interactive --quiet --deploy-hook "${DEPLOY_DIR}/reload-nginx.sh" || true
	fi
	sleep 21600 # 6 小时
done