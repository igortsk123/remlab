---
tier: 1
topic: catalog
scope: Каталог — состав, свежесть, дельта
tier2: "../domain/catalog-enrichment.md"
updated: 2026-08-29
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-29
---

# Каталог — Tier 1 сводка

**Состав:** 20 544 товара (29.08, после удаления nonton — ADR-0136), дев-БД `remlab-devdb`.
Загрузка: фиды `load3.py` + **API Гдеслона** `catalog_api_sync.py` (HD-фото 800×600 в
`image_url_hd` — 11.9k, описания; ID в API побиты float64 → связь по картинке+названию).
Cron 09:40 `refresh_daily.sh`: feed_guard → shops_check → load3 → catalog_api → phash →
enrich-дельта (sync через Vercel, ADR-0135) → style-дельта → …; алерты alert.sh.

**Медиа — производные данные (ADR-0124):** резолвятся из `products` (`catalog_media.py`).
nonton **УДАЛЁН 29.08** (партнёрка закрыта; бэкап graveyard_nonton_* в БД). Проверки живости
фото/страниц ТРЁХЗНАЧНЫЕ (уроки 320/326): сбой или шаблонный текст — не приговор; корзина/qty
сильнее маркера (`img_alive.py`, `health.py`).

**Роль товара — из дерева категорий фида** (`category_map.py` → `products.cat_role`, ADR-0078).

**Обогащение и дельта:** active-пул (`gpt-5.6-luna`), phash 99.7%; строка enrichment у новинки
появляется ДО вызова LLM — долг мерить по `enriched_at is null` (урок 325).

**Размеры (ADR-0079):** evidence-резолвер `tools/scout/dim_resolver.py`, провенанс dims_source/
evidence; 0 битых, +4 610 с шириной. Предохранители T0 — `feed_guard.py`. Детали — Tier 2.

**Выбор модели (К3):** голден 256 — luna 92.6/89.8%; человеческий эталон `gold_human.py` (400).

**Свежесть фидов (ADR-0107):** `feed_guard` → `feed-freshness.json`; pod — только из живых
фидов; nonton retired (26.08).

**Роль по листу категории** (ADR-0108, `tools/scout/category_map.py`); capability-модель Q6a;
рубильник `openai.off`, лимит $5/день. Лечение банка копирует габариты и конверт банда
(22.08, `tools/scout/sets_incremental.py`). **Дыры ассортимента:** премиум-тир беден у половины
ролей; лофт/неокл/джапанди дефицитны; тв-тумбы без стиль-фита во всех 6 стилях (снабжение — владелец).

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md` · `../core/furniture.md`.
