#!/usr/bin/env bash
# СЕРВЕРНАЯ часть деплоя. Запускается на exit-fi ПОД ЗАМКОМ и одинаково обоими путями —
# автодеплоем (`.github/workflows/deploy.yml`) и ручным `deploy.sh`:
#
#   flock -w 900 /opt/remlab/.deploy.lock \
#     env REMLAB_IMAGE=ghcr.io/…/remlab-app:<sha> APP_VERSION=<sha> /opt/remlab/scripts/deploy-remote.sh
#
# ПОРЯДОК ВАЖЕН (05.09, ADR-0179). Раньше было `compose up -d` → миграции: приложение
# переключалось ДО схемы, и провал SQL оставлял прод на новой версии, а smoke по одному коду 200
# считал такой выкат успешным. Теперь: цель отката → образ → БД и миграции → и только потом
# активация приложения.
#
# ЗАМОК тот же, что у cleanup (`/opt/remlab/.deploy.lock`): сторож диска перечисляет и удаляет
# теги образов, деплой их тегирует и тянет — одновременно им нельзя. Сам cleanup вызывается
# ВНЕ этого скрипта (он берёт замок сам, вложенный вызов повис бы).
#
# VPN-нода `remnanode` делит хост — здесь трогаются только сервисы remlab через compose-проект.
set -euo pipefail

: "${REMLAB_IMAGE:?REMLAB_IMAGE не задан (образ, который выкатываем)}"
: "${APP_VERSION:?APP_VERSION не задан (версия для /api/health)}"
export REMLAB_IMAGE APP_VERSION
cd /opt/remlab

test -f .env || { echo 'FATAL: нет /opt/remlab/.env'; exit 1; }
grep -q '^GEMINI_API_KEY=' .env || { echo 'FATAL: нет GEMINI_API_KEY в .env'; exit 1; }

# 1. Цель отката — образ РЕАЛЬНО РАБОТАЮЩЕГО контейнера, по image ID.
#    Прежняя строка `docker tag ${IMAGE}:latest remlab-app:prev` не срабатывала никогда: сервер
#    тянет образ по SHA, локального тега `:latest` у него нет, а ошибку глушило `|| true`.
#    Итог — `remlab-app:prev` протух на 6 недель, и «откат» вернул бы прод к июльскому коду.
cur=$(docker inspect -f '{{.Image}}' remlab-app 2>/dev/null || true)
if [ -n "$cur" ]; then
  docker tag "$cur" remlab-app:prev
  echo "цель отката remlab-app:prev := $cur"
else
  echo "цель отката: контейнера remlab-app нет (первый деплой) — откатывать будет не на что"
fi

# 2. Образ. Ручной путь заливает его через `docker load` — тогда тянуть нечего.
if docker image inspect "$REMLAB_IMAGE" >/dev/null 2>&1; then
  echo "образ $REMLAB_IMAGE уже на сервере"
else
  docker compose pull app
fi

# 3. БД и схема — ДО переключения приложения. Миграции аддитивные и идемпотентные, старая
#    версия приложения переживает их без простоя.
docker compose up -d db
for i in $(seq 1 20); do
  docker compose exec -T db pg_isready -U remlab -d remlab >/dev/null 2>&1 && break
  sleep 3
done
docker compose exec -T db pg_isready -U remlab -d remlab >/dev/null 2>&1 || {
  echo 'FATAL: БД не поднялась за минуту'; exit 1; }

DB_INIT_DIR=/opt/remlab/db/init \
PSQL_CMD='docker compose exec -T db psql -U remlab -d remlab -q -v ON_ERROR_STOP=1' \
  /opt/remlab/scripts/apply-db-init.sh

# 4. Активация новой версии.
docker compose up -d
echo "активирован $REMLAB_IMAGE (APP_VERSION=$APP_VERSION)"
