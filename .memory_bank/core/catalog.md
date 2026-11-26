---
tier: 1
topic: catalog
scope: Каталог — загрузка из фидов/API, свежесть, сторожа
tier2: "../domain/catalog-enrichment.md"
updated: 2026-11-19
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-11-26
review_after: 2026-12-05
---

# Каталог — Tier 1 сводка

**Состав (18.11):** 17 928 в наличии из 23 742, 7 магазинов (ВсеИнструменты НЕ подключён — ADR-0240); БД `remlab-devdb`.
**Цикл:** crontab `40 10 * * *` UTC + `@reboot`; солвер — крон по пн; `refresh_daily.sh` — шаги
`ok|warn|FAIL|skipped`, статус на прод, дайджест `alert.sh`, прод-сторож (ADR-0172, [[deployment]]).

**Источник истины (ADR-0171, `tools/scout/load3.py`):** ФИД — ключ `(merchant_id, id)`, название, ссылка,
фото, `original_picture → image_url_hd` (без HD и ревизии меша; иначе `hd_backfill.py`), `article`, цена, категория, params, описание (пустое не затирает).
API (`catalog_api_sync.py`, ежедневно, ADR-0239) — `charge`, пустые HD и описание; каноном состава НЕ является;
комиссия — `article` (иначе картинка, API ≤14 дн), HD — картинка → название, описание — картинка. Вычисляем: размеры (`dim_resolver.py`; глубина с чертежа — [[stock-and-dims]]),
роль (`category_map.py` → `products.cat_role` → витрина `lr_roles`, ADR-0236; детское — `rug_kids.py`, `category_map.py:soft_kids`; свет —
`category_map.py:light_role`; диван/кресло/пуф — первое слово-тип в названии, `category_map.py:seat_role`; `component` — без роли, `component_guard.py`),
`in_stock` (`stock_truth.reconcile()`).

**Дельта (`load3.py:HASH_VERSION` = 10; смена правил `dim_resolver` — подъём, сторож `RULES_FINGERPRINT`):** text/geometry/image/attrs → `stale`
(commercial и image_hd — счётчики), смена контракта → baseline. Исчез → `missing`, 3 дня → `archived`.
Порог «< 70 %» — по магазину против последнего успеха (`catalog_import_runs`).
Карантин фидов — `feed_guard.py` (30–54 ч `degraded` грузится; `stale/broken/empty` — пропуск). Обогащение `enrich.py --vision` — ежедневно (кроме `openai.off`), ≤200, сперва товары банков (`enrich.py:daily_pick`).

**Наличие и размеры** — [[stock-and-dims]] (без размеров — карантин, ADR-0309, `dimless.py`).

**Стили и готовность к мешам (ADR-0237/0238).** `style_score.py` (правила → CLIP → `gpt-6-luna`) пишет в `product_style_scores`;
витрина `catalog_ready` (`bootstrap.sql`). **Сторож «слот ↔ роль»** — `bank_invariants.py:slot_catalog_compatible`. **Тесты:** `--selftest` модулей — CI `scout-selftest`.

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md`.
