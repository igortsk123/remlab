---
tier: 1
topic: stock-and-dims
scope: Наличие и честность размеров — состояния, парсер, footprint
tier2: "../domain/stock-and-dims.md"
updated: 2026-09-03
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-09-03
review_after: 2026-12-05
---

# Наличие и размеры честно — Tier 1 (план `stock-and-dims-honesty`, 03.09)

**Правила владельца:** размер не придумывается; `available` API не собираем; антибот-магазины не дёргаем и
честно пишем «неизвестно»; 404 и сбои сайта ≠ «нет в наличии».

**Наличие (`tools/scout/stock_check.py`, `page_alive.py`, `stock_truth.py`):** якорь домена (главная + 3 живых
карточки) перед обходом, карантин окончателен (`disposition=quarantined`), негатив только по текущей ссылке
(`products.direct_url_hash`), гейт по решающим ответам с пределом при малой выборке, канарейка адреса; антибот
подтверждён только у mdm (`probe_domain_status.policy=disabled`, проба раз в неделю). Модель в `products`:
`availability_state` (in_stock|out_of_stock|unknown), `page_state` (alive|gone|unknown), `availability_basis`
(page|feed|none), `stock_evidence_at`; пишет только `stock_truth.reconcile()`; демо показывает «наличие не
проверено». 03.09: page 5 408 / feed 13 706. Парсер v2 (snake_case, `href=`, JSON-LD Product, inline-остаток
tvoydom) — в тени (`STOCK_PARSER_V2=1 stock_check.py --shadow`, `stock_shadow_report.py`) до gold. Цена/имя со
страницы — только наблюдения (`product_page_facts`).

**Размеры (`tools/scout/footprint.py`, `dim_resolver.py`):** одно правило «Ш×Г или диаметр из каталога» для
compose2, `sets_incremental`, `catalog_media`, `solver_run` (`DIMS_STRICT=1`), `scene_build`, `export_plans_ai`,
`flat215_demo`; дефолты убраны. Тройка «Ш×Г×В» в названии — авторитет; tvoydom «Длина» = фасад (замер 1 100
карточек). Банк №3: 126 сетов, 2 479 позиций, 0 напольных без размера.

**Отрицательно (не повторять без новых данных):** глубина из меша по одному фото (`mesh_dims.py`: меш додумывает
глубину), `available` API как источник наличия.

**Tier 2:** `../domain/stock-and-dims.md` · план `plans/stock-and-dims-honesty.md`.
