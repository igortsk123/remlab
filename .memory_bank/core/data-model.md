---
tier: 1
topic: data-model
scope: Модель данных, ключевые таблицы, pgvector, RLS
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-07-01
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-07-01
review_after: ""
---

# Data Model — Tier 1 сводка

## Иерархия сущностей
`users → properties (квартира) → rooms → room_projects (подпроект) → result_versions (версия)`.
Профиль вкуса: `style_profiles`. Фото/анализ: `uploaded_images`, `detected_objects`.

## Группы таблиц
- **Генерация:** `generation_jobs` (mode, status, model_used, cost_usd, latency_ms — статус в Realtime/polling), `generated_images` (structure/style score, is_selected).
- **Каталог:** `products` (source_shop, external_id, цены, наличие, габариты, теги, freshness), `product_embeddings` (image/text `vector(768)`), `price_snapshots`, `product_previews` (free/locked).
- **Cost Engine (Stage 1B):** `cities`, `work_types`, `work_rates`, `material_categories`, `material_rates`, `*_coefficients`, `cost_estimates`, `estimate_lines`.
- **Платежи:** `payments` (provider_payment_id — идемпотентность).

## Правила
- **RLS с первого дня** — юзер видит только своё (регресс-защита от утечки). Тест RLS — часть e2e.
- Индексы: hnsw/ivfflat на `image_embedding`; btree `(category_normalized, price_current, availability)`.
- `vector(768)` — под выбранный эмбеддер (согласовать при wiring). Миграции Drizzle обратимые (down).
- Наш деплой: БД — контейнер `postgres:17 + pgvector` (ADR-0002), `CREATE EXTENSION vector`.

**Tier 2:** `../../docs/tech-spec-ts-stack.md` §4 (полная схема полей) + `../../docs/cjm-ux-v0.2.md` §13.
