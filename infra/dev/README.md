# DEV-конвейер remlab на другой машине (b2b-08 п.1)

Что это: всё, что сейчас делает домашний компьютер — загрузка каталога, обогащение и стиль, заказ моделей на Salad и
сторожа денег, сборка и публикация демо, ночной экзамен расстановки, копии базы прода — в двух контейнерах:
`remlab-devdb` (база каталога) и `remlab-dev` (скрипты по расписанию `infra/dev/crontab`).

## Запуск (≈ 30 минут)
1. Linux с Docker. `git clone` репозитория в `/home/pakar/igor/remlab` (пути внутри повторяют домашние).
2. Перенести со старой машины: `~/scout-scenes/` (сцены, меши, фиды — десятки ГБ; без мешей конвейер работает, но
   заново заказывает модели), `~/.ssh/` (ключ к серверу), `tools/scout/.env`, `tools/scout/.env.alert`,
   `~/scout-scenes/salad.env` — значения в `.memory_bank/_secrets/ACCESS.md` (вне git).
3. `infra/dev/.env`: `DEVDB_PASSWORD=…`, `DOCKER_GID=$(getent group docker | cut -d: -f3)`.
4. База: `docker compose -f infra/dev/docker-compose.yml up -d devdb`, затем залить дамп старой базы
   (`docker exec remlab-devdb pg_dump -U remlab remlab > dev.sql` на старой машине →
   `docker exec -i remlab-devdb psql -U remlab remlab < dev.sql` на новой). С нуля — `tools/scout/bootstrap.sql` и
   миграции `tools/scout/0*.sql` (так собирает интеграционный тест `tools/scout/tests/pipeline_chain_dbtest.py`).
5. `docker compose -f infra/dev/docker-compose.yml up -d --build dev`.
6. На старой машине закомментировать строки remlab в `crontab -e` — два расписания одновременно дадут двойные волны.

## Проверка «работает»
- `docker ps` — `remlab-dev` healthy (ночной прогон был за последние 30 часов; первые 2 часа — «starting»).
- `docker exec remlab-dev /home/pakar/venvs/scout/bin/python tools/scout/tests/pipeline_chain_dbtest.py` — зелёный.
- Утром — дайджест в Telegram, страница `/test/pipeline/` обновилась.

## Что не входит
Ночной экзамен с 10 воркерами просит памяти (8 ГБ лимит); браузерные шаги (`demo_live`, `demo_warm`) требуют
Playwright один раз: системные пакеты — `docker exec -u root remlab-dev npx playwright install-deps chromium`, браузер —
`docker exec remlab-dev npx playwright install chromium` (в контейнере Debian: в `tools/ops/node-env.sh` подмену платформы
`PLAYWRIGHT_HOST_PLATFORM_OVERRIDE` для контейнера убрать). Сервис рендера DEV (`tools/scout/dev_render_backend.sh`,
ускоритель кадров через туннель) в контейнер не входит — без него кадры делает сервер (ADR-0280).
