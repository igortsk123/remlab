# Plans — активные планы

## Lifecycle
```
draft → in_progress → completed → перенос в completed_plans/
                   ↘ partial   → остаётся здесь
        cancelled → остаётся здесь
```
Только `completed` переносятся в `completed_plans/`. `partial`/`cancelled` остаются здесь.
**Гейт:** план не становится `completed`, пока не выполнен `/memory-check` и audit не «чисто»
(см. `.claude/rules/agent-workflow.md`).

## Статусы
| Статус | Описание |
|--------|----------|
| `draft` | Создан, ждёт команду «деплой» |
| `in_progress` | Деплой начат |
| `partial` | Прерван, часть выполнена — НЕ переносить |
| `completed` | Всё выполнено → перенести в `completed_plans/` |
| `cancelled` | Отменён явно |

## Реестр активных планов

<!-- GENERATED:plans-registry START -->
<!-- Таблицу регенерирует tools/memory-audit.mjs из frontmatter. Не редактируй вручную. -->

| slug | Название | status | created | updated |
|------|----------|--------|---------|---------|
| sub-ml-sizes | ML: стабилизация замера (контур, площади пола, footprint) | draft | 2026-07-11 | 2026-07-11 |
| sub-e8-scale | Э8 Второй мотор и масштаб — B2B, надёжность, UK (скелет) | draft | 2026-07-11 | 2026-07-11 |
| sub-e7-growth | Э7 Рост — SEO, шаринг, e-mail, anti-abuse (скелет) | draft | 2026-07-11 | 2026-07-11 |
| sub-e6-eval | Э6 Eval-контур качества — golden-набор, тесты, /admin/eval, промоушен-gate | draft | 2026-07-11 | 2026-07-11 |
| sub-e5-fit-integration | Э5 (=Ф8): ml-service в проде — fit, вставка в масштабе, правка человеком | draft | 2026-07-11 | 2026-07-11 |
| sub-e4-payments | Э4 Монетизация: YooKassa, тарифы 1490/9900, entitlements | draft | 2026-07-11 | 2026-07-11 |
| sub-e3-foundation | Э3 Фундамент продаж — async-джобы, файлы вместо base64, аккаунты, квоты | draft | 2026-07-11 | 2026-07-11 |
| sub-e2-feeds | Э2 — фиды Гдеслон, автоподбор, постбэки | draft | 2026-07-11 | 2026-07-11 |
| sub-e1-validation | Э1 Stage 0 — concierge-валидация экономики на живом трафике | draft | 2026-07-11 | 2026-07-11 |
| sub-e0-stopkran | Э0 Стоп-кран: безопасность, лимиты, рельсы измерения | draft | 2026-07-11 | 2026-07-11 |
| cost-first-funnel | Ценовая воронка — «посчитай ремонт/материалы» как вход, реф-смета как монетизация | draft | 2026-07-11 | 2026-07-11 |
| commercial-master-plan | Коммерческий мастер-план — от демо к зарабатывающему продукту (v0.3) | active | 2026-07-11 | 2026-07-11 |
| ads-bath-calc | Директ, кампания №2 — Ванная/Плитка + Калькуляторы материалов | partial | 2026-07-11 | 2026-07-11 |
| ads-autopilot | Автопилот рекламы — стоп-кран, авто-минусовка, A/B-тексты, отчёты (сервер + Gemini) | draft | 2026-07-11 | 2026-07-11 |
| round-oval-footprint | — | draft | 2026-07-07 | — |
| unified-measurement-pipeline | — | draft | 2026-07-06 | 2026-07-06 |
| object-size-reference | — | draft | 2026-07-06 | 2026-07-06 |
| accuracy-upgrade-fal | — | draft | 2026-07-06 | 2026-07-06 |
| MASTER-roadmap | — | active | 2026-07-06 | 2026-07-06 |
| room-measurement-a4 | — | draft | 2026-07-05 | 2026-07-05 |
| stage1-skeleton | — | draft | 2026-07-01 | 2026-07-01 |
| stage1-master-roadmap | — | draft | 2026-07-01 | 2026-07-01 |
<!-- GENERATED:plans-registry END -->

> Шаблон нового плана — `_template.md`. Реестр регенерирует аудит — руками не правим.
> Audit также ловит зомби: `in_progress` без движения (PLAN-STUCK) и `completed`,
> забытый в этой папке (PLAN-MISPLACED).
