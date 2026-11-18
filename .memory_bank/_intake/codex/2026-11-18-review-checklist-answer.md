## Заключение

Вердикт по черновику: **CHANGES REQUIRED**.

Основа хорошая: независимая проверка diff, борьба с пустыми доказательствами, конвейер вместо заплатки, визуальная приёмка и живая проверка. Но как универсальная процедура черновик пока опасен по двум причинам:

1. Перепутан жизненный цикл: живая проверка стоит до вливания, а вливание — «после PASS». Нужны два рубежа: внутренний `READY TO MERGE` и окончательный `PASS` только после CI и фактической выкладки.
2. В 19 пунктах смешаны универсальные решения, частные триггеры remlab и закрывающая бухгалтерия. Такой список будут выполнять выборочно.

Главное правило должно помещаться в 14 строк; подробности и матрица триггеров — в отдельном руководстве и автоматическом отчёте.

## Что отсутствует или требует исправления

| Проблема | Что должно быть в процедуре | Доказательство |
|---|---|---|
| PASS до merge/deploy | `READY TO MERGE` после локальной проверки; `PASS` только после CI, версии и живого пути | Черновик: живая проверка в п.16, merge только в п.17 «после PASS» — [draft:29](/home/pakar/igor/remlab/.memory_bank/_intake/codex/2026-11-18-review-checklist-draft.md:29). Между тем завершённый код обязан дойти до прода — [agent-workflow:61](/home/pakar/igor/remlab/.claude/rules/agent-workflow.md:61). |
| Нет фиксации точного SHA | В начале записывать `base SHA`, `review SHA`; проверять и вливать именно его, даже если ветка подвинулась | Урок 612: во время проверки появился новый коммит, и ff вершины увёл бы непроверенное — [devops-deploy:423](/home/pakar/igor/remlab/.memory_bank/lessons/devops-deploy.md:423). |
| Недостаточная защита основной копии | Перед review проверить грязный main, untracked/ignored, симлинки и полноту коммита; грязные cron-пути — немедленный STOP | Урок 516: незакоммиченный код из основной копии подхватил cron и удалил 39 комплектов — [dev-ops:18](/home/pakar/igor/remlab/.memory_bank/lessons/dev-ops.md:18). Worktree без игнорируемых входов тоже врёт — урок 525, [dev-ops:21](/home/pakar/igor/remlab/.memory_bank/lessons/dev-ops.md:21). |
| Не проверяется состояние CI до вливания | Нельзя добавлять несвязанные изменения поверх красного main; исключение — задача, чинящая этот CI | CI был красным часами: урок 569, [devops-deploy:393](/home/pakar/igor/remlab/.memory_bank/lessons/devops-deploy.md:393); 17 часов и ~205 коммитов — урок 713, [devops-deploy:511](/home/pakar/igor/remlab/.memory_bank/lessons/devops-deploy.md:511). |
| «Prepush зелёный» трактуется слишком сильно | Отдельно показывать выполненные, пропущенные и не успевшие проверки; `SKIPPED/UNKNOWN` не равно PASS | `prepush_check.py` исключает pnpm, docker, Playwright, pip и pytest — [prepush_check.py:14](/home/pakar/igor/remlab/tools/ops/prepush_check.py:14); обычная проверка, не успевшая в бюджет, не блокирует — [prepush_check.py:206](/home/pakar/igor/remlab/tools/ops/prepush_check.py:206). |
| Не проверяется CI-job и его зависимости | Новый тест должен быть включён в правильный job и запущен в его Python 3.12/зависимостях, не в общем богатом venv | Уроки 665 и 684: локально зелёно, CI без shapely/planner красный — [devops-deploy:442](/home/pakar/igor/remlab/.memory_bank/lessons/devops-deploy.md:442), [devops-deploy:469](/home/pakar/igor/remlab/.memory_bank/lessons/devops-deploy.md:469). Урок 661: тест вообще отсутствовал в CI — [floorplan-trial:63](/home/pakar/igor/remlab/.memory_bank/lessons/floorplan-trial.md:63). |
| Полный merged tree проверяется не полностью | На итоговом слиянии нужны стандартные typecheck/lint/test/build; path-specific e2e/golden; CI остаётся финальным гейтом | Урок 696: в main влили до завершения полного прогона, ночной cron взял сломанный код — [dev-ops:80](/home/pakar/igor/remlab/.memory_bank/lessons/dev-ops.md:80). Адреса ломали e2e после зелёных unit/typecheck/build — урок 572, [devops-deploy:403](/home/pakar/igor/remlab/.memory_bank/lessons/devops-deploy.md:403). |
| Пустое доказательство описано, но критерий слаб | Требовать свежесть входа, непустой eligible-набор, причины отказов, положительный и отрицательный контроль, old→new | «101/101 совпало» было 101 отказом — [session-scratch:51](/home/pakar/igor/remlab/.memory_bank/_intake/session-scratch.md:51). Паритет «равно» при пустых комнатах — урок 646, [devops-deploy:437](/home/pakar/igor/remlab/.memory_bank/lessons/devops-deploy.md:437). |
| «Пересчитать одно число» недостаточно | Независимо воспроизвести главный итог и проверить инварианты: суммы, знаменатель, причины, масштаб и затронутые группы | Тень дала +1629 вместо узкой ожидаемой группы — факт записан в [mesh-ready.json:5](/home/pakar/igor/remlab/tools/scout/rules/mesh-ready.json:5). Scope blow-up при пересборке банка — урок 681, [layout-solver:322](/home/pakar/igor/remlab/.memory_bank/lessons/layout-solver.md:322). |
| Нет требования проверять настоящий продуктовый путь | Принимать через боевой сервис, его unit/env и опубликованный артефакт, не через личный драйвер | Урок 702: свой скрипт работал с GPU, живая кнопка сутки шла на CPU — [devops-deploy:480](/home/pakar/igor/remlab/.memory_bank/lessons/devops-deploy.md:480). Урок 712: ручной прогон без env unit взял старую модель — [devops-deploy:507](/home/pakar/igor/remlab/.memory_bank/lessons/devops-deploy.md:507). |
| «Прод не позади» недостаточно | Проверять CI нужного коммита, наличие образа при задержке и `version` запущенного сервиса | Уроки 513 и 713: прод был старым при зелёном/красном CI — [devops-deploy:381](/home/pakar/igor/remlab/.memory_bank/lessons/devops-deploy.md:381), [devops-deploy:511](/home/pakar/igor/remlab/.memory_bank/lessons/devops-deploy.md:511). |
| Не хватает packaging/deployment boundary | Проверять Docker context, bundle completeness, proxy/service limits | Урок 674: локальная и CI-сборка зелёные, Docker build упал из-за `.dockerignore` — [devops-deploy:462](/home/pakar/igor/remlab/.memory_bank/lessons/devops-deploy.md:462). Урок 706: новый импорт не попал в пакет GPU — [devops-deploy:498](/home/pakar/igor/remlab/.memory_bank/lessons/devops-deploy.md:498). Урок 701: лимит сервиса был выше лимита Caddy — [devops-deploy:473](/home/pakar/igor/remlab/.memory_bank/lessons/devops-deploy.md:473). |
| Визуальная проверка недостаточно точна | Каждый выданный кадр смотрит ведущий; UI — реальные состояния и обе локали; без браузера нельзя писать «проверено» | Основное правило — [orchestration:114](/home/pakar/igor/remlab/.claude/rules/orchestration.md:114). Урок 697: из 16 кадров ведущий пропустил пустые картины — [viz-render:261](/home/pakar/igor/remlab/.memory_bank/lessons/viz-render.md:261). |
| Нет координации с живыми процессами | До push/restart проверить платную съёмку, refresh/publish, активное задание службы | Push сорвал платную съёмку — урок 556, [devops-deploy:393](/home/pakar/igor/remlab/.memory_bank/lessons/devops-deploy.md:393); публикация поверх `refresh_daily` даёт смешанный результат — урок 666, [demo-planner:284](/home/pakar/igor/remlab/.memory_bank/lessons/demo-planner.md:284). |
| Не включена независимая сверка плана и памяти | Для >5 файлов/новой подсистемы — read-only verify: критерии, scope, память↔код | Это уже обязательная процедура — [agent-workflow:27](/home/pakar/igor/remlab/.claude/rules/agent-workflow.md:27), формат доказательств — [verify.md:22](/home/pakar/igor/remlab/.claude/agents/verify.md:22). |

