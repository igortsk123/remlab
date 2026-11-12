---
tier: 2
topic: deployment-details
scope: Деплой exit-fi — подробности конвейера, сторожа, история правок сервера
tier1: "../deployment.md"
updated: 2026-11-12
importance: med
source: manual
last_verified: 2026-11-06
---

# Деплой — подробности

Сводка (что помнить всегда) — `../deployment.md`. Здесь детали, которым не место в Tier 1.

## Конвейер выката (ADR-0179)

Порядок шагов `.github/workflows/deploy.yml`:

1. **Что выкатываем.** `TARGET_SHA = github.event.workflow_run.head_sha || github.sha`. Для
   события `workflow_run` `github.sha` — HEAD ветки по умолчанию на момент запуска, а НЕ SHA
   прошедшего CI: пока деплой был красным, следующий пуш успевал обогнать проверенный коммит.
   Один и тот же `TARGET_SHA` идёт в checkout, тег образа, `APP_VERSION` и в smoke.
1a. **Нужна ли выкладка** (T-20261106-66/2): `tools/ops/deploy-need.sh "$TARGET_SHA"` сравнивает дерево ВЫКАТАННОЙ
   версии (`/api/health` → version) с целью; изменены только `.memory_bank/`, `docs/`, `.claude/`, `.vscode/`, корневые
   `*.md` → `deploy=false`, сборка/выкат/smoke пропускаются (`::notice` + Step Summary). Цель — строгий предок
   выкатанной версии (CI кончились не по порядку, T-20261110-01) → тоже пропуск, проверяется ДО здоровья: старый
   коммит сам не выкатывается никогда (`deploy-need.sh:older_than_prod`). Прочее сомнение (версия не 40-hex, `ok≠true`,
   draft ≠ сайт, коммит не найден, шаг упал) → выкладка; история глубже `HIST_DEPTH` (`order=2`) — только «старой не признана»
   + хвост «порядок не доказан», дальше обычные проверки: разница лишь в доках → `skip` (`deploy-need.sh:70-84`; комментарии
   `deploy-need.sh:11-12` и `deploy.yml:47` здесь неточны); `workflow_dispatch` — всегда.
   «Прод не позади main» — `bash tools/ops/deploy-need.sh --status` (rc 0 — разница только документы), не `version == HEAD`.
   Caddy (`caddy/Caddyfile` сниппет `retry_restart`): app и draft — повтор до 15 с при пересоздании контейнера;
   `request_buffers 1MB` обязателен — без него повтор POST падает «invalid Read on closed Body» (проба 06.11).
2. **Сборка** — нативный arm64-раннер (`ubuntu-24.04-arm`), кэш слоёв `type=gha`, push в GHCR.
   Эмуляция arm64 через QEMU крашила Next-SWC-воркер (SIGILL) — не возвращать.
3. **Синхронизация сервера.** `docker-compose.yml` — `scp`; `db/init` — `rsync -az --delete`
   (репозиторий владеет каталогом целиком); `tools/apply-db-init.sh`, `deploy-remote.sh`, `caddy-sync.sh`, сторожа,
   `salad-deadman.py`, `cleanup.sh` и др. (список — `deploy.yml`) — в `/opt/remlab/scripts/`; `Caddyfile.new` → `caddy-sync`.
4. **Место на диске** — `cleanup.sh` ДО pull (он берёт `.deploy.lock` сам, поэтому вызывается вне
   критической секции: вложенный вызов под тем же замком повис бы).
5. **Критическая секция** — `flock -w 900 /opt/remlab/.deploy.lock … deploy-remote.sh`:
   цель отката → образ → `up -d db` + миграции → `caddy-sync.sh` → активация (`compose up -d`) → проверка кадров
   по `/health` (`infra/server/deploy-remote.sh`). Замок общий со сторожем
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

**Миграция дев-БД под паузой кронов (05.11, onb-12 ч.2, ADR-0330 п.6)** — `tools/ops/db-migrate-safe.sh <файл.sql> [--check '<boolean>']`
вместо голого `db_migrate.py` под работающими кронами. Шаги: `cron-pause.sh on` (ждёт конца тяжёлых задач, `--wait`; не дождались —
код 3, ничего не тронуто) → `pg_dump --clean` затронутых таблиц в `~/backups/migrate/<метка>-<имя>/` (ПОСЛЕ паузы, чтобы крон не
записал между копией и миграцией; вся БД — если в SQL функции/вью/DO-блоки или на таблицу опирается вью/внешний ключ, как
`products` ← `lr_roles`, `catalog_ready`; только схема — если все таблицы новые) → SQL `--single-transaction`, проверка `--check`
в той же транзакции (не прошла — откат всей миграции, код 7) → `\d` новых таблиц в `after.txt` → `cron-pause.sh off` всегда (trap),
но чужую паузу не трогает (код 4). Журнал — `~/backups/migrate/journal.log` (когда, итог, путь дампа, `bash …/rollback.sh`).
Отказ сразу: свои BEGIN/COMMIT, CONCURRENTLY/VACUUM, `--db` не dev. Сухой прогон `--dry-run` только читает базу (какие таблицы есть).
Самопроверка на заглушках — `tools/ops/db-migrate-safe.sh selftest` (в `pnpm test`: `tests/unit/db-migrate-safe.test.ts`).
Дампы не чистятся сами — ~800 МБ база, полный дамп сжатый заметно меньше; уборка руками.
Гарда — CI-job `db-init`: чистый postgres → вся прод-схема → второй проход (идемпотентность) →
проверка, что таблицы приложения на месте.

