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
ID в API побиты float64 → связь по картинке+названию). Cron 09:40 `refresh_daily.sh`:
feed_guard → shops_check → load3 → catalog_api → phash → enrich-дельта (ADR-0135) →
style-дельта → …; алерты alert.sh.

**Медиа — производные данные (ADR-0124):** резолвятся из `products` (`catalog_media.py`).
Живость фото/страниц — трёхзначная (уроки 320/326): сбой/шаблон — не приговор; корзина/qty
сильнее маркера (`img_alive.py`, `health.py`).

**Наличие — НЕ РАБОТАЕТ (разбор 31.08, фикса нет):** фид не отдаёт `available`, `load3.py`
ставит `in_stock` жёстко true (`tools/scout/load3.py:173,243`); вердикты `health.py`/
`linkcheck.py` load3 перебивает наутро; 353 ссылки с 404 «в наличии». Детали — Tier 2.

**Роль товара** — по листу дерева категорий фида (ADR-0078/0108, `tools/scout/category_map.py`
→ `products.cat_role`); capability Q6a.

**Обогащение и дельта:** active-пул (`gpt-5.6-luna`), phash 99.7%; долг мерить по
`enriched_at is null` — строка появляется ДО вызова LLM (урок 325); `openai.off`, лимит $5/день.

**Размеры (ADR-0079):** evidence-резолвер `tools/scout/dim_resolver.py`, провенанс dims_source/
evidence. Предохранители T0 — `feed_guard.py`. **Выбор модели (К3):** голден 256 — luna
92.6/89.8%, человеческий эталон `gold_human.py` (400). Детали — Tier 2.

**Свежесть фидов (ADR-0107):** `feed_guard` → `feed-freshness.json`; pod — только из живых
фидов. nonton удалён 29.08 (партнёрка закрыта; бэкап graveyard_nonton_* в БД).

**Дыры ассортимента:** премиум-тир беден у половины ролей; лофт/неокл/джапанди дефицитны;
тв-тумбы без стиль-фита во всех 6 стилях (снабжение — владелец).

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md` · `../core/furniture.md`.
