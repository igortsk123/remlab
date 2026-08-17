---
tier: 1
topic: catalog
scope: Каталог — состав, свежесть, дельта
tier2: "../domain/catalog-enrichment.md"
updated: 2026-08-17
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-08
---

# Каталог — Tier 1 сводка

**Состав:** ~32 000 товаров (ADR-0070; фиды divan.ru/mdm-complect 07.08), дев-БД
`remlab-devdb`; pgvector нет. Загрузка `load3.py`, cron 09:40 `refresh_daily.sh`
(feed_guard → load3 → phash → обогащение дельты → индексы/heal → health; алерты alert.sh).

**Роль товара — из дерева категорий фида** (`category_map.py` → `products.cat_role`, ADR-0078).

**Обогащение:** active-пул (`gpt-5.6-luna`); стиль — признаки+ранги (ADR-0071); батчи ADR-0073;
судья terra ежедневно (`enrich-drift.jsonl`); phash 99.7%. Перед платным прогоном — `--sample 0` (дельта).

**Дельта (К1, ADR-0068):** `product_enrichment` переживает пропажу из фида; статусы в `load3.py`;
контракт `delta_check.py`.

**Размеры (ADR-0079):** evidence-резолвер `tools/scout/dim_resolver.py`, провенанс dims_source/
evidence; 0 битых, +4 610 с шириной. Предохранители T0 — `feed_guard.py`. Детали — Tier 2.

**Выбор модели (К3):** голден 256 — luna 92.6/89.8% = model-agreement (эталон terra); человеческий
эталон `tools/scout/gold_human.py` (400, разметка — владелец); merge text/vision — парные батчи #t/#v.

**Свежесть фидов (ADR-0107):** `refresh_daily.sh` проверяет zip, `load3.py` пропускает broken/stale,
`feed_guard` хранит mids/quarantine_pending (`feed-freshness.json`); nonton (116933) — карантин ждёт
владельца; pod-комплекты — только из живых фидов. Divan.ru фид bceea2bc = тот же 112923.

**17.08 (ADR-0108):** роль — по ЛИСТУ категории (`tools/scout/category_map.py`; кресла divan.ru 335,
пуфы 376 вернулись); capability-модель Q6a (`tools/scout/capabilities.py`); OpenAI: `openai.off`,
лимит $5/день (`tools/scout/openai_budget.py`).
**Дыры:** премиум-тир беден у половины ролей; лофт/неокл/джапанди дефицитны (снабжение — владелец).

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md` · `../core/furniture.md`.
