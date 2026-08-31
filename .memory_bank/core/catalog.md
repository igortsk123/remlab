---
tier: 1
topic: catalog
scope: Каталог — состав, свежесть, дельта
tier2: "../domain/catalog-enrichment.md"
updated: 2026-08-31
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-31
---

# Каталог — Tier 1 сводка

**Состав:** 20 544 товара (29.08, после удаления nonton — ADR-0136), дев-БД `remlab-devdb`.
Загрузка: фиды `load3.py` + **API Гдеслона** `catalog_api_sync.py` (HD-фото 800×600, описания;
ID в API побиты float64 → связь по картинке+названию). Cron 09:40 `refresh_daily.sh` (под
`flock`): feed_guard → shops_check → load3 → catalog_api → **stock_check** → phash →
enrich-дельта (ADR-0135) → … → sets_heal → stock_audit; алерты alert.sh.

**Медиа (ADR-0124):** резолвятся из `products` (`catalog_media.py`); подтверждённо мёртвая
карточка сильнее карантина фида. Живость фото трёхзначная (уроки 320/326): сбой/шаблон —
не приговор (`img_alive.py`).

**Наличие — производное, ОДИН писатель (ADR-0141, 31.08):** `in_stock` = фид `active` И
программа не `retired` И карточка не `gone/oos`; материализует только `stock_truth.reconcile()`,
сторож `--audit` ночью. Свидетельство даёт `stock_check.py` (классификатор `page_alive.py`:
schema.org, контракт магазина sku/series); снятие — по ДВУМ отрицательным по одной ссылке
(≥15 мин), `unknown` не снимает. Прежде писали пятеро, побеждал `load3`. Детали — Tier 2.

**Роль товара** — по листу дерева категорий фида (ADR-0078/0108, `category_map.py` →
`products.cat_role`); capability Q6a.

**Обогащение и дельта:** active-пул (`gpt-5.6-luna`), phash 99.7%; долг — по
`enriched_at is null` (строка появляется ДО LLM, урок 325); `openai.off`, лимит $5/день.

**Размеры (ADR-0079):** evidence-резолвер `dim_resolver.py`, провенанс dims_source/evidence.

**Свежесть фидов (ADR-0107):** `feed_guard` → `feed-freshness.json`; pod — из живых фидов.
nonton удалён 29.08 (партнёрка закрыта; бэкап graveyard_nonton_* в БД).

**Дыры ассортимента:** премиум-тир беден у половины ролей; лофт/неокл/джапанди дефицитны;
тв-тумбы без стиль-фита во всех 6 стилях (снабжение — решение владельца).

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md` · `../core/furniture.md`.
