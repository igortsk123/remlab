## Вывод

Диагноз основной красноты верен: `008/009` ошибочно попали в prod-схему. Но план в текущем виде не починит деплой: после `git mv` старые `008/009` останутся на сервере, а серверный glob продолжит их выполнять.

Кроме того, C нельзя применять как единый «smoke+rollback». `!cancelled()` корректно заставит шаг выполниться после ошибки, но smoke увидит старую или уже запущенную новую версию с HTTP 200 и примет её за успешный деплой. Нужны раздельные стадии: подготовка → миграции → активация → проверка именно целевого SHA → условный rollback.

## 1. Диагноз и вторая причина красноты

### [блокер] Перенос файлов не удаляет серверные копии

Workflow только копирует текущие SQL поверх существующего каталога:

- [deploy.yml:84](/home/pakar/igor/remlab/.github/workflows/deploy.yml:84)
- затем выполняет **все** `/docker-entrypoint-initdb.d/*.sql`: [deploy.yml:96](/home/pakar/igor/remlab/.github/workflows/deploy.yml:96)

Каталог примонтирован непосредственно с сервера: [docker-compose.yml:116](/home/pakar/igor/remlab/docker-compose.yml:116).

После `git mv` серверные `008-mesh-binding.sql` и `009-photo-origin.sql` никуда не исчезнут. Следующий workflow снова упадёт на старом `008`.

Нужно синхронизировать каталог как репозиторно-владеемый набор, например scoped `rsync --delete`, либо перед применением удалять серверные `*.sql`, отсутствующие в явном manifest. Простого `scp` недостаточно.

### [блокер] Деплоится не обязательно тот коммит, который прошёл CI

Workflow запускается через `workflow_run`, но делает checkout ветки `main`: [deploy.yml:31](/home/pakar/igor/remlab/.github/workflows/deploy.yml:31), а образ тегирует `${{ github.sha }}`: [deploy.yml:63](/home/pakar/igor/remlab/.github/workflows/deploy.yml:63).

Для события `workflow_run` `GITHUB_SHA` — последний коммит default branch, а не обязательно SHA завершившегося CI. Это прямо указано в [документации GitHub](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run). Значит workflow способен собрать более свежий, ещё не проверенный коммит.

Для автоматического запуска источником должен быть `github.event.workflow_run.head_sha`; checkout, тег образа, `APP_VERSION` и smoke должны использовать один `TARGET_SHA`. Для ручного запуска — отдельный явно вычисленный SHA.

### [важно] Разброс 100 запусков я подтвердить не смог

Доступ к GitHub API из текущего окружения закрыт, поэтому независимо проверить логи всех 100 прогонов нельзя. Представленный лог и код доказывают детерминированную причину всех запусков, дошедших до SQL-цикла после появления `008`, но не исключают дополнительные сетевые/SSH/GHCR-сбои в отдельных прогонах.

## 2. Критика правки C

