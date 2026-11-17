---
tier: 1
topic: photo-render
scope: Фото по кнопке — рендер, «Улучшить», машина Salad
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-11-17
importance: high
source: manual
status: working
source_of_truth: canonical
review_after: 2026-12-01
last_verified: 2026-11-17
---

# Фото по кнопке — рендер и улучшение

**Поток (ADR-0428, ещё не в main — вкладка T-20261117-20/2; на странице пока прежний GPT-поток):** как прежний GPT-поток. 3D: фото этой расстановки есть — кнопки нет; нет или изменили — «Сделать фото» (кнопка шторки
/ модалка «Вы изменили комнату…») → рендер Cycles 2 ракурсов → % → «Фото» → внизу «Улучшить фото» → нейросеть по кадру рендера →
улучшенное без кнопок. /demo и туры одинаково. Страница `tools/scout/flat215-demo/index.html`.

**Сервер (в main 01c575fe, 7b16e399):**
- маршруты `POST /api/render/cycles` (демо) и `POST /api/trial/<id>/photo` с `mode:"render"` (тур) — `tools/scout/draft_service.py`,
  `app/api/trial/[id]/photo/route.ts`, контракт `contracts/trial.ts`; `check:true` возвращает `scene_hash`/`cached` без заказа — признак кнопки;
- снимок расстановки — `tools/scout/render_snapshot.py`, очередь и пределы (8 в очереди, 2 на адрес/тур, 40 в час) — `tools/scout/render_jobs.py`,
  исполнитель `LocalCpuExecutor` (CPU DEV) и заготовка `salad-gpu` — `tools/scout/render_exec.py`; ход `GET /api/job?id=` — стадии scene/C1/C2/save, %;
- выгрузка сцены — `tools/scout/cycles_probe/demo_scene_dump.mjs` (потолок оболочки не выгружается, шторы — группа curtains),
  рендер — `tools/scout/cycles_probe/render_cycles.py` (`--device auto|optix|cuda|cpu`, несколько ракурсов в одном процессе, сторож картин
  `wall_art.has_content`), пресет — `tools/scout/cycles_probe/render-preset.json` (1536×1116, 64 выборки + OIDN);
- «Улучшить» — прежний GPT-маршрут с `render_key`, промпт `improve-render-v5.2` (ADR-0419).

**Машина (ADR-0429):** Salad RTX 4090 $0,33/ч, пара ≈8 с (TG 1688); CPU DEV — ≈185 с кадр Blender (`tools/scout/render_gpu/README.md`), прикидка очереди 600 с (`tools/scout/render_jobs.py:DEFAULT_SEC`). Образ — `tools/scout/render_gpu/Dockerfile.render`,
замер — `tools/scout/render_gpu/bench_run.py`. Кнопка вкл/выкл в ботах, «прогрелась»,
автостоп/потолок $, сторож `render-*` — T-20261117-24 (в работе), план `plans/render-machine-01.md`. Меш-сторож гасит только `mesh-*`
(`infra/server/salad-deadman.py`).

**Открыто:** цвет товара (T-23); живой `remlab-render` (8600) перезапустить с выкладкой вкладки. Уроки 697–700.