## Сторожа

- **Каталог (ADR-0172):** `remlab-catalog-watchdog.timer` 15:30 UTC — нет сегодняшнего статуса в
  `refresh-status.json` или `overall=FAIL` → Telegram. Kill-switch `DISABLED`, откат
  `systemctl disable --now`; юниты — `infra/server/systemd/`.
- **Диск и очистка (ADR-0005/0176):** `remlab-cleanup` weekly + из CI (теги `remlab-app:*` кроме
  используемых, под flock); `pg_dump` ×7; `remlab-watchdog.timer` ежечасно: ≥80% → cleanup →
  Telegram; рестарты `remlab-app` → `backups/app-mem.log`. Системный журнал прода ограничен 1 ГБ
  (`/etc/systemd/journald.conf.d/remlab-size.conf`, 12.11, вне репо: рос до 3,6 ГБ, свободное упало до 6,9 ГБ < ворот волн мешей 7 ГБ
  `tools/scout/salad/sink_health.py:verdict` — волны 18 ч не стартовали, урок 630).
- Скрипты `infra/server/*` деплой везёт по списку в `deploy.yml` (тот же список — `deploy.sh`), с 20.10 (T-20261020-02)
  в нём и `infra/server/db-backup.sh`, и `infra/server/scripts/catalog-watchdog.sh`; сторож `tests/unit/deploy-scripts.test.ts` — каждый
  `ExecStart=/opt/remlab/scripts/<файл>` из `infra/server/systemd/*.service` обязан быть в scp и `chmod +x` обоих списков.
  Руками остаются: юниты systemd (без `daemon-reload` в деплое), аварийный `draft-run.sh` (ADR-0278, на сервере — своя
  версия) и `infra/server/ads-watchdog/*` (свой `deploy-watchdog.sh`, сторожем `deploy-scripts.test.ts` не покрыт).
- **Ночная копия базы:** `remlab-db-backup.timer` 03:30 по часам сервера (в юните без UTC) → `/opt/remlab/scripts/db-backup.sh` →
  `/opt/remlab/backups/db-<ts>.sql.gz`; `cleanup.sh` оставляет 7, но идёт раз в неделю (вс 04:30), при деплое и от сторожа диска — на деле
  7–13 копий. Лежит на том же сервере, что и база (копии вне сервера нет — вопрос владельцу, `b2b-09`).

## Правки сервера 31.08
sshd, iptables-туннель DEV-рендера, `remlab-draft` через docker cp — ADR-0139
(бэкапы `*.bak-20260831`).

## Секреты
`.env` в `/opt/remlab` (вне git): `POSTGRES_PASSWORD` / `GEMINI_API_KEY` / `TRACE_ADMIN_TOKEN` и др. (полный список —
`environment:` app в `docker-compose.yml`; без `MESH_SINK_TOKEN` compose не стартует). Кадры — `/opt/remlab/draft/.env`.
Compose передаёт app ЯВНЫЙ `environment:`-список — новый ключ = правка compose.

## Caddy, статик и контейнеры — детали (вынесено из сводки 2026-09-05, сверено с кодом)
- Лимиты памяти (ADR-0004): app 1G / pg 1G / caddy 128M / imagor 256M / mesh-receiver 256M / draft 2200M, 2 CPU.
- `caddy/Caddyfile` проксирует `/api/{draft,warm,render,job,share}*` → `draft:8099` — это
  `tools/scout/draft_service.py` (DEV-рендер демо через обратный ssh-туннель, ADR-0139), сервис
  compose с 14.10 (ADR-0278). Блока `/lab/*` в Caddyfile нет и не было — `/lab/*` отдаёт Next (`remlab-app:3000`).
- Маршрут `/test/mesh-audit/*` (05.09, ADR-0194): `public, max-age=604800, immutable` для партий
  моделей и постеров приёмки; каталоги `/opt/remlab/test/mesh-audit/{releases,posters}` создаёт
  публикатор или руки. **Caddyfile едет деплоем (13.10, ADR-0256):** `deploy.yml` и `deploy.sh` кладут
  `caddy/Caddyfile.new`, `infra/server/caddy-sync.sh` (из `deploy-remote.sh`, до активации app) сверяет боевой
  со снимком `Caddyfile.deployed` (не совпал — ручная правка, стоп), `validate` через stdin, подмена `cat >`
  (bind по inode), `reload`, при провале — возврат бэкапа. Руками на сервере не править.
