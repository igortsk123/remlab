## Вердикт

Нужна эшелонированная защита: hooks дают ранний отказ, CI не позволяет влить обход, а runtime-права и подписанный provenance физически запрещают менять live-артефакты вне конвейера. Одних инструкций и hooks недостаточно.

## 1. Где сейчас проходят ручные исправления

1. **Live/generated-файлы вне Git.** `.gitignore:36` скрывает почти весь `tools/scout/*`, включая `sets3.json`, `sets-bedroom.json`, `sets3.next.json`, индексы и snapshots. Git/CI не видят их ручную замену.

2. **Административные обходы:** `bank_prepare.py --force`, `bank_promote.py --force/--force-ready/--no-exam`, `bank_refresh.py --force`; `refresh_daily.sh --force`; `demo-realistic.mjs --force`. Инцидент подтверждён в `.memory_bank/_intake/peredacha/otchety-direktoru.md:160`: спальня продвинута с `--force` при `promote_enabled=false`.

3. **Прямые entrypoint’ы вне ночи:** `flat215_demo.py`, `publish_demo.sh`, `tour-reissue.sh`, `tools/floorplan/reissue.py`, `trial_bundle.py`, `sets_incremental.py --apply`. Их можно вызвать отдельно и получить корректный по формату, но незаконный по происхождению результат.

4. **Подмена путей и лимитов через env:** `SETS_OUTPUT`, `ROOM_SETS_OUTPUT`, `BANK_CANDIDATE`, `BANK_PROMOTE`, `BANK_GENERATIONS`, `BANK_MAX_PROMOTE_SHARE`. Часть защищена SHA/realpath, но общей политики нет.

5. **Неполный provenance.** [build_stamp.py](/home/pakar/igor/remlab/tools/scout/build_stamp.py:17) хеширует только `rules/*.json`, пропуская `rules/room-templates/**` и `tools/scout/rules/profiles/**`; `nogit/norules` не блокируют сборку. Метка доказывает сходство demo/tour, но не законность запуска.

6. **Claude hooks.** [settings.json](/home/pakar/igor/remlab/.claude/settings.json:5) имеет PreToolUse только для Bash; [guard-bash.mjs](/home/pakar/igor/remlab/tools/hooks/guard-bash.mjs:1) блокирует лишь `pkill/pgrep -f` и намеренно fail-open. Для Edit/Write есть только неблокирующий PostToolUse.

7. **Prepush.** [prepush_check.py](/home/pakar/igor/remlab/tools/ops/prepush_check.py:144) пропускает slow-тесты; не успевшие проверки не блокируют push, сам hook обходится `--no-verify`, что прямо напечатано на строке 197.

8. **CI.** [ci.yml](/home/pakar/igor/remlab/.github/workflows/ci.yml:294) хорошо проверяет bank chain, SHA, rollback, room guards, money guard и порядок refresh, но нет общего generated/provenance gate и lint на частные ID/ветки. Нужен обязательный GitHub ruleset без bypass для агентов.

9. **Специсключения уже имеют разные формы:** `data/flat3d/front-overrides.json` — ручной per-SKU override вне `rules/`; `feed_guard.py:82` — идентификатор в коде; `smoke_manifest.py:20` — список конкретных сцен. Не все плохи, но единого реестра исключений нет.

10. **Брифы/отчёты.** Форматы в `.claude/rules/orchestration.md:121` и `.memory_bank/guides/orchestration.md:28` требуют файлы/тесты/отступления, но не требуют назвать изменённое правило, генератор, ночной шаг и остальные потребители.

Существующие `run_id`, candidate/live/hybrid SHA, journal/snapshots, доля 25 %, money lease и `heavy-slot` полезны, но защищают отдельные операции, не сам принцип «только через конвейер».

## 2. Предохранители по ценности/стоимости

| Приоритет | Предохранитель | Ценность | Стоимость |
|---|---|---:|---:|
| P0 | `tools/ops/conveyor-manifest.yml`: generated/live пути → единственный generator → inputs → nightly stage → publisher | Очень высокая | Низкая |
| P0 | Runtime write barrier: live-банки и publish-каталоги принадлежат отдельному Unix-пользователю конвейера; агентам доступен только staging/scratch | Максимальная | Средняя |
| P0 | Удалить обычный `--force`; заменить подписанной одноразовой owner-capability | Максимальная | Средняя |
| P0 | Обязательный CI job `conveyor-guard`, защищённая `main`, bypass только владельцу/боту | Очень высокая | Низкая |
| P1 | PreToolUse для Edit/Write и Bash из того же manifest | Высокая | Низкая |
| P1 | AST/literal lint частных tour/SKU/MSID/room-id и special-case branches | Высокая | Средняя |
| P1 | Полный recursive provenance + отказ publisher при несовпадении | Высокая | Средняя |
| P1 | Обязательные поля брифа, отчёта и ревью | Средняя | Низкая |

