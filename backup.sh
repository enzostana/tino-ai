#!/bin/bash
set -euo pipefail

DEST=/opt/backups/tino
RETENCAO_DIAS=14

mkdir -p "$DEST"

ARQUIVO="$DEST/tino_$(date +%Y%m%d_%H%M).sql.gz"

docker exec tino-db pg_dump -U tino -d tino | gzip > "$ARQUIVO"

find "$DEST" -name "tino_*.sql.gz" -mtime +$RETENCAO_DIAS -delete

echo "$(date '+%Y-%m-%d %H:%M:%S') backup ok: $ARQUIVO"