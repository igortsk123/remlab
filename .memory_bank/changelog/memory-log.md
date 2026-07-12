# Memory Log — журнал очисток и архиваций

> Append-only лог изменений памяти, сделанных `/memory-cleanup` (и ручных архиваций).
> Нужен для прозрачности и обратимости: видно, что/когда/почему изменили или заархивировали.
> Новые записи добавляются СВЕРХУ. Этот файл исключён из аудита.

## Формат записи

```
## YYYY-MM-DD — <короткий заголовок прогона>
Команда: /memory-cleanup [--apply]
Approval: <кто подтвердил / «dry-run, без применения»>

- ARCHIVE  <путь> → archive/YYYY/MM/<файл>  — причина: <...>
- MERGE    <путь A> + <путь B> → <итог>      — причина: <дубль>
- COMPRESS <путь>                            — было N KB, стало M KB
- DELETE   <путь> (архивная копия: archive/YYYY/MM/<файл>) — причина: <...>
- VERIFY   <путь>                            — поднят вопрос: <...>
- FIX      INDEX/ссылки                      — <что починили>
```

---

## 2026-07-12 — апгрейд кита v1.1.0 → v1.3.0
Команда: upgrade.sh

- UPGRADE  kit-owned файлы — обновлено: 3, добавлено: 0, конфликтов: 0 (*.kit-new)

## 2026-07-09 — апгрейд кита v(до версионирования) → v1.1.0
Команда: upgrade.sh

- UPGRADE  kit-owned файлы — обновлено: 0, добавлено: 5, конфликтов: 7 (*.kit-new)

<!-- Реальные записи прогонов очистки добавляются ниже (сверху — свежие). -->
- 2026-07-01 — добавлены наработки авто-ведения памяти: скилл /memory-consolidate, усилен memory-discipline (единственное хранилище + цикл сессии), guides/memory-automation.md, INDEX/CLAUDE.
- 2026-07-01 — добавлено рыночное исследование RU/UK: docs/market-research-ru-uk.md + core/market.md (Tier1), обогащён product_brief; INDEX regen.
- 2026-07-01 /memory-consolidate: прод LIVE Stage 1 (v814761f) + фиксы (bodySizeLimit, /rooms cookie); PostHog ADR-0012; авто-деплой GHCR настроен, но НЕ активен (нет секрета DEPLOY_SSH_KEY); CI-ключ на сервере; PAT read-only.
- 2026-07-02 /memory-consolidate: (1) трейсинг ADR-0013 ЗАДЕПЛОЕН в прод (версия tracing-142829, imagor+том remlab-traces, trace-таблицы, sequence→#1, TRACE_ADMIN_TOKEN на сервере, бэкап pre-tracing) — обновлены project-state (статус LIVE, прод впереди main) и completed_plans/pipeline-tracing (follow-up отмечены); (2) пивот бизнес-модели v0.2→v0.3 (ADR-0014): master-brief-v0.3 + 3 варианта «что сделать с комнатой» (бесплатно / 1 490 ₽ / 9 900 ₽), affiliate-first, Гдеслон, Postgres self-host подтверждён — обновлены CLAUDE, source-of-truth, product_brief, core/{market,user-flow,data-model,access-and-integrations}, decisions, DECISIONS, INDEX.

## 2026-07-11 — Пивот v0.4 «Смета-first» (ADR-0016): ревизия планов
Архивировано 12 планов → `archive/plans/` (commercial-master-plan, MASTER-roadmap,
cost-first-funnel, sub-e1/e5/e6/e8, accuracy-upgrade-fal, object-size-reference,
round-oval-footprint, stage1-master-roadmap, stage1-skeleton) — причины в шапках файлов
и в таблице «Судьба прежних планов» мастер-плана `plans/MASTER-cost-first.md`.
Остались: sub-e0/e2(скоуп+материалы)/e3/e4/e7, ml-замеры (для «сфоткай—посчитаем»), ads-*.
