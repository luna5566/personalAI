#!/usr/bin/env bash
# 个人 AI 知识助手备份脚本（Linux / macOS）
#
# 备份内容：
#   1. PostgreSQL 数据库（pg_dump 自定义格式，可用 pg_restore 恢复）
#   2. 文件存储（docker-compose 卷 personal_ai_storage，含上传文件与本地对象存储）
#
# 用法（在项目根目录执行）：
#   ./ops/backup.sh
#   ./ops/backup.sh --output-dir /var/backups/personal-ai --keep-days 14
#
# 恢复方法与定时任务见 README.md「备份与恢复」一节。

set -euo pipefail

OUTPUT_DIR="./backups"
KEEP_DAYS=30

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --keep-days)
            KEEP_DAYS="$2"
            shift 2
            ;;
        *)
            echo "未知参数：$1（支持 --output-dir <dir> --keep-days <days>）" >&2
            exit 2
            ;;
    esac
done

STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTPUT_DIR"

DB_FILE="$OUTPUT_DIR/personal_ai_db_$STAMP.dump"
echo "备份数据库到 $DB_FILE ..."
docker compose exec -T db pg_dump -U postgres -d personal_ai -Fc > "$DB_FILE"

STORAGE_FILE="$OUTPUT_DIR/personal_ai_storage_$STAMP.tar.gz"
echo "备份文件存储到 $STORAGE_FILE ..."
docker run --rm \
    -v personal_ai_storage:/data:ro \
    -v "$(cd "$OUTPUT_DIR" && pwd)":/backup \
    alpine tar czf "/backup/$(basename "$STORAGE_FILE")" -C /data .

echo "完成：数据库 $(du -h "$DB_FILE" | cut -f1)，存储 $(du -h "$STORAGE_FILE" | cut -f1)"

if [[ "$KEEP_DAYS" -gt 0 ]]; then
    find "$OUTPUT_DIR" -maxdepth 1 -type f \
        -name "personal_ai_*" \
        -mtime "+$KEEP_DAYS" \
        -print -delete | sed 's/^/清理过期备份：/'
fi
