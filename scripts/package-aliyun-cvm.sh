#!/bin/sh
set -eu

COPYFILE_DISABLE=1
export COPYFILE_DISABLE

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUTPUT_DIR="$REPO_ROOT/dist"
COMMIT=$(git -C "$REPO_ROOT" rev-parse --short HEAD)
PUBLIC_IP=${1:-}

if ! printf '%s\n' "$PUBLIC_IP" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; then
	printf '%s\n' 'Usage: scripts/package-aliyun-cvm.sh <server-public-ipv4>' >&2
	exit 2
fi

for octet in $(printf '%s\n' "$PUBLIC_IP" | tr '.' ' '); do
	if [ "$octet" -gt 255 ]; then
		printf '%s\n' 'The server address must be a valid IPv4 address.' >&2
		exit 2
	fi
done

TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/moyu-aliyun.XXXXXX")
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

git -C "$REPO_ROOT" archive --format=tar HEAD -- . \
	':(glob,exclude)**/README*' \
	':(glob,exclude)**/AGENTS.md' \
	':(exclude)docs/**' \
	':(glob,exclude)**/tests/**' \
	':(top,exclude)index.html' \
	':(top,exclude)dom-architecture.html' \
	':(top,exclude)df-contracts.html' \
	':(top,exclude)lc-task.html' \
	':(top,exclude)seq-keystroke.html' \
	':(exclude).vscode/**' \
	':(exclude).superpowers/**' \
	':(exclude).dsh/**' \
	':(exclude).workbuddy/**' | tar -xf - -C "$TMP_DIR"

install -m 644 "$TMP_DIR/compose.aliyun.yaml" "$TMP_DIR/compose.yaml"
rm "$TMP_DIR/compose.aliyun.yaml"
mkdir -p "$OUTPUT_DIR"
PACKAGE="$OUTPUT_DIR/aliyun-cvm-deploy-$COMMIT.tar.gz"
tar -czf "$PACKAGE" -C "$TMP_DIR" .
chmod 600 "$PACKAGE"

printf '%s\n' "Created $PACKAGE for $PUBLIC_IP (server credentials are not included)."
