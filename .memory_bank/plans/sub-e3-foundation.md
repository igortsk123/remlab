---
workstream: commercial
slug: sub-e3-foundation
title: Э3 Фундамент продаж — async-джобы, файлы вместо base64, аккаунты, квоты
status: draft
created: 2026-07-11
updated: 2026-07-11
completed:
---

# Э3 Фундамент продаж — async-джобы, файлы вместо base64, аккаунты, квоты

## Цель
Генерация переживает рестарт (очередь + реальный статус), фото не раздувают БД (файлы на томе),
у пользователя есть аккаунт (magic-link) с квотой free-генераций, чужие проекты закрыты и покрыты тестами.

## Источник задачи
Этап Э3 мастер-плана [[commercial-master-plan]], сессия 2026-07-11.

## Прочитай сначала
- [[commercial-master-plan]] + `.memory_bank/guides/execution-playbook.md` (правила, чекпоинты).
- `modules/generation-job/index.ts` (runAnalyze/runGenerate); `app/api/p/[id]/generate/route.ts` + `components/GenerateOnMount.tsx` — сейчас синхронно, прогресс имитирован таймером.
- `lib/trace/assets.ts` — ОБРАЗЕЦ файлового хранения (диск + storageKey, без base64).
- `app/actions.ts` (fileToPhoto) + `contracts/project.ts` — base64 в `photos[]` И `previewImage` (оба — схема `photo`).
- `modules/store/pg-repository.ts` — дыра владения: `get(id)` без session_id; `lib/session.ts`.
- `db/schema.ts` + `tools/migrate.mjs` + `db/init/` — паттерн идемпотентных миграций.
- `docker-compose.yml` + `.memory_bank/deployment.md`; `.claude/rules/pipeline-tracing.md`.

## Скоуп — что входит
Очередь (Inngest Cloud, fallback pg-boss); async-generate + поллинг статуса; фото jsonb → volume +
imagor + миграция; magic-link аккаунты + merge сессий; квоты free; authz + тест-матрица.

## Скоуп — что НЕ входит
Платежи/YooKassa/entitlements — Э4 (`sub-e4-payments`); OAuth; подписки; fit; фиды; i18n; Cost Engine.

## Файлы к изменению
- [ ] `modules/generation-job/index.ts`; `modules/generation-job/queue.ts` (новый)
- [ ] `app/api/inngest/route.ts` (новый); `app/api/p/[id]/generate/route.ts`; `app/api/p/[id]/generation-status/route.ts` (новый)
- [ ] `components/GenerateOnMount.tsx` — реальный поллинг
- [ ] `contracts/project.ts` — photo + `storageKey`, `dataUrl` → optional
- [ ] `lib/images/photo-store.ts` (новый); `app/api/p/[id]/photo/[photoId]/route.ts` (новый)
- [ ] `app/actions.ts`; страницы `app/p/[id]/*` + `app/rooms/page.tsx` — `<img>` на endpoint, 404 чужим
- [ ] `lib/auth/` (новый) + `app/login/page.tsx` (новый); `lib/session.ts` — хелпер viewer
- [ ] `db/schema.ts` + `tools/migrate.mjs` + `db/init/004-users.sql` (новый); `tools/migrate-photos.mjs` (новый)
- [ ] `modules/store/repository.ts` + `pg-repository.ts` — listByUser, userId
- [ ] `lib/env.ts` — `RESEND_API_KEY`, `INNGEST_EVENT_KEY`, `INNGEST_SIGNING_KEY`, `PHOTOS_DIR`
- [ ] `docker-compose.yml` — том фото; `next.config.mjs` — bodySizeLimit (сейчас 12mb)
- [ ] `e2e/` + `tests/unit/`

