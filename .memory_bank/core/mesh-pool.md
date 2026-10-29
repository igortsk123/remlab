---
tier: 1
topic: mesh-pool
scope: Пул нод Salad — группы, тарифы, деньги, стопоры
tier2: "../domain/mesh-pool-ops.md"
updated: 2026-10-29
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-10-11
review_after: 2027-01-09
---

# Пул нод Salad — Tier 1 (деньги и эксплуатация)

**Запуск и остановка прогона — [[mesh-run]].**

**Что это.** Группы SaladCloud с образом Hunyuan3D под конвейером
`tools/scout/salad/` (`batch_show.py` + раздатчик `ssh_run.py`); тариф, окно, цена — ТОЛЬКО из
`tools/scout/rules/salad-groups.json` (ADR-0177). Путь меша — [[mesh-pipeline]].

**Карты и тариф (ADR-0315):** любые NVIDIA ≥ 16 ГБ, кроме RTX 50xx и 4090; тариф `low`/`batch`, выше — только владелец.
По факту — RTX 4060 Ti 16 ГБ. Фильтр ОЗУ машины выключен (`node_ram.min_gb 0`, ADR-0316): обрывы — вытеснение тарифом (`Instance
Interrupted (Priority)`), не OOM. Квота 50 реплик общая; ресурсы/GPU/образ — только новой группой
(`recreate_group.py`, `queue_setup.py`; урок 518).

**Транспорт (ADR-0317):** очередь Salad (Job Queue) — группа с `queue_connection` при создании, посредник `queue_proxy.py` (порт 8001)
отдаёт машину задания; транспорт `auto` по правилам группы. SSH (молчит на ~половине машин) — запасной.
Боевая `mesh-q-low-1` создана и выключена (`disabled`); подъём — словом владельца.

**Деньги.** Платим за `running`, не за работу (ADR-0135; `downloading` не оплачивается). **Потолок 1,5 ₽/меш (ADR-0313):**
сторож цены `tools/scout/salad/mesh_price.py` в цикле `money_guard.py` судит по средней после 8 ч работы группы; цена — по классу
карты (`prices_by_class_usd_h`), меши — только новые `job_id` (урок 523); дорого → stop + `mesh-price-halt.json`, снимает человек.
Учёт по машине — `pool_ledger.py` (события Salad + журнал). 27.10 очередь — 0,92 ₽/меш в работе.

**Стопоры — один свод (ADR-0175).** Стоп-файл `mesh-group-halt.json` сильнее автостарта (ADR-0169/0174); приёмник проверяется ДО
раздачи; кредиты кончились — только по `no_credits_available` (урок 404); слепой опрос ≠ «не платим» (урок 519); ручной старт — с
`--rub-cap` (ADR-0317). **ADR-0198:** `/start` — только лежащим группам

**Чистка приёмника** — только через API `DELETE /prefix/...` (ADR-0178), сторож `sink_keeper.sh`, порог 6 ГБ (ADR-0199).

**Tier 2:** `../domain/mesh-pool-ops.md` (регламент, замеры, разбор остановок) · ADR-0135, 0154, 0174–0178, 0198–0200, 0313–0317.
