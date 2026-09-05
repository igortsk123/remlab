## 1. Вывод

В текущем виде diff я бы не вливал. Направление верное, но есть два блокера:

- `_kill_group()` не гарантирует уничтожение всей группы: он прекращает эскалацию, как только умер shell-лидер, даже если его потомок пережил `SIGTERM`.
- Новый тест удаляет настоящий боевой `mesh-group-halt.json`. Запуск стенда рядом с продовым процессом может снять запрет сторожа и вернуть платные ноды.

Логику `/start` тоже надо поправить: не нужен редкий «слепой старт». Нужны явные состояния группы и отдельная диагностика её реплик.

## 2. Доказательства и замечания по A

### Блокер: SIGKILL может никогда не отправиться

В [_kill_group()](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:62) после `SIGTERM` проверяется только `p.wait()`:

```python
os.killpg(pgid, SIGTERM)
p.wait(...)
return
```

`p` — `/bin/sh`, а не вся группа. Shell может умереть немедленно, а Python-потомок проигнорировать или задержать `SIGTERM`. Тогда `p.wait()` завершится и код выйдет, не послав `SIGKILL`.

Правильно:

1. Послать `SIGTERM` группе.
2. До конца grace-периода проверять существование именно группы через `killpg(pgid, 0)`.
3. Если группа ещё существует — `SIGKILL`.
4. Отдельно reap `p`.
5. В `finally` закрыть пайпы.

Текущий тест этого не ловит: `sleep` послушно умирает от `SIGTERM` ([tests_pool.py:698](/home/pakar/igor/remlab/tools/scout/salad/tests_pool.py:698)). Нужен потомок с `trap '' TERM`, иначе ветка `SIGKILL` вообще не проверена.

### Может ли killpg задеть конвейер или соседние шаги?

В нормальном пути — нет. `start_new_session=True` в [sh()](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:95) создаёт отдельные session/PGID для каждого запуска. Одновременные `ssh_run` и post-processing оказываются в разных группах.

Остаточные случаи:

- Потомок может сам вызвать `setsid()` и уйти из группы — `killpg` его уже не достанет.
- Ветка `pgid == os.getpgid(0)` убивает только shell и воспроизводит исходную утечку ([batch_show.py:80](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:80)). Это должно считаться аварией изоляции, а не успешной очисткой.
- Для абсолютной гарантии против `setsid()` нужен cgroup/systemd scope, а не дерево PID или PGID.

Обычные `python`, `rsync` и `ssh -o BatchMode=yes` сами не daemonize, поэтому для текущих команд process group практически достаточна.

### `kill → communicate`

Сам порядок правильный. Дополнительный поток для чтения пайпов не нужен: `communicate()` читает stdout и stderr без взаимной блокировки.

Но сейчас остаются дефекты:

- Если повторный `communicate()` тоже истёк, ранее накопленный вывод выбрасывается ([batch_show.py:104-108](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:104)).
- Процесс после второго таймаута больше не добивается и пайпы явно не закрываются.
- Весь вывод 45-минутного шага хранится в RAM, хотя возвращаются только последние 1500 байт. На VM с 11 ГБ лучше писать длинные шаги во временный лог с ограниченным tail.

### SIGTERM или сразу SIGKILL

Сразу `SIGKILL` не рекомендую. Для `rsync`, записи реестра и purge это увеличивает риск временных/частичных файлов. Разумно:

- 3–5 секунд для чисто вычислительных post-шагов;
- до 10 секунд для `rsync`/drain;
- затем обязательный `SIGKILL` оставшейся группе.

### Другие места с тем же классом дефекта

- Блокер: [ssh_run.sink_relief()](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:250) запускает shell-команды через `subprocess.run(..., shell=True, timeout=1800)` ([строка 267](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:267)). Там снова может умереть только shell. Кроме того, работа идёт в daemon-thread: завершение `ssh_run` способно оставить drain/purge сиротой даже без таймаута.
- [mesh_demand subprocess](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:719) убивает только прямой Python; риск появится, если тот начнёт порождать долгоживущих детей.
- [ssh_text()](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:330) и [run_job()](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:340) запускают прямой `ssh`, поэтому локальной shell-утечки обычно нет. Но уничтожение локального SSH не гарантирует прекращения уже принятого удалённого `/generate`. Это другой класс риска; process group на DEV его не решает.

Отдельный общий runner следует вынести и использовать как минимум в `batch_show.sh()` и `ssh_run.sink_relief()`.

## 3. Критика B: запуск групп

### Важно: `None` ошибочно трактуется как `stopped`

`group_states()` документирует `None` как «не смогли узнать» ([batch_show.py:127](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:127)), но `ensure_group_started()` отправляет `/start` и для `None` ([batch_show.py:263-269](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:263)).

При сбое WAF/API это снова превращается в слепой старт. Для денежного контура безопаснее:

- `None` → повторить GET с backoff, затем alert/fail-closed;
- `/start` → только для достоверно стартуемого состояния.

Дополнительно `curl -s` не проверяет return code/HTTP status ([batch_show.py:139](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:139)). Нужны `-S`, проверка `returncode` и диагностический tail ответа.

### Важно: отрицательный список состояний ненадёжен

Сейчас «поднятым» считается любое значение, кроме `stopped`, `failed`, `None`. Неизвестное терминальное состояние тоже будет принято за живое.

Нужны явные множества:

- `ACTIVE = {фактически подтверждённые состояния Salad}`;
- `STARTABLE = {'stopped', возможно 'failed'}`;
- всё остальное → unknown/alert.

