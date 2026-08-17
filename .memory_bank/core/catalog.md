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

**Свежесть фидов (16.08, ADR-0107):** конвейер стоял с 11.08 (nonton 404 → BadZipFile) — теперь
`refresh_daily.sh` проверяет zip, `load3.py` пропускает broken/stale/empty (`_feed_hash`), `feed_guard`
хранит mids/broken_since (`feed-freshness.json`, вне git); `compose2.py` не берёт broken/stale в новые
сеты; nonton (116933, 1076 позиций) — карантин отложен, решение владельца. Pod-комплект (кресло 3/4 +
столик 2, `seating_pods.pod_kit`) — только из живых фидов (fail-closed). Divan.ru «новый» фид bceea2bc =
тот же магазин 112923 (не грузим). В фидах есть кушетки/банкетки/консоли/раскладные — спрятаны ролями
и фильтром импорта (Q6a: разметка ролей).

**Дыры:** премиум-тир беден у половины ролей; лофт/неокл/джапанди дефицитны (снабжение — владелец).

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md` · `../core/furniture.md`.
