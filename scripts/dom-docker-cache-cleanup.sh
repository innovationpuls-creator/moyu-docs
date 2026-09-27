#!/bin/sh
set -eu

DOCKER_ROOT=$(docker info --format '{{.DockerRootDir}}')
AVAILABLE_KIB=$(df -Pk "$DOCKER_ROOT" | awk 'END { print $4 }')
THRESHOLD_KIB=2097152
STATE_DIR=/var/lib/dom-docker-cache-cleanup
TRIGGER_FILE="$STATE_DIR/cleaned-this-cycle"

case "$AVAILABLE_KIB" in
	'' | *[!0-9]*)
		printf '%s\n' 'Could not determine free space for Docker storage.' >&2
		exit 1
		;;
esac

if [ "$AVAILABLE_KIB" -gt "$THRESHOLD_KIB" ]; then
	if [ -e "$TRIGGER_FILE" ]; then
		rm "$TRIGGER_FILE"
	fi
	exit 0
fi

if [ -e "$TRIGGER_FILE" ]; then
	exit 0
fi

install -d -m 700 "$STATE_DIR"
logger -t dom-docker-cache-cleanup "Docker storage has ${AVAILABLE_KIB} KiB free; pruning unused build cache once."
docker builder prune --all --force
: > "$TRIGGER_FILE"
