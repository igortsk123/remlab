---
name: memory-cleanup
description: >
  Глубокая уборка Memory Bank после крупных изменений: пересобрать связи и INDEX, найти дубли,
  устаревшее и противоречия, классифицировать (оставить/сжать/слить/в архив/удалить) и — по
  подтверждению — безопасно применить с архивацией (не удалением) и логом. По умолчанию dry-run:
  сначала отчёт, файлы не меняются. Опирается на правила `.memory_bank/CLEANUP_POLICY.md` и
  переиспользует `tools/memory-audit.mjs` (или делает его проверки сам, без Node). Запускать
  периодически — после merge, смены этапа, перед хендоффом. Для быстрой гигиены есть `/memory-check`.
---

# memory-cleanup — глубокая уборка памяти (dry-run по умолчанию)

Ты приводишь Memory Bank в порядок по правилам `.memory_bank/CLEANUP_POLICY.md`. **Сначала всегда
dry-run** (отчёт, без правок). Применяешь только когда пользователь явно сказал «применить».

Прочитай перед началом: `CLEANUP_POLICY.md`, `METADATA_SCHEMA.md`, `archive/README.md`.

## Режимы
- **dry-run (по умолчанию):** проанализировать, выдать отчёт-классификацию. Файлы НЕ менять.
- **apply (только по явной команде «применить»/`--apply`):** выполнить одобренные действия с safety-моделью ниже.

## Шаг A — детерминированная проверка (как `/memory-check`)
Если доступен Node — запусти `node tools/memory-audit.mjs <projectRoot> --check` и собери вывод.
Если Node нет — сделай те же проверки сам:
- пересобрать decision tree в `INDEX.md` (блок `GENERATED:decision-tree`) из frontmatter Tier 1;
- **orphan** — content-док без `topic`;
- **stale** — Tier 1, чей `tier2`-док новее (`Tier2.updated > Tier1.updated`);
- **broken** — указатели `tier1`/`tier2` и `[[ссылки]]`, которые не резолвятся.

(Скоуп аудита: все `*.md` в `.memory_bank/`, КРОМЕ `_intake/`, `completed_plans/`, `archive/`,
`changelog/`, файлов `README.md`/`_template.md`/`INDEX.md`/`METADATA_SCHEMA.md`/`CLEANUP_POLICY.md` и `plans/*`.)

## Шаг B — смысловой проход (то, чего не видит audit)
Прочитай шапки (+ при необходимости содержимое) memory-доков и найди:
- **Дубли/перекрытия** — два дока про одно → MERGE.
- **Устаревшее по смыслу** — факты, противоречащие текущему коду / `source-of-truth.md` / свежему `project-state.md`.
- **Просроченное** — `review_after` в прошлом; `canonical` без `last_verified`.
- **Раздутое** — Tier 1 сводка >3 KB или с листингами (детали должны быть в Tier 2) → COMPRESS.
- **Неверный tier / провенанс** — Tier 2 контент в Tier 1; `source` пустой; `status: deprecated`.
- **Смешанные темы** в одном доке → SPLIT.
- **Сироты вне навигации** — живой док без `topic` или не достижимый из `INDEX`.

## Шаг C — классификация
Каждой находке — категория из `CLEANUP_POLICY.md`:
`KEEP · VERIFY · COMPRESS · MERGE · SPLIT · ARCHIVE · DELETE · PROMOTE_TO_SOURCE_OF_TRUTH · DEMOTE_FROM_SOURCE_OF_TRUTH`.
Неуверен — ставь **VERIFY**, не ARCHIVE/DELETE.

## Шаг D — отчёт (dry-run)
Выдай отчёт фиксированного вида:

```md
# Memory Cleanup Report
Дата: YYYY-MM-DD
Режим: dry-run
Скоуп: .memory_bank/

## Сводка
KEEP: N · VERIFY: N · COMPRESS: N · MERGE: N · SPLIT: N · ARCHIVE: N · DELETE: N

## Audit (Шаг A)
- <orphan/stale/broken или «чисто»>; decision tree: <обновлён/актуален>

## Находки
### VERIFY
- `<путь>` — <почему> → <что сделать>
### MERGE
- `<путь A>` + `<путь B>` — дубль → свести в `<итог>`
### ARCHIVE
- `<путь>` — устарело/заменено `<чем>` → archive/YYYY/MM/
...

## Если применить
- архивируется: N · сжимается: N · сливается: N · удаляется (после архива): N
- связи/INDEX: <что починится>
```
Заверши вопросом: «Применить? (да / точечно: какие пункты)».

## Шаг E — применение (только по подтверждению)
Соблюдай safety-модель `CLEANUP_POLICY.md`:
1. **Archive-before-delete.** ARCHIVE/DELETE → сначала перенести оригинал в `archive/YYYY/MM/` с archive-note frontmatter (см. `archive/README.md`). Hard-delete без архивной копии запрещён.
2. **Canonical под защитой.** `source_of_truth: canonical` (`source-of-truth.md`, `decisions.md`, `project-state.md`, …) не переписывать/не удалять без явного «да» по конкретному доку. `decisions.md`: устаревшее решение не стирать — добавить отменяющую ADR-запись.
3. **Не трогать** `plans/*` (draft/in_progress), `_intake/*`.
4. **Перестроить связи:** починить `[[ссылки]]` и `tier1/tier2`, обновить `updated`/`last_verified` у тронутых доков, убедиться, что каждый живой док маршрутизирован из `INDEX` (regen decision tree).
5. **Залогировать** каждое действие в `changelog/memory-log.md` (формат — в файле; свежие записи сверху): дата, файл, действие, причина, approval, команда.
6. **Сверить:** перепрогнать Шаг A — убедиться, что «чисто».
7. **Отчитаться:** что заархивировано/слито/сжато/починено, путь к лог-записи, как откатить (поднять из `archive/`).

## Принципы
- Dry-run сначала, применение — по явному подтверждению.
- Сомнение → VERIFY. Историю не теряем — она уходит в `archive/`.
- Меняем структуру и провенанс, а не смысл решений.
