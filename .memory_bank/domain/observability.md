---
tier: 2
topic: observability-details
scope: Детали трейсинга AI-пайплайна — БД, env, роуты, подписанные URL, imagor, ретеншн, гочи прода
tier1: ../core/observability-tracing.md
updated: 2026-11-12
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-11-12
---

# Observability — детали (Tier 2 к [[observability-tracing]])

> Сверено с кодом 2026-11-12 (verify-агент, T-20261112-84). Tier 1: `../core/observability-tracing.md`.

## Сущности БД — детали (`db/schema.ts`, `db/init/003-traces.sql`, `tools/migrate.mjs`)
- `generation_runs` — прогон = один запуск превью. `seq` из sequence `generation_seq` —
  человекочитаемый **номер генерации**. Хранит pipelineId+version, projectId, sessionId, статус,
  итоги (время/стоимость), meta (title, roomType).
- `generation_steps` — шаг = один вызов LLM: stepName, kind (vision/image/text), provider, model,
  promptId+version+дословный рендер промпта, params, input/output-текст, статус/ошибка, latency, cost.
- `generation_assets` — картинки (роль input/intermediate/output): **байты на диске** (том),
  в БД только ссылка+метаданные. Base64 в БД НЕ пишем.

## Захват — механика
- `runWithTrace` (`lib/trace/recorder.ts`) открывает прогон; контекст — AsyncLocalStorage
  (`lib/trace/context.ts`), вложенные вызовы видят прогон без протаскивания ctx.
- `getImageProvider()/getVisionProvider()` (`lib/providers/index.ts`) оборачивают провайдера в
  инструментированную версию (`instrumentImageProvider/instrumentVisionProvider`,
  `lib/providers/traced.ts`) — каждый вызов LLM логирует себя как шаг.
- Вне прогона (тесты, скрипты, пред-шаг `runAnalyze`) — passthrough, ничего не пишется.
- Стоимость шага — оценка `lib/pricing.ts` (ориентир, НЕ биллинг; ~4 символа/токен); обновлять
  при смене моделей/тарифов вместе с реестром пайплайна.

## Сжатие (imagor) — детали
`lib/images/compress.ts` → сервис **imagor** (Go+libvips, internal-only на remlab-net, как в SUP2/ADR D18).
URL вида `<IMAGOR_BASE_URL>/unsafe/fit-in/1536x1536/filters:format(webp):quality(80):strip_exif()/<key>`;
imagor читает файл из `FILE_LOADER_BASE_DIR` (= том TRACE_DIR) по относительному ключу (временный файл
в `_tmp`). Дефолты: maxDim 1536 (fit-in только уменьшает), quality 80. `IMAGOR_BASE_URL` не задан
(напр. `http://remlab-imagor:8000`) или ошибка → возвращаем исходник (best-effort).

## Разбор («генерация N») — инструменты
- Скилл `/trace` (`.claude/skills/trace/`) — триггер «генерация N» → краткий+подробный вид + фото.
  Формат вывода: по каждому шагу — дословный промпт + дословный ответ модели + ссылки
  input/intermediate/output.
- CLI: `pnpm trace <N>` (`tools/trace-show.mjs`) — из БД, печатает путь + пути к файлам-ассетам.
- `GET /api/trace/<N>` (JSON + asset URLs), `GET /api/trace/asset/<id>` (байты) — за admin-гардом
  `TRACE_ADMIN_TOKEN` — только заголовком `x-trace-token` (`?token=` с 13.10 не принимается, ADR-0256);
  токен не задан: в production закрыто, в dev открыто (`lib/trace/admin.ts:traceAdminOk`). Кнопка «Сообщить о проблеме» →
  `POST /api/trace/report`.

