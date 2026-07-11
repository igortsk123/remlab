---
workstream: quality
slug: sub-e6-eval
title: Э6 Eval-контур качества: golden-набор, тесты, /admin/eval, промоушен-gate
status: draft
created: 2026-07-11
updated: 2026-07-11
completed:
---

# Э6 Eval-контур качества

## Цель
Владелец-не-кодер ловит деградацию качества генераций без чтения кода; промпт/модель не меняются «молча» — любое изменение проходит eval-прогон и явный аппрув.

## Источник задачи
Этап Э6 коммерческого мастер-плана [[commercial-master-plan]], сессия 2026-07-11.

## Прочитай сначала
- `.memory_bank/plans/commercial-master-plan.md` — место Э6, зависимость от Э5 (частично параллельно).
- `.memory_bank/guides/execution-playbook.md` — правила исполнения.
- `.claude/rules/pipeline-tracing.md` — инварианты версий промптов/пайплайнов (сюда впишем gate).
- `lib/prompts/registry.ts` + `lib/pipelines/registry.ts` — что версионируем (restyle v2, room-analysis v2, ideas v1; preview-v2).
- `lib/trace/admin.ts` — гард `traceAdminOk` и `signedAssetUrl` (образец для /admin/eval).
- `db/schema.ts` + `db/init/003-traces.sql` + `tools/migrate.mjs` — паттерн схемы/идемпотентных миграций.
- `tools/trace-show.mjs` — образец node-скрипта с доступом к БД/трейсам.
- `app/actions.ts` (`startProject`/`saveBrief`/`saveSelection`) + `app/api/p/[id]/{analyze,generate}` — флоу, который повторяет eval-прогон.
- `.github/workflows/deploy.yml` — паттерн «нет секрета → job скипается».
- `contracts/project.ts`, `contracts/style.ts` — формат брифа для golden-кейсов.

## Скоуп — что входит
1. Golden-набор 20–30 кейсов (фото webp + бриф) в `eval/golden/`, версионируется вместе с реестром промптов.
2. Детерминированные проверки = блок мержа (vitest): снапшоты рендера промптов, целостность golden-геометрии; при появлении ml-service (Э5) — точные числа fit/площадей там же (pytest).
3. Перцептивные проверки = сигнал, не блок: `tools/eval-run.mjs` — SSIM на keep-объектах, edge-IoU, SigLIP-близость к брифу (fal/Replicate), бюджеты cost/latency из трейса.
4. `/admin/eval` за TRACE_ADMIN_TOKEN: грид «до/после», метрики, кнопки OK/Fail → таблица `eval_runs`.
5. Промоушен-gate как процесс в `.claude/rules/pipeline-tracing.md`.
6. Автоматика: GH Action `eval` (workflow_dispatch + nightly подвыборка 5 фото, ~$0.4/ночь, $-лимит), алерт на дрейф cost/error-rate.

## Скоуп — что НЕ входит
- Полноценный LLM-judge, внешние eval-платформы (Braintrust/LangSmith и т.п.).
- Реализация fit-логики в TS (это Э5/ml-service) — здесь только фикстуры и каркас тестов.
- PostHog-инсайты/дашборды сверх простого чека в nightly (follow-up).
- Юридика по фото людей в golden (ПДн) — TODO, не блокироваться.