- Smoke: `deploy.yml` сверяет `ok=true` и `version == TARGET_SHA` на шаге `!cancelled()`; ручной
  `deploy.sh:55-74` решает успех по одному HTTP 200, `ok` не проверяет и версию только печатает.
- Очистка диска: `infra/server/cleanup.sh` + `infra/server/systemd/*.service`; таймеры — `infra/server/systemd/*.timer`.

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
- **Прибитые пути.** `/test/` встречается абсолютным путём в сотнях мест `tools/` (14.10: 306 строк в 67 файлах),
  каталог `/opt/remlab/test` = 4.6 ГБ. Новый публичный адрес вводить alias-маршрутом на тот же
  `root`, а не переносом файлов: иначе ломаются генераторы и уже разосланные ссылки.

## Проверка .env после машинной правки (перенесено из Tier 1, 11.10)
`infra/server/deploy-remote.sh` перезаписывает `/opt/remlab/.env` машинно (строки `REMLAB_IMAGE`, `APP_VERSION`, `REMLAB_DRAFT_IMAGE`).
Правило: после такой правки прогнать `docker compose config --quiet` — он молча подтверждает, что
файл разбирается. СТОРОЖА В СКРИПТАХ НЕТ: проверка процедурная, её делает человек (сверка 11.10).

## Безопасность (13.10, ADR-0256; перенесено из Tier 1)
- Инцидент 08.09 (ADR-0207): CVE-2025-55182 — на Next 15.5.4 приехал майнер; подняли до 15.5.25; журнал и заслон `@nextrce` в Caddy.
- ПДн — только в базе: заявки «отправить себе» — `share_requests` (90 дней) через внутреннюю ручку
  `app/api/internal/share-request/route.ts` (секрет `INTERNAL_API_TOKEN` в `/opt/remlab/.env` и
  `/opt/remlab/draft/.env`; снаружи Caddy 404 на `/api/internal/*`).
- Лимиты частоты и дневной потолок платного — `lib/ratelimit/*` (таблица `rate_limits`); у сервиса кадров —
  свой счёт в памяти (`tools/scout/draft_guard.py`).
- Закрыто без секрета: вебхук ЮKassa (IP + перезапрос API), Telegram-вебхуки (401), трейсы и подписанные
  фото в production; токен трейса — только заголовком `x-trace-token`.
- Заголовки на весь сайт: `frame-ancestors 'self'` (Caddy ставит его, только если приложение не поставило свой CSP — страница
  встраивания `/embed/…` ставит `frame-ancestors` с доменами партнёра, ADR-0283), `nosniff`, `Referrer-Policy` (`caddy/Caddyfile`).
- Ежечасный `infra/server/disk-watchdog.sh`: чистит просроченные `share_requests`/старые `rate_limits`, будит
  владельца при файлах `_queue` под веб-корнем и при расхождении `Caddyfile` со снимком `Caddyfile.deployed`.
- После деплоя — шаг `tools/security-smoke.sh` (13 проверок снаружи, без отката).
- `remlab-draft` с 14.10 — сервис compose (ADR-0278): образ `ghcr.io/…/remlab-draft:<sha>` собирает CI, деплой ждёт
  `/health` с версией и при сбое возвращает прежний образ; `infra/server/draft-run.sh` — только аварийный (урок 474).

## Прод без DEV — что ломается (13.10, план b2b-09, ADR-0266)
| С DEV зависит | DEV выключен — что видит покупатель/владелец | Через сколько | Что делать |
|---|---|---|---|
| Рендер кадров и фото «Сделать фото» (`tools/scout/dev_render_backend.sh`, туннель `172.18.0.1:8601`) | черновые кадры — прод сам падает на локальный рендер (`draft_service.py`, `backend`), дольше; платное фото (ключа шлюза на проде нет) и фото тура пробы — 503 `unavailable` | сразу | ничего; готовые кадры лежат на сервере |
| Ночной прогон каталога `refresh_daily.sh` (10:40 по DEV): цены, наличие, сборка и публикация демо | демо и 3D живут на последнем опубликованном `demo-data.json` (лежит на сервере); цены стареют | сутки | сторож каталога на сервере (15:30 UTC) шлёт тревогу |
| Конвейер мешей и сторож простоя Salad (`tools/scout/salad/idle_guard.sh`, cron DEV) | ноды Salad гасит сервер: нет отметки жизни конвейера 30 мин → `/stop` с проверкой — только группы с машинами (`pending` без машин — `no_machines`); файл `/opt/remlab/mesh/deadman-off-until` с датой в будущем отключает (`inhibited`) (`infra/server/salad-deadman.py`, ADR-0274) | ≤ 40 мин | ничего |
| Мост приёмки мешей (`mesh_review_sync.py`) | решения владельца на `/lab/mesh-*` копятся на сервере, не теряются | — | догонит при включении |
| Копия бэкапа вне сервера (`tools/ops/backup-pull.sh`, 04:15) и репетиция (`restore-drill.sh`, вс 04:30) | копии нет за эти сутки; дампы на сервере остаются (7 шт.) | — | после включения — `backup-pull.sh` руками |
| Публикация моделей/статики (scp с DEV) | новые модели не появляются | — | — |