`if: ${{ !cancelled() && ... }}` действительно выполнит шаг после предыдущей ошибки: наличие status-функции отменяет неявное `success()`. GitHub рекомендует `!cancelled()` вместо `always()` для таких случаев: [GitHub Actions expressions](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#status-check-functions).

Но бизнес-логика шага останется опасной:

- Если деплой упал до `compose up`, smoke увидит старый prod с 200 и запустит cleanup.
- Сейчас `compose up -d` выполняется **до миграций**: [deploy.yml:93](/home/pakar/igor/remlab/.github/workflows/deploy.yml:93). Поэтому при ошибке SQL новая версия уже может работать; smoke увидит 200 и не откатит её.
- Проверяется только HTTP-код, хотя health возвращает `version`: [health.ts:13](/home/pakar/igor/remlab/lib/health.ts:13).
- `prev` создаётся из `${IMAGE}:latest`, а не из образа реально работающего контейнера: [deploy.yml:92](/home/pakar/igor/remlab/.github/workflows/deploy.yml:92). Это может быть не фактическая предыдущая версия.
- Rollback образа не откатывает уже применённые миграции.

Успешный поздний шаг не «озеленит» ранее упавший шаг: ненулевой exit остаётся failure всего job. Это подтверждается [контрактом exit codes GitHub Actions](https://docs.github.com/en/actions/how-tos/create-and-publish-actions/set-exit-codes). Опасность другая — ложный smoke и неверное действие, а не зелёный статус.

Рекомендуемая структура:

1. Синхронизировать файлы и проверить prerequisites.
2. Зафиксировать image ID реально работающего `remlab-app` как rollback target.
3. Применить backward-compatible миграции **до** переключения приложения.
4. Отдельным шагом активировать новый образ.
5. Проверить `200`, `ok=true` и `version == TARGET_SHA`.
6. Rollback запускать только если target фактически активирован и его smoke провален.
7. Cleanup запускать только после успешной проверки точного SHA.

`continue-on-error` на SQL категорически не подходит: он разрешит запуск приложения с неподготовленной схемой. Отдельный rollback-job возможен, но для этого проекта сложнее и требует надёжной передачи состояния. Лучше отдельные steps одного job.

## 3. Перенос в `tools/scout/006/007`

### [блокер] «Содержимое не меняю» не работает

`008` зависит сразу от трёх таблиц:

- `products`: [008-mesh-binding.sql:14](/home/pakar/igor/remlab/db/init/008-mesh-binding.sql:14)
- `asset_revisions`: [008-mesh-binding.sql:27](/home/pakar/igor/remlab/db/init/008-mesh-binding.sql:27)
- `mesh_demand`: [008-mesh-binding.sql:33](/home/pakar/igor/remlab/db/init/008-mesh-binding.sql:33)

`bootstrap.sql` создаёт только `products` и `scrape_queue`: [bootstrap.sql:5](/home/pakar/igor/remlab/tools/scout/bootstrap.sql:5). Control-plane таблицы создаются runtime-строкой Python: [mesh_queue.py:61](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:61).

Поэтому перенесённый `006-mesh-binding.sql` упадёт на чистой dev-БД даже после `bootstrap.sql`. Это нельзя оставлять follow-up, если критерий плана — работоспособная цепочка миграций.

Правильный порядок:

1. `bootstrap.sql` как формально описанный baseline либо полноценная `000-baseline.sql`.
2. Миграции `001–005`.
3. Миграция создания `mesh_demand`, `mesh_jobs`, `asset_revisions`, `orientation_state`, `product_photo_current`, `photo_assessment`.
4. Миграция mesh-binding и view.
5. Миграция photo-origin.

Runtime-DDL из `mesh_queue.py` должен исчезнуть либо читать тот же канонический SQL. Два независимых определения схемы снова разойдутся.

Номер `006/007` сам по себе не конфликтует, но предложенный порядок зависимостей неверен.

## 4. CI-гарда

Идея правильная, но одной чистой БД и двух `psql`-проходов недостаточно.

### Обязательно

- Если это отдельная job, ей нужен собственный Postgres service: service из job `gate` между jobs не разделяется — [ci.yml:9](/home/pakar/igor/remlab/.github/workflows/ci.yml:9).
- Использовать тот же `pgvector/pgvector:pg17`, пользователя и `ON_ERROR_STOP=1`, что и prod.
- Выполнять файлы строго в сортированном порядке.
- Первый проход проверяет чистую инициализацию, второй — повторное применение.
- Вынести цикл применения в один репозиторный скрипт и вызывать его из CI, GitHub deploy и ручного deploy. Иначе CI тестирует похожий, но не идентичный путь.
- Проверить конечные обязательные таблицы/indexes, а не только exit code.

### Ограничения гарды

- Чистый checkout не обнаружит старые лишние SQL на сервере. Это закрывается только manifest-sync/`--delete`.
- Два прогона по чистой схеме не проверяют upgrade с реального исторического состояния prod.
- Прямой `psql` воспроизводит явную миграцию deploy, но не полностью Docker entrypoint. В данном случае это нормально, потому что prod тоже вручную повторяет файлы; отдельно полезен один тест инициализации пустого volume через entrypoint.

## 5. Другие расхождения prod-пути

### [важно] Ручной и GitHub-деплой уже расходятся

Ручной deploy копирует явные `001–007`: [deploy.sh:44](/home/pakar/igor/remlab/deploy.sh:44), но при миграции применяет только `002–006`: [deploy.sh:57](/home/pakar/igor/remlab/deploy.sh:57). На существующей БД он не применяет `007-mesh-review`.

Пункт плана «ручной deploy не трогаем» неверен. Оба пути должны использовать один migration runner и один manifest файлов.

### [важно] Prod собирается из нескольких несинхронизированных источников схемы

Прод-схема одновременно описана в:

- `db/init/*.sql`;
- [tools/migrate.mjs](/home/pakar/igor/remlab/tools/migrate.mjs:12);
- [db/schema.ts](/home/pakar/igor/remlab/db/schema.ts:167).

CI-тест только `db/init` не обнаружит их расхождение. Минимум — schema assertion для таблиц, используемых приложением; лучше постепенно оставить один миграционный источник.

### [важно] Часть серверного runtime остаётся ручной

`mesh-receiver` запускает файл `/opt/remlab/mesh-receiver.py`, который «кладётся руками»: [docker-compose.yml:130](/home/pakar/igor/remlab/docker-compose.yml:130). GitHub workflow не доставляет ни его, ни `caddy/Caddyfile`, ни `infra/server/*`; он копирует лишь compose и SQL: [deploy.yml:84](/home/pakar/igor/remlab/.github/workflows/deploy.yml:84).

Следовательно, commit может менять receiver/Caddy/watchdog, успешно «деплоиться», но prod останется на старом коде. Это тот же класс дефекта границы владения.

### [важно] Серверный deploy-lock не охватывает деплой целиком

`cleanup.sh` использует `/opt/remlab/.deploy.lock`: [cleanup.sh:11](/home/pakar/igor/remlab/infra/server/cleanup.sh:11), но GitHub workflow держит его только внутри отдельного вызова cleanup. Pull/tag/compose проходят уже без lock. Watchdog-cleanup может снять новый SHA-тег между pull и запуском.

Нужен один серверный lock вокруг всей критической секции stage/migrate/activate/smoke/cleanup.

## Рекомендация

До начала кода изменить план так:

1. Добавить удаление серверных `008/009` и далее синхронизировать `db/init` с удалением лишних repo-owned SQL.
2. Использовать `workflow_run.head_sha`, а не `main`/`github.sha`.
3. Разделить deploy на prepare, migrate, activate, smoke exact SHA, rollback.
4. Проверять в health точный `version`, не только 200.
5. Создавать `prev` из image ID работающего контейнера.
6. Не использовать общий smoke-step после любой ошибки; `!cancelled()` оставить для state reconciliation/rollback.
7. Не переносить `008` неизменённым: сначала мигрировать control-plane DDL из `mesh_queue.py`.
8. Объединить migration runner GitHub и ручного deploy.
9. Добавить в CI fresh-init, second-pass и конечные schema assertions.
10. Зафиксировать, какие server-side файлы принадлежат deploy, и доставлять их либо явно исключить из обещания «prod == commit».

После этого перенос каталожных SQL из `db/init` — правильное решение.

## Неопределённости

Вывод о единой причине всех 100 красных запусков изменят полные логи этих runs: сейчас доказан один детерминированный блокер, но не отсутствие дополнительных ошибок. Также нужно проверить на сервере:

- фактический список `/opt/remlab/db/init/*.sql`;
- совпадает ли `ghcr.io/...:latest` с image ID работающего `remlab-app`;
- точный JSON `/api/health`;
- применялись ли когда-либо `tools/migrate.mjs` и `007-mesh-review` вручную.