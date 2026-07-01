#!/usr/bin/env bash
# remlab weekly cleanup — SCOPED, не трогает VPN-образы/контейнеры.
# Никакого `docker system prune -a` (он мог бы задеть образ VPN-ноды).
set -euo pipefail
LOG=/opt/remlab/backups/cleanup.log
mkdir -p /opt/remlab/backups
exec >>"$LOG" 2>&1
echo "=== $(date '+%F %T') remlab-cleanup ==="

# 1. dangling-образы (untagged, ни к чему не привязаны — безопасно)
docker image prune -f || true

# 2. build cache старше недели
docker builder prune -f --filter 'until=168h' || true

# 3. остановленные remlab-контейнеры
docker ps -a --filter 'name=remlab' --filter 'status=exited' -q | xargs -r docker rm || true

# 4. старые теги remlab-app, кроме latest/prev (deploy.sh держит актуальные)
docker images 'remlab-app' --format '{{.Tag}}' 2>/dev/null \
  | grep -vE '^(latest|prev|<none>)$' | tail -n +3 \
  | while read -r t; do [ -n "$t" ] && docker rmi "remlab-app:$t" 2>/dev/null || true; done

# 5. ротация дампов БД — держим последние 7
ls -1t /opt/remlab/backups/db-*.sql.gz 2>/dev/null | tail -n +8 | xargs -r rm -f || true

echo "disk after: $(df -h / | tail -1)"