## Задачи
### A — очередь
- [ ] A1. `queue.ts`: `enqueueGenerate(projectId, runId)`; вызывающий код не знает про Inngest; pg-boss = другая реализация.
- [ ] A2. Inngest Cloud: событие `generation.requested`, ретраи `step.run` (шаги: превью, идеи), таймаут на шаг; serve-endpoint. Ключи — только ИМЕНА env, значения в `.env` на сервере.
- [ ] A3. POST generate: run со status=running ДО enqueue — расширить `lib/trace/recorder.ts` (runWithTrace сам делает allocSeq+insertRun — научить продолжать готовый run); ответ `{ runId, seq }`, код 202. Повторный POST при живом running-run второй не создаёт.
- [ ] A4. Ошибка после ретраев → status=error + текст + `captureError` (`lib/analytics.ts`); шаги трейса — как раньше.
- [ ] A5. GET generation-status: последний run проекта (started_at desc) → `{ status, seq }`; только владельцу.
- [ ] A6. `GenerateOnMount.tsx`: POST → поллинг раз в 2 с (до ~120 с) → ok → `router.refresh()`; error → «Повторить»; STAGES оставить, «готово» — только по реальному ok.

### B — фото в файлы
- [ ] B1. `photo-store.ts` по образцу `lib/trace/assets.ts`: `PHOTOS_DIR` (прод `/app/data/photos`, dev `./.data/photos`), savePhoto(bytes,mime)→storageKey; named volume.
- [ ] B2. photo + `storageKey: z.string().optional()`, `dataUrl` optional; старые записи парсятся.
- [ ] B3. fileToPhoto → файл + storageKey; generation-job — байты с диска, previewImage тоже файлом (dataUrl — легаси-fallback).
- [ ] B4. Endpoint фото: файл с диска, ресайз imagor (`IMAGOR_BASE_URL`, паттерн `lib/images/compress.ts`), authz; заменить `<img src={...dataUrl}>` в preview и rooms.
- [ ] B5. `migrate-photos.mjs`: photo с dataUrl (photos[] и previewImage) → файл + storageKey, dataUrl убрать; идемпотентно, битые логировать и пропускать; на проде после бэкапа БД (deploy.sh делает).
- [ ] B6. Проверить bodySizeLimit (`next.config.mjs`) и лимит Caddy фото ~8–10 МБ.

### C — auth magic-link
- [ ] C1. Auth.js (Email/Resend) vs Lucia: App Router/Next 15, живость (Lucia объявляла сворачивание — проверить), только-Postgres, объём кода. Выбор → ADR в `docs/DECISIONS.md`. ⏸ ниже.
- [ ] C2. `users` (id, email unique, created_at, free_generations_used int default 0) + таблицы библиотеки; `projects.user_id text` nullable + индекс. DDL: `db/schema.ts`, `tools/migrate.mjs`, `db/init/004-users.sql`.
- [ ] C3. `/login`: e-mail → письмо через Resend (from-домен remont-lab.online — DNS SPF/DKIM); в dev/e2e ссылку логировать вместо отправки.
- [ ] C4. Merge при логине: `UPDATE projects SET user_id=$user WHERE session_id=$sid AND user_id IS NULL`.
- [ ] C5. `app/rooms/page.tsx`: залогинен → listByUser, иначе listBySession.

### D — квоты
- [ ] D1. Единая точка лимитов (согласовать с планом Э0 `sub-e0-stopkran`): перед enqueue — user по `users.free_generations_used`, аноним по числу runs session_id. Квота — env-константа; число задаёт владелец (⏸).
- [ ] D2. Превышение → 402 + экран «лимит исчерпан» со ссылкой на paywall. Инкремент — при успешном enqueue.

### E — authz
- [ ] E1. `requireProjectAccess(projectId, viewer)`: session_id ИЛИ user_id, иначе 404. ВЕЗДЕ: `app/p/[id]/*`, actions (saveBrief, saveSelection, unlockPack), API (analyze, generate, generation-status, photo).
- [ ] E2. Тест-матрица (unit+e2e): {аноним-владелец, чужая сессия, залогиненный владелец, чужой user} × endpoint/action. Чужой → 404, не 403.
- [ ] E3. e2e merge: аноним создал проект → логин по magic-link (ссылка из лога) → `/rooms` показывает комнату.

