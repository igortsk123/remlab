#!/usr/bin/env bash
# remlab deploy: локальная сборка образа -> перенос на exit-fi -> compose up -> smoke -> откат при провале.
# Использование: ./deploy.sh [tag]   (tag по умолчанию — короткая метка времени, передаётся аргументом)
set -euo pipefail

SERVER="${REMLAB_SERVER:-root@89.167.127.0}"
REMOTE_DIR="/opt/remlab"
DOMAIN="remont-lab.online"
TAG="${1:-$(date +%Y%m%d-%H%M%S)}"
IMAGE="remlab-app"
PLATFORM="linux/arm64"   # exit-fi = Hetzner ARM (aarch64). Локальная машина amd64 -> кросс-сборка под эмуляцией.

echo "==> [0] Проверка кросс-сборки arm64 (binfmt + buildx builder)"
docker buildx inspect remlabx >/dev/null 2>&1 || docker buildx create --name remlabx --driver docker-container >/dev/null
docker run --privileged --rm tonistiigi/binfmt --install arm64 >/dev/null 2>&1 || true

echo "==> [1/6] Локальная кросс-сборка образа $IMAGE:$TAG под $PLATFORM (APP_VERSION=$TAG)"
docker buildx build --builder remlabx --platform "$PLATFORM" --provenance=false --sbom=false \
  --build-arg APP_VERSION="$TAG" -t "$IMAGE:$TAG" -t "$IMAGE:latest" --load .

echo "==> [2/6] Сохранить предыдущий образ на сервере как :prev (для отката)"
ssh "$SERVER" "docker image inspect $IMAGE:latest >/dev/null 2>&1 && docker tag $IMAGE:latest $IMAGE:prev || echo '(prev нет — первый деплой)'"

echo "==> [3/6] Перенос образа на сервер"
docker save "$IMAGE:$TAG" "$IMAGE:latest" | gzip | ssh "$SERVER" 'gunzip | docker load'

echo "==> [4/6] Синхронизация compose/caddy/db-init/env-check"
ssh "$SERVER" "mkdir -p $REMOTE_DIR/caddy $REMOTE_DIR/db/init"
scp docker-compose.yml "$SERVER:$REMOTE_DIR/docker-compose.yml"
scp caddy/Caddyfile "$SERVER:$REMOTE_DIR/caddy/Caddyfile"
scp db/init/001-extensions.sql "$SERVER:$REMOTE_DIR/db/init/001-extensions.sql"
ssh "$SERVER" "test -f $REMOTE_DIR/.env || { echo 'FATAL: нет $REMOTE_DIR/.env (скопируй из .env.example и задай POSTGRES_PASSWORD)'; exit 1; }"

echo "==> [5/6] Запуск на сервере (APP_VERSION=$TAG)"
ssh "$SERVER" "cd $REMOTE_DIR && APP_VERSION=$TAG docker compose up -d"

echo "==> [6/6] Smoke-test https://$DOMAIN"
ok=0
for i in $(seq 1 20); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "https://$DOMAIN/api/health" || true)
  if [ "$code" = "200" ]; then ok=1; break; fi
  echo "  ждём HTTPS/сертификат... ($i) code=$code"; sleep 6
done
if [ "$ok" = "1" ]; then
  ver=$(curl -s --max-time 8 "https://$DOMAIN/api/health" | grep -o "\"version\":\"$TAG\"" || true)
  echo "OK: https://$DOMAIN/api/health = 200 ${ver:+(version=$TAG подтверждён)}"
  # очистка: держим последние 2 тега, убираем dangling (scoped)
  ssh "$SERVER" "docker image prune -f >/dev/null 2>&1 || true"
  echo "DEPLOY DONE: $IMAGE:$TAG"
else
  echo "SMOKE FAILED -> откат на :prev"
  ssh "$SERVER" "cd $REMOTE_DIR && docker image inspect $IMAGE:prev >/dev/null 2>&1 && docker tag $IMAGE:prev $IMAGE:latest && APP_VERSION=prev docker compose up -d && echo 'откат выполнен' || echo 'prev нет — ручной разбор'"
  exit 1
fi
