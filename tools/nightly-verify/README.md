# nightly-verify — ночная сверка памяти с кодом (v1.11)

Каждую ночь 1–2 дока банка сверяются с текущим кодом субагентом `verify` в headless-сессии Claude.
Найденные расхождения правятся в отдельной ветке `memory/nightly-<ГГГГММДД>-<N>`, а утром ведущий её смотрит и
вливает сам. **Push и авто-влива нет.** Зачем: банк догоняет код каждый день маленькими порциями, а не перед
приёмкой (план remlab `mem-freshness-01` п. 4, разбор Codex 05.11 § «Ночная сверка»).

## Что делает один запуск
1. `flock` на проект (`<git-common-dir>/memory-bank/nightly-verify.lock`): второй запуск сразу выходит с кодом 3.
2. `git fetch` и чистая копия **вне `.claude/`** на свежем `origin/main`. По умолчанию это `<проект>/.nightly-verify/wt`:
   - копия скрыта в `.git/info/exclude`;
   - журналы её сессий учёт токенов (`tokeny`) относит к тому же проекту;
   - соседняя папка `<проект>-nightly` считалась бы отдельным проектом.
3. Очередь собирается заново при каждом запуске (общего файла очереди нет), в таком порядке:
   - **а)** доки, задетые кодом за последние 24 ч (`tools/memory-impact.mjs`, статус «в очередь сверки»). Внутри группы: `importance: high` → задеты названия → больше файлов;
   - **б)** `--drift-report` с «!»: код изменён после сверки дока, и в изменённых файлах встречаются названия из текста дока;
   - **в)** остальной дрейф: сначала `importance: high`, затем самый давний коммит сверки;
   - **г)** ротация: самый давний `last_verified`, сводки и Tier 2. Доки из `_kit/no-anchor-ignore.txt` в ротацию не попадают.
4. Бюджет — не больше `max_docs` доков и `max_claims` утверждений. Утверждения считаются оценкой: строки дока со ссылкой в `коде`.
   - Док больше бюджета из групп а–в пропускается с пометкой «крупные — вручную».
   - **Пустая очередь — выход 0 без вызова модели.**
5. Ветка `memory/nightly-<id>`, затем `claude -p`:
   - первая строка запроса — метка учёта токенов (`label`);
   - агент `verify` из `.claude/agents/verify.md` в режиме «по списку доков», как `/memory-check` этап 1.6;
   - права: чтение, правка файлов и `node tools/memory-health.mjs --log-verify` (без хуков проекта: `--setting-sources user`);
   - без MCP и плагинов пользователя (`--strict-mcp-config`, включённые плагины выключаются через `--settings`). Иначе плагин-канал (Telegram) поднял бы второй сервер и перехватил бота живой сессии;
   - правки допустимы только в выбранных доках и `changelog/verify-log.tsv`; любой другой изменённый файл — отмена.
6. Оба аудита чистые (запись реестров, затем `--check`; `memory-project-audit.mjs`, если он есть) → коммит в ветку.
   Аудит копии запускается и **до** модели. По умолчанию (`audit_gate=clean`) грязная копия — отмена без платного запуска.
   При `audit_gate=new` допустимы только проблемы, которые уже были до сверки. Это нужно проектам, где чистая копия из git сама не проходит аудит: ссылки на файлы вне git, `ROADMAP` #15 п. 5.
7. Если main уехал за время прогона — rebase и повтор аудитов. Конфликт или грязный аудит — отмена: ветка
   переименовывается в `…-otmena`, в main ничего не попадает. Модель ничего не изменила — ветка `…-pusto`.

Отчёт:
- вывод в stdout (`journalctl --user -u nightly-verify-<проект>`);
- файл `<git-common-dir>/memory-bank/nightly-verify/<id>/report.md`; рядом лежат `prompt.txt`, `claude.json` (ответ, цена) и `claude.stderr.txt`;
- строка телеметрии в `<git-common-dir>/memory-bank/nightly-verify.log`: время, итог, доки, утверждения.

Коды выхода: 0 — коммит в ветке, пустая очередь или сухой прогон; 1 — отмена; 2 — ошибка запуска; 3 — занято.

## Сухой прогон
```bash
node tools/nightly-verify/nightly-verify.mjs --dry-run
```
Печатает очередь и бюджет по дереву как есть (HEAD). Не запускает модель, не делает fetch, не создаёт копию и ветку, ничего не пишет.
Ключ `--tools <папка>` берёт `memory-audit`/`memory-impact` из другой папки, например из копии кита до апгрейда проекта.

## Установка
Требования:
- кит ≥ 1.11: `tools/memory-impact.mjs`, `memory-audit.mjs` с `--drift-report`, `memory-health.mjs --log-verify`;
- агент `.claude/agents/verify.md`;
- `node` ≥ 20, `claude` (вход по подписке выполнен), `flock`;
- systemd пользователя и linger (`loginctl enable-linger $USER`), чтобы таймер работал без входа в систему.

```bash
cp -r <кит>/_optional/nightly-verify tools/nightly-verify
cp tools/nightly-verify/nightly-verify.conf.example .memory_bank/_kit/nightly-verify.conf   # правка: model, label
git add tools/nightly-verify .memory_bank/_kit/nightly-verify.conf && git commit -m "chore: ночная сверка памяти"
tools/nightly-verify/postavit_taymer.sh --proba    # проверки + текст юнитов, ничего не пишет
tools/nightly-verify/postavit_taymer.sh            # ~/.config/systemd/user/nightly-verify-<проект>.{service,timer}
```
- Время запуска задаёт `NIGHTLY_VREMYA=03:30` (по Лондону); запускать из основной копии.
- Конфиг читается из основной копии. Скрипты и аудиты берутся из свежей копии `origin/main`, поэтому сам модуль должен быть в main.
- Снять таймер: `systemctl --user disable --now nightly-verify-<проект>.timer`.

## Конфиг `.memory_bank/_kit/nightly-verify.conf`
`ключ=значение`, `#` — комментарий. Все ключи с умолчаниями — в `nightly-verify.conf.example`:
- `model` — модель headless-сессии;
- `max_docs` / `max_claims` — бюджет ночи;
- `since_hours` — окно «код за сутки»;
- `remote`/`branch` — откуда брать свежий код;
- `label` — метка в первой строке запроса;
- `worktree` — где лежит копия (внутри `.claude/` запрещено);
- `claude_bin` — путь к `claude`;
- `max_budget_usd` — предохранитель `--max-budget-usd`;
- `audit_gate` — `clean` или `new`, см. шаг 6.

Неизвестный ключ — предупреждение в отчёте, а не ошибка.

## Утром
```bash
git log --oneline main..memory/nightly-<id>; git diff main...memory/nightly-<id>
git merge --ff-only memory/nightly-<id>    # или rebase, если main ушёл; ветку потом удалить
```