## Что лишнее или избыточно

- Пункты 8–10 — одна тема: общее правило, переиспользование, потребители и blast radius. Их лучше объединить.
- Отдельный запуск `conveyor_check` в п.13 дублирует `prepush`: он уже входит в `ALWAYS` — [prepush_check.py:40](/home/pakar/igor/remlab/tools/ops/prepush_check.py:40).
- «Любой новый `rules/*.json` → `DEMO_INPUTS`» неверно. Добавлять надо только файл, реально читаемый сборкой. Это уже определяет [build_inputs.py:7](/home/pakar/igor/remlab/tools/ops/build_inputs.py:7).
- «Рискованное всегда за выключателем, по умолчанию выкл.» слишком широко. Для локального bugfix это создаёт лишний путь. Флаг нужен при широком blast radius или поэтапном rollout.
- «Перезапустить службы, если менялся их код» опасно как автоматическое правило: некоторый код запускается отдельным процессом; активное задание нельзя обрывать.
- Пункт 19 логически не может быть «после PASS»: обязательное замечание означает `CHANGES REQUIRED`; необязательный nit — отдельная задача.
- Пункт 18 — закрытие задачи, не проверка кода. Его следует оставить после окончательного PASS.
- Жёсткая матрица 375×667 + 1280 для любого «видимого человеком» чрезмерна. Для web — 375×667 и принятый desktop viewport, сейчас в уроках указан 1440; для PNG/рендера — исходный размер и целевой носитель.
- Формат отчёта и четыре строки конвейера не надо повторять целиком в коротком правиле. В нём достаточно ссылки на обязательный формат; в отчёте допускается только содержательное `N/A: причина`, не пустота.

