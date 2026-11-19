---
tier: 1
topic: photo-render
scope: Фото по кнопке — рендер, «Улучшить», машина Salad
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-11-19
importance: high
source: manual
status: working
source_of_truth: canonical
review_after: 2026-12-01
last_verified: 2026-11-18
---

# Фото по кнопке — рендер и улучшение

**Поток (ADR-0428):** 3D → «Сделать фото» → рендер Cycles 2 ракурсов с % → «Фото» → «Улучшить фото» (нейросеть по кадру). /demo и туры одинаково.

**Где код:** маршруты `tools/scout/draft_service.py` (`POST /api/render/cycles`), `app/api/trial/[id]/photo/route.ts`; снимок
`tools/scout/render_snapshot.py`; очередь `tools/scout/render_jobs.py`; исполнитель `tools/scout/render_exec.py` по `RENDER_EXECUTOR` из юнита
`tools/scout/systemd/remlab-render.service` (урок 702); рендер `tools/scout/cycles_probe/render_cycles.py` (пресет v4, плечо светов
`data/flat3d/light-rules.json`); «Улучшить» — `improve-render-v5.5` + `improve_mode.match_luma` (`tools/scout/improve_mode.py:69,77`).

**Машина (ADR-0429/0430/0432):** Salad 4090, группа — `tools/scout/rules/salad-groups.json` (18.11 `render-4090m13`), контроллер
`tools/scout/render_gpu/render_machine.py` (автостоп 20 мин, $3/день; расход по меткам `--by` — `state.spent_by`; смена группы гасит прежнюю, сироты — `infra/server/render-guard.py`).
**Заказ человека включает машину** (`on --by order`, ≤360 с, поле `machine`; CPU — только при сбое). Заготовка /demo — `tools/scout/render_prewarm.py`
(`render_jobs.WARM_SUFFIX`; потолок — по своим тратам, ADR-0434). Тур греет машину с получения фото, рендеры по версиям —
`tools/scout/render_tour.py` (ADR-0435, выкл `TRIAL_TOUR_WARM=0` — читает `tools/floorplan/worker.py:430`). Холодный старт ≈2 мин, ≈$0,0025 за рендер.

**Какое фото в окне (ADR-0434):** только снимок текущего состава — `index.html:realPubPick` + `tools/scout/rules/demo-photo-pick.json`; готовый
рендер нетронутого варианта — `check` сервиса. Ключ кадра по комнате — `tools/scout/render_input.py` (за `RENDER_KEY_V2`, план `render-key-01`).

**Подготовка:** кэш `render_exec._prep_key` (урок 707). **Сторож кадров:** `tools/scout/cycles_probe/frame_qa.py` (выкл
`RENDER_QA_GATE=0`), ночью `tools/scout/render_gpu/qa_night.py`.

**Заказ из тура:** ключ товара `sku.pid` (`tools/scout/trial_bundle.py:pid_of`), снимок ищет по `sid` или `pid` — подробно в Tier 2.
**Ожидание (ADR-0439):** заказ живёт вне окна — `index.html:ordersResume`. Ключ тура = страницы — ADR-0442, урок 726; скорость — ADR-0444.
Открыто: ADR-0419 на пересмотре (TG 1811). Подробно — `domain/viz-fidelity-playbook.md`. Уроки 697–720.
