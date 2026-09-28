#!/bin/sh
# gateway 容器入口：bootstrap（仅 80/ACME）→ 等待 Let's Encrypt 短期 IP 证书
# → 渲染生产配置（443/TLS）→ nginx -s reload（不重启进程，连接不断）。
set -eu

PUBLIC_IP=${PUBLIC_IP:?PUBLIC_IP is required}
DEPLOY_DIR=/opt/dom/deploy

mkdir -p /var/www/certbot /run

# $1 = 模板文件名（位于 $DEPLOY_DIR），$2 = 输出路径
render() {
	sed "s/__PUBLIC_IP__/${PUBLIC_IP}/g" "${DEPLOY_DIR}/$1" > "$2"
}

render bootstrap.conf.template /etc/nginx/conf.d/default.conf
nginx -t >/dev/null
nginx -g 'daemon off;' &
NGINX_PID=$!
trap 'kill -QUIT "$NGINX_PID" 2>/dev/null || true; wait "$NGINX_PID" 2>/dev/null || true' TERM INT

cert_dir="/etc/letsencrypt/live/${PUBLIC_IP}"
while [ ! -s "${cert_dir}/fullchain.pem" ] || [ ! -s "${cert_dir}/privkey.pem" ]; do
	if ! kill -0 "$NGINX_PID" 2>/dev/null; then
		wait "$NGINX_PID" 2>/dev/null || true
		exit 1
	fi
	sleep 2
done

render production.conf.template /etc/nginx/conf.d/default.conf
nginx -t >/dev/null
nginx -s reload

wait "$NGINX_PID"