## Гейты
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build` — зелёные.
- [ ] `pnpm e2e` — включая merge и authz (REMLAB_FAKE_AI=1).
- [ ] Живучесть: генерация → `docker kill remlab-app` mid-run → `docker compose up -d` → run доезжает до ok (или честный error).
- [ ] Ретрай: fail-режим в `lib/providers/fake.ts` (добавить, env-флаг) → в `pnpm trace <N>` виден повторный шаг.
- [ ] SQL: `select count(*) from projects where data::text like '%;base64,%'` = 0.
- [ ] `curl -s https://remont-lab.online/api/health` — ok; POST generate → 202 < 1 с.
- [ ] `docker stats --no-stream` при 2–3 параллельных генерациях — суммарно < 3.4 GB.

## Чекпоинты владельца
- ⏸ ПОКАЗАТЬ (до кода, блок A): «Inngest Cloud vs pg-boss» простыми словами (внешний сервис видит события генераций vs всё у нас, но больше кода и нагрузка на БД). Ок ли внешний сервис?
- ⏸ ПОКАЗАТЬ (блок C): выбор библиотеки логина одним абзацем; от владельца нужны аккаунт Resend и DNS-записи домена (дам инструкцию). Заводим Resend?
- ⏸ СПРОСИТЬ (блок D): сколько бесплатных генераций на аккаунт/анонима? (граница free/paid — решение владельца).
- ⏸ ПОКАЗАТЬ (финал): живой прогон на проде; скрин письма-логина; «убил контейнер — генерация доехала». Принимаем этап?

## Если пошло не по плану
- Inngest не достукивается → `INNGEST_SIGNING_KEY` и путь в Caddy; не лечится за день → pg-boss (тот же `queue.ts`) + ADR.
- runWithTrace не разделяется малой кровью → POST только enqueue, статус поллит последний run; отметить в логе.
- Битые dataUrl при миграции → пропускать, id в лог, список владельцу; не блокироваться.
- Письма не доходят → DNS-инструкция владельцу, временно ссылка в серверный лог; >3 дней → эскалация.
- RAM > 3.4 GB → параллелизм воркера 1, шаги мельче; не помогает → эскалация (апгрейд — деньги).
- Auth-библиотека несовместима с Next 15 → вторая из сравнения, ADR обновить.

## Критерии приёмки
- [ ] POST generate → 202; UI поллит реальный статус; имитации нет.
- [ ] Kill контейнера mid-run → джоба доезжает; сбой провайдера → ретрай в трейсе.
- [ ] В projects нет base64; фото — через endpoint с authz.
- [ ] Magic-link на проде работает; e2e «аноним → логин → комнаты на месте» зелёный.
- [ ] Квота enforced (402 + экран), число согласовано; чужой проект → 404 везде.
- [ ] RAM < 3.4 GB; VPN-нода remnanode не тронута; прод выкачен (`./deploy.sh`), main не позади.

## Definition of Done — память (без этого `completed` запрещён)
- [ ] Обновлены: `core/architecture.md` (очередь, файлы), `core/data-model.md` (users, user_id, storageKey), `core/user-flow.md` (логин/merge), `core/access-and-integrations.md` (Inngest, Resend — ГДЕ ключи, без значений), `decisions.md` (ADR очередь; ADR auth), `project-state.md` (снимок).
- [ ] Новая область → `core/auth-accounts.md`, видна в INDEX.
- [ ] `/memory-check` выполнен, audit «чисто»; реестр [[commercial-master-plan]] обновлён.

## Лог выполнения
- 2026-07-11 — план создан, draft

## Completion summary

## Follow-up work
- [ ] Э4: YooKassa + entitlements поверх users (`sub-e4-payments`).
- [ ] OAuth — при явном спросе; rate-limit на magic-link письма (Э7).
- [ ] Inngest упрётся в free-tier → pg-boss по интерфейсу `queue.ts`.