## Подписанные ссылки на ассеты (`lib/trace/sign.ts`, `lib/trace/admin.ts`)
- `[seq]`-роут отдаёт абсолютные `url` вида `<TRACE_PUBLIC_BASE_URL>/api/trace/asset/<id>?exp=..&sig=..`.
- Подпись — HMAC-SHA256 от `id.exp` на ключе `TRACE_ADMIN_TOKEN` (отдельный секрет не заводим; HMAC
  односторонний — токен из ссылки не восстановить). TTL — `TRACE_ASSET_TTL_MS`, дефолт 7 дней.
- Владелец открывает картинку в браузере, админ-токен НЕ раскрывается. Asset-роут пускает по валидной
  подписи (`verifyAssetSig`, timingSafeEqual) ИЛИ по admin-гарду. Токен не задан: в dev — без подписи,
  в production — закрыто (`lib/trace/sign.ts:verifyAssetSig`, ADR-0256).

## Env
| Переменная | Значение |
|---|---|
| `TRACE_DIR` | путь к тому трейсов; локально `./.data/traces` (в .gitignore) |
| `TRACE_ADMIN_TOKEN` | admin-гард trace-роутов + ключ HMAC подписи ассетов |
| `TRACE_PUBLIC_BASE_URL` | база абсолютных подписанных URL в ответе `[seq]`-роута; пусто → origin запроса (`lib/trace/admin.ts:signedAssetUrl`) |
| `TRACE_ASSET_TTL_MS` | TTL подписи ассета (дефолт 7 дней) |
| `TRACE_RETENTION_DAYS` | ретеншн прогонов (дефолт 90) |
| `IMAGOR_BASE_URL` | адрес imagor; пусто → без сжатия (исходник) |

## Хранение, ретеншн, гочи прода
- Named-том `remlab-traces` (`docker-compose.yml`; не bind `/opt/remlab/data/traces`): app rw как `/app/data/traces`, imagor ro как `/mnt/data`.
- ⚠️ **Гоча (была причиной «0 ассетов» на проде):** app работает под `nextjs` (uid 1001), а свежий
  named-том принадлежит root → запись картинок падала молча (best-effort глушил EACCES). Фикс: сервис
  `traces-init` в `docker-compose.yml` — под root `chown -R 1001:65533` + `chmod -R u+rwX` перед стартом
  app (идемпотентно; тем же шагом — том пробы `remlab-trial`). `saveAsset` (`lib/trace/assets.ts`) при сбое пишет `console.warn` (без секретов),
  чтобы такой класс багов не прятался. Картинки прогонов ДО фикса невосстановимы (байты не захватывались).
- Ретеншн: ежедневно 04:10 UTC таймер `remlab-retention` (`infra/server/systemd/remlab-retention.timer`) →
  `POST /api/internal/retention` (заголовок `x-internal-token` = `INTERNAL_API_TOKEN`, иначе 403;
  `app/api/internal/retention/route.ts`) → `modules/retention/run.ts:runRetention` — одна транзакция под
  advisory-замком; прогоны + шаги + ассеты старше `TRACE_RETENTION_DAYS` (90), строка удаляется только после
  удаления её файлов; из `_tmp` — файлы старше суток; каждый запуск — строка на каждый вид данных (трейсы, заявки,
  контакты, проба) в `retention_runs`; замок занят → `skipped: "busy"`, без строк (план b2b-04, ADR-0268). `pnpm trace:prune` (`tools/trace-prune.mjs`) — ручной дубль, `_tmp` чистит целиком.
  (До b2b-04, 13.10, таймера не было — чистили руками.)
- Логирование best-effort: ошибка записи НЕ валит пайплайн. Сбои записи прогона/шага в БД считаются
  (`lib/trace/recorder.ts` → `lib/trace/failures.ts:traceWriteFailed` → `traceWriteFailures` в `/api/health`, `lib/health.ts`);
  сбой `saveAsset` (файл/строка ассета) в счётчик не идёт — только `console.warn`. Секреты (API-ключи) в лог не пишем.
- Фото — ПДн (TODO legal, не блокируемся).