Не зависит от DEV: сайт, демо, 3D, коллекции, ссылки менеджеров и сигналы (таймер на сервере), отчёт застройщику.

**DEV-рендер как юниты systemd пользователя (18.10, T-04):** `remlab-render` (draft_service, 127.0.0.1:8600, OOMScoreAdjust=200 — первая жертва earlyoom) и `remlab-render-tunnel` (ssh -R 172.18.0.1:8601, OOMScoreAdjust=100, RestartSec=3). Исходники — `tools/scout/systemd/*.service`; ставит и чинит `tools/scout/dev_render_backend.sh` (крон `*/10` — `infra/dev/crontab`; строки @reboot в копии crontab нет). Статус: `systemctl --user status remlab-render remlab-render-tunnel`; логи — `~/scout-scenes/dev-render.log`, `dev-tunnel.log`. Живой ли туннель — с сервера `curl 172.18.0.1:8601/health` (version "dev"); `/api/draft/paid` жив ли туннель прямо не показывает: без своего ключа шлюза прод берёт баланс у DEV `GET /credits` через туннель (кэш 30 с), туннель мёртв → `{available:false, code:"unavailable"}` — неотличимо от других причин (`tools/scout/draft_service.py`). Юнит пользователя не может получить OOMScoreAdjust ниже 100; защита ssh — `--avoid` в `/etc/default/earlyoom` (sudo).

**Память DEV (18.10, по слову владельца; к 10.11 RAM 15 ГБ — `free -g`):** было RAM 9,8 ГБ; своп `/swap.img` 4 ГБ + `/swap2.img` 8 ГБ (в `/etc/fstab`, копия `/etc/fstab.bak-20261018-1805`); zram 4,8 ГБ zstd, приоритет 100 (`/etc/systemd/zram-generator.conf`, `dev-zram0.swap`). Зачем: earlyoom (`-m 10,5 -s 10,5`) при полном свопе убивал draft_service и браузеры проверок. Перед пробами браузера — урок 512.
earlyoom (`/etc/default/earlyoom`, сверено 10.11): `-r 3600 -m 10,5 -s 10,5 --avoid (sshd|ssh|autossh|systemd…) --prefer (qemu|buildkitd|containerd-shim)` —
первым гасится сборщик образов, затем `remlab-render` (OOMScoreAdjust=200). Что съедало память 05–07.11: сухой прогон `orient_worker.decide` по 86 мешам
одним процессом (6 ГБ), тень ориентации каскадом (6,5 ГБ к 152-му мешу), рисовалка `mesh_render` пачкой (кэш `lite_parts`, 5,5 ГБ за ~40 моделей),
стенд паритета + orient_infer разом (05.11 earlyoom 8 раз за 5 мин снимал живое демо) — такие прогоны порциями в новых процессах и под очередью (ниже).

