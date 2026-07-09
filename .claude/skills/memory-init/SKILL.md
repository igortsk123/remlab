---
name: memory-init
description: >
  Поднять Memory Bank из intake-папок. Вызывать после копирования шаблона в проект и наполнения
  .memory_bank/_intake/brief (цель/описание) и _intake/history (история). Читает intake, определяет
  стек, генерирует Tier 0/1/2 (CLAUDE.md, INDEX, core/, source-of-truth, project-state, decisions),
  активирует нужные optional-модули и прогоняет memory-audit.
---

# memory-init — bootstrap Memory Bank

Ты разворачиваешь Memory Bank из заготовки-шаблона. Цель — за один проход превратить пустой
скелет + два intake-источника в рабочий многоуровневый memory bank. Действуй по шагам, не пиши
код проекта, только наполняй память. В конце покажи итог.

## Предусловия
- В проекте есть `.memory_bank/_intake/brief/` и `.memory_bank/_intake/history/`.
- Шаблонные файлы с плейсхолдерами `{{...}}` уже на месте (скопированы из template/).
Если intake пуст — скажи об этом и попроси положить хотя бы `brief/goal.md`.

## Шаги

1. **Прочитать intake.** Всё в `_intake/brief/*` и `_intake/history/*`. Сформировать понимание:
   проблема, ЦА, цель, scope, стек, стадия, история решений, домен.

2. **Определить стек.** Найти `package.json` / `requirements.txt` / `*.csproj` / `go.mod` /
   `Cargo.toml` / `pom.xml`. По нему:
   - адаптировать `paths:` и примеры в `.claude/rules/code-standards.md`;
   - если нет фронтенда — удалить `.claude/rules/ui-rules.md`;
   - заполнить `{{STACK}}` и список правил `{{RULES_LIST}}`.

2b. **Определить тип проекта.** Прочитать `_intake/brief/_project-type.txt` (его пишут apply-скрипты):
   - `dev` (или файла нет) — кодовый проект: оставить строгий plan-first (`agent-workflow.md`),
     в `CLAUDE.md` подчеркнуть «код только после апрува плана».
   - `notes` — база знаний без кода: plan-first не навязывать. Удалить `.claude/rules/code-standards.md`
     и `ui-rules.md` (нерелевантны), в `agent-workflow.md` оставить лёгкую версию (план для крупных
     задач по желанию, без жёсткого гейта на код). В `CLAUDE.md` отразить, что это knowledge base.

3. **Сгенерировать `product_brief.md`** из `brief/` — заполнить все `{{...}}`.

4. **Выделить домены проекта — ЯВНЫМ списком.** По intake и структуре кода (если код уже есть —
   пройдись по каталогам/подсистемам) перечисли ВСЕ крупные функциональные области, а не только
   типовые. Под КАЖДУЮ создать `core/<тема>.md` по `core/_template.md` (типовые: architecture,
   data-models, flows, access-and-integrations + домен-специфичные). У каждой: frontmatter
   (`tier:1`, `topic`, `scope`, `tier2`, `updated`, `importance`, `source`) и финальная строка
   `Tier 2:`. Стартовое decision tree обязано покрывать реальную структуру проекта, не только
   «product». Реестр `core/README.md` пересоберёт аудит (шаг 9) — руками не заполнять.

5. **Заполнить `source-of-truth.md` и `project-state.md`** из brief+history. ВАЖНО: project-state —
   только текущий срез (снимок ≤ ~10 KB); хронологию из history — в `changelog/project-history.md`
   (append), чтобы снимок не родился уже раздутым. Принятые решения из истории внести в
   `decisions.md` в ADR-формате (Дата/Решение/Почему/Альтернативы/Влияет на).
   У canonical-доков проставить `last_verified` (= дата init) и `review_after` (например +90 дней).

6. **Активировать OPTIONAL по детекту** (копировать из `_optional/`, проставить frontmatter,
   зарегистрировать):
   - есть прод/CI → `_optional/memory/deployment.md` → `.memory_bank/deployment.md`;
   - внешний backend/репо как источник правды → `sync-with-external.md`;
   - используется кодоген (v0/copilot) или в истории есть повторяющиеся ошибки → `anti-patterns.md`;
   - боевой трафик / критичный живой флоу → `_optional/rules/guardrails.md` → `.claude/rules/`;
   - типовые повторяющиеся экраны/фичи → `patterns.md`;
   - важна консистентность терминов → `glossary.md`;
   - планируется много параллельных агентов → `_optional/rules/agent-orchestration.md` → `.claude/rules/`;
   - готовится к проду/пилоту или важна зрелость качества → `_optional/memory/quality-criteria.md` →
     `.memory_bank/` + релевантные `_optional/quality-standards/*` → `.memory_bank/reference/quality-standards/`
     (backend/sql/frontend/android — по стеку проекта).
   Неактуальные модули НЕ копировать.

7. **Заполнить ВСЕ плейсхолдеры `{{...}}`**: в `CLAUDE.md` (`{{PROJECT_NAME}}`, `{{ONE_LINER}}`,
   `{{STACK}}`, `{{STAGE_NOTE}}`, `{{RULES_LIST}}`), в INDEX (`{{PROJECT_NAME}}`, `{{ONE_LINER_SHORT}}`)
   и дату вместо `{{DATE}}` во всех доках банка — ВКЛЮЧАЯ скопированные из шаблона (`guides/*`,
   `changelog/project-history.md`), а не только созданные. Остаточный `{{...}}` audit флагает
   как PLACEHOLDER — после init их быть не должно.

8. **Архивировать intake** → переместить обработанные файлы в `_intake/_processed/`. В `source:`
   сгенерированных доков указать ссылку на исходник.

9. **Проверить консистентность:** выполнить шаги скилла `/memory-check` (сам, без внешних
   инструментов) — пересобрать decision tree в INDEX из frontmatter и проверить orphan/stale/битые
   ссылки. Починить, что выявил. (Если в проекте установлен Node, можно вместо этого запустить
   `node tools/memory-audit.mjs .` — тот же результат детерминированно.)

10. **Показать итог:** какие файлы созданы/заполнены, какие core-темы заведены, какие optional-модули
    активированы, отчёт аудита, и что прочитать первым (`INDEX.md` → `project-state.md`).

## Принципы
- Не выдумывай факты, которых нет в intake — помечай пробелы как `{{TODO}}` и спрашивай.
- Держи Tier 0 тонким (`CLAUDE.md`+`INDEX.md` ≤ ~5 KB). Детали — в Tier 2.
- Не дублируй: один факт — один дом, остальное ссылается (`[[name]]`).
