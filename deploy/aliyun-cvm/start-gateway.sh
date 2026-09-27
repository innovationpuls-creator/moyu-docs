#!/bin/sh
set -eu

mkdir -p /run /var/www/certbot
envsubst '${PUBLIC_IP}' < /opt/aliyun/bootstrap.conf.template > /etc/nginx/conf.d/default.conf
nginx -t
nginx -g 'daemon off;' &
nginx_pid=$!

while [ ! -s "/etc/letsencrypt/live/${PUBLIC_IP}/fullchain.pem" ] || [ ! -s "/etc/letsencrypt/live/${PUBLIC_IP}/privkey.pem" ]; do
	if ! kill -0 "$nginx_pid" 2>/dev/null; then
		wait "$nginx_pid"
		exit 1
	fi
	sleep 2
done

nginx -s quit
wait "$nginx_pid"
envsubst '${PUBLIC_IP}' < /opt/aliyun/production.conf.template > /etc/nginx/conf.d/default.conf
nginx -t
exec nginx -g 'daemon off;'
