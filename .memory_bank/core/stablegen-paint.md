---
tier: 1
topic: stablegen-paint
scope: Покраска StableGen — пакет, повторы
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-11-21
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-11-20
review_after: 2026-12-05
---

# Покраска мешей StableGen — как гоняем пакет (T-90/11–12, 20.11)

Проба: результат — `painted.glb`, на сайт только после «принято» (P-059). Код — `tools/scout/stablegen/`.
**С 20.11 основной путь — не StableGen**, а «фото + заливка» по 10 этапам (`tools/scout/paint_stage.py`) — ADR-0455, `plans/paint-photo-fill-01.md`; ниже — ориентир «до».

## Конвейер
- **Форма:** Salad (TRELLIS.2, `trellis_trial.py`) отдаёт GLB **без развёртки** → ОБЯЗАТЕЛЬНО `sg_prep_batch.sh` (`sg_prep_shape.py`: ≤150 тыс. граней + слой `BakeUV`). Без UV запекание не кончается (≈$1,9 впустую 20.11): стоп «форма без UV» ДО пода — `sg_salad.build_cfg`, `sg_drive.py`.
- **Нода:** Salad 5090 (`sg_salad.py`, Qwen-Image-Edit-2509 Q5_K_M + Lightning) или RunPod A6000 (`sg_runpod.py`). Прогрев 5–13 мин; 504 — `api_retry`; «готова» ≠ видит модели — ждать список ≤120 с.
- **Очередь прогонов `sg_queue.RunQueue` — одна для обоих драйверов:** нода красит, мы запекаем (следующий товар — когда у предыдущего stage bake/export); сторож запекания >3× (300 с) → убить; первый товар упал или 2 подряд — стоп группы; место <1,5 ГБ — стоп; усадка успешного прогона 125 → ≈21 МБ.
- **Сбои связи (T-153/1):** мост `sg_relay.py` и Blender повторяют шаг до 3 раз (403, 502–504, «isn't reachable»); признаки — `tools/scout/rules/stablegen-transient.json` (`sg_transient.py`).
- **Подписи видов:** роль из каталога → существительное (`sg_views.role_noun`, порядок слов не важен); фото только видам ≤~100° от переда, подпись без цвета только у первого вида (`variant q2509t5i`).

## Цифры пакета 39 (20.11)
≈7,3 мин и $0,07 на товар (покраска 297 с, запекание 103 с); список — `~/remlab-logs/t90-1119/sg/painted-1120.tsv`.

## Дефекты (журнал — `plans/mesh-type-rules-01.md`)
Малиновое у 7 из 36 — служебная заливка «не покрашено», задним видам при `no_photo` (урок 773); «лицо» на заду; цвет перёд/зад; «мрамор» велюра.
Сторожа T-154 остановлены (TG 2883) → профилактика `plans/paint-prevent-01.md` v2 (`qwen_context_cleanup` — не профилактика). Показ — на форме с сайта (`photo.json` `glb_in`).
