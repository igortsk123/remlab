---
tier: 1
topic: catalog
scope: Каталог товаров — состав, свежесть, обогащение, дельта
tier2: "../domain/catalog-enrichment.md"
updated: 2026-08-07
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-07
---

# Каталог — Tier 1 сводка

**Состав:** ~32 000 товаров (ADR-0070 + кашпо А2 + фиды divan.ru/mdm-complect 07.08:
ковры 26→211, стулья 585→1179, стеллажи→1538, тв-тумбы→794), дев-БД `remlab-devdb`; pgvector нет. Загрузка — `load3.py`, cron 09:40 `refresh_daily.sh` (vision-обогащение дельты +
автозабор `enrich_wait.sh` + судья `enrich_judge.py`; алерты `alert.sh`).

**Роль товара — из дерева категорий фида** (`feed_taxonomy.py` → `category_map.py` →
`products.cat_role`): 1 931 категория, берём 76. Регекс-view `lr_roles` — историческая, не источник.

**Обогащение (06.08):** весь active-пул **25 664/25 664** (`gpt-5.6-luna`, furniture-v1/p3/s5,
качество 0.86 — эвристика, не голден); стиль — признаки+ранги (ADR-0071); батчи — ADR-0073
(гейт+журнал); дельта text/geometry сбрасывает версию (А1); phash 99.7%. Мониторинг: судья
terra ежедневно, дрифт `enrich-drift.jsonl`, копилка `golden-candidates.jsonl` (замер:
роль 96.7%, стиль 100%). Легаси: `style-scores.json`, `embeddings.npz`.

**Дельта и жизненный цикл (К1, ADR-0068):** `product_enrichment` переживает пропажу из фида;
статусы в `load3.py`; phash; обратный индекс; контракт `delta_check.py`.

**Выбор модели (К3):** голден 256 товаров (`golden_eval.py`) — `gpt-5.6-luna`: роль 92.6%,
функция 89.8%, ≈16 $ за пул пакетом. Отчёт — `/test/golden/golden.html`.



**Дыры каталога:** картин нет; премиум-тир беден у половины ролей (кресло/тв-тумба/стеллаж 0);
лофт/неокл/джапанди дефицитны (снабжение — за владельцем). Ковры и стулья закрыты 07.08.
К4 закрыт: `sets_incremental --refresh` (еженедельно) + heal из живого индекса.

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md` · `../core/furniture.md`.
