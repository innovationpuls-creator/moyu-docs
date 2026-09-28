#!/bin/sh
# certbot --deploy-hook：向 gateway（共享 PID namespace + /run 卷）的 nginx
# master 进程发送 HUP，重读证书配置。签名后无文件/无进程时静默跳过。
set -eu

PID_FILE=/run/nginx.pid
if [ -s "$PID_FILE" ]; then
	kill -HUP "$(cat "$PID_FILE")" 2>/dev/null || true
fi