#!/bin/sh
# 在开发机打包部署归档（排除重型/本地目录），输出到 ./dist/deploy/。
# 用法:  scripts/deploy-aliyun/package.sh
# 上传:  scp dist/deploy/dom-deploy-<ts>.tar.gz root@<SERVER>:/opt/
# 解压:  ssh root@<SERVER> 'mkdir -p /opt/moyu && tar xzf /opt/dom-deploy-<ts>.tar.gz -C /opt/moyu'
set -eu

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
TS=$(date +%Y%m%d-%H%M%S)
OUT_DIR="$ROOT/dist/deploy"
mkdir -p "$OUT_DIR"

cd "$ROOT"
tar czf "$OUT_DIR/dom-deploy-${TS}.tar.gz" \
	--exclude='./.git' \
	--exclude='./.github' \
	--exclude='./node_modules' \
	--exclude='./.pnpm-store' \
	--exclude='./.venv' \
	--exclude='./.dsh' \
	--exclude='./.agents' \
	--exclude='./.env' \
	--exclude='./.env.*' \
	--exclude='./.worktrees' \
	--exclude='./.workbuddy' \
	--exclude='./.superpowers' \
	--exclude='./.vscode' \
	--exclude='./.mypy_cache' \
	--exclude='./.pytest_cache' \
	--exclude='./.ruff_cache' \
	--exclude='./.playwright-browsers' \
	--exclude='./.uv-cache' \
	--exclude='./.tmp-*' \
	--exclude='./dist' \
	--exclude='./._*' \
	--exclude='./backups' \
	--exclude='./*.log' \
	--exclude='./README-*.png' \
	--exclude='./README-*.jpg' \
	.

printf '生成: %s（%.1f MiB）\n' "$OUT_DIR/dom-deploy-${TS}.tar.gz" \
	"$(du -m "$OUT_DIR/dom-deploy-${TS}.tar.gz" | cut -f1)"