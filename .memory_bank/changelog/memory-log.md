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

## 2026-09-05 — аудит и реструктуризация памяти (план `plans/memory-bank-audit-2026-09.md`)
Команда: ручной прогон по одобренному плану (фазы 1–7), скрипты в scratchpad; бэкап `~/backups/remlab-membank-2026-09-05.tgz`
Approval: владелец 05.09 (план в Plan Mode; Фаза 0: фокус A, перенос уроков, манифест архивации, гейт после /memory-check)

- MOVE     _intake/*.log ×77 (22 МБ, gitignored) → ~/scout-logs/2026-09/ — причина: логи — не память; живые batch-hardened.log/money-guard.log остались
- ARCHIVE  _intake/_processed/ ×4 → archive/2026/07/intake-init/ — причина: были в git и в .gitignore разом, единственная копия
- MOVE     _intake/salad-ssh-key.txt → infra/keys/salad-mesh.pub — причина: публичный ключ, место — infra, не intake
- FIX      _intake/README.md — индекс входной папки (tools/intake-index.mjs): 159 файлов, сведено/не сведено
- SPLIT    decisions.md (474 КБ, 187 записей) → decisions.md (индекс 36 КБ, «по темам») + decisions/adr-0001-0050 … adr-0151-0200 — тексты дословно (хеши 187/187)
- FIX      дубли номеров ADR: 0028→0180, 0135→0181, 0136→0182, 0158→0183, 0159→0184, 0168→0185, 0173→0186 (+пометка Legacy в теле, ссылки в 8 доках и 5 файлах кода)
- MOVE     docs/DECISIONS.md: 8 полных ADR → приложение adr-0001-0050.md; копия → archive/2026/09/docs-DECISIONS.md; файл → указатель legacy
- ARCHIVE  plans/ ×53 → archive/plans/ (поля archived/archive_reason/superseded_by; манифест — scratchpad plans-manifest-all.tsv, копия ниже) — причина: отменённые (2), отложенные ступени М2/М4/М5/М7 (11), заморожено 19.08 / поглощено ADR (40); открытых 21
- FIX      [[slug]] архивированных планов → `archive/plans/<slug>.md` в 11 контент-доках; partial-планы получили pause_reason/resume_trigger/review_after; мастера — plan_kind/parent_plan
- ARCHIVE  goals-one-photo-furnish-fit.md → archive/2026/09/ — причина: цели v0.3 перекрыты v0.4 и мебельным треком; core/goals.md, product_brief.md переписаны под v0.4
- FIX      Tier 0 (CLAUDE.md, INDEX.md), source-of-truth.md, project-state.md (9.5 → 6 КБ) — под решение владельца ADR-0187 (М5 раньше М2–М4); README банка под кит v1.6; docs/README, advertising/README
- ADD      core/mesh-pool.md ↔ domain/mesh-pool-ops.md — пул Salad: деньги, стопоры, замеры (вынесено из снимка)
- FIX      review_after у 24 tier-1 доков; frontmatter у .claude/rules/codex-adviser.md; memory-discipline.md ужат до ~55 строк (детали → guides/memory-automation.md)
- FIX      оглавления в 13 доках >15 КБ (domain/guides/история/тома ADR)
- ADD      tools/memory-project-audit.mjs + tests (ADR-уникальность/индекс, TTL планов, блокнот, канон→intake, секреты, md5 кита) — в CI и SessionStart-хук
- (уроки)  anti-patterns.md → lessons/<тема>.md дословно + core/lessons.md как маршрутизатор — см. запись ниже по завершении Фазы 4

Манифест архивации планов (slug — причина): sub-e2-feeds, entry-and-axis (cancelled) · room-measurement-a4, unified-measurement-pipeline, sub-ml-sizes, ads-autopilot, sub-e4-payments, sub-e7-growth, ads-bath-calc, solver-speed, layout-polygon-rooms (deferred) · sub-e0-stopkran, sub-e3-foundation, ergonomics-planner, gdeslon-catalog, living-room-sets, adaptive-sets, set-quality-fixes, MASTER-viz-quality, llm-layout-planner, viz-pipeline, viz-scene-compiler, catalog-freshness-chain, MASTER-pipeline-hardening, MASTER-zones-first, layout-rules-v2, viz-track-a-restore (superseded) · calc-materials-roadmap, layout-engine-gaps, scalability-hardening, design-order-pipeline, sets-compose-v2, catalog-freshness, layout-quality, occupancy-rules-research, prod-layout-engine, room-size-fit, sets-style-v3, viz-object-binding, MASTER-catalog-ai, catalog-enrichment-pipeline, sets-feasibility-first, MASTER-layout-v5, MASTER-truth-first, inventory-additions, layout-composition-deep, layout-priors-from-datasets, referee-hardening, seating-template-ladder, template-integrity, mask-quality-rgba-contract, entry-low-storage, template-library-v2 (absorbed).

## 2026-08-04 — апгрейд кита v1.4.0 → v1.6.0
Команда: upgrade.sh

- UPGRADE  kit-owned файлы — обновлено: 8, добавлено: 0, конфликтов: 0 (*.kit-new)

## 2026-07-23 — апгрейд кита v1.3.0 → v1.4.0
Команда: upgrade.sh

- UPGRADE  kit-owned файлы — обновлено: 9, добавлено: 3, конфликтов: 0 (*.kit-new)

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

## 2026-07-31 — Восстановлен autopilot (ADR-0033) + починен корневой баг кита
Симптом: агент переспрашивал на каждой команде, хотя проект в режиме `autopilot`. Причина —
не промпты и не хуки: 2026-07-23 повторным `apply.sh` поверх autopilot лёг пресет `important`,
`ask` склеился 13 → 26, а `ask` в Claude Code сильнее `allow`. Правки: `.claude/settings.local.json`
→ чистый autopilot (хуки и `autoMode` сохранены, бэкап `.bak-20260731-090154`); заведён
`_kit/permission-mode.txt` = `autopilot`; ADR-0033 в `decisions.md`. Корень починен апстримом —
кит v1.4.1 (`merge-settings.py/.ps1`: вычитание kit-managed записей при смене режима). Банк
не менялся структурно, audit чист (55 доков, Tier 0 7.9 KB / 1.7%).

## 2026-07-31 — /memory-check после calc-walls-ui-header-fixes
Захват: уроки 7–8 в `core/lessons.md` (гистерезис sticky-коллапса; активная кнопка — заливкой);
`core/estimate.md` (стены из карточки размеров), `core/user-flow.md` (шапка) обновлены. Мост
авто-памяти: пусто (3 файла — per-user). План → `completed_plans/`. TIER1-BLOAT (estimate,
lessons, user-flow) ужат без потери смысла. Audit чист (55 доков, Tier 0 7.9 KB / 1.7%).

## 2026-07-31 — /memory-check после calc-empty-hint-above-card
UI-грабли сведены в Tier 2: `anti-patterns.md` §6 (скрытый скролл навигации, мерцание sticky-шапки,
активная кнопка «в рамочке», подсказка под формой) — в `core/lessons.md` остался bullet 2 со ссылкой
(Tier 1 упирался в лимит 3 KB). План → `completed_plans/`. Audit чист (56 доков, Tier 0 7.9 KB / 1.7%).

## 2026-07-31 — /memory-check после calc-wall-card-compact
`anti-patterns.md` §7: иконка-подсказка в отдельной строке (пустая полоса) и рядом с зоной
разрушающих действий; при переносе к левому краю — `.help--start` (сторона тултипа). План →
`completed_plans/`. Audit чист.

## 2026-07-31 — /memory-check после calc-assumed-defaults-visible
ADR-0034 (не считать по молчаливым дефолтам) в `decisions.md`; правило в `core/estimate.md`,
урок 7 в `core/lessons.md`. План → `completed_plans/`. Tier 1 (estimate, lessons) ужаты под
лимит 3 KB. Audit чист (56 доков, Tier 0 7.9 KB / 1.7%).

## 2026-07-31 — /memory-check после calc-openings-restore
ADR-0035 (возврат проёмов, откат ADR-0027) уже был в decisions.md; `core/estimate.md` — UX-строка
обновлена («проёмы скрыты» устарело), урок 8 в `core/lessons.md` (удаление функциональности —
только с явного «да» владельца). План → `completed_plans/`. Tier 1 ужаты. Audit чист.
- 2026-08-17 /memory-check после Q5 (ADR-0107): захват блокнота (23 строки) → decisions/core-layout/core-catalog/lessons 272–277/project-state (снимок переписан, 12→8 KB, старое → project-history)/anti-patterns (267–271); 6 планов in_progress с 02.08 → partial (поглощены сводами); audit чисто.
- 2026-08-17 (вечер) /memory-check: ADR-0108 (каноны/pod-heal/роли по листу/OpenAI бюджет/ускорение), project-state переписан, lessons 278–282 (272–277 → anti-patterns), core layout/catalog обновлены; блокнот очищен.
