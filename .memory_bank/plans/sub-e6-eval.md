---
workstream: quality
slug: sub-e6-eval
title: Э6 Eval-контур качества — golden-набор, тесты, /admin/eval, промоушен-gate
status: draft
created: 2026-07-11
updated: 2026-07-11
completed:
---

# Э6 Eval-контур качества

## Цель
Владелец-не-кодер ловит деградацию без чтения кода; изменение промпта/модели проходит eval и явный аппрув.

## Источник задачи
Этап Э6 [[commercial-master-plan]], сессия 2026-07-11.

## Прочитай сначала
- `plans/commercial-master-plan.md`, `guides/execution-playbook.md`, `.claude/rules/pipeline-tracing.md`.
- `lib/{prompts,pipelines}/registry.ts`, `lib/trace/admin.ts`; `contracts/{project,enums,style}.ts` — ⚠️ `roomType` только `living_room|bedroom`, `detectedObject` без bbox.
- `db/schema.ts`, `deploy.sh`; `app/actions.ts`, `app/api/p/[id]/{analyze,generate}/route.ts`.

## Скоуп — что входит
Блоки A–F ниже (golden, тесты-гейт, перцептивный прогон, /admin/eval, промоушен-gate, nightly с дрейф-чеком).

## Скоуп — что НЕ входит
LLM-judge/eval-платформы; fit в TS (Э5); расширение `roomType`; PostHog-дашборды (follow-up); юридика фото — TODO.

## Файлы к изменению
- [ ] `eval/golden/` (+`manifest.json`), `eval/baseline.json`, `eval/run.mjs` (новые; раннер НЕ в `tools/` — тот в `.gitignore`)
- [ ] `tests/unit/{prompt-snapshots,eval-geometry}.test.ts`; `app/admin/eval/page.tsx`; `app/api/eval/{run,report,verdict}/route.ts` (новые)
- [ ] `db/schema.ts`; `db/init/004-eval.sql` (новый); `deploy.sh` — scp+psql 004 (только так DDL едет в прод); `tools/migrate.mjs` — идемпотентный блок
- [ ] `package.json` — `"eval": "node eval/run.mjs"`, devDep `sharp`; `.env.example` — `EVAL_BASE_URL`, `EVAL_BUDGET_USD`; `.gitignore` — `eval/out/`
- [ ] `.github/workflows/eval.yml` (новый); `.claude/rules/pipeline-tracing.md`; `.memory_bank/core/regression-net.md` (Tier 1 уже есть); `.memory_bank/guides/eval-owner.md` (новый)

## Задачи

### A — Golden
- [ ] Кейс: `photo.webp` (sharp, ≤300 KB) + `brief.json` по Zod (`briefSchema`+`styleProfile`+`objectChoices`+`wish`). Фото из `/home/pakar/mltest/` (в git — по `sub-ml-sizes`) + добрать до 20–30; только `living_room|bedroom`, разный свет/захламлённость, без людей.
- [ ] `manifest.json`: `{id, tags, hasGeometry}` + `thresholds` + версии из реестров. `geometry.json`: площадь пола, px/см, fit-вердикты товаров.

### B — Детерминированные (блок мержа)
- [ ] `prompt-snapshots.test.ts`: `build()` каждого промпта на 2–3 golden-входах → снапшот `id@version`; правка без бампа → красный; + тест `PIPELINES`.
- [ ] `eval-geometry.test.ts`: Zod-валидация `geometry.json` + точные равенства; fit уедет в ml-service (Э5, pytest там же) — комментарий. Оба в `tests/unit/` → CI блокирует мерж.

### C — Перцептивный прогон
- [ ] `eval/run.mjs` по образцу `trace-show.mjs`. Env (не логировать): `EVAL_BASE_URL`, `EVAL_BUDGET_USD`, `TRACE_ADMIN_TOKEN`, `FAL_KEY`/`REPLICATE_API_TOKEN` (уже в `.env.example`). Режимы `--all | --sample N | --case <id> | --recompute <dir>` (пересчёт по сохранённым картинкам).
- [ ] Прогон: `POST /api/eval/run` — создаёт проект из кейса, гонит analyze→generate кодом server actions; `meta.eval=true` в `generation_runs`.
- [ ] Метрики (sharp → raw, простой JS): SSIM всего кадра (bbox нет — follow-up); edge-IoU (Sobel → границы → IoU); SigLIP-близость к брифу (fal/Replicate; без ключей — скип). cost/latency — `GET /api/trace/[seq]` (прод-БД снаружи закрыта).
- [ ] Итог: `eval/out/<ts>/report.json` + `POST /api/eval/report` → `eval_runs`; против `baseline.json` → `auto_status: ok|review`. Пороги (manifest, калибровка по 1-му прогону): SSIM ≥0.85, edge-IoU ≥0.60, SigLIP ≥ baseline−0.03, cost ≤1.5×; стоп по `EVAL_BUDGET_USD`.

