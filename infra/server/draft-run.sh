#!/usr/bin/env bash
# ПЕРЕСОЗДАТЬ СЕРВИС КАДРОВ remlab-draft (план b2b-01; до переезда в compose по плану b2b-08).
#
# Сервис живёт вне compose, а его код годами докладывался `docker cp` прямо в работающий
# контейнер — образ `remlab-draft` от 27.08, свежий код только в слое контейнера. Простое
# пересоздание молча вернуло бы августовский код. Поэтому:
#   1. снимок работающего контейнера → образ `remlab-draft:snap-<время>` (он же точка отката);
#   2. новые файлы кода (аргументы) кладутся в снимок поверх;
#   3. старый контейнер ОСТАНАВЛИВАЕТСЯ и переименовывается в remlab-draft-prev (не удаляется);
#   4. новый запускается с теми же сетью/алиасом/томом/лимитами и env из /opt/remlab/draft/.env
#      (вне git, chmod 600; секреты — только там).
# Откат: docker rm -f remlab-draft && docker rename remlab-draft-prev remlab-draft && docker start remlab-draft
#
#   infra/server/draft-run.sh /opt/remlab/draft/draft_service.py /opt/remlab/draft/draft_guard.py
# VPN-нода `remnanode` делит хост — здесь трогается только remlab-draft.
set -euo pipefail

ENVF=/opt/remlab/draft/.env
[ -f "$ENVF" ] || { echo "FATAL: нет $ENVF"; exit 1; }
TS=$(date +%Y%m%d-%H%M%S)
SNAP=remlab-draft:snap-$TS

docker commit -m "snapshot before recreate $TS" remlab-draft "$SNAP" >/dev/null
echo "снимок: $SNAP"

# Новые файлы — в образ поверх снимка (через временный контейнер, без пересборки зависимостей).
if [ "$#" -gt 0 ]; then
  tmp=$(docker create "$SNAP")
  for f in "$@"; do docker cp "$f" "$tmp:/app/$(basename "$f")"; done
  docker commit "$tmp" "$SNAP" >/dev/null
  docker rm "$tmp" >/dev/null
  echo "в снимок положены: $*"
fi

docker rm -f remlab-draft-prev >/dev/null 2>&1 || true
docker stop remlab-draft >/dev/null
docker rename remlab-draft remlab-draft-prev

docker run -d --name remlab-draft \
  --network remlab-net --network-alias draft \
  -v /opt/remlab/test/share:/app/share \
  --env-file "$ENVF" \
  --memory 2200m --cpus 2 --restart unless-stopped \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
  -w /app "$SNAP" python draft_service.py >/dev/null

for i in $(seq 1 30); do
  if docker exec remlab-draft python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8099/health',timeout=3)" 2>/dev/null; then
    echo "remlab-draft запущен из $SNAP, /health отвечает"; exit 0
  fi
  sleep 2
done
echo "FATAL: новый remlab-draft не отвечает — откатываю на remlab-draft-prev"
docker logs --tail 30 remlab-draft || true
docker rm -f remlab-draft
docker rename remlab-draft-prev remlab-draft
docker start remlab-draft
exit 1
