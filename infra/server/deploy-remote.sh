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

# 3б. Конфиг входа (Caddyfile) — из репозитория, с проверкой и откатом (план b2b-01). До
#     активации: битый конфиг останавливает деплой, а прежняя версия сайта продолжает работать.
/opt/remlab/scripts/caddy-sync.sh

# 4а. СЕРВИС КАДРОВ В COMPOSE (b2b-08, ADR-0278). Первый раз: контейнер remlab-draft жил вне compose — откладываем
#     его (имя занято бы, `up -d` упал бы) и запоминаем его образ тегом remlab-draft:prev. Новый образ — из CI
#     (REMLAB_DRAFT_IMAGE); не пришёл — остаётся закреплённый в .env.
if docker inspect remlab-draft >/dev/null 2>&1 && [ -z "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' remlab-draft)" ]; then
  docker tag "$(docker inspect -f '{{.Config.Image}}' remlab-draft)" remlab-draft:prev
  docker rm -f remlab-draft-legacy >/dev/null 2>&1 || true
  docker stop remlab-draft >/dev/null && docker rename remlab-draft remlab-draft-legacy
  echo "сервис кадров вне compose отложен (remlab-draft-legacy, образ — remlab-draft:prev)"
fi
DRAFT_OLD=$(grep -E '^REMLAB_DRAFT_IMAGE=' /opt/remlab/.env | cut -d= -f2- || true)
if [ -n "${REMLAB_DRAFT_IMAGE:-}" ]; then
  docker image inspect "$REMLAB_DRAFT_IMAGE" >/dev/null 2>&1 || docker pull -q "$REMLAB_DRAFT_IMAGE" >/dev/null || REMLAB_DRAFT_IMAGE=""
fi
export REMLAB_DRAFT_IMAGE="${REMLAB_DRAFT_IMAGE:-${DRAFT_OLD:-remlab-draft:prev}}"

# 4. Активация новой версии.
docker compose up -d
echo "активирован $REMLAB_IMAGE (APP_VERSION=$APP_VERSION), кадры — $REMLAB_DRAFT_IMAGE"

# 4б. Кадры обязаны ответить своей версией (тег образа = DRAFT_VERSION) за минуту; нет — возвращаем прежний образ,
#     сайт при этом не откатываем (кадры — отдельный сервис).
WANT=${REMLAB_DRAFT_IMAGE##*:}
DRAFT_OK=""
for i in $(seq 1 30); do
  h=$(docker exec remlab-draft python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8099/health',timeout=3).read().decode())" 2>/dev/null || true)
  if printf '%s' "$h" | grep -q '"ok": true'; then
    case "$WANT" in [0-9a-f][0-9a-f][0-9a-f][0-9a-f]*) printf '%s' "$h" | grep -q "$WANT" && DRAFT_OK=1;; *) DRAFT_OK=1;; esac
    break
  fi
  sleep 2
done
if [ -z "$DRAFT_OK" ]; then
  echo "WARN: сервис кадров $REMLAB_DRAFT_IMAGE не ответил своей версией — возвращаю ${DRAFT_OLD:-remlab-draft:prev}"
  REMLAB_DRAFT_IMAGE="${DRAFT_OLD:-remlab-draft:prev}" docker compose up -d --no-deps draft
  REMLAB_DRAFT_IMAGE="${DRAFT_OLD:-remlab-draft:prev}"
fi

# 5. ЗАКРЕПИТЬ ОБРАЗ В .env (08.09). В compose образ задан как `${REMLAB_IMAGE:-remlab-app:latest}`,
#    и любой ручной `docker compose up` БЕЗ этой переменной молча откатывал прод на локальный
#    `latest` шестинедельной давности (поймано на себе: правка тома caddy пересоздала и app).
#    Теперь боевой образ живёт в `.env` — compose подставит его сам, без переменных в команде.
umask 077
TMP_ENV=$(mktemp /opt/remlab/.env.XXXXXX)
grep -v -E '^REMLAB_IMAGE=|^APP_VERSION=|^REMLAB_DRAFT_IMAGE=' /opt/remlab/.env > "$TMP_ENV" || true
{
  echo "# боевой образ (пишет deploy-remote.sh): ручной compose берёт его отсюда, а не дефолт"
  echo "REMLAB_IMAGE=$REMLAB_IMAGE"
  echo "APP_VERSION=$APP_VERSION"
  echo "REMLAB_DRAFT_IMAGE=$REMLAB_DRAFT_IMAGE"
} >> "$TMP_ENV"
mv "$TMP_ENV" /opt/remlab/.env
chmod 600 /opt/remlab/.env
