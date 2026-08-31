---
slug: topview-from-mesh
status: in_progress
owner_approved: 2026-08-31 «делай»
updated: 2026-08-31
---
# Вид сверху из мешей для планировщика flat215-demo

Цель: заменить спрайты планировщика честными видами сверху из наших 3D-мешей,
механика прежняя (перетаскивание/поворот картинки, без вращения 3D, страница лёгкая).

Решение: GLB в браузер не грузим. Сервер-сайд рендер top-view PNG из model.repaired.glb
(или model.glb) с учётом фронта из orientation_state (калибратор mesh_orient.py).
Где меша нет — автоматом остаётся спрайт. Сначала тест-страница сравнения
/test/topview-test/ (спрайт vs top-рендер) — владелец решает, что лучше.

Шаги: 1) калибровка фронта готовых мешей (mesh_orient); 2) topview_render.py;
3) тест-страница + публикация; 4) после одобрения — гибрид в flat215-demo data.
Файлы: tools/scout/salad/topview_render.py (новый), tools/scout/mesh_orient.py (прогон),
tools/scout/flat215_demo.py (позже, шаг 4).
