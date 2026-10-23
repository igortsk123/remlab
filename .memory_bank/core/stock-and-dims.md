---
tier: 1
topic: stock-and-dims
scope: Наличие и честность размеров — состояния, парсер, footprint
tier2: "../domain/stock-and-dims.md"
updated: 2026-10-23
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-11
review_after: 2026-12-05
---

# Наличие и размеры честно — Tier 1 (план `stock-and-dims-honesty`, 03.09)

**Правила владельца:** размер не придумывается; `available` API не собираем; антибот-магазины не дёргаем и
честно пишем «неизвестно»; 404 и сбои сайта ≠ «нет в наличии».

**Наличие (`tools/scout/stock_check.py`, `page_alive.py`, `stock_truth.py`):** якорь домена перед обходом, карантин окончателен,
негатив только по текущей ссылке; модель `availability_state`/`page_state`/`availability_basis`/`stock_evidence_at` пишет только
`stock_truth.reconcile()`; парсер v2 включён (`page_alive.py:PARSER_V2`); цену показа выбирает `price_truth.py` (ADR-0260).

**Размеры (`tools/scout/footprint.py`, `dim_resolver.py`):** одно правило «Ш×Г или диаметр из каталога» для сборки, лечения,
солвера, сцены, экспорта и демо; выдуманных дефолтов нет. Тройка «Ш×Г×В» в названии — авторитет; оси по магазинам —
`dim_resolver.py:SHOP_DIM_KEYS`.

**Выведенные размеры — «чтобы влезло», с провенансом в `dims_evidence.<ось>.source` (ADR-0310):** `role_prior` — глубина по роли
и форме (`dim_prior.py`); `shape_rule:sphere` — ваза-шар (`dim_resolver.py:sphere_height`); `shape_rule:transformer` — трансформер
Орматека по спальному месту (`dim_resolver.py:transformer_dims`, доказано для `bank_ready.py`). Свет: порог высоты 1 см у люстры и бра.
Категория без размеров — карантин, роль остаётся (ADR-0309, `dimless.py`).

**Вылет люстры (ADR-0311):** минимальная подвеска ≤ потолок − 210 (`compose_gates.py:pendant_out`); поля `drop_*` в `dims_evidence.h`
(`dim_resolver.py:pendant_drop`); потолок — `ceilingCm` квартиры (`contracts/partner.ts`), нет — 270 (`contracts/apartment.ts:DEFAULT_CEILING_CM`).

**Отрицательно:** глубина из меша по одному фото (`mesh_dims.py`), `available` API, семейный приор высоты ламп (владелец 23.10).

**Tier 2:** `../domain/stock-and-dims.md` (правила, числа, замеры) · `completed_plans/stock-and-dims-honesty.md`.