Полный список реальных `current_state.status` в репозитории не закреплён — его надо получить из сохранённых ответов Salad или документации до финализации.

### Важно: мгновенный повтор `/start`

После принятого POST код сразу повторно читает состояние и может повторить POST, если API ещё показывает старое `stopped` ([batch_show.py:294-312](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:294)). Это eventual-consistency race.

Кроме того, `group_status()` возвращает первый non-stopped статус, включая `failed`, поэтому результат смешанного `running + failed` зависит от порядка групп ([batch_show.py:150-161](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:150)).

Лучше убрать агрегат из процедуры старта:

- один POST на каждую достоверно остановленную группу;
- записать результат отдельно по группе;
- следующий GET через 10–30 секунд либо на следующем обычном тике;
- cooldown на повторный `/start`;
- `no_credits_available` классифицировать на каждой попытке, включая повтор.

### Нужен ли редкий слепой `/start` при отсутствии мешей?

Нет. По наблюдаемому контракту `/start` на `running` возвращает `replicas_quota_exceeded`; он не лечит отсутствие или зомби-реплики.

Разделение должно быть таким:

- Группа `stopped` → `/start`.
- Группа активна, но реплик нет → ожидание allocation + alert; не `/start`.
- Реплики `running`, но не готовы → существующие `probe_health`, `silent_fault`, `cull_dead_warmups`.
- Оплаченные реплики долго не дают мешей → `money_guard` останавливает пул.

Сигнал тишины уже есть в [money_guard.last_mesh_at()](/home/pakar/igor/remlab/tools/scout/salad/money_guard.py:204) и сохраняется в `mesh-money-guard.json` ([money_guard.py:35](/home/pakar/igor/remlab/tools/scout/salad/money_guard.py:35), [310-318](/home/pakar/igor/remlab/tools/scout/salad/money_guard.py:310)). Повторно сканировать весь растущий JSONL из `batch_show` не стоит; можно читать сохранённое состояние O(1). Но этот сигнал должен запускать диагностику/остановку, не слепой `/start`.

## 4. Дефекты новых тестов

### Блокер: тест удаляет боевой halt-файл

[tests_pool.py:743](/home/pakar/igor/remlab/tools/scout/salad/tests_pool.py:743):

```python
os.path.exists(B.HALT) and os.remove(B.HALT)
```

`B.HALT` здесь не подменён временным путём. Содержимое также не восстанавливается. Это ровно нарушение, от которого уже защищён старый `case_halt_blocks_start()` ([tests_pool.py:458](/home/pakar/igor/remlab/tools/scout/salad/tests_pool.py:458)).

Нужно временно подменять `B.HALT`, как делает существующий тест. Из-за этого дефекта я стенд не запускал.

Также:

- pidfile теста общий для всех запусков: `/tmp/tests_pool-child.pid`; параллельные тесты могут убить чужой PID.
- `PermissionError` в проверке `os.kill(pid, 0)` ошибочно считается отсутствием процесса.
- Не проверяются stubborn-child, сохранение tail, изоляция от соседнего процесса и ветка API `None`.
- Не проверяются stale `stopped` после успешного POST, смешанные `failed/running` в обоих порядках и `no_credits_available`.
- `case_group_status_mixed()` меняет `SALAD_GROUP`, но не восстанавливает его ([tests_pool.py:679](/home/pakar/igor/remlab/tools/scout/salad/tests_pool.py:679)).

## 5. Альтернативы

- Лучший небольшой вариант: общий `run_step()` с новой сессией, bounded-log и корректной эскалацией группы. Использовать и в `batch_show`, и в `ssh_run`.
- Сильнейшая гарантия: отдельный systemd/cgroup scope на шаг с `KillMode=control-group`. Он ловит даже потомков, сделавших `setsid`, но требует проверить права DEV-VM.
- `psutil` с обходом descendants проще cgroup, но гоняется с reparenting и хуже PGID.
- Для topview наиболее чисто убрать shell-цикл и сделать цикл в Python: тогда каждый `topview_render.py` — прямой управляемый процесс.

## 6. Что рекомендую

До merge:

1. Исправить `_kill_group`: проверять жизнь PGID, а не только shell-лидера.
2. Гарантированно добивать/reap процесс и закрывать пайпы после второго таймаута.
3. Перенести `sink_relief()` на тот же безопасный runner; убрать риск daemon-thread-сироты.
4. Подменить `B.HALT` временным путём в тесте.
5. Добавить тест с потомком, игнорирующим `SIGTERM`, и отдельным соседним процессом.
6. В `ensure_group_started()` считать `None` неизвестностью, а не разрешением на POST.
7. Заменить отрицательную классификацию состояний явным state machine.
8. Убрать немедленный второй `/start`; повторять по группе после cooldown.
9. Не добавлять blind-start по тишине.
10. В [finale()](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:843) проверять ошибку остановки: сейчас ненулевой код `stop_group` лишь печатается, после чего выполнение продолжается. Нужны повтор и тревога — иначе `finally` формально выполнен, а тарификация продолжается.

## 7. Допущения и что изменило бы вывод

Допускаю Linux/POSIX и отсутствие намеренной daemonization в текущих post-командах. Неизвестен полный enum состояний Container Group Salad и задержка согласования состояния после `/start`.

Вывод о blind-start изменился бы, если логи/API Salad покажут, что `/start` на группе со статусом `running` действительно восстанавливает отсутствующие реплики, а не только возвращает `replicas_quota_exceeded`. Вывод о достаточности PGID изменился бы, если среди вызываемых скриптов найдутся процессы, сознательно делающие `setsid()` — тогда сразу нужен cgroup.