## Файлы к изменению
- [ ] `eval/golden/` (новый) — 20–30 кейсов: `<case-id>/photo.webp` + `brief.json` (+ `geometry.json` где есть промеры)
- [ ] `eval/golden/manifest.json` (новый) — реестр кейсов, теги, пороги, baseline-версии промптов
- [ ] `eval/baseline.json` (новый) — эталонные метрики последнего аппрувнутого прогона
- [ ] `tests/unit/prompt-snapshots.test.ts` (новый) — снапшоты рендера промптов по версиям
- [ ] `tests/unit/eval-geometry.test.ts` (новый) — целостность golden-геометрии (точные числа)
- [ ] `tools/eval-run.mjs` (новый) — перцептивный прогон + бюджеты + отчёт
- [ ] `app/admin/eval/page.tsx` (новый) — грид «до/после» + вердикты владельца
- [ ] `app/api/eval/verdict/route.ts` (новый) — POST вердикта (гард `traceAdminOk`)
- [ ] `db/schema.ts` — таблица `eval_runs`
- [ ] `db/init/004-eval.sql` (новый) — DDL `eval_runs` для чистого volume
- [ ] `tools/migrate.mjs` — идемпотентное создание `eval_runs`
- [ ] `package.json` — скрипт `eval`, devDependency `sharp` (декодирование картинок для метрик)
- [ ] `.github/workflows/eval.yml` (новый) — workflow_dispatch + nightly cron
- [ ] `.claude/rules/pipeline-tracing.md` — раздел «Промоушен-gate промпта/модели»
- [ ] `.memory_bank/core/quality-eval.md` (новый) — Tier 1 сводка домена + памятка владельцу

## Задачи

### Блок A — Golden-набор
- [ ] Создать `eval/golden/`: на кейс — `photo.webp` (компактный, ориентир ≤300 KB; пережать имеющимся тулингом или sharp) + `brief.json` строго по Zod-схемам из `contracts/project.ts`/`contracts/style.ts` (roomType, interventionLevel, стиль, choices keep/change/remove, wish).
- [ ] Переиспользовать фото из `ml/golden` (план [[sub-ml-sizes]]), где типы комнат совпадают; добить недостающие (спальня/кухня/детская/санузел, светлые/тёмные, захламлённые/пустые) до 20–30. Фото без людей.
- [ ] `manifest.json`: массив кейсов `{id, tags, hasGeometry}` + блок `thresholds` (пороги из блока C) + `promptVersions`/`pipelineVersion` на момент снятия baseline (брать из реестров).
- [ ] Кейсы с промерами: `geometry.json` — эталонные числа (площадь пола м², масштаб px/см, ожидаемые fit-вердикты для 2–3 товаров) из проверенных прогонов mltest.

### Блок B — Детерминированные проверки (блок мержа)
- [ ] `tests/unit/prompt-snapshots.test.ts`: для каждого промпта реестра (`room-analysis`, `restyle`, `ideas`) вызвать `build()` на 2–3 фиксированных входах из golden-брифов; результат сверять со снапшотом, в имени/содержимом которого — `id@version`. Меняешь текст без бампа версии → тест красный. Плюс тест на состав `PIPELINES` (id/version/steps как ожидается).
- [ ] `tests/unit/eval-geometry.test.ts`: провалидировать все `geometry.json` Zod-схемой и проверить внутреннюю согласованность чисел точными равенствами (никаких «примерно»). Это каркас: сами вычисления fit живут в ml-service (Э5) — при его появлении те же фикстуры гоняет pytest внутри ml-service, здесь оставить комментарий-указатель.
- [ ] Убедиться, что оба теста входят в `pnpm test` (vitest подхватывает `tests/unit/*` автоматически) → CI (`.github/workflows/ci.yml`) блокирует мерж без правок workflow.

### Блок C — Перцептивный прогон `tools/eval-run.mjs`
- [ ] Скрипт по образцу `tools/trace-show.mjs` (env: `DATABASE_URL`, `EVAL_BASE_URL`, `TRACE_ADMIN_TOKEN`, `FAL_KEY`/`REPLICATE_API_TOKEN` — уже в `.env.example`; значения не логировать). Режимы `--all | --sample N | --case <id>`.
- [ ] Прогон кейса: повторить флоу HTTP-запросами к работающему приложению (изучить `app/actions.ts` и `/api/p/[id]/{analyze,generate}`); если server actions из скрипта неудобны — добавить служебный `POST /api/eval/run` за `traceAdminOk`, создающий проект из кейса и запускающий генерацию. Прогоны помечать `meta.eval=true` в `generation_runs` (исключение из продуктовой аналитики).
- [ ] Метрики пары «до/после»: (1) SSIM по bbox keep-объектов из analyze-ответа; (2) edge-IoU — Sobel по grayscale обеих картинок, IoU бинарных карт границ (структура комнаты сохранилась); (3) SigLIP-близость результата к текстовому брифу через fal (fallback Replicate) — при отсутствии ключей метрика скипается с пометкой. Декодирование webp/png → raw пиксели через sharp; сами метрики — простой JS по буферам.
- [ ] cost/latency: по `seq` прогона прочитать `total_cost_usd`/`total_latency_ms` из `generation_runs` (SQL или `/api/trace/[seq]`).
- [ ] Итог: `eval/out/<timestamp>/report.json` (в .gitignore) + строка в `eval_runs`; сравнение с `eval/baseline.json` → `auto_status: ok | review`. Стартовые пороги (в manifest, калибровать по первому прогону): SSIM keep ≥ 0.85, edge-IoU ≥ 0.60, SigLIP ≥ baseline − 0.03, cost ≤ 1.5× baseline. Суммарный бюджет прогона — стоп при превышении `EVAL_BUDGET_USD` (дефолт 1).

