---
tier: 2
topic: deployment-details
scope: Деплой exit-fi — подробности конвейера, сторожа, история правок сервера
tier1: "../deployment.md"
updated: 2026-10-13
importance: med
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

## Caddy, статик и контейнеры — детали (вынесено из сводки 2026-09-05, сверено с кодом)
- Лимиты памяти (ADR-0004): app 1G / pg 1G / caddy 128M / imagor 256M / mesh-receiver 256M.
- `caddy/Caddyfile` проксирует `/api/{draft,warm,render,job,share}*` → `draft:8099` — это
  `tools/scout/draft_service.py` (DEV-рендер демо через обратный ssh-туннель, ADR-0139), сервис
  вне compose. Блока `/lab/*` в Caddyfile нет и не было — `/lab/*` отдаёт Next (`remlab-app:3000`).
- Маршрут `/test/mesh-audit/*` (05.09, ADR-0194): `public, max-age=604800, immutable` для партий
  моделей и постеров приёмки; каталоги `/opt/remlab/test/mesh-audit/{releases,posters}` создаёт
  публикатор или руки. **Caddyfile едет деплоем (13.10, ADR-0256):** `deploy.yml` и `deploy.sh` кладут
  `caddy/Caddyfile.new`, `infra/server/caddy-sync.sh` (из `deploy-remote.sh`, до активации app) сверяет боевой
  со снимком `Caddyfile.deployed` (не совпал — ручная правка, стоп), `validate` через stdin, подмена `cat >`
  (bind по inode), `reload`, при провале — возврат бэкапа. Руками на сервере не править.
- Smoke: `deploy.yml` сверяет `ok=true` и `version == TARGET_SHA` на шаге `!cancelled()`; ручной
  `deploy.sh:63-70` решает успех по одному HTTP 200, `ok` не проверяет и версию только печатает.
- Очистка диска: `infra/server/cleanup.sh` + `infra/server/systemd/*.service`; `.timer` в репо нет
  (на сервере расписание — проверить `systemctl list-timers` при следующей правке).

## Откат прода вручную (перенесено из сводки 08.09)
```
flock /opt/remlab/.deploy.lock env REMLAB_IMAGE=remlab-app:prev APP_VERSION=prev \
  docker compose up -d
```
Тег `prev` ставит `infra/server/deploy-remote.sh` по image ID работающего контейнера ДО
переключения. Боевой образ он же пишет в `/opt/remlab/.env` (ADR-0202), поэтому обычный
`docker compose up -d --no-deps app` возвращает текущую версию без переменных в команде.

## Caddy: публичные маршруты и рассинхрон конфига (28.09.2026)
- **Адрес без слэша — другой маршрут.** `handle_path /x/*` НЕ матчит `/x`: запрос проваливается
  в `reverse_proxy remlab-app:3000` и Next.js отдаёт 404. Полный маршрут статики = блок
  `handle_path /x/*` + парный `redir /x /x/ 301`. У `/demo` редирект есть (`caddy/Caddyfile`),
  у `/test` — нет, поэтому `remont-lab.online/test` = 404, а `/test/` = 200.
  Диагностируя «ссылка не работает», проверять ОБА варианта адреса.
- **[История, сведено 13.10]** Серверный Caddyfile был НОВЕЕ репозиторного: блок `log` и матчер `@nextrce`
  (инцидент 08.09, ADR-0207) жили только на сервере; 13.10 перенесены в `caddy/Caddyfile` (строки `log`,
  `@nextrce`), с ADR-0256 рассинхрон ловят `caddy-sync.sh` при деплое и ежечасный сторож. Копирование
  репо-версии поверх СНЯЛО БЫ заслон — это повтор урока 07.08 (деплой затирал серверный блок).
  Порядок сведения: бэкап живого файла + его SHA → перенести серверные блоки в репо дословно →
  `caddy validate` и `caddy adapt` в одноразовом контейнере того же тега → `reload` (не
  перезапуск стека: рядом боевая VPN-нода `remnanode`).
- **Порядок директив:** `redir` в Caddyfile вычисляется РАНЬШЕ `handle`/`handle_path`, поэтому
  точечный редирект корня (`/x`, `/x/`) сосуществует с раздачей глубоких адресов из того же блока.
- **Прибитые пути.** `/test/` встречается абсолютным путём в 91 месте в 38 файлах `tools/`,
  каталог `/opt/remlab/test` = 4.6 ГБ. Новый публичный адрес вводить alias-маршрутом на тот же
  `root`, а не переносом файлов: иначе ломаются генераторы и уже разосланные ссылки.

## Проверка .env после машинной правки (перенесено из Tier 1, 11.10)
`infra/server/deploy-remote.sh` перезаписывает `/opt/remlab/.env` машинно (строка `REMLAB_IMAGE`).
Правило: после такой правки прогнать `docker compose config --quiet` — он молча подтверждает, что
файл разбирается. СТОРОЖА В СКРИПТАХ НЕТ: проверка процедурная, её делает человек (сверка 11.10).

## Безопасность (13.10, ADR-0256; перенесено из Tier 1)
- ПДн — только в базе: заявки «отправить себе» — `share_requests` (90 дней) через внутреннюю ручку
  `app/api/internal/share-request/route.ts` (секрет `INTERNAL_API_TOKEN` в `/opt/remlab/.env` и
  `/opt/remlab/draft/.env`; снаружи Caddy 404 на `/api/internal/*`).
- Лимиты частоты и дневной потолок платного — `lib/ratelimit/*` (таблица `rate_limits`); у сервиса кадров —
  свой счёт в памяти (`tools/scout/draft_guard.py`).
- Закрыто без секрета: вебхук ЮKassa (IP + перезапрос API), Telegram-вебхуки (401), трейсы и подписанные
  фото в production; токен трейса — только заголовком `x-trace-token`.
- Заголовки на весь сайт: `frame-ancestors 'self'`, `nosniff`, `Referrer-Policy` (`caddy/Caddyfile`).
- Ежечасный `infra/server/disk-watchdog.sh`: чистит просроченные `share_requests`/старые `rate_limits`, будит
  владельца при файлах `_queue` под веб-корнем и при расхождении `Caddyfile` со снимком `Caddyfile.deployed`.
- После деплоя — шаг `tools/security-smoke.sh` (13 проверок снаружи, без отката).
- `remlab-draft` вне compose, свежий код — в слое контейнера (урок 474): пересоздание только
  `infra/server/draft-run.sh` (снимок `docker commit` → запуск из снимка, старый — `remlab-draft-prev`).