**Тяжёлые прогоны на DEV — только через общую очередь (05.11, T-20261105-57):** `tools/ops/heavy-slot.sh <метка> [--min-gb N] -- <команда>` или в питоне `with heavy_slot('<метка>', min_gb=6):` на шаг (`tools/ops/heavy_slot.py`). До пяти тяжёлых сразу (11.11, владелец, T-20261111-07; было три с 06.11, T-20261106-74; два, T-57/3): дополнительный слот (`slot<k>.lock`) — только пока занят другой и свободно ≥ Σ по держателям max(порог − PSS дерева держателя, 0) + свой + запас max(1 ГБ, 10 % RAM — ниже начинается SIGTERM earlyoom) (до T-74 порог держателя вычитался дважды — очередь стояла при простое CPU); одиночный — свободно ≥ свой порог, без запаса; сторож: свободно < запаса — новых не пускать. Пик PSS пишется в `~/.cache/remlab-heavy-slot/peaks.tsv`; порог по замеру (T-74; с ОДНОГО замера — T-20261106-91): есть засчитанный замер типа задачи (держание ≥ 30 с) → порог = min(объявленный, max(k × наибольший пик, 0,5 ГБ)), k = 2,0 при 1–2 замерах (следующий прогон типа доходил до 1,8× первого пика), 1,5 при 3+; держатель превысил свой порог в этом прогоне → его доля у следующих = max(объявленный, пик прогона) (`tools/ops/heavy_slot.py:eff_mult`, docstring «ПОРОГ ПО ЗАМЕРУ»); `--stats` — сводка замеров; держание > 45 мин — WARN в журнал. Обгон головы (T-20261106-79): голова не проходит по памяти — следующий, кто проходит сейчас, берёт дополнительный слот (слот 1 — всегда голове); голова ждёт головой ≥ `HEAVY_SLOT_BACKFILL_MIN` (20 мин, 0 — без обгона) — обгон закрыт, слоты стекают к ней; `--status` — строка ОБГОН. `HEAVY_SLOT_SLOTS=1` — строго по одному (flock `~/.cache/remlab-heavy-slot/slot.lock`), затем ждёт MemAvailable ≥ N; `--status` — кто держит/ждёт; журнал `~/remlab-logs/heavy-slot.log`; обход — только явный `--no-slot` (по слову ведущего): обёртка ставит `HEAVY_SLOT_NOSLOT=<pid>`, вложенные `heavy_slot` её потомков идут мимо очереди («без очереди по предку pid=…»), чужой процесс с тем же env ждёт (T-20261106-97, `heavy_slot.py:_noslot_parent`). Длинное (вырезка 1229 фото ≈ 7 ч) одним слотом запирает очередь — дробить на порции ≈ 30–40 мин, каждая — свой вызов. Разовые скрипты с рендером и прогрев демо — тоже под слотом (ночь 06→07.11: лист рабочего 5,5 ГБ мимо очереди + прогрев `--no-slot` → earlyoom снял рендер и buildkitd). Порядок — по классу `--prio` (0 обычный, 1 тур, 2 «Обустроить»; ждущий > 30 мин — старший), внутри — по приходу (билеты, T-57/2); сверх пяти — 1 резервный слот только для класса ≥ 1 (`HEAVY_SLOT_PRIO_SLOTS`); держатель, ждущий память > 10 мин, уступает тому, кому памяти хватает сейчас, не больше 3 раз (защита от голодания). Порог по задаче: при эксклюзивной очереди 5 ГБ хватает (orient_infer ~3,2 ГБ); 6+ при фоне 5,3–5,8 ГБ стоит часами. Свои циклы `free -m` не писать: разные пороги стартуют разом, и earlyoom снимает `remlab-render`. Самопроверка `tools/ops/heavy-slot-selftest.sh` (CI).
**Ядра и долгие (11.11, T-20261111-17; владелец TG 1488, 1490/1491):** в 13:55 нагрузка 24 на 15 ядрах (`nproc`) при свободной памяти: пять регрессов разбора `-j 3` в пяти слотах + 3D-страница в Playwright. Поэтому `--cores N` / `heavy_slot(cores=N)` — сколько ядер займёт задача (без ключа — выведено из команды, T-17/2, иначе 2: прочие старые вызовы 6 × 2 = 12 ≤ 15 — пускаются, как раньше); команда получает `HEAVY_SLOT_CORES` = целое ≤ N, `vitest.config.ts` берёт из неё maxWorkers/minWorkers (без переменной — как прежде, CI и сборка не меняются; `regress.py -j` задаёт сама команда; pytest-xdist на DEV не стоит); допуск — дополнительно к памяти и везде, где она проверяется (слот 1, дополнительный слот, обгон, уступка): Σ ядер других держателей + свои ≤ бюджета (`HEAVY_SLOT_CORES_BUDGET`, иначе `nproc`) (`tools/ops/heavy_slot.py:_cores_ok`). Держатель слота 1, ждущий память/ядра, бронирует свои ядра — обгоняющие их не займут; голова-билет ядра не бронирует, её мелкие обгоняют, пока действует защита 20 мин (как с памятью). Шире бюджета — только одна: ждёт слот 1 и в нём ухода держателей, бронь закрывает старт новым — не ждёт вечно. Класс ≥ 1 (проба агента) бюджет ядер не ждёт. Вывод ядер без `--cores` (`heavy_slot.py:cores_hint`, строка журнала «ядра выведены: N (по …)»; ключ перекрывает): регресс разбора `regress.py run … -j K` → K (без `-j` — 4); `pnpm test` / vitest / pytest → 3 (замер 11.11 при нагрузке 10–15: 638 с процессора за 245 с = 2,6 ядра в среднем, без `HEAVY_SLOT_CORES` vitest 2 пускал до `nproc` − 1 = 14 процессов), Playwright → 6 (3D без видеокарты рисует процессор; без 3D — укажи `--cores 2`), прочее, в т. ч. `pnpm typecheck` (1,75), → 2. Долгие — `--long` или по признаку в команде (`heavy_slot.py:long_auto`: `regress.py`, `playwright`, `pnpm e2e`, скрипт js/cjs/mjs/ts/py, подключающий playwright; `--short` — не считать): обёртка после взятия слота ставит себе `nice` +10 (`HEAVY_SLOT_LONG_NICE`), команда наследует — вливания и короткие тесты получают процессор первыми; очередь и допуск не меняются; в питоне `long=True` — только метка. `--status`: у держателя и ожидающего «ядер N», у долгого «долгая, nice 10» (фактический nice из /proc), строка «ЯДРА: держатели X из 15 … · нагрузка за 1 мин». Переходный период: процессы старой версии ядер не знают — их держатели считаются по 2.

## Сторож доступности и бэкапы вне сервера (13.10, ADR-0266)
- `/api/health` (`lib/health.ts`): `select 1` к базе (2 с) и витрина `demo-data.json`; база не ответила → `ok:false` и 503
  (смоук деплоя откатит выпуск). Витрина не загрузилась → `checks.showcase=fail`, но `ok:true`.