## Автоматизация

### Уже существующее

- `tools/ops/merge-queue.sh branch@<sha> --steps typecheck,lint,test,build,prepush,memory` — временный чистый worktree, точный SHA, merged tree, журнал и выявление baseline/flaky. Возможности описаны в [merge_queue.py:2](/home/pakar/igor/remlab/tools/ops/merge_queue.py:2). По умолчанию build отсутствует, e2e не поддерживается — это важно.
- `bash tools/ops/prepush-check.sh --files … --dry` — показывает выбранные дешёвые проверки из `ci.yml`; обычный запуск их выполняет.
- `python tools/ops/conveyor_check.py` уже объединяет:
  - реестр generated-файлов и писателей;
  - `build_inputs.py` / `DEMO_INPUTS`;
  - `docker_context.py`;
  - `render_inputs.py` — [conveyor_check.py:289](/home/pakar/igor/remlab/tools/ops/conveyor_check.py:289).
- `python tools/ops/conveyor_ids.py --block` — на review должен быть именно блокирующий режим. Обычный prepush пока лишь предупреждает — [conveyor_ids.py:21](/home/pakar/igor/remlab/tools/ops/conveyor_ids.py:21).
- `node tools/ops/demo-i18n-scan.mjs --check` — точный RU/EN-гейт статической demo-страницы.
- `python tools/scout/tests/test_tmp_hygiene.py` — запускать при любом новом/изменённом scout test/selftest, пока prepush не получил глобальный триггер. Уроки 715/673 показывают текущую дыру.
- `bash tools/ops/ci-status.sh` — одноразовая проверка main; `bash tools/ops/deploy-need.sh --status` — версия прода относительно main.
- `.claude/agents/verify.md` — независимая проверка больших изменений.

### Маленький новый helper

Предлагаю `tools/ops/review_check.py` с двумя фазами:

```text
python tools/ops/review_check.py premerge --task T-ID --plan PATH --base main --head SHA
python tools/ops/review_check.py postpush --head SHA
```

Два запуска неизбежны: CI и прод появляются только после push. Helper должен печатать следующую точную команду, не опрашивать GitHub циклом.

`premerge`:

- фиксирует base/head SHA и предупреждает, если ветка ушла;
- печатает `status`, name-status, stat, numstat, commits, untracked/ignored;
- блокирует грязные cron-пути в основной копии;
- сверяет файлы с планом;
- показывает потенциальных потребителей: импорты, текстовые ссылки, тесты и owning CI jobs;
- печатает триггеры: TS, UI, route/e2e, DB migration, systemd/cron, rules, demo, новый тест/selftest;
- запускает `git diff --check`, conveyor, IDs `--block`, нужный i18n/tmp гейт;
- использует `prepush_check` для карты, но отдельно перечисляет пропущенные slow-команды;
- проверяет, что новый тест упомянут в `ci.yml`, и показывает job с его `pip install`;
- завершает кодом `0=автогейты зелёные`, `1=FAIL`, `2=UNKNOWN/SKIPPED`; код 2 запрещает PASS.

`postpush`:

- проверяет CI именно для review SHA либо зелёного потомка, содержащего его;
- отдельно проверяет текущий main, чтобы не пропустить новую красную полосу;
- читает `/api/health`, проверяет ancestry deployed SHA;
- при задержке >15 минут предлагает/выполняет проверку manifest;
- для `/demo` сообщает, что нужен отдельный build/publish hash, а не только app health.

Важно: «найдены все потребители» полностью автоматизировать нельзя. `rg`/import scan — список кандидатов, не доказательство полноты. Аналогично общий RU/EN-анализ вне demo будет шумным; там нужны доменные тесты.

## Предлагаемое короткое правило — 14 строк

```text
1. Приёмка относится к точному SHA работника и текущему base SHA; вершина ветки сама целью не становится.
2. Прочитай бриф/план/отчёт и сопоставь каждый критерий, отступление и обязательное поле.
3. До вливания main должен быть зелёным; поверх красного CI несвязанные изменения не вливать.
4. Проверяй итоговый diff в чистом merge-worktree: scope, status, untracked/ignored, секреты и полнота коммита.
5. Грязный cron-код в основной копии — STOP; generated-файлы меняются только своим генератором.
6. Найди потребителей, тесты, доки, упаковку, сборщик, публикатор и шаг перевыпуска изменённого контракта.
7. Доказательство обязано быть непустым: свежий вход, знаменатель, успехи/отказы, ±контроли, old→new и масштаб.
8. Запусти review-helper и все его обязательные проверки на финальном merged tree; SKIPPED/UNKNOWN не зелёный.
9. Новый тест должен быть в правильном CI-job с его зависимостями; новый temp-код проходит tmp hygiene.
10. Проверь записи/удаления/миграции/деньги/cron/службы/публикацию, разрешение, предел, backup и rollback.
11. Видимое человеком ведущий смотрит сам на фактическом результате: нужные состояния, RU/EN и целевые размеры.
12. Продуктовый путь проверяется через боевой сервис/unit/env и опубликованный артефакт, не личным скриптом.
13. Вливай только проверенный SHA; перед push не ломай живой прогон; после push PASS ещё не объявляется.
14. PASS только после зелёного CI нужного SHA/потомка, правильной live-версии и smoke; затем память, план и отчёт.
```

## Детальное руководство

1. **Вход и цель.** Зафиксировать T-ID, цикл, plan/brief, base SHA, review SHA, заявленные файлы и критерии. Пустой обязательный отчёт или четыре строки конвейера без содержания — `CHANGES REQUIRED`; для неприменимого пункта требуется `N/A: причина`.

2. **Baseline.** Проверить main CI до merge. Если он красный, разрешена только задача, устраняющая этот сбой. Отделить новый дефект от уже существующего или flaky: повтор упавшего шага и тот же шаг на чистом main.

3. **Scope и полнота.** В чистом merge-worktree проверить commits, status, diff/stat/numstat, untracked/ignored и файлы вне плана. Для `tools/scout/**`, `infra/**`, `assets/*.sh`, `tools/ops/**` отдельно подтвердить отсутствие грязных правок в основной копии.

4. **Код и конвейер.** Проверить общее правило, отсутствие особого ID, один источник истины, вызывающих потребителей, тесты, generated outputs, Docker/bundle, restart/rebuild/reissue. Флаг нужен только при реальном rollout/rollback-риске.