### D — /admin/eval + eval_runs
- [ ] `eval_runs` по образцу `generation_runs`: case_id, run_seq, версии pipeline/prompts (jsonb), metrics (jsonb), auto_status, owner_verdict, created_at.
- [ ] `page.tsx`: доступ как `traceAdminOk` (`searchParams.token`; без токена — dev-only, в проде notFound). Грид: «до/после» (`signedAssetUrl`), светофор метрик, OK/Fail → `POST /api/eval/verdict`. Тексты простые: «структура совпадает на 83%», не «SSIM 0.83».

### E — Промоушен-gate
- [ ] В `pipeline-tracing.md`: bump версии → `pnpm test` зелёный → `pnpm eval --all` → не хуже baseline → владелец жмёт OK → деплой → обновить `baseline.json` + `promptVersions`. Памятка → `guides/eval-owner.md`; краткая — на странице.

### F — Автоматика
- [ ] `eval.yml`: dispatch (`--all`) + nightly (`--sample 5`) на прод (`EVAL_BASE_URL`); секреты `TRACE_ADMIN_TOKEN`/`FAL_KEY`, без них — skip (паттерн `deploy.yml`). Дрейф-чек: cost и error-rate vs baseline; за порогом job падает.

## Гейты
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build`; `pnpm e2e`; `pnpm db:migrate` дважды подряд без ошибок.
- [ ] Мутация: строка в `restylePrompt.build` без бампа → `pnpm test` красный → откатить.
- [ ] Детерминизм: `pnpm eval --case <id>` + дважды `--recompute` → метрики бит-в-бит.
- [ ] Инъекция: убрать «СОХРАНИВ её геометрию» из restyle (с бампом) → кейсы в `review` → откатить, в лог.
- [ ] `curl -s -o /dev/null -w "%{http_code}" https://remont-lab.online/admin/eval` → без токена не 200, с `?token=` 200; `/api/health` зелёный.

## Чекпоинты владельца
- ⏸ ПОКАЗАТЬ ВЛАДЕЛЬЦУ: состав golden — грид фото. «Похожи на комнаты пользователей? Каких не хватает?»
- ⏸ ПОКАЗАТЬ ВЛАДЕЛЬЦУ: первый прогон — /admin/eval + расшифровка цифр. «Нажми OK/Fail — станет эталоном.»
- ⏸ ПОКАЗАТЬ ВЛАДЕЛЬЦУ: сам проходит «правка слова в промпте → eval → аппрув → деплой». «Вышло без помощи? Где застрял?» — приёмка Э6.

## Если пошло не по плану
- SigLIP недоступен → скип; метрики шумят → пороги по перцентилям 1-го прогона; нет сигнала → cost/latency + глаза, в `docs/DECISIONS.md`. Не эскалировать.
- Eval засоряет прод → `meta.eval=true` + фильтр; мешает → локальный compose с реальными ключами (`REMLAB_FAKE_AI=1` не ставить).
- Nightly дорог → `--sample 3` / 2 раза в нед. Э5 не готов → геометрия — каркас, не блокирует.
- Владелец не прошёл цикл → упростить памятку/UI, повторить; повторно — эскалация: gate не сдан.

## Критерии приёмки
- [ ] Внесённая регрессия ловится метрикой или уходит на review (живой прогон).
- [ ] /admin/eval на проде за токеном, вердикты в `eval_runs`; nightly прошёл ночь в бюджете; владелец сам прошёл цикл (чекпоинт 3).

## Definition of Done — память
- [ ] `core/regression-net.md` (секция eval, `updated:`); `guides/eval-owner.md` (frontmatter); `core/observability-tracing.md` сверен.
- [ ] Пороги/метрики/gate → `decisions.md` (ADR); `project-state.md`; `/memory-check` + audit «чисто»; реестр [[commercial-master-plan]]; план → `completed_plans/`.

## Лог выполнения
- 2026-07-11 — план создан, draft.

## Completion summary

## Follow-up work
- SSIM по bbox keep-объектов (после Э5); pytest geometry — `sub-e5-fit-integration`; PostHog-дашборд дрейфа; golden до 50+ (реальные фото с согласия, новые roomType); vision-judge при нужде.