### Блок D — /admin/eval + eval_runs
- [ ] Схема `eval_runs`: `id, created_at, pipeline_id, pipeline_version, prompt_versions jsonb, model, case_id, run_seq, metrics jsonb, auto_status, owner_verdict, notes` → `db/schema.ts` + `db/init/004-eval.sql` + идемпотентный блок в `tools/migrate.mjs` (по образцу traces).
- [ ] `app/admin/eval/page.tsx`: доступ — `searchParams.token === process.env.TRACE_ADMIN_TOKEN` (тот же принцип, что `traceAdminOk`; токен не задан → открыт только в dev, в проде без токена — notFound). Грид по последнему прогону: кейс → «до/после» (картинки через `signedAssetUrl` из `lib/trace/admin.ts`), метрики со светофором против baseline, кнопки OK/Fail.
- [ ] Кнопки → `POST /api/eval/verdict` (гард `traceAdminOk`) → `owner_verdict`.
- [ ] Тексты — простым языком: не «SSIM 0.83», а «объекты, которые просили не трогать, сохранились на 83%».

### Блок E — Промоушен-gate (процесс)
- [ ] Дополнить `.claude/rules/pipeline-tracing.md`: новый промпт/модель → bump версии в реестре → `pnpm test` зелёный (снапшоты обновлены осознанно) → `pnpm eval --all` → перцептивные не хуже baseline → владелец смотрит /admin/eval и жмёт OK → деплой → обновить `eval/baseline.json` и `promptVersions` в manifest.
- [ ] Памятка владельцу «как прогнать eval и что значат цифры» — в `.memory_bank/core/quality-eval.md`, короткая версия — текстом на самой странице /admin/eval.

### Блок F — Автоматика
- [ ] `.github/workflows/eval.yml`: `workflow_dispatch` (полный прогон) + `schedule` nightly (`--sample 5`). Гоняет против прода (`EVAL_BASE_URL=https://remont-lab.online`) с секретами `TRACE_ADMIN_TOKEN`/ключами; нет секретов → job скипается (паттерн `deploy.yml`).
- [ ] Дрейф-чек в конце nightly: средний cost/генерацию и error-rate прогона vs baseline; выход за порог → job падает (красный бейдж + письмо GitHub). PostHog-insight — в Follow-up.

## Гейты
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build` — зелёные; `pnpm e2e` — зелёный.
- [ ] Мутация-проверка: временно изменить строку в `restylePrompt.build` без бампа версии → `pnpm test` красный → откатить.
- [ ] Детерминизм: `pnpm eval --case <id>` дважды → детерминированные числа (геометрия, снапшоты, cost по трейсу) идентичны бит-в-бит.
- [ ] Регрессия-инъекция: убрать из restyle-промпта требование «СОХРАНИВ геометрию» (с бампом версии) → eval помечает кейсы `review` (edge-IoU падает) → откатить, результат в лог.
- [ ] `curl -s -o /dev/null -w "%{http_code}" https://remont-lab.online/admin/eval` → не 200 без токена; с `?token=…` → 200.
- [ ] `pnpm db:migrate` идемпотентен (два запуска подряд без ошибок), `/api/health` зелёный после деплоя.

