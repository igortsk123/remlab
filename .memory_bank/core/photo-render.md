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

**Поток (ADR-0428; вкладка — T-20261117-20/2, ещё не в main):** 3D → «Сделать фото» (нет фото этой расстановки или её изменили) →
рендер Cycles 2 ракурсов с % → «Фото» → «Улучшить фото» (нейросеть по кадру рендера) → улучшенное. /demo и туры одинаково.

**Где код:** маршруты — `tools/scout/draft_service.py` (`POST /api/render/cycles`), `app/api/trial/[id]/photo/route.ts` (`mode:"render"`);
снимок — `tools/scout/render_snapshot.py`; очередь и пределы — `tools/scout/render_jobs.py`; исполнитель — `tools/scout/render_exec.py`
по `RENDER_EXECUTOR` из юнита `tools/scout/systemd/remlab-render.service` (= `salad-gpu,local-cpu`; без неё — только CPU, урок 702);
рендер — `tools/scout/cycles_probe/render_cycles.py` (сторож картин `wall_art.has_content`, вход как в 3D — `wall_art.art_stats`);
«Улучшить» — промпт `improve-render-v5.4` + выравнивание яркости `improve_mode.match_luma` в `tools/scout/draft_render.py` (ADR-0419).

**Машина (ADR-0429 + поправки):** Salad RTX 4090 medium, группа `render-4090m4`, контроллер `tools/scout/render_gpu/render_machine.py`
(автостоп 20 мин / 4 ч / $2 в день), пакет fmt 2 — ассеты по sha256 в приёмнике `tools/scout/salad/receiver.py`; запас fmt 2 → fmt 1 → CPU.
Время (18.11, живой 8600): повтор 0 с, прогретая 20–30 с, новый вариант ≈30–47 с; CPU DEV 8–16 мин.

**Открыто:** заказ из ТУРА — `bad_item` на каждом варианте: снимок ищет товары по `sid` (`render_snapshot.sku_index`,
`lib/trial/repo-render.ts:collectSkus`), а публичный бандл тура `sid` не несёт по правилу (`tools/scout/trial_bundle.py` `NEVER_KEYS`) →
контракт по `msid` (T-20/3, до выкладки вкладки в турах); подогрев ассетов и срок по исполнителю (T-24/7), вкладка T-20/2, солнечные пятна в «Улучшить». Подробно —
`domain/viz-fidelity-playbook.md` § «Фото по кнопке — устройство подробно». Уроки 697–702.
