# Metadata Schema — frontmatter memory-доков

> Что писать в `---`-шапке каждого memory-дока. Все значения — **плоские строки** (без YAML-массивов
> и вложенности): так шапку одинаково читают и `tools/memory-audit.mjs` (zero-dep), и скиллы
> `/memory-check`, `/memory-cleanup`. Массив/вложенность в шапке audit флагает как BAD-FM
> (парсер их не видит — поле молча теряется). Неизвестные ПЛОСКИЕ поля audit игнорирует —
> расширять безопасно.

## Базовые поля (как было, остаются обязательными для content-доков)

| Поле | Обяз. | Значение |
|------|:----:|----------|
| `tier` | да | `0` \| `1` \| `2` |
| `topic` | да* | slug темы (без него док — orphan, невидим в навигации). *Кроме scaffold: `README.md`, `_template.md`, `plans/*`, `_intake/*`, `archive/*`. |
| `scope` | да | одна строка — «когда читать этот док» (идёт в decision tree) |
| `tier1` \| `tier2` | — | указатель на парный док (`tier2:` у сводки → на полный док; `tier1:` у полного → на сводку) |
| `updated` | да | `YYYY-MM-DD` — дата последней правки содержимого |
| `importance` | да | `high` \| `med` \| `low` |
| `source` | да | `manual` \| `_intake/<...>` (provenance) |

## Поля жизненного цикла (РЕКОМЕНДУЮТСЯ для canonical и tier-1 доков)

Их проверяет audit (`REVIEW` — `review_after` в прошлом; `UNVERIFIED` — canonical без
`last_verified`) и использует `/memory-cleanup` для классификации. `/memory-init` проставляет
`last_verified` (= дата init) и `review_after` (например +90 дней) canonical-докам; `/memory-check`
обновляет `last_verified` при верификации. У прочих доков отсутствие поля — «неизвестно», не ошибка.

| Поле | Значение | Зачем |
|------|----------|-------|
| `status` | `draft` \| `working` \| `stable` \| `stale` \| `deprecated` \| `archived` | стадия жизни дока |
| `source_of_truth` | `canonical` \| `supporting` \| `derived` \| `historical` | насколько доку можно доверять при конфликте |
| `last_verified` | `YYYY-MM-DD` | когда содержимое последний раз сверяли с реальностью (кодом/прод) |
| `review_after` | `YYYY-MM-DD` | дата, после которой док стоит пересмотреть (триггер для cleanup) |

### Допустимые значения — пояснения

**`source_of_truth`:**
- `canonical` — первоисточник истины (например `source-of-truth.md`, `decisions.md`). При конфликте побеждает он. Очистка такие доки **не переписывает и не удаляет** без явного подтверждения.
- `supporting` — поддерживающий контекст (большинство `core/`, `domain/`).
- `derived` — выведено из кода/других доков (например repo-map); может устаревать, перегенерируемо.
- `historical` — архив/история; не отменяет текущее состояние.

**`status` → действие очистки (ориентир):**
- `stable`/`working` → KEEP.
- `stale` → VERIFY или COMPRESS (сверить с реальностью).
- `deprecated` → ARCHIVE (после подтверждения).
- `archived` → должен лежать в `archive/` (если нет — переместить).

## Минимальный пример (content-док Tier 1)

```yaml
---
tier: 1
topic: project-state
scope: Снимок «где проект сейчас» — точка ресинхронизации при /clear и resume
tier2: ""
updated: 2026-06-14
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-06-14
review_after: 2026-06-21
---
```

## Правила
- Массивы не используем. Если нужно несколько значений — короткой строкой через запятую в тексте дока, не в шапке.
- `canonical`-док без `last_verified` — audit флагает UNVERIFIED; cleanup классифицирует VERIFY.
- `review_after` в прошлом — audit флагает REVIEW (триггер пересмотра).
- **Always-on tier-1** (`source-of-truth`, `project-state`, `decisions`) легитимно живут с пустым
  `tier2: ""` — они не входят в decision tree (своя секция в INDEX), пустой указатель не ошибка.
- Архивные доки (`archive/`), лог (`changelog/`) и `_secrets/` из аудита исключены — там своя шапка (см. `archive/README.md`).
