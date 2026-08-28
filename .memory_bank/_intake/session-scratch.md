# Session scratch — блокнот захвата на ходу (append-only)

> **Зачем.** Захватывать durable-факт/решение в МОМЕНТ, когда он принят (там он ярче всего),
> а не раскапывать весь диалог на выдохе в конце сессии. `/memory-check` (Этап 1) консолидирует
> эти строки в `.memory_bank/` и очищает блокнот. Это амортизирует дорогой захват и лечит
> «согласованное замерзание» (частый провал: работал → не записал).

> **Как писать.** Принял ADR-значимое/durable (решение, миграция, контракт/API, интеграция,
> смена этапа, неочевидная грабля) → СРАЗУ допиши 1–2 строки СЮДА, не прерывая работу.
> Формат: `- ГГГГ-ММ-ДД — <что> — <почему/куда в память>`. Это НЕ канон, а сырьё для консолидации.

> **Что НЕ писать.** То, что и так в коде/git (структура, разовые правки), и то, что важно
> только для этого диалога. Значения секретов — НИКОГДА (только в `_secrets/`, вне git).

<!-- SCRATCH START — /memory-check переносит обработанное в банк и усекает до этой метки -->
- 26.08 ОТКРЫТО (к следующему заходу): (1) плумбинг диагностики оси — `_axis_contract.media` пишет глобал, перетираемый последним вызовом place_media; (2) расхождение артефакт↔экспорт 4 см по ковру (`test_pose_hash_round_trip`, set10); (3) вердикт владельца по плану №210: set105-pylons собирает `two_sofas_2armchairs` — нужен пересмотр сторожа; (4) лесенка состава + сертификат низкого заполнения (Codex q13).
- Деплой mesh-queue-orientation (c073d1a): control plane в dev-БД (mesh_demand/mesh_jobs/asset_revisions/orientation_state — `mesh_queue.py`, схему создаёт сам); спрос = сеты + top-5 корзин candidates-index + резерв 30/роль по воротам; ingest = SHA-256 байтов фото (протокол-относительные URL фида чинить https:); идемпотентность доказана (повторный --run = 0 заданий, 1084 в очереди); экспорт батча совместим с salad/submit.py. Legacy Trellis-меши = superseded (не закрывают спрос — только Hunyuan/Salad).
- Каскад ориентации: `orient_infer.py` (venv orienter, матрица Кабшем resid=0, quat w≥0) + `orient_worker.py` (flock, каскад: символ по подтипу → up_tilt>15°=review → сиденье-авторитет → VLM qwen как второй свидетель, авто-разворот запрещён). Прогон 37 локальных: 30 auto, 7 review. `mesh_front.infer_seat_front(has_back=)` — банкетка со спинкой направлена.
- Страница /lab/mesh-review (прод): кука HMAC HttpOnly+SameSite=Strict, machine Bearer, fail-closed без env; таблицы mesh_review_tasks/decisions (007-mesh-review.sql в ОБА пути деплоя + migrate.mjs); DEV-мост `mesh_review_sync.py` (--push задачи с 4 ракурсами data-URL, --pull курсором после применения). Секреты MESH_REVIEW_* — сервер .env (бэкап .env.bak-meshreview), ~/.config/remlab/env, _secrets/ACCESS.md.
- Правило «сеты только с мешами»: единый предикат `mesh_ready.py` (accepted не-legacy ревизия + решённая ориентация), фазы off/shadow/hard_new/rolling/full через MESH_GATE_PHASE; hard fail-closed в _slot_ok; shadow-отчёт покрытия в refresh_daily (сейчас 0/126 — Salad-ассетов ещё нет). CI: job scout-orient (orient_selftest на процедурной фикстуре).
