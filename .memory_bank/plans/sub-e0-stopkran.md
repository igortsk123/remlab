---
workstream: commercial
slug: sub-e0-stopkran
title: Э0 Стоп-кран: безопасность, лимиты, рельсы измерения
status: draft
created: 2026-07-11
updated: 2026-07-11
completed:
---

# Э0 Стоп-кран

## Цель
Закрыть риски перед коммерцией: владение, лимиты трат, пин моделей, e2e, прод=main+авто-деплой, paywall v0.3 fake-door, аналитика, `ml/` в git.

## Источник задачи
Этап Э0 [[commercial-master-plan]].

## Прочитай сначала
- `.memory_bank/plans/commercial-master-plan.md` + `guides/execution-playbook.md`; `.claude/rules/pipeline-tracing.md`.
- `docs/master-brief-v0.3.md` + `docs/DECISIONS.md` (ADR-0014) — тарифы/тексты paywall.

## Скоуп — что входит
mltest→`ml/`; владение по session_id; лимиты + $-kill-switch; пин Gemini; e2e; прод=main+авто-деплой; paywall fake-door 1 490/9 900 ₽; события PostHog; trace-prune на таймер; вопросы для Гдеслон.

## Скоуп — что НЕ входит
YooKassa, Cost Engine, ML в проде, реф-ссылки (Э1), Inngest; ПДн — TODO.

## Файлы к изменению
- [ ] Новые: `ml/`, `lib/project-access.ts`, `lib/limits.ts`, `infra/server/systemd/remlab-trace-prune.*`.
- [ ] Правки: `app/actions.ts`; `app/p/[id]/*/page.tsx` (5); `app/api/p/[id]/*/route.ts` (2); `components/GenerateOnMount.tsx`; `lib/{env,analytics}.ts`; `lib/providers/gemini.ts`; `lib/pipelines/registry.ts`; `docs/DECISIONS.md`; `e2e/flow.spec.ts`; `tests/unit/*`; `.gitignore`; `.dockerignore`; `Dockerfile`; `.memory_bank/deployment.md`.

## Задачи

### A — mltest → `ml/`
- [ ] Из `/home/pakar/mltest` — только 24 `*.py`, `demo_catalog.json`, `room1.jpg`, `room2.jpg`. Бинарники (~2 ГБ: jpg/png/npy, `cache/`, `__pycache__/`, `venv/`, `weights/`) — нет; маски в `.gitignore`. `.env` (fal.ai) не коммитить — указатель в `.memory_bank/_secrets/ACCESS.md`.
- [ ] `ml/README.md`: назначение и запуск скриптов; замер масштаба 0.3% (199.5 vs 200 см, A4+solvePnP); ссылки: `unified-measurement-pipeline`, MASTER-roadmap.

### B — дыра владения
- [ ] `lib/project-access.ts`: `repo().get(id)` + сверка `sessionId` с cookie (`readSessionId()` — страницы, `getSessionId()` — actions/API); чужой/нет сессии → null.
- [ ] Встроить: 5 страниц `app/p/[id]/*` → `notFound()`; `saveBrief`/`saveSelection`/`unlockPack` → `redirect("/")`; оба API-роута → 404 JSON.
- [ ] Юнит «A недоступен из B» (образец `tests/unit/pg-repository.test.ts`); e2e: `clearCookies()` → `/p/<id>/preview` → 404.

### C — лимиты
- [ ] `lib/limits.ts`: за 24ч count runs по `session_id` + sum `total_cost_usd` (Drizzle, `gt(generationRuns.startedAt,…)`), как в pg-repository.
- [ ] `lib/env.ts`: новая Zod-схема рядом с `providerEnv()`: `REMLAB_DAILY_GEN_LIMIT` (10), `REMLAB_DAILY_COST_LIMIT_USD` (5), `z.coerce.number()`.
- [ ] Роуты перед `runGenerate`/`runAnalyze`: превышение → 429 + JSON `message`; в `GenerateOnMount.tsx` показать `message` при 429.
- [ ] Юнит: INSERT runs с разными `started_at`; убедиться, что фейк (`instrument*` из `lib/providers/traced.ts`) пишет runs; нет → см. ниже.

### D — пин моделей
- [ ] WebSearch: стабильная версия Gemini (не `-latest`) → заменить `TEXT_MODEL` (`lib/providers/gemini.ts:17`); `node tools/smoke-providers.mjs`; бамп `version` в `lib/pipelines/registry.ts`; ADR в `docs/DECISIONS.md`.

### E — e2e
- [ ] Переписать `e2e/flow.spec.ts` (устарел) под реальный UI: «Разобрать фото» → «Что меняем на фото?» → «Сгенерировать комнату» (селекторы из кода); + cross-session из B; `pnpm e2e` зелёный.

