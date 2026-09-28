#!/bin/sh
# 单机最小备份（RPO 取决于定时频率）：PostgreSQL 全库 pg_dump 压缩转储。
# 用法（compose 项目根 /opt/moyu）:  ./scripts/deploy-aliyun/backup.sh
# 建议 cron： 23 2 * * *  cd /opt/moyu && ./scripts/deploy-aliyun/backup.sh
# 说明：
#  - 备份保留 7 天；请把 ./backups 定期同步到主机之外（rsync/OSS），
#    单机方案的底线保障是数据不只在服务器磁盘上。
#  - MinIO（附件）快照（每日全量镜像，覆盖式；alias 经 MC_HOST_local 注入）：
#      docker compose run --rm -v "$PWD/backups:/backups" minio-init \
#        mirror --overwrite local/dom-assets /backups/minio-dom-assets
set -eu

PROJECT_DIR=${PROJECT_DIR:-$(pwd)}
cd "$PROJECT_DIR"

if [ ! -f compose.yaml ]; then
	printf '%s\n' '请在 compose.yaml 所在目录运行（或设置 PROJECT_DIR）。' >&2
	exit 2
fi
if [ ! -f .env ]; then
	printf '%s\n' '缺少 .env：先运行 scripts/deploy-aliyun/initialize-env.sh <公网IP>。' >&2
	exit 2
fi

# 读取 .env（compose 同款键值格式）
set -a
. ./.env
set +a

BACKUP_DIR="$PROJECT_DIR/backups"
mkdir -p "$BACKUP_DIR"
TS=$(date +%Y%m%d-%H%M%S)
DUMP="$BACKUP_DIR/dom-${TS}.dump.gz"

printf '备份 PostgreSQL -> %s\n' "$DUMP"
docker compose exec -T postgres \
	pg_dump -U "${POSTGRES_USER:-dom_app}" -d "${POSTGRES_DB:-dom}" -Fc \
	| gzip > "$DUMP"

# 保留 7 天
find "$BACKUP_DIR" -name 'dom-*.dump.gz' -mtime +7 -delete

printf '完成。当前备份：\n'
ls -lh "$BACKUP_DIR"