- `remlab-health-watch.timer` раз в 2 мин → `infra/server/health-watch.sh`: через Caddy и TLS проверяет `/api/health`,
  `/demo/`, `/api/draft/health`; две неудачи подряд → Telegram (бот из `/opt/remlab/catalog-watchdog/.env`), затем раз в
  час; восстановилось → «снова работает». Проверка без тревоги: `DRY=1 STATE=/tmp/x SITE=… health-watch.sh`.
  Юниты ставятся руками (`infra/server/systemd/remlab-health-watch.*`), скрипт обновляет деплой.
- Внешний монитор (смерть самого сервера) — выбор сервиса за владельцем (вопрос в `_intake/owner-questions.md`).
- Копия дампа: DEV `tools/ops/backup-pull.sh` (cron 04:15) → `~/remlab-backups`, 14 шт., проверки возраст ≤30 ч / gzip /
  размер ≥ половины прошлого. Репетиция: `tools/ops/restore-drill.sh` (cron вс 04:30) поднимает дамп во временном
  `pgvector/pgvector:pg17` (1 ГБ), считает таблицы и строки, удаляет контейнер; журнал `~/remlab-backups/drill.log`.
  Первая репетиция 13.10: 17 таблиц, 3 с, 0 ошибок. Шаг `dev_checks` в `refresh_daily.sh` (`tools/ops/dev-checks.sh`)
  кладёт в дайджест: диск DEV ≥85 %, копии нет >48 ч, репетиция не прошла.

## DEV: диск (13.10; 20.10 — 292 ГБ; к 10.11 — 391 ГБ)
20.10 диск растянут до 292 ГБ (по слову владельца, делал ведущий tamara), свободно ~62. До этого 94 % — `wave_guard`
отказывал в автозапуске волны («disk»). Крупное: `~/scout-scenes` 36 ГБ (меши 28; точных дублей 4,5 ГБ — почти все живые
копии галереи демо, решение 20.10 — не трогать, списки `~/remlab-logs/dupes-2010*.json`), `~/igor/tamara` 55, `~/igor/julia` 21.
Docker общий с tamara: автоочистка кэша сборок и безымянных образов `~/.local/bin/docker-clean.sh` (крон 05:40 UTC, ведёт tamara).

**Сторож места (07.11, T-20261107-48):** диск DEV к 10.11 — 391 ГБ, занято 95 % (`df -h /`); 07.11 оставалось 10–21 ГБ при резерве
tamara 25 ГБ. Ночной шаг `disk_keeper` (`tools/scout/refresh_daily.sh`) → `tools/ops/disk-keeper.py --apply --digest`: убирает только
БЕЛЫЙ СПИСОК `tools/scout/rules/dev-disk.json` — подпапки `~/remlab-scratch` (кроме `parity` и `tmp/node-compile-cache`, контейнер `tmp`), `~/remlab-logs`
(кроме `heavy-slot.log`, `batch-window.log`, `money-guard.log`), `~/onb06-out`, в `~/scout-scenes` — только папки задач по шаблонам
`only`, `never` (меши, галерея, кадры, `flat215-demo`) не трогает; папка старше `dir_days` 7 сут, журналы `log_days` 14; папку, которую
называет код, не трогает; свободно < `warn_free_gb` 30 → `WARN:disk_free`. Болванки `shape.glb` старше `shape_max_age_d` 14 сут
уходят и без приёмки меша (`tools/scout/salad/prune_shapes.py`; владелец 07.11 TG 486 — меняет условие ADR-0233), кроме стоящих в
очереди перегона/перекраски. Ручная уборка ведущего 06–07.11 — влитые worktree (`git worktree remove`), старые копии баз стенда
паритета (`remlab_parity_*`); нужное для стендов держать в `~/remlab-scratch`, не в worktree (банк-кандидат пропал вместе с worktree).

**Второй круг уборки (10.11, ADR-0379, T-20261110-30):** `tools/ops/disk_clean.py` по правилам `tools/scout/rules/dev-disk-clean.json`
(удаляет только `approved: true`; виды — влитые worktree, кэши стенда разбора планов, старые поколения мешей без ссылок, висячие тома
и контейнеры стендов БД; `.memory_bank`, `_secrets`, `.env*` не трогает никогда). Ночной шаг `disk_clean` в
`tools/scout/refresh_daily.sh:202` — с `--apply --digest`. Повод: 10.11 на 391 ГБ осталось 7 ГБ (47 влитых worktree — 16 ГБ).
Диск DEV к 12.11 — 411 ГБ.

## /demo: заранее сжатые копии (10.11, T-20261110-43/2)
`tools/scout/publish_demo.sh` после сборки кладёт рядом с текстами `.br` (brotli 11) и `.gz` (gzip 9) — `tools/scout/precompress.mjs`
(пересоздаёт при смене исходника, сирот убирает); не вышло целиком — убирает ВСЕ свои копии (устаревшая сжатая хуже сжатия на лету).
Caddy отдаёт их по `precompressed br gzip` (`caddy/Caddyfile`, блок /demo). Разметка /demo 411 → 290 КБ, данные 161 → 99 КБ.
Самопроверка — `tools/scout/tests/test_publish_demo.py` (`PUB_PRECOMPRESS_CMD`).

