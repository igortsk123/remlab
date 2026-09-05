---
tier: 2
topic: deployment-details
scope: Деплой exit-fi — подробности конвейера, сторожа, история правок сервера
tier1: "../deployment.md"
updated: 2026-09-05
importance: medium
source: manual
last_verified: 2026-09-05
---

# Деплой — подробности

Сводка (что помнить всегда) — `../deployment.md`. Здесь детали, которым не место в Tier 1.

## Конвейер выката (ADR-0179)

Порядок шагов `.github/workflows/deploy.yml`:

1. **Что выкатываем.** `TARGET_SHA = github.event.workflow_run.head_sha || github.sha`. Для
   события `workflow_run` `github.sha` — HEAD ветки по умолчанию на момент запуска, а НЕ SHA
   прошедшего CI: пока деплой был красным, следующий пуш успевал обогнать проверенный коммит.
   Один и тот же `TARGET_SHA` идёт в checkout, тег образа, `APP_VERSION` и в smoke.
2. **Сборка** — нативный arm64-раннер (`ubuntu-24.04-arm`), кэш слоёв `type=gha`, push в GHCR.
   Эмуляция arm64 через QEMU крашила Next-SWC-воркер (SIGILL) — не возвращать.
3. **Синхронизация сервера.** `docker-compose.yml` — `scp`; `db/init` — `rsync -az --delete`
   (репозиторий владеет каталогом целиком); `tools/apply-db-init.sh` и
   `infra/server/deploy-remote.sh` — в `/opt/remlab/scripts/`.
4. **Место на диске** — `cleanup.sh` ДО pull (он берёт `.deploy.lock` сам, поэтому вызывается вне
   критической секции: вложенный вызов под тем же замком повис бы).
5. **Критическая секция** — `flock -w 900 /opt/remlab/.deploy.lock … deploy-remote.sh`:
   цель отката → образ → `up -d db` + миграции → активация приложения. Замок общий со сторожем
   диска: он перечисляет и удаляет теги, деплой их тянет и тегирует.
6. **Smoke** — `if: !cancelled()`, чтобы страховка работала и после провала предыдущего шага.
   Успех = `200` И `ok=true` И `version == TARGET_SHA`. Сайт жив, но версия чужая → выкат не
   состоялся, откат НЕ делаем (он лишь сменил бы живую версию на более старую). Сайт мёртв →
   откат на `remlab-app:prev`. Разбор ответа — `sed`/`grep`, намеренно без `jq`: отсутствие
   утилиты дало бы пустую версию и откат исправного выката.
7. **Cleanup после успеха** — снимаем теги прошлых деплоев (`prev` остаётся).

Цель отката `remlab-app:prev` ставится по image ID работающего контейнера
(`docker inspect -f '{{.Image}}' remlab-app`). Прежняя строка `docker tag ${IMAGE}:latest
remlab-app:prev` не срабатывала ни разу — сервер тянет образ по SHA, локального `:latest` у него
нет, ошибку глушило `|| true`; `prev` протух на 6 недель (22.07 → 05.09).

## Схема БД: две базы, не путать

| Что | Где лежит | Кто применяет | Куда |
|-----|-----------|---------------|------|
| Прод-схема | `db/init/NNN-*.sql` | `tools/apply-db-init.sh` | боевая БД `remlab-db` |
| Каталог | `tools/scout/NNN-*.sql` | `tools/scout/db_migrate.py` | дев-БД `remlab-devdb` |

Таблиц каталога (`products`, `mesh_demand`, `asset_revisions`) на проде нет и не должно быть.
Гарда — CI-job `db-init`: чистый postgres → вся прод-схема → второй проход (идемпотентность) →
проверка, что таблицы приложения на месте.

## Сторожа

- **Каталог (ADR-0172):** `remlab-catalog-watchdog.timer` 15:30 UTC — нет сегодняшнего статуса в
  `refresh-status.json` или `overall=FAIL` → Telegram. Kill-switch `DISABLED`, откат
  `systemctl disable --now`; юниты — `infra/server/systemd/`.
- **Диск и очистка (ADR-0005/0176):** `remlab-cleanup` weekly + из CI (теги `remlab-app:*` кроме
  используемых, под flock); `pg_dump` ×7; `remlab-watchdog.timer` ежечасно: ≥80% → cleanup →
  Telegram; рестарты `remlab-app` → `backups/app-mem.log`.
- Скрипты `infra/server/*` (кроме двух деплойных) кладутся на сервер руками — деплой их не
  доставляет. Это известный долг: коммит может менять приёмник/Caddy и «успешно выкатиться», а
  сервер останется на старом коде.

## Правки сервера 31.08
sshd, iptables-туннель DEV-рендера, `remlab-draft` через docker cp — ADR-0139
(бэкапы `*.bak-20260831`).

## Секреты
`.env` в `/opt/remlab` (вне git): `POSTGRES_PASSWORD` / `GEMINI_API_KEY` / `TRACE_ADMIN_TOKEN`.
Compose передаёт app ЯВНЫЙ `environment:`-список — новый ключ = правка compose.
