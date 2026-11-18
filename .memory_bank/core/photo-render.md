---
tier: 1
topic: photo-render
scope: Фото по кнопке — рендер, «Улучшить», машина Salad
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-11-18
importance: high
source: manual
status: working
source_of_truth: canonical
review_after: 2026-12-01
last_verified: 2026-11-17
---

# Фото по кнопке — рендер и улучшение

**Поток (ADR-0428):** 3D → «Сделать фото» → рендер Cycles 2 ракурсов с % → «Фото» → «Улучшить фото» (нейросеть по кадру рендера). /demo и туры одинаково.

**Где код:** маршруты `tools/scout/draft_service.py` (`POST /api/render/cycles`), `app/api/trial/[id]/photo/route.ts`; снимок
`tools/scout/render_snapshot.py`; очередь `tools/scout/render_jobs.py`; исполнитель `tools/scout/render_exec.py` по `RENDER_EXECUTOR` из юнита
`tools/scout/systemd/remlab-render.service` (урок 702); рендер `tools/scout/cycles_probe/render_cycles.py` (пресет v4, плечо светов
`data/flat3d/light-rules.json`); «Улучшить» — `improve-render-v5.5` + `improve_mode.match_luma` (`tools/scout/draft_render.py`).

**Машина (ADR-0429/0430):** Salad 4090 medium, боевая `render-4090m7` (образ jpg2), контроллер `tools/scout/render_gpu/render_machine.py`
(автостоп 20 мин / 4 ч / $2 в день, днём не держим); ассеты по sha (`tools/scout/salad/receiver.py`). Заготовка 16 комнат /demo —
`tools/scout/render_prewarm.py`. Время: повтор 0 с, смена 1 товара на прогретой 19–22 с (цель ≈15 с), CPU DEV 8–16 мин.

**Подготовка сцены:** кэш `render_exec._prep_key`, ключ кадров по содержимому `tools/scout/scene_inputs.py`, постоянные процессы
`tools/scout/cycles_probe/export_server.py`, картинки декора вне GLB (`RENDER_XIMG`); p50 гостиной 3,25 с. План `plans/render-prep-speed-01.md`.

**Сторож кадров:** `tools/scout/cycles_probe/frame_qa.py` — ворота в заказе (`render_exec.RenderBrak`, выкл `RENDER_QA_GATE=0`), ночной
шаг `tools/scout/render_gpu/qa_night.py` (03:10). План `plans/render-qa-gate-01.md`.

**Открыто:** заказ из ТУРА — `bad_item`: снимок ищет по `sid`, бандл тура его не несёт (`tools/scout/trial_bundle.py` `NEVER_KEYS`), у ковров
нет и `msid` → публичный ключ товара `sku.pid` (решение по Codex 18.11 — playbook § «День 18.11», T-20261118-03/9); перевод боевой на
образ с `qa_reports` (m11). Подробно — `domain/viz-fidelity-playbook.md` § «Фото по кнопке». Уроки 697–706.
