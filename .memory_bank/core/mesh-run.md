---
tier: 1
topic: mesh-run
scope: Прогон мешей — РАБОЧИЙ вариант, старт, остановка
tier2: "../domain/mesh-run-playbook.md"
updated: 2026-10-27
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-11
review_after: 2027-01-09
---

# Прогон мешей — рабочий вариант и процедура

**Боевая конфигурация:** прогон 31.08–05.09 (2 327 мешей, лучший день 857). Что НЕ повторять —
Tier 2 § 5.

## Рабочий вариант (образ с 02.10; группы и карта — 20.10)
- **Образ:** `ghcr.io/igortsk123/mesh-hunyuan:cu124-localpaint2` =
  `sha256:f9a9ad6d0d859a24102416632d730f59dda2ec6e9a699d85664917ddc8a656cb`. К этому digest'у
  прибиты обе группы; локально образ не держим (ADR-0232). Рецепт — `tools/scout/salad/`.
- **Генератор:** Hunyuan3D 2.1, коммит апстрима `82920d643c0d`, CUDA 12.4.1, torch 2.5.1.
- **Карта:** только RTX A5000 (почему — [[mesh-pool]]), ОЗУ 24 ГБ, `STAGED=1` (форма 8 ГБ →
  выгрузка → покраска 14 ГБ).
- **Группы:** `mesh-low-8` (low), `mesh-batch-5` (batch, окно 09–15 UTC); тариф и окно — ТОЛЬКО из
  `tools/scout/rules/salad-groups.json` (ADR-0177).
- **Замер:** меш ≈ 176 с; потолок 172 меша/час на ~23 машинах при `--batch 2000`; ≈1,12 ₽/меш.

## Три команды
- **Старт** (единственный законный): `tools/scout/mesh_wave_start.sh --launch --rub-cap N` (₽ обязателен).
- **Наблюдение:** лог `$MESH_BATCH_LOG`; цена — `tools/scout/salad/tier_compare.py`.
- **Остановка:** `touch ~/scout-scenes/mesh-batch.PAUSE` — выход на границе пачки, группы гасит
  `finale()`; `mesh-draining` групп НЕ гасит; срочно — стоп группы через API.

**Перед стартом — чек-лист Tier 2 § 1**; скрипт сам проверяет только сирот и приёмник.

## Запреты (каждый уже стоил денег или часов)
- **НЕ собирать снимок очереди руками** и не обнулять курсор: он позиционный, снимок поверх
  неразобранного переставит сделанные меши (`tools/scout/mesh_wave_start.sh` §зачем процедура).
- **НЕ `kill -9` / `pkill -f`** по конвейеру: сироты с `ppid=1`, а `pkill -f` убьёт и сессию агента.
- **НЕ менять образ, ресурсы, GPU у живой группы** — только новой (`tools/scout/salad/recreate_group.py`,
  Tier 2 § 4; ADR-0154). **НЕ удалять с приёмника мимо API** (ADR-0178). **НЕ лечить цвет перегоном
  по seed** — он уходит только в форму (ADR-0145).

**Tier 2:** `../domain/mesh-run-playbook.md` (чек-лист, остановка, тупики с ценой) ·
[[mesh-pipeline]] · [[mesh-pool]] · [[mesh-owner-audit]] · [[pipeline-order]].