## Чекпоинты владельца
- ⏸ ПОКАЗАТЬ ВЛАДЕЛЬЦУ: состав golden-набора — грид фото с подписями (ссылка на /admin/eval или таблица). Вопрос: «Эти комнаты похожи на то, что будут снимать пользователи? Каких не хватает?»
- ⏸ ПОКАЗАТЬ ВЛАДЕЛЬЦУ: первый полный прогон — ссылка на /admin/eval + расшифровка метрик в 3 предложениях. Вопрос: «Пройди по кейсам, нажми OK/Fail — это станет эталоном (baseline), с которым будем сравнивать все будущие изменения.»
- ⏸ ПОКАЗАТЬ ВЛАДЕЛЬЦУ: цикл своими руками — по памятке владелец сам проходит «правка слова в промпте → eval → аппрув в /admin/eval → деплой». Вопрос: «Получилось без моей помощи? Где застрял?» (это приёмочный критерий Э6).

## Если пошло не по плану
- **SigLIP через fal/Replicate недоступен или дорог** → метрика скипается флагом, SSIM/edge-IoU/cost работают локально без API. Не эскалировать.
- **Перцептивные метрики шумят (все кейсы review)** → откалибровать пороги по перцентилям первого прогона; если сигнала нет вовсе — оставить cost/latency + обзор глазами, зафиксировать в `docs/DECISIONS.md`, владельцу сказать честно.
- **Eval-прогоны засоряют прод-данные/трейсы** → `meta.eval=true` + фильтр в аналитике; если мешает всё равно — гонять против локального `docker compose` с `REMLAB_FAKE_AI=0`.
- **Nightly выходит за бюджет** → `--sample 3` или 2 раза в неделю; `EVAL_BUDGET_USD` — жёсткий стоп.
- **ml-service (Э5) ещё не готов** → геометрия остаётся каркасом фикстур, план НЕ блокируется; зависимость отметить в реестре мастер-плана.
- **Владелец не смог пройти цикл сам** → упростить памятку/UI и повторить; если и после второй итерации нет — эскалировать: gate Э6 не сдан, обсудить, что именно непонятно.

## Критерии приёмки
- [ ] Специально внесённая регрессия (сломанный промпт) ловится метрикой или уходит на review — показано на живом прогоне.
- [ ] Повторный прогон даёт идентичные детерминированные числа.
- [ ] Правка текста промпта без бампа версии не проходит `pnpm test`.
- [ ] /admin/eval работает на проде за токеном; вердикты сохраняются в `eval_runs`.
- [ ] Nightly-workflow прошёл минимум одну ночь, бюджет соблюдён.
- [ ] Владелец сам прошёл цикл «правка промпта → eval → аппрув → деплой» без помощи.

## Definition of Done — память
- [ ] `.memory_bank/core/quality-eval.md` создан (Tier 1, frontmatter, tier2-указатели).
- [ ] Решения (пороги, выбор метрик, gate-процесс) → `decisions.md` (ADR); смена этапа → `project-state.md`.
- [ ] `.claude/rules/pipeline-tracing.md` дополнен gate'ом; `core/observability-tracing.md` сверен.
- [ ] `/memory-check` выполнен, audit «чисто».
- [ ] Статус в реестре [[commercial-master-plan]] обновлён; план → `completed_plans/` только после всего выше.

## Лог выполнения
- 2026-07-11 — записан черновик БЕЗ verify-прохода (проверка путей/фактов вдогонку перед «деплой»)
- 2026-07-11 — план создан, draft.

## Completion summary

## Follow-up work
- PostHog-инсайт/дашборд дрейфа cost и error-rate (вместо падающего job).
- Расширение golden до 50+ кейсов по мере реальных пользовательских фото (с согласия).
- pytest-слой на тех же geometry-фикстурах внутри ml-service — закрывается в [[sub-e5-fit-integration]].
- Полу-LLM-judge (vision-модель оценивает «похоже на бриф?») — только если ручной обзор станет узким местом.
