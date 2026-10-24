---
workstream: mesh
slug: mesh-18-salad-job-queue
title: mesh-18 — задания на машины Salad через Job Queue вместо SSH-шлюза (у части машин вход Salad рвёт SSH до приветствия)
status: in_progress
created: 2026-10-24
updated: 2026-10-24
---

## Цель
Задание доходит до каждой прогретой машины, независимо от SSH-шлюза Salad. Цель по деньгам — ≈ 1,1 ₽/меш на low (расчёт mesh-17,
`~/remlab-logs/t24-01/ev-0109/model2.py`) при потолке 1,5 ₽.

## Источник задачи
mesh-17: ночь 23→24.10 — 108 из 202 прогретых машин раздатчик не увидел (54 % оплаты). Проба 24.10 (T-20261024-02, ≈ 8 ₽): у всех машин
`ssh_ip` = 195.181.163.241, ручной ssh — «kex_exchange_identification: Connection closed by remote host» при живом контейнере
(`~/remlab-logs/t24-02/`). Salad в документации признаёт машины без терминала и советует пересадку (Codex,
`_intake/codex/pool-transport-2026-10-24-answer.md` § 1). Рекомендация Codex § 2 — Salad Job Queues; свой pull — запасной.

## Что есть (сверено ведущим)
- Прошлая попытка 28.08 (`tools/scout/salad/submit.py:4`): очередь привязывали PATCH к существующей группе → `container_groups` пуст,
  задания `pending`. По документации `queue_connection` задаётся ТОЛЬКО при создании группы (Codex § 2) — причина ясна.
- Воркер — HTTP `/generate` на 8000 (`worker.py:156`), `/ready` честно 503 до прогрева (`worker.py:65`), `/health` всегда 200 (:49);
  логический `status:"failed"` при HTTP 200 (`worker.py:273`) → разбирать `output.status`; идемпотентность — `job_id` + `complete.json` (:193).
- Образ: есть wget и Python (`Dockerfile:55`), CMD — `Dockerfile:146`; `command` группы заменяет CMD целиком.
- `migrate_groups.py:94` не переносит `queue_connection`; создавать — отдельным путём (`recreate_group.py --create-only` или новый скрипт).

## Скоуп — что входит
1. **Бесплатно:** очередь `mesh-q` (API Salad), остановленная группа `mesh-q-canary` (autostart=false, 1 реплика, low, тот же образ и
   ресурсы, что mesh-low-10) с `queue_connection` 8000 `/generate`, readiness `/ready`; `command` — обёртка: скачать закреплённую
   версию `salad-http-job-queue-worker` с проверкой SHA-256 и запустить рядом с `python -u /app/worker.py` (оба процесса под присмотром,
   падение одного — выход контейнера). GET-проверка: `queue_connection` записана, у очереди группа видна; одно тестовое задание
   остаётся `pending`. Обёртку проверить локально (скачивание, sha, два процесса, остановка).
2. **Сборщик** результатов: задание очереди → статус (`pending/running/succeeded/failed`), `output.status` (ok/cached/failed/input_failed)
   → нынешняя политика повторов и учёт попыток (`mesh-run-progress.jsonl`); файлы по-прежнему в приёмник. Режим раздатчика
   `--transport queue` рядом с ssh (ssh не удалять).
3. **Платная канарейка — ⚑ владелец:** 1 реплика ~15–20 мин, одно реальное идемпотентное задание; критерий `pending → running →
   succeeded`, `complete.json` в приёмнике, SSH не использован; затем одна пересадка и повтор на второй машине. Стоп ≤ 15 ₽.
4. По итогу канарейки — решение о переводе mesh-low-10 (новой группой) — ⚑ владелец.

## Скоуп — что НЕ входит
- Пересборка образа; Container Gateway (таймаут 100 с — Codex § 2); удаление групп, мешей и ssh-пути.

## Файлы к изменению
- [ ] `tools/scout/salad/` — создание очереди/группы (новый скрипт или `recreate_group.py`), обёртка запуска, сборщик, режим транспорта
- [ ] `tools/scout/rules/salad-groups.json` — канарейка (выключенная по умолчанию), транспорт группы
- [ ] тесты пула + самопроверка обёртки и сборщика

## Критерии приёмки
- [ ] Бесплатная часть: GET показывает `queue_connection` и связь очередь↔группа; тестовое задание `pending`; обёртка проверена локально.
- [ ] Тесты пула зелёные; ssh-путь не сломан.
- [ ] Канарейка (после слова владельца): ≥ 2 машины, задания `succeeded`, `complete.json` в приёмнике, трата в отчёте.

## Definition of Done — память
- [ ] `core/mesh-pool.md` (+ `domain/mesh-pool-ops.md`): транспорт очереди; ADR «очередь Salad вместо SSH»; урок «queue_connection — только
  при создании группы»; `/memory-check`.

## Лог выполнения
- 2026-10-24 — план создан ведущим по итогу пробы T-20261024-02 и разбору Codex; бесплатная часть (п.1–2) — работник 2, T-20261024-03/1.
- 2026-10-24 — [работник 2] T-20261024-03/1, ветка `worktree-meshq` b0f6cffc: очередь `mesh-q` (id cc0a0187) и ОСТАНОВЛЕННАЯ группа `mesh-q-canary` созданы `salad/queue_setup.py` (образ и ресурсы = mesh-low-10, autostart false, 1 реплика, low, без шлюза, `queue_connection` 8000 `/generate`, готовность `/ready`, `command` = `queue_entry.sh` 989/1000 знаков, воркер очереди v0.7.0 sha256 074a329c…c9e4). GET группы: `queue_connection` записана; GET очереди: `container_groups` = [] (у остановленной группы — до старта не проверить; первый пункт канарейки). Тестовое задание f3260d38 — `pending`. Сборщик `salad/queue_run.py` + `ssh_run/batch_show --transport queue`; тесты `salad/tests_queue.py` (13 случаев + `--real` с настоящим бинарём) зелёные, tests_pool зелёный.

## Completion summary

### Уроки (ОБЯЗАТЕЛЬНО; для partial/cancelled — особенно)

## Follow-up work
