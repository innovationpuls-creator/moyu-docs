#!/bin/sh
set -eu

request_certificate() {
	certbot certonly \
		--non-interactive \
		--agree-tos \
		--register-unsafely-without-email \
		--preferred-profile shortlived \
		--webroot \
		--webroot-path /var/www/certbot \
		--ip-address "$PUBLIC_IP" \
		--deploy-hook /opt/aliyun/reload-nginx.sh
}

while :; do
	if [ ! -s "/etc/letsencrypt/live/${PUBLIC_IP}/fullchain.pem" ]; then
		request_certificate || sleep 21600
	else
		certbot renew --non-interactive --quiet --deploy-hook /opt/aliyun/reload-nginx.sh || true
		sleep 21600
	fi
done