### F — paywall fake-door (после B; тексты — бриф v0.3)
- [ ] `paywall/page.tsx`: убрать `PRICE = 490`; карточки 1 490 ₽ «Комната целиком» и 9 900 ₽ «Под ключ»; состав — бриф + ADR-0014.
- [ ] Клик → email-форма «Сообщим о запуске» (оплаты НЕТ); action в `app/actions.ts`: `{variant, email, at}` в jsonb `data` через `repo().update` + TODO ПДн.
- [ ] События: `paywall_viewed`, `paywall_variant_click` `{variant}`, `cost_fake_door_viewed` (форма 9 900); `unlockPack` не удалять — согласовать с e2e.

### G — PostHog
- [ ] Дошить отправку объявленных в `EventName`: `brief_completed` (`saveBrief`), `style_selected` (`saveSelection`) + F; в union добавить `product_link_click`, `paywall_variant_click`, `fit_check_interest` (отправка 1-го и 3-го — Э1).

### H — trace-prune на таймер
- [ ] Скрипт не в проде (`tools/` в `.gitignore` и `.dockerignore`): `!tools/trace-prune.mjs` в `.gitignore`, сузить `tools` в `.dockerignore`, `COPY` в runtime-стадию `Dockerfile` (`postgres` в deps есть).
- [ ] Юниты по образцу `remlab-cleanup.{service,timer}`: раз в сутки `docker exec remlab-app node tools/trace-prune.mjs`; бэкап конфигов; `remnanode` НЕ трогать; шаги → `deployment.md`.

### I — git/деплой (в конце)
- [ ] Ветка УЖЕ влита, merge не нужен (сверить: `git merge-base --is-ancestor feature/pipeline-tracing main`); прод позади main → `git push origin main`, `./deploy.sh`.
- [ ] После секрета: `deploy.yml` без «DEPLOY_SSH_KEY не задан», прод обновился.

## Гейты
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build`, `pnpm e2e` — зелёные, CI на main тоже.
- [ ] После деплоя `curl -s https://remont-lab.online/api/health` → ok; прод не позади main.
- [ ] Чужой `/p/<id>/preview` без cookie → 404; `REMLAB_DAILY_GEN_LIMIT=0` → 429 с сообщением.
- [ ] `git ls-files ml/` непуст и без npy/cache; `grep -r "gemini-flash-latest" lib/` пуст; `systemctl list-timers | grep trace-prune` активен.

## Чекпоинты владельца
- [ ] ⏸ ПОКАЗАТЬ ВЛАДЕЛЬЦУ (I): в GitHub добавить секрет `DEPLOY_SSH_KEY` (Settings→Secrets→Actions) = приватный `~/.ssh/remlab_ci_deploy` (публичный на сервере); у агента read-only PAT. «Добавили? Проверю авто-деплой».
- [ ] ⏸ ПОКАЗАТЬ ВЛАДЕЛЬЦУ: скрин paywall. «Цены 1 490/9 900 и тексты ок?»
- [ ] ⏸ ПОКАЗАТЬ ВЛАДЕЛЬЦУ: лимиты 10 генераций/сутки, $5/сутки на всех. «Ок? Правятся в .env».
- [ ] ⏸ ПОКАЗАТЬ ВЛАДЕЛЬЦУ (Гдеслон): вопросы — окно атрибуции cookie, переход web→app, комиссия («оформлен»/«выкуплен»), ставки мебель/DIY, формат/частота фида, subid. «Зарегистрируйтесь, задайте менеджеру».

## Если пошло не по плану
- Фейк-ИИ не пишет runs: лимиты юнитом с INSERT, e2e-проверку лимита → Follow-up.
- Пин недоступен: вернуть `gemini-flash-latest` + TODO + DECISIONS → Follow-up.
- Старые проекты недоступны (другая cookie): ожидаемо, не чинить.
- Таймер конфликтует: `systemctl disable --now remlab-trace-prune.timer`, откат из бэкапа; `remnanode` не трогать.

## Критерии приёмки
- [ ] Все гейты и чекпоинты пройдены; тексты лимитов дружелюбные; e2e = реальный UI; ADR + бамп версий; paywall 2 тарифа + email-форма; события в PostHog; `ml/` с README; main == прод.

## Definition of Done — память (без этого `completed` запрещён)
- [ ] Memory Bank: `core/*` (владение/лимиты; пин/таймер → `access-and-integrations`), `decisions.md`, `project-state.md` (прод=main, Э0 закрыт); `ml/` — сводка в INDEX.
- [ ] `/memory-check` выполнен, audit «чисто»; статус подплана обновлён в [[commercial-master-plan]].

## Лог выполнения
- 2026-07-11 — создан (draft).

## Completion summary

## Follow-up work
- [ ] `product_link_click`/`fit_check_interest` — в Э1; YooKassa — после валидации спроса.
- [ ] Email-заявки из jsonb в таблицу при объёме (+ вопрос ПДн).
