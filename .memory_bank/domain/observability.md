---
tier: 2
topic: observability-details
scope: Детали трейсинга AI-пайплайна — БД, env, роуты, подписанные URL, imagor, ретеншн, гочи прода
tier1: ../core/observability-tracing.md
updated: 2026-07-09
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-09
---

# Observability — детали (Tier 2 к [[observability-tracing]])

> Сверено с кодом 2026-07-09. Tier 1: `../core/observability-tracing.md`.

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
  `TRACE_ADMIN_TOKEN` (токен не задан = dev → открыто). Кнопка «Сообщить о проблеме» →
  `POST /api/trace/report`.

## Подписанные ссылки на ассеты (`lib/trace/sign.ts`, `lib/trace/admin.ts`)
- `[seq]`-роут отдаёт абсолютные `url` вида `<TRACE_PUBLIC_BASE_URL>/api/trace/asset/<id>?exp=..&sig=..`.
- Подпись — HMAC-SHA256 от `id.exp` на ключе `TRACE_ADMIN_TOKEN` (отдельный секрет не заводим; HMAC
  односторонний — токен из ссылки не восстановить). TTL — `TRACE_ASSET_TTL_MS`, дефолт 7 дней.
- Владелец открывает картинку в браузере, админ-токен НЕ раскрывается. Asset-роут пускает по валидной
  подписи (`verifyAssetSig`, timingSafeEqual) ИЛИ по admin-гарду. Токен не задан (dev) → без подписи.

## Env
| Переменная | Значение |
|---|---|
| `TRACE_DIR` | путь к тому трейсов; локально `./.data/traces` (в .gitignore) |
| `TRACE_ADMIN_TOKEN` | admin-гард trace-роутов + ключ HMAC подписи ассетов |
| `TRACE_PUBLIC_BASE_URL` | база абсолютных подписанных URL в ответе `[seq]`-роута |
| `TRACE_ASSET_TTL_MS` | TTL подписи ассета (дефолт 7 дней) |
| `TRACE_RETENTION_DAYS` | ретеншн прогонов (дефолт 90) |
| `IMAGOR_BASE_URL` | адрес imagor; пусто → без сжатия (исходник) |

## Хранение, ретеншн, гочи прода
- Том `remlab-traces` → `named-том remlab-traces (см. docker-compose.yml; НЕ bind /opt/remlab/data/traces)` (app rw как `/app/data/traces`, imagor ro как `/mnt/data`).
- ⚠️ **Гоча (была причиной «0 ассетов» на проде):** app работает под `nextjs` (uid 1001), а свежий
  named-том принадлежит root → запись картинок падала молча (best-effort глушил EACCES). Фикс: сервис
  `traces-init` в `docker-compose.yml` — под root `chown -R 1001:65533` + `chmod -R u+rwX` перед стартом
  app (идемпотентно). `saveAsset` (`lib/trace/assets.ts`) при сбое пишет `console.warn` (без секретов),
  чтобы такой класс багов не прятался. Картинки прогонов ДО фикса невосстановимы (байты не захватывались).
- Ретеншн: `pnpm trace:prune` (`tools/trace-prune.mjs`) — удаляет прогоны + шаги + ассеты + файлы (в т.ч.
  `_tmp`) старше `TRACE_RETENTION_DAYS`; вешается на серверный таймер `remlab-cleanup` (ops-шаг деплоя).
- Логирование best-effort: ошибка записи/диска НЕ валит пайплайн. Секреты (API-ключи) в лог не пишем.
- Фото — ПДн (TODO legal, не блокируемся).

## Ключевые файлы
`lib/trace/*` (recorder, context, store, assets, sign, admin, types), `lib/providers/traced.ts` +
`lib/providers/index.ts`, `lib/prompts/registry.ts`, `lib/pipelines/registry.ts`,
`lib/images/compress.ts`, `lib/pricing.ts`, `db/schema.ts`, `db/init/003-traces.sql`,
`tools/migrate.mjs`, `tools/trace-show.mjs`, `tools/trace-prune.mjs`, `app/api/trace/*`.
Правило: `.claude/rules/pipeline-tracing.md`.
