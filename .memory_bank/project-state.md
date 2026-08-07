---
tier: 1
topic: project-state
scope: Снимок «где проект сейчас» — точка ресинхронизации при /clear и resume
tier2: "changelog/project-history.md"
updated: 2026-08-08
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-08
---

# Project State — снимок состояния

> Это СНИМОК «где проект сейчас», НЕ журнал (держи ≤ ~8 KB). Обновляя,
> ПЕРЕПИСЫВАЙ разделы под текущее состояние, а не дописывай хронологию: история сессий/волн —
> append в `changelog/project-history.md`, завершённые планы — в `completed_plans/`. Снимок =
> что истинно СЕЙЧАС + ссылки. Первое, что читает агент при resume/`/clear`; обновил — `updated:`.

## Зоны-first (2026-08-08, ADR-0074) — текущий фокус

**`plans/MASTER-zones-first.md` (Z0–Z6, in_progress, «деплой подряд»)** — компоновка перестроена
с «предмет-first» на «зоны-first» по двум верифицированным документам владельца + вердиктам Q1–Q8:
- **Z0–Z4, Z6 выполнены**: цифры канона в `occupancy.json` (hard = только физика, числа soft);
  библиотека 10 посадочных групп `services/planner-solver/rules/zones.json`; пороги подтверждены 5 742 гостиными 3D-FRONT
  (датасеты удалены, таблица — владельцу на утверждение); `services/planner-solver/planner/zones.py` (usable-площадь,
  pick_group, solve_zoned, ЛЕКСИКОГРАФИЧЕСКИЙ финальный отбор) — 73 теста, включая 3 Э8-контура;
  compose2 собирает состав ОТ ГРУППЫ (диван 2/кресла×N; столик 55–75% дивана; обеденная только
  при остатке usable ≥6 м²; extras_max); зонная семантика в промпте генератора.
- **Z5 идёт**: приёмка на зафиксированных **252 сценах** (`acceptance-scenes.json` в git),
  A/B beam vs zoned — `acceptance_run.py` (8 воркеров, jsonl-resume). После A/B: пересборка
  126 составов по Z4 → контрольный zoned-прогон → решение о боевом движке.
- **Разбор внешних систем** (2 письма советника: ProcTHOR/Holodeck/Infinigen/Function2Scene/
  MolmoSpaces): замена ядра не оправдана, полезное берём модульно; полный документ (с правками
  рецензента) — https://remont-lab.online/test/zones-vs-external/ (`tools/scout/pages/`).
- **Блокеры/решения владельца:** кредиты OpenAI исчерпаны — судья сетов стоит (пополнить
  биллинг); утвердить таблицу порогов inventory-prior; TG-токен для алертов.
- **Прочие остатки:** backtracking 26–30 ([[layout-engine-gaps]]); косые стены Э8 (трапеция —
  пока осевая аппроксимация); target_box хвоста виз-приёмки; калибровка DUMB_T вердиктами;
  3 новых фида в проде (divan.ru mid 112923, mdm-complect 96431 + ещё один) — каталог ~32k.

Предыдущий фокус (аудит 06.08 и MASTER-pipeline-hardening А0–А7 — выполнен, beam везде,
117/126) — хронология в `changelog/project-history.md`.

## Каталог и стиль (2026-08-06)

Мебельный трек перешёл от «угадать по названию» к «взять из данных»:
- **Роль товара — из дерева категорий фида** (ADR-0070). База очищена: 87 672 → 25 034 товара,
  загрузчик берёт только 76 нужных категорий (дыры: кашпо 0, ковёр 26 — волна А2).
- **Обогащение построено и покрывает весь active-пул** (`MASTER-catalog-ai` К0–К3 + А0):
  `product_enrichment`, хеши дельты (пока не триггерят переобогащение — А1), статусы,
  каскад на `gpt-5.6-luna`.
- **Стиль — сумма наблюдаемых признаков с рангами** (ADR-0071), честный ответ «стиля нет».
  Распределение: минимализм 49%, сканди 21%, современный 12%, неоклассика 11%, лофт 4%,
  джапанди 3%, нейтральных 11%.
- **Правило по деньгам** (ADR-0072): всё платное — сперва пробной партией; батчи — ADR-0073.

В очереди за мастер-планом: пересобрать комплекты на новых оценках, К5 (зоны, оценка набора).

## Что готово (детали — по ссылкам)
Bootstrap S1–S4 (`completed_plans/remlab-bootstrap.md`) · Stage 1 M0–M8
(`archive/plans/stage1-master-roadmap.md`) · Observability/PostHog (ADR-0012) · навигация+каркасы
(ADR-0017, `completed_plans/site-nav-and-scenarios.md`) · Калькулятор v2 в проде (ADR-0018,
`core/estimate.md`; К5/К6 ждут ключей) · трейсинг пайплайна в проде (ADR-0013,
`core/observability-tracing.md`). Хронология — `changelog/project-history.md`.

## Ключевые решения (строкой; полные — `decisions.md`, `docs/DECISIONS.md`)
ADR-0001 self-host compose на exit-fi, не Vercel · 0002 pg17+pgvector в контейнере, не Supabase ·
0003 LE TLS-ALPN-01 :443 через Caddy · 0004 mem-лимиты app 1G/pg 1G/caddy 128M ·
0005 автоочистка+swap 4G · 0006 кросс-сборка arm64 · 0007 Gemini одним ключом · 0008 in-memory
store → 0011 Postgres при `DATABASE_URL` · 0009 japandi / restyle фото / «Скоро» для стоимости ·
0010 фейк-ИИ по флагу (e2e) · 0012 PostHog, без Sentry · 0013 трейсинг пайплайна · 0014 пивот
v0.3 · 0015 авто-коммит+пуш · **0016 пивот v0.4 «Смета-first»**.
Стек: TS strict + Next.js + Drizzle + Zod + Inngest + внешний инференс (спека §1).

## Что НЕ делаем (вне scope v0.4)
Свой каталог бригад · точная смета работ (только грубо, отдельной строкой) · fit-движок ·
UK · кухня как вход (пока).

## Open questions / TODO
- `trace:prune` повесить на таймер `remlab-cleanup`.
- Код под v0.4 — см. «Код-долг» в разделе Концепции.
- Прокси-анблокер (Bright Data/Zyte) для чтения Ozon/WB — решение/оплата владельца (ADR-0032).
- Auth: anonymous session id (интерим) vs GoTrue — Stage 1. Realtime job: polling vs self-host — Stage 2.

## Policies (как ведём разработку)
- План-first (`.claude/rules/agent-workflow.md`): код только после «деплой».
- Не ломать VPN-ноду на exit-fi: бэкап+rollback перед правками сервера, изоляция сети/лимиты.
- Секреты только в `.env` на сервере, не в git/памяти.
- Гипотезы, не аксиомы: отклонения → `docs/DECISIONS.md`.
- Migration-ready: приложение = compose + env + volume-dump + образ.
- **Память: durable — только в `.memory_bank/`.** Конец сессии — `/memory-check` (свод+гигиена);
  концепция — `guides/memory-automation.md`.