### CI `conveyor-guard`

- Запрет diff по tracked-generated путям, если они не пересобраны объявленной командой; для детерминированных файлов — regeneration в temp и `git diff --exit-code`.
- Для live/untracked — проверка схемы provenance: generator/version, recursive inputs SHA, rule/template SHA, git tree, `run_id`, previous generation, timestamp, output SHA.
- Любая правка `room-templates/**`, `tools/scout/rules/**`, `services/planner-solver/rules/**` обязана менять ожидаемый fingerprint и запускать связанные contract/golden/nightly-order тесты.
- Проверять, что каждый mutator/publisher зарегистрирован в manifest и достижим из `refresh_daily.sh`; неизвестный writer — FAIL.
- Lint запрещает ID-литералы и сравнения `if sku/tour_id/room_id == ...` вне `rules`, tests и утверждённого allowlist.
- Lint отдельно запрещает новые CLI-обходы `--force`, `--no-exam`, `--force-ready`, прямой live output и изменение лимита через env.
- `prepush` всегда запускает быстрый `conveyor-guard`; таймаут этого gate должен блокировать, а не считаться «проверит CI».

### Owner-capability вместо статического токена

Подписанный файл: `{action, target, expected_sha, T-ID, ADR, expires, nonce}`. Публичный ключ лежит в репо, приватный — только у владельца. Capability одноразовая, узкая по действию и SHA, записывается в append-only audit. Статический `OWNER_TOKEN` хуже: агент может его переиспользовать или случайно вывести.

### Claude Code hooks

- `PreToolUse Edit|Write`: блокировать live/generated пути из manifest; разрешать только правило/шаблон, generator и scratch.
- `PreToolUse Bash`: блокировать mutator/publisher напрямую, `--force`, перенаправление/cp/mv в generated paths; разрешать canonical wrapper или валидную capability.
- Разбирать argv/tool input, а не искать подстроку: иначе будут ложные срабатывания в комментариях и `git --force-with-lease`.
- Hooks — UX-слой, не security boundary: Bash можно обфусцировать, поэтому обязательны Unix-права и проверка publisher.

### Бриф и отчёт

В каждый бриф добавить обязательные ответы:

- «Какое template/rule меняется? Почему это общее правило?»
- «Где ещё оно применяется: demo, tour, все типы комнат, nightly, reissue?»
- «Какой generator/nightly stage пересоберёт результат? Generated-файлы вручную не трогать».
- «Какие контрпримеры доказывают отсутствие per-tour/per-SKU фикса?»

В отчёт: изменённые template/rule; canonical-команда; `run_id`/provenance; generated paths untouched; «где ещё проверено». PASS запрещён при пустых полях.

## 3. Ложные срабатывания и исключения

- Допустимы ID в tests/fixtures/goldens, документации и CLI-примерах; room type `bedroom|hall` — архитектурный plugin, не `room_id`.
- Curated smoke-сцены и доказанные per-SKU решения допустимы только как данные в `rules/**`, не ветка кода.
- Создать `tools/ops/conveyor-exceptions.yml`: точный detector/path/symbol, причина, ADR, владелец, дата истечения, тест. Wildcard и бессрочные записи запрещены.
- Golden обновляется только объявленным `--update-golden`; CI сверяет команду и входной fingerprint.
- `--force` сторонних безопасных инструментов разрешать точечно по argv; не делать глобальное исключение.
- `data/flat3d/front-overrides.json` следует перенести в схемированный rules-реестр с evidence/ADR/expiry либо запретить новые записи.

## 4. Первые пять действий

1. Ввести `conveyor-manifest.yml` и обязательный CI-аудит writers/generated paths.
2. Закрыть `bank_* --force/--force-ready/--no-exam` и `refresh_daily --force` подписанной owner-capability.
3. Добавить blocking PreToolUse для Edit/Write/Bash, питающийся тем же manifest.
4. Перевести live-банки/publish на отдельного service user и включить recursive signed provenance.
5. Обновить шаблоны брифа/отчёта и добавить AST-lint special cases сначала в warn, через неделю — в block.

Файлы не изменял; рабочее дерево до/после аудита оставлено как было.