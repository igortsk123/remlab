---
tier: 1
topic: mesh-run
scope: Прогон мешей — РАБОЧИЙ вариант, старт, остановка
tier2: "../domain/mesh-run-playbook.md"
updated: 2026-10-29
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-11
review_after: 2027-01-09
---

# Прогон мешей — рабочий вариант и процедура

Что НЕ повторять — Tier 2 § 5.

## Рабочий вариант (образ с 23.10; группы и карты — 22–27.10)
- **Образ:** `ghcr.io/igortsk123/mesh-hunyuan` тег `memtrim-d8c51952` (слой поверх `cu124-localpaint2`: память
  отдаётся после стадии) — `tools/scout/salad/migrate_groups.py:42`; Hunyuan3D 2.1, CUDA 12.4.1.
- **Карты:** любые NVIDIA ≥ 16 ГБ, кроме RTX 50xx и 4090 (ADR-0315); фильтр ОЗУ машины выключен (ADR-0316).
- **Группы:** SSH — `mesh-low-10` (low) + `mesh-batch-7` (batch, 09–15 UTC); очередь Salad — `mesh-q-low-1` (выключена до слова
  владельца, ADR-0317). Тариф, окно, цена — ТОЛЬКО `tools/scout/rules/salad-groups.json` (ADR-0177).
- **Что генерим:** только под демо — профиль `demo` (закреплённые + недобор ленты + спрос кандидата банка, потолок 150; ADR-0314).
- **Замер:** 27.10 очередь — 0,92 ₽/меш в работе; потолок 1,5 ₽ (ADR-0313).

## Три команды
- **Старт** (единственный законный): `tools/scout/mesh_wave_start.sh --launch --rub-cap N` (₽ обязателен).
- **Наблюдение:** лог `$MESH_BATCH_LOG`; цена — `tools/scout/salad/tier_compare.py`.
- **Остановка:** `touch ~/scout-scenes/mesh-batch.PAUSE` — выход на границе пачки; конец работы гасит группы сразу
  (`batch_show.py:wave_tail`); `mesh-draining` групп НЕ гасит; срочно — стоп группы через API. Лечение — только `--heal`.

**Перед стартом — чек-лист Tier 2 § 1** (скрипт проверяет лишь сирот и приёмник).

## Запреты (каждый уже стоил денег или часов)
- **НЕ собирать снимок очереди руками** и не обнулять курсор: он позиционный, снимок поверх
  неразобранного переставит сделанные меши (`tools/scout/mesh_wave_start.sh`).
- **НЕ `kill -9` / `pkill -f`** по конвейеру: сироты `ppid=1`, `pkill -f` убьёт сессию агента.
- **НЕ менять образ, ресурсы, GPU у живой группы** — только новой (`tools/scout/salad/recreate_group.py`,
  Tier 2 § 4; ADR-0154). **НЕ удалять с приёмника мимо API** (ADR-0178). **НЕ лечить цвет перегоном
  по seed** — он уходит только в форму (ADR-0145).

**Tier 2:** `../domain/mesh-run-playbook.md` (чек-лист, остановка, тупики с ценой) ·
[[mesh-pipeline]] · [[mesh-pool]] · [[mesh-owner-audit]] · [[pipeline-order]].
