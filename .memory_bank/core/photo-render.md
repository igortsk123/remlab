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

**Машина (ADR-0429/0430/0432):** Salad 4090, группа — `tools/scout/rules/salad-groups.json` (18.11 `render-4090m13`), контроллер
`tools/scout/render_gpu/render_machine.py` (автостоп 20 мин, $2/день; смена группы гасит прежнюю, сироты — `infra/server/render-guard.py`).
**Заказ человека включает машину** (`on --by order`, ≤360 с, поле `machine`; CPU — только при сбое). Заготовка /demo — `tools/scout/render_prewarm.py`
(`render_jobs.WARM_SUFFIX`). Смена товара p50 17,3 с (машина 8–11), холодный старт ≈2 мин, ≈$0,0025 за рендер.

**Подготовка:** кэш `render_exec._prep_key`, ключ `tools/scout/scene_inputs.py`, процессы живут 1200 с + `warm_prep`, лента замен — в горячем
списке (`tools/scout/render_gpu/showcase_assets.py`); p50 гостиной 1,46 с; подпись кэша без mtime (урок 707).

**Сторож кадров:** `tools/scout/cycles_probe/frame_qa.py` — ворота в заказе (`render_exec.RenderBrak`, выкл `RENDER_QA_GATE=0`), ночной
шаг `tools/scout/render_gpu/qa_night.py` (03:10). План `plans/render-qa-gate-01.md`.

**Заказ из тура:** публичный ключ товара `sku.pid` (`tools/scout/trial_bundle.py:pid_of`), снимок ищет по `sid` или `pid`
(`tools/scout/render_snapshot.py:pid_index`), ковёр/картина/зеркало без меша — по `ref`; отделка по умолчанию (`export_scene.with_default_finish`).
Туры получат `pid` перевыпуском `--carry-pids-by-img`. Новый поток на /demo — после выкатки сервера (ADR-0433). Открыто: ADR-0419 на пересмотре
(TG 1811). Подробно — `domain/viz-fidelity-playbook.md`. Уроки 697–712.
