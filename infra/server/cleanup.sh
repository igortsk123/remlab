#!/usr/bin/env bash
# remlab cleanup — SCOPED, не трогает VPN-образы/контейнеры (remnawave/*), caddy, pgvector, imagor.
# Никакого `docker system prune -a` (он мог бы задеть образ VPN-ноды).
#
# ЗАЧЕМ ШАГ 4б (04.09). CI-деплой (deploy.yml) тянет на сервер ОТДЕЛЬНЫЙ тег на каждый push —
# ghcr.io/igortsk123/remlab-app:<sha>. Он не dangling (шаг 1 его не видит) и не совпадает с
# шаблоном 'remlab-app' (шаг 4 ищет локальный репозиторий). За месяц накопилось 135 тегов × 308 МБ
# = 19 ГБ, диск ушёл в 88%, приёмник мешей начал отвечать 507 — ноды считали меши за деньги и
# роняли отправку (104 отказа за вечер, 10 часов простоя пула).
#
# ЗАМОК. Cleanup и деплой не должны бежать одновременно: деплой тегирует/тянет образы, cleanup их
# перечисляет. Один flock на /opt/remlab/.deploy.lock — CI и deploy.sh берут тот же.
# Запуск: еженедельно (remlab-cleanup.timer), из disk-watchdog при заполнении, из CI до pull.
set -euo pipefail
LOG=/opt/remlab/backups/cleanup.log
mkdir -p /opt/remlab/backups
exec >>"$LOG" 2>&1
exec 9>/opt/remlab/.deploy.lock
flock -w 600 9 || { echo "$(date '+%F %T') cleanup: замок занят 10 мин — пропускаю"; exit 0; }
echo "=== $(date '+%F %T') remlab-cleanup === disk before: $(df -h / | tail -1)"

# 1. dangling-образы (untagged, ни к чему не привязаны — безопасно)
docker image prune -f || true

# 2. build cache старше недели
docker builder prune -f --filter 'until=168h' || true

# 3. остановленные remlab-контейнеры
docker ps -a --filter 'name=remlab' --filter 'status=exited' -q | xargs -r docker rm || true

# 4. старые теги локального remlab-app, кроме latest/prev (deploy.sh держит актуальные)
docker images 'remlab-app' --format '{{.Tag}}' 2>/dev/null \
  | grep -vE '^(latest|prev|<none>)$' | tail -n +3 \
  | while read -r t; do [ -n "$t" ] && docker rmi "remlab-app:$t" 2>/dev/null || true; done

# 4б. теги ghcr-образа приложения, кроме используемых. Держим по IMAGE ID (не по тегу): образ
# работающего контейнера, что бы за тег на нём ни висел; remlab-app:prev (откат); latest.
# Снятие тега с образа, который делит слои с latest, лишь снимает тег — слои остаются.
# `docker ps --format` поля ImageID не имеет (проверено 04.09 — падал шаблон): id образа
# каждого РАБОТАЮЩЕГО контейнера берём через inspect самих контейнеров.
USED=$( { docker ps -q | xargs -r docker inspect --format '{{.Image}}'; \
          docker image inspect remlab-app:prev remlab-app:latest --format '{{.Id}}' 2>/dev/null; } \
        | sed 's/^sha256://' | cut -c1-12 | sort -u)
docker images 'ghcr.io/igortsk123/remlab-app' --format '{{.Tag}} {{.ID}}' 2>/dev/null \
  | while read -r t id; do
      [ -z "$t" ] || [ "$t" = latest ] || [ "$t" = '<none>' ] && continue
      echo "$USED" | grep -q "^${id:0:12}" && continue
      docker rmi "ghcr.io/igortsk123/remlab-app:$t" 2>/dev/null && echo "снят тег $t" || true
    done

# 5. ротация дампов БД — держим последние 7
ls -1t /opt/remlab/backups/db-*.sql.gz 2>/dev/null | tail -n +8 | xargs -r rm -f || true

echo "disk after: $(df -h / | tail -1); образов remlab-app: $(docker images 'ghcr.io/igortsk123/remlab-app' -q | sort -u | wc -l)"
