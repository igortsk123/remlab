---
tier: 1
topic: mesh-pipeline
scope: 3D-меши товаров — генерация, приёмка, ориентация
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-09-04
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-09-02
---

# Конвейер 3D-мешей — Tier 1 сводка

**Зачем:** планировщик и 3D-квартиры. **Генератор — свой Hunyuan3D 2.1 на SaladCloud**
(ADR-0131). Код — `tools/scout/salad/`. **Объём:** пул 11 631, очередь 11 704.

**Путь меша:** вход — RGBA-вырезка (`hybrid_mask.py`, ADR-0133/0136) → приёмка
`mesh_gate.py` → `mesh_gate_pbr.py` → `web_ready` → ориентация orient-v2 (ADR-0129).
Ремонт ОТМЕНЁН (ADR-0143); цвет — [[mesh-color]] (ADR-0145);
небелый фон — метка, не блокировка (ADR-0155). Показ — `/test/mesh-pilot10/`, разбор —
`batch_show.py`. Очередь — ADR-0153. Выкатка — ADR-0154/0157 (НОВАЯ группа: PATCH образа
молчит). Обстановка — ADR-0162; модели с ДИСКА образа (ADR-0168/0173).

**Пул, приёмник, деньги.** ADR-0175: приёмник проверяется ДО раздачи (`sink_health`,
канарейка), красный = инфра, не вина ноды. ADR-0176: обрыв SSH с диагнозом; конвейер
singleton (`mesh-draining`); цена по ОПЛАЧЕННЫМ нодо-часам. **ADR-0178:**
удаление на транзите — только через `DELETE /prefix/...` (счётчик `receiver._SIZE` вычитает
байты лишь там; `rm -rf` мимо API дал призрак 2.24 ГБ и погасил пул); чистка продублирована
вне конвейера — `sink_keeper.sh`, крон `*/15`, молчит пока конвейер жив.

**Цифры 03.09:** 100 мешей/час на 20 нодах, GPU 87–92%, **1.35 ₽ за меш** по оплаченному.
**Тарифы — ADR-0177:** batch по окну 09–15 UTC, low — круглосуточно; на сопоставимых часах
batch **1.86 ₽/меш** против **1.61–1.62 ₽**. Состав 04.09: `mesh-low-4/5`, `mesh-batch-3`,
образ `cu124-localpaint2`; тариф/окно/цена — только `tools/scout/rules/salad-groups.json`.
**Открытые дефекты (уроки 400–402):** `autostart_policy: true` поднимает группу при СОЗДАНИИ,
окно не гасит; пересадка снимает ноду со 100 %; красный приёмник всегда `shared_infra` — пул
не встаёт сам после уборки.

**Tier 2:** `../domain/viz-fidelity-playbook.md` · планы `mesh-bulk-salad-hunyuan`,
`mesh-dino-baked`, `mesh-pool-hardening` · ADR-0129…0134, 0146, 0168–0170, 0173–0178.
