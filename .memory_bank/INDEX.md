# Memory Bank — Index (Tier 0)

remlab — «Смета-first» v0.4 (ADR-0016): расчёт → реф-смета; мастер `plans/MASTER-cost-first.md`;
сейчас первым идёт М5 «мебельный трек» (ADR-0187). Инварианты: один факт — в одном месте;
банк = канон, авто-память харнесса = per-user, мост — `/memory-check`.

## Decision tree — что читать (Tier 1 `core/*` → Tier 2 по `tier2:`)

<!-- GENERATED:decision-tree START -->
<!-- Таблицу регенерирует tools/memory-audit.mjs из frontmatter. Не редактируй вручную. -->

| Задача (scope) | Tier 1 | Tier 2 |
|----------------|--------|--------|
| Интеграции/доступы — ключи, клиенты | `core/access-and-integrations.md` | `../domain/integrations.md` |
| Стек, модули, генерация, деплой — по коду | `core/architecture.md` | `../../docs/tech-spec-ts-stack.md` |
| Каталог — загрузка из фидов/API, свежесть, сторожа | `core/catalog.md` | `../domain/catalog-enrichment.md` |
| Схема БД, миграции, pgvector | `core/data-model.md` | `../../docs/tech-spec-ts-stack.md` |
| Демо-планировщик для партнёра — расстановка и кадр | `core/demo-planner.md` | `../domain/demo-planner-ui.md` |
| Деплой/откат/сервер exit-fi | `deployment.md` | `domain/deployment-details.md` |
| Смета — калькуляторы, /go/ реф | `core/estimate.md` | `../domain/pricing-works-ru.md` |
| Мебель — сеты, визуализация | `core/furniture.md` | `../domain/viz-fidelity-playbook.md` |
| Цели v0.4 — сценарий, монетизация, порядок ступеней | `core/goals.md` | `../plans/MASTER-cost-first.md` |
| Source-KB из книг — спека, KB0–KB9 | `core/knowledge-db.md` | `../../remlab_knowledge_db_v1/spec/SPEC_source_kb_v1.md` |
| Расстановка: правила, зоны, прод-ядро | `core/layout.md` | `../domain/occupancy-rules.md` |
| Лид-канал — заявка, TG-бот | `core/leads.md` | — |
| Уроки перед планированием — что НЕ сработало | `core/lessons.md` | `../lessons/README.md` |
| Композиция гостиной — доли | `core/lr-composition.md` | `../domain/lr-composition-guide.md` |
| Рынок RU/UK — спрос, монетизация | `core/market.md` | `../domain/market-research.md` |
| Реклама — Яндекс, семантика | `core/marketing-acquisition.md` | `../domain/wordstat-semantics.md` |
| Цвет мешей — диагноз, мерка, рычаги | `core/mesh-color.md` | `../domain/viz-fidelity-playbook.md` |
| Приёмка мешей владельцем — /lab/mesh-audit | `core/mesh-owner-audit.md` | `../completed_plans/mesh-owner-audit.md` |
| 3D-меши — генерация, учёт, приёмка | `core/mesh-pipeline.md` | `../domain/viz-fidelity-playbook.md` |
| Пул нод Salad — группы, тарифы, деньги, стопоры | `core/mesh-pool.md` | `../domain/mesh-pool-ops.md` |
| Трейсинг AI-пайплайна — лог, разбор | `core/observability-tracing.md` | `../domain/observability.md` |
| Порядок конвейера — от фида до расстановки | `core/pipeline-order.md` | `../domain/pipeline-order-details.md` |
| Бизнес-контекст — кто, зачем, как зарабатываем | `product_brief.md` | `domain/brief-details.md` |
| Регресс-защита — тесты, CI, гардрейлы | `core/regression-net.md` | `../../docs/tech-spec-ts-stack.md` |
| Замер комнаты по фото | `core/room-measurement.md` | `../domain/room-measurement.md` |
| Наличие и честность размеров — состояния, парсер, footprint | `core/stock-and-dims.md` | `../domain/stock-and-dims.md` |
| Стили — паспорта, скоринг, сеты | `core/styles.md` | `../domain/interior-styles.md` |
| Stage 1 UX-flow, аналитика | `core/user-flow.md` | `../domain/user-flow-details.md` |
| Состав гостиной — роли и пригодность | `core/lr-checklist.md` | `../domain/living-room-checklist.md` |
<!-- GENERATED:decision-tree END -->

## Always-on docs (Tier 0/1)
`source-of-truth.md` · `project-state.md` · `decisions.md` (индекс; тексты — `decisions/`) ·
`deployment.md` · уроки — `core/lessons.md` → `lessons/`.

## Планы
Портфель `plans/MASTER-cost-first.md`; треки — `plans/README.md` § «Сейчас в работе»; архив — `archive/plans/`.

## Обслуживание
`/memory-check` · `/memory-cleanup` · `METADATA_SCHEMA.md` · `changelog/memory-log.md` · `tools/memory-project-audit.mjs`.