## DEV: `/tmp` — tmpfs с квотой; временное конвейера — на диск (07.11, T-20261107-02/13, урок 528)
`/tmp` на pakardev — tmpfs ~788 МБ с квотой на пользователя; его забивают чужие проекты (mycoruja-img 255 МБ), папки сессий
Claude и тысячи `playwright_*`. При квоте запись падает EDQUOT — часто молча (Bash-вывод теряется, скрипт с `rc 0`): ночь 06.11
публикация демо упала rc 2 без причины в журнале (tar и журнал шага в `/tmp`), ночь 07.11 — `demo_rt.sh` (вывод `publish_rt` в
`/tmp`) → демо не опубликовалось. Правило в коде: `tools/ops/remlab-tmp.sh` (shell, подключать через `.`) и `tools/scout/remlab_tmp.py`
задают `REMLAB_TMP` = `~/remlab-scratch/tmp` (shell: в CI при `CI`/`GITHUB_ACTIONS` и непустом `RUNNER_TEMP` — он; python: в CI без
`REMLAB_TMP` — `None` = системный `tempfile`, вне CI — `~/remlab-scratch/tmp`, только если `~/remlab-scratch` уже есть); `refresh_daily.sh` экспортирует `TMPDIR=$REMLAB_TMP` и пишет в
журнал свободное место; шаг `tmp_sweep` (`tools/ops/tmp-sweep.sh`) убирает своё старше суток; CI — `tools/scout/tests/test_tmp_hygiene.py`
(новый питон-тест с временным — `tempfile`, `/tmp` — сразу через `remlab_tmp.use`, иначе красный). gltfpack 0.24 пишет временные текстуры ЖЁСТКО
в `/tmp/gltfpack-temp*` (TMPDIR не слушает) и при EDQUOT кладёт `data:…ERR` с `rc 0` (ночь 07.11: 14 моделей / 28 копий `/rt/` белые на проде) — страховка: сторож текстур в
`tools/assets/runtime_mesh.py` (битая копия не пишется, без KTX2 — запасная JPEG; T-20261107-15). Venv, pip `TMPDIR`, песочницы рабочих — в `~/remlab-scratch`, не в `/tmp` и не в scratchpad сессии.

## CI: статус без токена, проверка перед пушем, «как в CI» (06–07.11, T-20261106-58, T-20261107-41)
- **Статус main** — `bash tools/ops/ci-status.sh` (публичный API `actions/workflows/<файл>/runs`, без входа; код 0/1/2) и ночной шаг
  `ci_status` → строка DIGEST, красный — `WARN:ci_status` (`tools/ops/ci_status.py`). `gh` на pakardev протух (401) — не нужен. Лимит API
  без токена — 60 запросов/час на адрес DEV (общий с ночными кронами): ждать CI не чаще раза в 3–5 мин (опрос раз в 30–45 с выжег лимит
  07.11 и 09.11); прод — `tools/ops/deploy-need.sh --status` (без GitHub). После каждого вливания кода — статус CI: 05.11 гейт был красным
  3 ч, 06.11 — с 15:18 весь день (деплой «skipped» ≥ 30 пушей), 07.11 — ~3 ч / 37 пушей.
- **Перед пушем** — `.git/hooks/pre-push` → ссылка на `tools/ops/prepush-check.sh` (`tools/ops/prepush_check.py`): карта «путь → команда»
  разбирается из `ci.yml` (команда касается файла, если запускает его или её исходник его упоминает/импортирует), окружение job + `CI=true`,
  `GITHUB_ACTIONS=true`, `RUNNER_TEMP`, потолок 120 с (не успел — не стоп, проверит CI), упало → пуш остановлен (обход `--no-verify`).
  pnpm/docker/playwright/pip/pytest локально не гоняет — их ловит только CI (e2e — урок 09.11). Хук — в `.git/hooks`, не в git: на новой
  копии поставить ссылкой.
- **«Как в CI» руками:** python в CI — 3.12 (`ci.yml`, job planner/scout-orient/scout-selftest), на DEV системный 3.14 (там `file://?v=` и
  forkserver ведут себя иначе) → `docker python:3.12-slim` под своим uid; новый питон-тест — в ЧИСТОМ venv 3.12 ровно с пакетами job
  (06.11 красный от opencv/pillow/pydantic/trimesh, которых в job нет; `trimesh.split` тянет scipy); env `CI=true GITHUB_ACTIONS=true
  RUNNER_TEMP=…` (без них `remlab-tmp.sh` ведёт себя иначе). Правка `tools/scout/bank_*` или `tools/scout/rules/bank-*.json` → прогнать
  `tools/scout/tests/test_bank_spec_golden.py` (эталон вывода selftest и shipped-rules побайтно), ожидаемое отличие — `--record` тем же коммитом.