5. **Доказательства.** Указать источник и возраст данных; eligible/success/reject/skip; причины отказов; positive и negative control; old→new на одинаковом входе; ожидаемый и фактический blast radius. Нулевой знаменатель или одинаковый отказ с обеих сторон — провал проверки.

6. **Автопроверки.** На финальном merged tree выполнить helper. Для Next.js-кода — typecheck/lint/test/build; для маршрутов и пользовательских ссылок — соответствующий e2e; для правил/сборщиков — golden; для нового Python-теста — правильный CI-job и чистое окружение его job.

7. **По типу результата.**
   - UI/web: RU/EN, телефон и desktop, loading/empty/error/success, реальный браузер.
   - Кадры/дизайн: каждый выдаваемый кадр целиком в исходном размере.
   - Данные: provenance, команда, hash/version входов, суммы, дубликаты, причины исключений, side effects.
   - Память: каждое утверждение о коде — с `файл:строка`; затем memory audit/verify.
   - Сервис: запрос через настоящий endpoint и unit env; состояние до/после restart.

8. **Вливание и выпуск.** Влить проверенный SHA в чистой копии, ff main, push. Не пушить во время конфликтующего refresh/платного прогона. Не перезапускать службу, не проверив активную работу.

9. **Финальный гейт.** CI зелёный для проверенного SHA либо содержащего его потомка; текущий main не красный; приложение/образ/demo действительно обновлены; `/api/health` или release hash соответствует ожидаемому; живой сценарий пройден.

10. **Решение.** Только теперь `PASS`. Обязательный дефект — `CHANGES REQUIRED` тому же worker/T-ID/новому циклу. Невозможность проверить, внешний сбой или отсутствие разрешения — `BLOCKED`, а не условный PASS.

## Шаблон вердикта

```text
[ведущий] T-…/<цикл> · принято|правки|вопрос
Модель проверки: …
Вердикт: PASS | CHANGES REQUIRED | BLOCKED

Цель:
- base: <sha>
- reviewed: <sha>
- merged/deployed: <sha или N/A>

Критерии:
- [OK|FAIL|NOT CHECKED] <критерий> — <доказательство>

Scope/diff:
- файлов …, +…/−…
- вне плана: нет | …
- status/untracked/ignored: чисто | …

Доказательства:
- вход/версия/дата: …
- old → new: …
- eligible / success / reject / skip: …
- positive/negative control: …
- blast radius: ожидаемо …, фактически …

Проверки:
- <команда> → rc …, <существенный итог>
- SKIPPED/UNKNOWN: нет | …

Глазами:
- <URL/артефакт>, RU/EN, размеры/состояния: …
- что именно просмотрено: …

CI и выпуск:
- CI run SHA/conclusion: …
- live version/build hash: …
- smoke/боевой путь: …
- rollback: …

Находки:
- BLOCKER/MAJOR/MINOR: файл:строка — проблема — требуемый результат

Что не проверено:
- нет | пункт и причина

Следующий шаг:
- PASS: план/память/ссылка владельцу «куда нажать, что увидеть»
- CHANGES REQUIRED: тому же worker, тот же T-ID, цикл N+1
- BLOCKED: кто/что должно разблокировать
```

## Неопределённости

- Пример `101/101` пока живёт в session scratch, а `+1629` — в комментарии правила, не в нумерованном уроке. Если они становятся основанием универсального процесса, их стоит закрепить отдельным durable lesson.
- Политика расходится: orchestration запрещает ID в коде, но `conveyor_ids.py` по умолчанию ещё работает в режиме warning. Для review нужен `--block` либо явное решение переключить общий режим.
- `ci-status.sh` показывает последний завершённый run, который может относиться к предыдущему SHA, пока новый run ещё идёт. Без проверки SHA его зелёная строка недостаточна для PASS.
- В `ci.yml` только основной gate закреплён на Ubuntu 24.04; другие jobs используют `ubuntu-latest`. Поэтому «как CI» означает окружение конкретного job, а не одно общее локальное окружение.

Файлы не изменялись.