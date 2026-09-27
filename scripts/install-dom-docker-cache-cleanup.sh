#!/bin/sh
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ "$(id -u)" -ne 0 ]; then
	printf '%s\n' 'Run this installer as root.' >&2
	exit 1
fi

command -v docker >/dev/null 2>&1 || {
	printf '%s\n' 'Docker is required before installing the cache cleanup timer.' >&2
	exit 1
}
command -v systemctl >/dev/null 2>&1 || {
	printf '%s\n' 'systemd is required before installing the cache cleanup timer.' >&2
	exit 1
}

docker info >/dev/null
install -m 755 "$REPO_ROOT/scripts/dom-docker-cache-cleanup.sh" /usr/local/sbin/dom-docker-cache-cleanup
install -m 644 "$REPO_ROOT/deploy/systemd/dom-docker-cache-cleanup.service" /etc/systemd/system/dom-docker-cache-cleanup.service
install -m 644 "$REPO_ROOT/deploy/systemd/dom-docker-cache-cleanup.timer" /etc/systemd/system/dom-docker-cache-cleanup.timer
systemctl daemon-reload
systemctl enable --now dom-docker-cache-cleanup.timer
systemctl --no-pager --full status dom-docker-cache-cleanup.timer