## Аналитика: ключи доступа не уходят наружу, проверки не считаются (18.10, T-14/T-18/T-20)
- **Метрика без ключей.** `lib/metrika.ts` `metrikaSafeUrl` маскирует ключи в адресе: параметры `s`, `c`, `coll` → `*`; пути `/e/*`
  (смета — номер даёт правку), `/p/*/<шаг>` (проект), `/go/*/*`, `/try/*` (проба агента); `/calc` и `/embed` публичные.
  На `/manager`, `/partner`, `/try` Метрики нет вовсе (`lib/metrika.ts:noMetrikaPath`). Применяется в `components/MetrikaPageviews.tsx`
  и в старте счётчика `app/layout.tsx` (`init` с `defer`, `url`, `referrer`); на адресе с ключом выключены карта кликов и Вебвизор.
  Проба прода 18.10: 12 запросов к mc.yandex, утечек 0. Почему маска в `init`, а не только в хитах — урок 515. Открыто — вопрос 42.
- **Ночные проверки не попадают в счётчики.** Живые тесты шлют заголовок `x-remlab-check: 1` (`lib/http/live-check.ts` `isLiveCheck`):
  сервер не пишет `/api/events`, `stale_link` (`app/flat/page.tsx`), события ссылки менеджера (`app/api/sends/[id]/event`) и PostHog
  (кроме `app_error`). Метрика в живых тестах блокируется аргументом браузера `e2e/live/browser.ts` `LIVE_BROWSER_ARGS`; сторож —
  `e2e/live/live-check.live.ts`. Грабли запуска — урок 514.

## Вне трейсинга: фото демо и VLM ориентации (свод 06–09.11)
- **Фото в демо (кнопка «Сделать фото», `CTA_REAL` в `tools/scout/flat215-demo/index.html`; было «Сделать реалистичнее») в `generation_runs`
  не пишется** — его делает DEV-сервис `remlab-render` (`tools/scout/draft_render.py`,
  без `lib/trace`). Время шагов — строка `ФОТО-ЗАМЕР` в `~/scout-scenes/dev-render.log` (`draft_render.py:photo_mark`: путь, подготовка,
  модель, сохранение, исход); сводка и сторож скорости — `tools/ops/photo-speed.py` по `tools/scout/rules/photo-speed.json`, ночью из
  `refresh_daily.sh`. Цена каждого платного кадра — строка JSON в `~/scout-scenes/photo-cost.jsonl` (env `PHOTO_COST_LOG`): обёртка
  `draft_render.py:_photo_cost` на `gpt_edit` и `_chat_edit` (вложенный вызов — один раз), цена = разница баланса ключа шлюза до/после
  (`cost_source: balance_delta`; «после» — в фоне через `PHOTO_COST_SETTLE_S`, по умолчанию 2,5 с); параллельный платный вызов —
  `overlap: true`; баланс не снизился или не узнан — `cost_note`; метка — `cost_label` (demo/trial), иначе `PHOTO_COST_LABEL`, иначе
  имя скрипта. Отчёт — `tools/ops/photo-cost.py` (кадры с overlap в среднее не входят; T-20261109-28).
- **VLM ориентации** (`tools/scout/orient_worker.py`, qwen3-vl через шлюз): расход — оценкой по `tools/scout/rules/openai_prices.json`
  (`openai_budget.log_spend`), дневной лимит `openai_budget.allow`; не влезло — пачка без VLM (`vlm_pending`).

## Ключевые файлы
`lib/trace/*` (recorder, context, store, assets, sign, admin, types, failures), `lib/providers/traced.ts` +
`lib/providers/index.ts`, `lib/prompts/registry.ts`, `lib/pipelines/registry.ts`,
`lib/images/compress.ts`, `lib/pricing.ts`, `db/schema.ts`, `db/init/003-traces.sql`,
`tools/migrate.mjs`, `tools/trace-show.mjs`, `tools/trace-prune.mjs`, `app/api/trace/*`,
`modules/retention/run.ts`, `app/api/internal/retention/route.ts`.
Правило: `.claude/rules/pipeline-tracing.md`.
