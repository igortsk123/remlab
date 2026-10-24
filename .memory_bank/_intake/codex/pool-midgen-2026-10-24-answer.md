Короткий вердикт: вывод в целом верный. Но `mid_generation` сейчас не доказывает ни начало генерации, ни OOM; прямого `restart_count` в API инстанса нет. Перед полным подъёмом нужны системные события Salad и двухнодовая канарейка.

1. Память группы

- `24576` есть в шаблоне [`tools/scout/salad/container-group.json:8`](/home/pakar/igor/remlab/tools/scout/salad/container-group.json:8), но активное создание его не читает.
- `migrate_groups.build_body()` копирует `cpu/memory/gpu_classes/storage` с группы-донора: [`migrate_groups.py:94`](/home/pakar/igor/remlab/tools/scout/salad/migrate_groups.py:94), [`migrate_groups.py:102`](/home/pakar/igor/remlab/tools/scout/salad/migrate_groups.py:102). Новая группа создаётся POST: [`migrate_groups.py:153`](/home/pakar/igor/remlab/tools/scout/salad/migrate_groups.py:153).
- Явно память задаёт `recreate_group --memory`: [`recreate_group.py:112`](/home/pakar/igor/remlab/tools/scout/salad/recreate_group.py:112), подмена в теле — [`recreate_group.py:135`](/home/pakar/igor/remlab/tools/scout/salad/recreate_group.py:135), stop/delete/POST/проверка — [`recreate_group.py:158`](/home/pakar/igor/remlab/tools/scout/salad/recreate_group.py:158).
- `restart_policy` наследуется, обычно `always`: [`migrate_groups.py:110`](/home/pakar/igor/remlab/tools/scout/salad/migrate_groups.py:110). Поэтому OOM процесса правдоподобно выглядит как закрытие HTTP, затем SSH и рестарт.
- `migrate_groups.py --apply` сейчас не использовать: его `DONOR/NEW/DROP` — исторический состав [`migrate_groups.py:45`](/home/pakar/igor/remlab/tools/scout/salad/migrate_groups.py:45). Для канарейки — отдельное имя и `recreate_group --create-only`.

