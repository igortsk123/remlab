# Разбор: «Deploy prod» падает с 01.09, smoke-тест и авто-откат не выполняются

Ты — независимый senior-ревьюер. Не считай мою гипотезу верной: проверь по репозиторию сам.

## Что изменилось с прошлого раза
Последние коммиты `main`: `0ba3531` (mem), `d421d38` (feat(hub): ссылка на отчёт честности
каталога), `0507857` (mem), `0d1bec3`, `fe93010`. Прод на `0ba3531`, отвечает 200.

## НАБЛЮДАЕМЫЕ ФАКТЫ (без выводов)
1. Workflow `.github/workflows/deploy.yml` («Deploy prod») не имел ни одного успешного прогона за
   последние 100 запусков; первое падение — 2026-09-01T13:56Z.
2. Падает шаг «Деплой на сервер». Хвост лога job 101256447530 (run 33947613836):
   `psql:/docker-entrypoint-initdb.d/008-mesh-binding.sql:14: ERROR:  relation "products" does not exist`
   `##[error]Process completed with exit code 1.`
   Предыдущие файлы 003–007 применились (NOTICE «already exists, skipping»).
3. На боевой БД (`ssh root@… docker compose exec db psql -c '\dt'`) 12 таблиц: estimates,
   generation_assets, generation_runs, generation_steps, lead_messages, leads, link_clicks,
   link_routes, mesh_review_decisions, mesh_review_tasks, projects, style_results.
   Таблиц `products`, `mesh_demand`, `asset_revisions` там нет.
4. `db/init/008-mesh-binding.sql` и `db/init/009-photo-origin.sql` добавлены 01.09
   (коммиты a5196c7, e4129eb) и обращаются к `products`, `asset_revisions`, `mesh_demand`.
5. `tools/scout/db_migrate.py` (docstring) описывает контракт: каталог живёт только на дев-БД
   `remlab-devdb`, миграции каталога — `tools/scout/NNN-*.sql`; там сейчас 001–005.
6. `tools/scout/mesh_queue.py:62,84` создаёт `mesh_demand` и `asset_revisions` строкой
   `create table if not exists` в рантайме, а не миграцией.
7. Ручной `deploy.sh:44-50` перечисляет SQL-файлы явно (001–007) и не падает; в
   `deploy.yml:85` — глоб `scp db/init/*.sql`.
8. На дев-БД `products` уже имеет колонки из обоих файлов (mesh_*, photo_*) и оба индекса
   `products_photo_collage_idx`, `products_mesh_from_collage_idx`.
9. Grep по `app/ lib/ db/` не находит запросов к таблице `products` из Next-приложения.
10. `.github/workflows/ci.yml`, job `gate`, уже поднимает сервис `pgvector/pgvector:pg17`
    с комментарием «готов для integration-тестов Stage 1 (пока не используется)».

## МОЙ ПЛАН (критикуй)
Файл `.memory_bank/plans/deploy-db-init-scope-fix.md`. Кратко:
- A. `git mv db/init/008-mesh-binding.sql tools/scout/006-mesh-binding.sql` и
  `db/init/009-photo-origin.sql → tools/scout/007-photo-origin.sql` (содержимое не меняю).
- B. Новая CI-job `db-init`: поднять чистый postgres, применить `db/init/*.sql` по порядку
  с `ON_ERROR_STOP=1`, затем применить ВТОРОЙ раз (проверка идемпотентности — прод применяет их
  на каждом деплое). Цель: ловить ЛЮБУЮ поломку прод-инициализации, не только эту.
- C. В `deploy.yml` шагу «Smoke-тест + откат при провале» поставить
  `if: ${{ !cancelled() && steps.gate.outputs.ready == 'true' }}`, чтобы страховка (проверка
  health + откат на `remlab-app:prev`) выполнялась и когда предыдущий шаг упал.
- D. ADR + правка памяти; вынести в follow-up долг: control-plane таблицы из `mesh_queue.py`
  не покрыты миграциями, поэтому на ЧИСТОЙ дев-БД `db_migrate.py` упадёт на новом `006-*`.

## ВОПРОСЫ
1. Верен ли диагноз и полон ли он? Нет ли ВТОРОЙ причины красноты «Deploy prod» (например,
   шаг деплоя мог падать по другой причине в других прогонах — проверь разброс).
2. Правка C: не создаёт ли она опасного поведения? Меня беспокоят сценарии: (а) шаг деплоя упал
   ДО `docker compose up -d` — smoke увидит живой старый сайт, вернёт 0 и запустит cleanup.sh;
   (б) smoke сделает откат на `:prev`, хотя реальная причина не в образе; (в) не «позеленеет» ли
   job целиком. Что лучше: `!cancelled()`, `always()`, отдельный job, или step-level `continue-on-error`
   на SQL-шаге? Обоснуй по семантике GitHub Actions.
3. Правка A: нумерация 006/007 в `tools/scout/` — нет ли конфликта порядка применения с 001–005
   и с `bootstrap.sql`? Стоит ли разбивать 008 на «только products» и «asset_revisions + view»,
   учитывая факт 6 (зависимость от рантайм-таблиц)?
4. Правка B: как надёжнее реализовать гарду в CI? Достаточно ли `psql -f` по файлам из глоба,
   или нужно точно воспроизводить прод-путь (docker entrypoint, порядок, пользователь, extensions
   из 001)? Не даст ли она ложную зелёность/красноту?
5. Есть ли в репозитории ДРУГИЕ места, где дев-артефакты просачиваются в прод-путь деплоя
   (по аналогии), которые стоит закрыть тем же приёмом?
6. Что я упускаю: риски, побочные эффекты, лучшие альтернативы?

Не меняй файлы. Верни: вывод; доказательства с путями и строками; риски; альтернативы;
рекомендацию; неопределённости; какие данные изменили бы твой вывод.
