# Core — Tier 1 короткие сводки

> Файлы по 2–3 KB. Читаются как первый drill-down из `INDEX.md`. Каждый имеет frontmatter
> (`topic`/`tier:1`/`scope`/`tier2`/`updated`) и финальную строку `Tier 2:` для расширения.
> Шаблон новой сводки — `_template.md`. Типовые темы: `product`, `architecture`, `data-models`,
> `flows`, `access-and-integrations` (+ домен-специфичные).

## Реестр сводок

<!-- GENERATED:core-registry START -->
<!-- Таблицу регенерирует tools/memory-audit.mjs из frontmatter. Не редактируй вручную. -->

| Файл | topic | Когда читать (scope) | Tier 2 | updated |
|------|-------|----------------------|--------|---------|
| `access-and-integrations.md` | access-and-integrations | Интеграции/доступы — ключи, клиенты | `../domain/integrations.md` | 2026-11-12 |
| `agent-trial.md` | agent-trial | Проба агента недвижимости (UK) — план, воркер, стадии, тур /try | `../plans/MASTER-agent-trial.md` | 2026-11-13 |
| `apartment-configurator.md` | apartment-configurator | 3D-конфигуратор квартиры — что это, из чего собран, где детали | `../domain/flat3d-configurator.md` | 2026-11-12 |
| `architecture.md` | architecture | Стек, модули, генерация, деплой — по коду | `../../docs/tech-spec-ts-stack.md` | 2026-11-12 |
| `catalog.md` | catalog | Каталог — загрузка из фидов/API, свежесть, сторожа | `../domain/catalog-enrichment.md` | 2026-11-12 |
| `data-model.md` | data-model | Схема БД, миграции, pgvector | `../../docs/tech-spec-ts-stack.md` | 2026-11-12 |
| `demo-planner.md` | demo-planner | Демо-планировщик для партнёра — расстановка и кадр | `../domain/demo-planner-ui.md` | 2026-11-13 |
| `demo-scenarios.md` | demo-scenarios | Сценарии /demo — карта кнопок «ожидание → факт», живые проверки, дефекты | `../domain/demo-scenario-map.md` | 2026-11-13 |
| `estimate.md` | estimate | Смета — калькуляторы, /go/ реф | `../domain/pricing-works-ru.md` | 2026-10-17 |
| `furniture.md` | furniture | Мебель — сеты, визуализация | `../domain/viz-fidelity-playbook.md` | 2026-11-13 |
| `goals.md` | goals | Цели v0.4 — сценарий, монетизация, порядок ступеней | `../plans/MASTER-cost-first.md` | 2026-10-19 |
| `knowledge-db.md` | knowledge-db | Source-KB из книг — спека, KB0–KB9 | `../../remlab_knowledge_db_v1/spec/SPEC_source_kb_v1.md` | 2026-11-06 |
| `layout.md` | layout | Расстановка: правила, зоны, прод-ядро | `../domain/occupancy-rules.md` | 2026-11-13 |
| `leads.md` | leads | Лид-канал — заявка, TG-бот | — | 2026-10-18 |
| `lessons.md` | lessons | Уроки перед планированием — что НЕ сработало | `../lessons/README.md` | 2026-11-13 |
| `lr-composition.md` | lr-composition | Композиция гостиной — доли | `../domain/lr-composition-guide.md` | 2026-11-12 |
| `manager-links.md` | manager-links | Ссылка от менеджера застройщика покупателю, сигналы менеджеру, его страница и бот | `../domain/manager-links.md` | 2026-11-12 |
| `market.md` | market | Рынок RU/UK — спрос, монетизация | `../domain/market-research.md` | 2026-11-12 |
| `marketing-acquisition.md` | marketing-acquisition | Реклама — Яндекс, семантика | `../domain/wordstat-semantics.md` | 2026-11-09 |
| `mesh-color.md` | mesh-color | Цвет мешей — диагноз, мерка, рычаги | `../domain/viz-fidelity-playbook.md` | 2026-11-13 |
| `mesh-owner-audit.md` | mesh-owner-audit | Приёмка мешей владельцем — /lab/mesh-audit | `../completed_plans/mesh-owner-audit.md` | 2026-11-13 |
| `mesh-pipeline.md` | mesh-pipeline | 3D-меши — генерация, учёт, приёмка | `../domain/viz-fidelity-playbook.md` | 2026-11-13 |
| `mesh-pool.md` | mesh-pool | Пул нод Salad — группы, тарифы, деньги, стопоры | `../domain/mesh-pool-ops.md` | 2026-11-13 |
| `mesh-run.md` | mesh-run | Прогон мешей — РАБОЧИЙ вариант, старт, остановка | `../domain/mesh-run-playbook.md` | 2026-11-12 |
| `observability-tracing.md` | observability-tracing | Трейсинг AI-пайплайна — лог, разбор | `../domain/observability.md` | 2026-11-12 |
| `partners.md` | partners | Застройщик, ЖК, квартира, цена и сертификат — данные; реестр и карточка квартиры | `../completed_plans/b2b-06-apartment-as-data.md` | 2026-11-10 |
| `pipeline-order.md` | pipeline-order | Порядок конвейера — от фида до расстановки | `../domain/pipeline-order-details.md` | 2026-11-13 |
| `regression-net.md` | regression-net | Регресс-защита — тесты, CI, гардрейлы | `../../docs/tech-spec-ts-stack.md` | 2026-11-13 |
| `room-measurement.md` | room-measurement | Замер комнаты по фото | `../domain/room-measurement.md` | 2026-11-12 |
| `room-templates.md` | room-templates | Шаблоны комнат — порядок создания, паспорт, листы в масштабе | `../domain/room-templates.md` | 2026-11-13 |
| `stock-and-dims.md` | stock-and-dims | Наличие и честность размеров — состояния, парсер, footprint | `../domain/stock-and-dims.md` | 2026-11-12 |
| `styles.md` | styles | Стили — паспорта, скоринг, сеты | `../domain/interior-styles.md` | 2026-11-13 |
| `user-flow.md` | user-flow | Stage 1 UX-flow, аналитика | `../domain/user-flow-details.md` | 2026-11-12 |
| `bedroom.md` | bedroom | Спальня — каталог, банк наборов, показ на /demo, группы, детская | `../domain/pipeline-order-details.md` | 2026-11-13 |
| `design-figma.md` | design-figma | Дизайн демо в Фигме — книги, страницы, пересборка, ручные правки | `../completed_plans/design-01-figma-export.md` | 2026-11-10 |
| `lr-checklist.md` | lr-checklist | Состав гостиной — роли и пригодность | `../domain/living-room-checklist.md` | 2026-11-13 |
| `onboarding-quiz.md` | onboarding-quiz | Опрос-знакомство на /demo — показ, подбор 3 стилей, события, приёмка комнат | `../domain/onboarding-quiz.md` | 2026-11-12 |
<!-- GENERATED:core-registry END -->

> Реестр и decision tree в INDEX регенерирует `tools/memory-audit.mjs` (или `/memory-check`
> вручную, без Node). Создал сводку — проставь frontmatter и запусти аудит: он сам впишет её
> и в реестр, и в decision tree. Руками таблицы не правим.