Salad считает `memory` точным ресурсным ограничением при проверке доступности; `32768` должно исключить узел, неспособный выделить контейнеру 32 768 MB. Но это может исключить и часть номинальных 32-ГБ ПК из-за доступной, а не паспортной памяти — сначала запросить availability для точных GPU/CPU/RAM. [Официальный preflight Salad](https://docs.salad.com/agents/container-engine/discover-scope-and-preflight), [описание requested RAM](https://docs.salad.com/container-engine/explanation/container-groups/resource-utilization).

2. Что означает `mid_generation`

- Класс выставляется, если в эхо SSH встретилось `RLPY` или `/generate`: [`node_health.py:72`](/home/pakar/igor/remlab/tools/scout/salad/node_health.py:72). Эти строки уже содержатся в посланном shell-скрипте [`ssh_run.py:377`](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:377). Поэтому название переоценивает доказательство: команда дошла до терминала, но принятие задания воркером не подтверждено.
- Любой `transport_failed` объявляется виной ноды: [`node_health.py:93`](/home/pakar/igor/remlab/tools/scout/salad/node_health.py:93). OOM, рестарт контейнера, потеря узла и обрыв SSH не различаются.
- В журнал попадает только 200-символьный хвост ошибки: [`ssh_run.py:940`](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:940).
- Воркер возвращает traceback только если сам остался жив: [`worker.py:273`](/home/pakar/igor/remlab/tools/scout/salad/worker.py:273). При убийстве OOM ответа не будет. Пики RAM также попадают только в успешный результат: [`pipeline.py:584`](/home/pakar/igor/remlab/tools/scout/salad/pipeline.py:584), [`pipeline.py:654`](/home/pakar/igor/remlab/tools/scout/salad/pipeline.py:654).

Гипотеза OOM сильная: уже измерен пик процесса 23,4 ГБ при лимите группы 24 ГБ, без учёта остальных процессов и cgroup overhead. Кроме того, код сам фиксирует прежний пик 25,8 ГБ: [`pipeline.py:20`](/home/pakar/igor/remlab/tools/scout/salad/pipeline.py:20). Но формально это ещё не доказательство ночных 50 обрывов.

3. Что можно измерить без нового образа

- При доступном cgroup v2 — да: `memory.max/current/peak`, `memory.events.local` и `memory.stat`. Текущий `mem_probe.py` уже читает первые три, но не events: [`mem_probe.py:28`](/home/pakar/igor/remlab/tools/scout/salad/mem_probe.py:28).
- Снимать надо дельту `oom/oom_kill/max` и поток `current/peak` каждые 1–2 секунды во внешний журнал: после рестарта старый cgroup исчезнет. Семантика счётчиков описана в [документации ядра Linux](https://cdn.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html).
- Доступ не гарантирован: на замере 22.10 cgroup-файлы внутри Salad уже были невидимы. Поэтому сначала проверить `/proc/self/cgroup`, тип mount `/sys/fs/cgroup`; предусмотреть v1 `memory.max_usage_in_bytes`/`memory.failcnt`.
- `dmesg` — лишь best effort: root контейнера обычно не имеет host `CAP_SYSLOG`; при `dmesg_restrict=1` чтение запрещено. [Документация ядра](https://docs.kernel.org/admin-guide/sysctl/kernel.html).
- В API инстанса прямого счётчика рестартов нет. Нужны `query_log_entries` за окно инцидента и события `Instance Restarted`, `Instance Exited:137`, `Interrupted (Priority/Node Offline)`. Salad отдельно предупреждает, что 137 — вероятный, но не безусловный OOM. [System Events](https://docs.salad.com/container-engine/explanation/container-groups/system-events).

4. Отклонённые машины

Ваше исправление нужно, но с ограничителем:

- Сейчас слот списывается до API-вызова [`node_health.py:240`](/home/pakar/igor/remlab/tools/scout/salad/node_health.py:240), а любой 404 попадает в общий `False` [`node_health.py:250`](/home/pakar/igor/remlab/tools/scout/salad/node_health.py:250).
- RAM-reject использует тот же лимит и кладётся в `mem_low`: [`ssh_run.py:1013`](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:1013); супервизор сначала удаляет запись, потом вызывает API [`ssh_run.py:1086`](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:1086).

Исправление:

- Только `reason=ram` пересаживать сразу, вне общего 6/ч.
- 404 трактовать как «старый инстанс уже исчез, задача завершена»; слот не списывать.
- Для обычных пересадок — reservation с возвратом при любом ответе, кроме принятого `202`.
- Не делать бесконечную цепь: максимум 1–2 RAM-пересадки на реплику, затем пауза/остановка канарейки. Reallocate обещает другой Salad Node, но текущий код выбрасывает `machine_id` в [`ssh_run.py:116`](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:116), поэтому повтор физической машины не обнаружит. Нужно сохранять `machine_id` и TTL denylist. Долговременное решение — именно `memory=32768`, а не чехарда.

5. Порядок действий

До подъёма:

1. Бесплатно запросить события 23→24.10 по 50 `instance` и времени из журнала. Если есть корреляция `mid_generation → Exited:137/Restarted`, повторять 24-ГБ аварию не нужно.
2. Исправить RAM-reallocate/404 и добавить потоковую память плюс запись `machine_id/update_time`.
3. Проверить availability для RTX 4060 Ti + `memory=32768`.
4. Создать отдельную канарейку на 2 реплики, не трогая боевую группу.

По первому часу:

- `oom_kill>0`, `events.max` растёт или есть 137 при пике у `memory.max` → пересоздать канарейку с `32768`.
- При 32 ГБ пик выше ~85% лимита или остаются OOM → включить уже готовый `STAGE_PROC=1` [`pipeline.py:20`](/home/pakar/igor/remlab/tools/scout/salad/pipeline.py:20); дочерняя стадия при убийстве даст диагностируемую ошибку [`pipeline.py:86`](/home/pakar/igor/remlab/tools/scout/salad/pipeline.py:86).
- `Interrupted Priority/Node Offline` → память не лечит; причина Salad/тарифа.
- Инстанс и uptime не меняются, OOM/exit нет → искать SSH-шлюз/сеть.
- Не поднимать 30 реплик, пока нет нулевых OOM, запаса памяти и резкого падения `mid_generation`.

И экономический стоп: даже вычтя верхние 360 ₽ простоя RAM, остаётся `356/106 = 3,36 ₽/меш`. Значит эти две правки необходимы, но без устранения остального оплаченного простоя потолок 1,5 ₽ ещё не достигнут.