## DEV после перезагрузки — что не встаёт само (20.10, урок 522)
- **`remlab-devdb`** — у контейнера была политика перезапуска `no`: после перезагрузки база стояла, конвейер и сборки
  падали на БД. 20.10 поставлено `docker update --restart unless-stopped remlab-devdb`.
- **Туннель рендера 8601** — порт на проде держала старая sshd-сессия прежнего туннеля (у sshd прода ClientAlive был
  выключен — мёртвый пир висит вечно), новый туннель получал «remote port forwarding failed», платные фото молча шли
  через запасной рендер прода (630 с вместо ~30). Профилактика: `/etc/ssh/sshd_config.d/remlab-keepalive.conf`
  (ClientAliveInterval 30, CountMax 3; бэкап `/root/sshd_config.d.bak-20261020-2004`) и сторож `tools/scout/tunnel_watch.sh`
  из `tools/scout/dev_render_backend.sh` — туннель не встаёт 10 мин → Telegram, не чаще раза в час.
- **Конвейер мешей** умирает с машиной; после загрузки поднимает `wave_guard` (если диск позволяет). Сторож денег
  `tools/scout/salad/money_guard.py` поднимается кроном и перечитывает `SALAD_GROUP` на каждом тике (T-24).
- 20.10 машину перезагружали дважды (смена ресурсов ВМ владельцем): ~18:00 UTC она поднялась с 1,5 ГБ ОЗУ, в 18:56 — с 9,5.

## Сервис кадров `remlab-draft` — образ из репозитория (13.10, ADR-0267; с 14.10 — compose и CI, ADR-0278)
**С 14.10 ниже — история и аварийный путь:** обычная выкатка — CI собирает образ, `deploy-remote.sh` поднимает сервис
compose (очередь кадров, прогрев, время кадра — ADR-0280). Прежняя ручная сборка на сервере: контекст `git archive HEAD` с файлами из `infra/draft/Dockerfile.dockerignore` →
`docker build -f infra/draft/Dockerfile --build-arg DRAFT_VERSION=<sha> -t remlab-draft:<sha> .`; переключение —
`/opt/remlab/scripts/draft-run.sh --image remlab-draft:<sha>` (снимок старого → `remlab-draft:prev`; не та версия в
`/health` — откат). Откат вручную: `draft-run.sh --image remlab-draft:prev`. Env — `/opt/remlab/draft/.env` (в нём
лишние секреты: POSTGRES_PASSWORD, TRACE_ADMIN_TOKEN — сервису не нужны, убрать при переезде в compose).
Перед ручным переключением (13.10, не скриптом) — канарейка: тот же запрос `/render` (`no_proxy:1`, `quality:draft`) старому и временному
контейнеру `remlab-draft-canary`, сравнить JPEG.

**Задания и деньги (14.10, ADR-0287):** задания — `/opt/remlab/test/share/jobs.json` (`tools/scout/draft_jobs.py`): деплой их
не теряет, черновики досчитываются после старта, платные — `lost`. Новый файл образа — в `COPY`, в проверку импортов и в
`infra/draft/Dockerfile.dockerignore` (урок 486). Перед платным «Улучшить» — баланс шлюза: у прода ключа нет, он спрашивает
DEV `GET /credits` через туннель (снаружи `/api/draft/credits` — 404, сумму не показываем); наружу — `GET /api/draft/paid`
(`{available, code}`). Порог — env `REALISTIC_MIN_BALANCE` (0,30 $) и `REALISTIC_COST_USD` (0,25 $ на идущее платное).
**DEV-рендер (14.10, урок 485; с 18.10 — юниты systemd, см. выше):** крон DEV раз в 10 минут — `tools/scout/dev_render_backend.sh`
— теперь сторож: ставит юниты, убивает процессы вне юнита, делает `systemctl --user restart remlab-render`, если `/health`
молчит; дайджест — `tools/ops/dev-checks.sh` `WARN:dev_render_down|tunnel|fallback|restart`. Перезапуск руками —
`systemctl --user restart remlab-render` (юнит `Restart=always`: убитый PID поднимется сам). [История до 18.10: убить PID
с порта 8600, затем `bash tools/scout/dev_render_backend.sh`.] Память: фоновый лист для
«Улучшить» не собирается без денег на шлюзе, сборщику — потолок `SRC_MEM_EXTRA_MB` (+1,5 ГБ), урок 485.

## Модели 3D демо — кэш (14.10, b2b-12)
`handle_path /test/mesh-pilot10/*` в `caddy/Caddyfile`: `Cache-Control: public, no-cache` (браузер хранит и перепроверяет
по ETag — 304 без тела) вместо `no-store` общего `/test/*`; `browse` сохранён. Для пилота тогда — первый вход в 3D ≈30 МБ; /demo теперь грузит лёгкие копии `/rt/` (`rt-meshes.json` →
`runtimeMeshes`, `tools/scout/flat215-demo/index.html:rtMeshes`; Caddy — `immutable`).
