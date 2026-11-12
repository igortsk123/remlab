---
tier: 1
topic: catalog
scope: Каталог — загрузка из фидов/API, свежесть, сторожа
tier2: "../domain/catalog-enrichment.md"
updated: 2026-11-12
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-11-12
review_after: 2026-12-05
---

# Каталог — Tier 1 сводка

**Состав (11.10):** 20 552 товара, 7 магазинов (ВсеИнструменты НЕ подключён — ADR-0240); дев-БД `remlab-devdb`.
**Цикл:** crontab `40 10 * * *` UTC (фиды в 12:35 МСК) + `@reboot`; `refresh_daily.sh` — шаги
`ok|warn|FAIL|skipped`, статус на прод, дайджест в Telegram (`alert.sh` с повтором), прод-сторож (ADR-0172, [[deployment]]).

**Источник истины (ADR-0171, `tools/scout/load3.py`):** ФИД — ключ `(merchant_id, id)`, название, ссылка,
фото, `original_picture → image_url_hd`, `article`, цена, категория, params, описание (пустое не затирает).
API (`catalog_api_sync.py`, ежедневно, ADR-0239) — `charge`, пустые HD и описание; каноном состава НЕ является (видит 56 %);
комиссия — по `article`, HD и описание — по картинке/названию. Вычисляем: размеры (`dim_resolver.py`; глубина с чертежа — [[stock-and-dims]]),
роль (`category_map.py` → `products.cat_role` → витрина `lr_roles`, ADR-0236; детское — `rug_kids.py`, `category_map.py:soft_kids`; свет —
`category_map.py:light_role`; диван/кресло/пуф — первое слово-тип в названии, `category_map.py:seat_role`),
`in_stock` (`stock_truth.reconcile()`).

**Дельта (`load3.py:HASH_VERSION` = 10; смена правил `dim_resolver` — подъём, сторож `RULES_FINGERPRINT`):** text/geometry/image/attrs → `stale`
(commercial и image_hd — только счётчики), смена контракта → baseline. Исчез → `missing`, 3 дня → `archived`; не удаляем.
Порог «< 70 %» — по магазину против последнего успеха (`catalog_import_runs`).
Карантин фидов — `feed_guard.py` (30–54 ч `degraded` грузится; `stale/broken/empty` — пропуск, `load3.py:main`). Обогащение `enrich.py --vision` — ежедневно (кроме `openai.off`), ≤200, сперва товары банков (`enrich.py:daily_pick`).

**Наличие и размеры честно** — [[stock-and-dims]]; там же категория без размеров — карантин, роль остаётся (ADR-0309, `dimless.py`).

**Стили и готовность к мешам (ADR-0237/0238).** `style_score.py` (правила → CLIP → `gpt-6-luna`) пишет в `product_style_scores`;
витрина `catalog_ready` (`bootstrap.sql`) — Tier 2.

**Сторож «слот ↔ роль каталога»** — `bank_invariants.py:slot_catalog_compatible` (Tier 2). **Тесты:** `--selftest` модулей — CI `scout-selftest`.

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md`.
