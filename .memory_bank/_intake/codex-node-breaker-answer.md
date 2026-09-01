## Вывод

Корень — не отсутствие счётчика «3 сбоя», а неверная модель результата. Сейчас `input_failed` смешивает мёртвое фото, 404, сетевую неисправность ноды и ошибку препроцессинга, но `ssh_run` считает всё это терминальным успехом транспорта. Простое `NODE_FAULT_STATUSES={'input_failed'}` начнёт переаллоцировать здоровые ноды на трёх подряд 404.

Нужно разделить два измерения:

- `disposition`: `success | terminal_job | retryable`;
- `fault_scope`: `job | node | shared_infra | code | unknown`.

После этого: retryable-задание немедленно возвращается в очередь; только три последовательных `fault_scope=node` переаллоцируют инстанс.

## 1. Что происходит сейчас

| Статус | Источник | Текущее поведение | Вердикт |
|---|---|---|---|
| `ok`, `cached` | успешная генерация/кэш | Терминален, курсор идёт | Правильно |
| `transport_failed` | SSH timeout, нет маркера | Повтор до 3 раз, воркер ноды выходит; после исчерпания — `unresolved`, курсор останавливается | В целом правильно |
| `input_failed` | любое исключение `PRE.prepare()` | Считается терминальным; нода продолжает работу; курсор идёт | Главный дефект |
| `bad_cutout` | явный `PRE.BadCutout` | Терминален, но отдельного долговечного вердикта здесь нет | Товарный дефект, но нужен durable record |
| `flat_shape`, `slab_suspect` | shape-gate | Терминальны; публикуется shape-манифест; `apply_repairs` создаёт seed+1 | Правильно |
| `failed` | любое исключение генерации или публикации | Терминален, курсор идёт, результата обычно нет | Второй дефект |
| `not_generator_eligible` | защита стратегии | Терминален | Правильно |

Причина: единственный критерий в `worker()` — `status != transport_failed` в [ssh_run.py:382](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:382). `Jobs.done()` фиксирует любой такой ответ как результат в [ssh_run.py:300](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:300), а `summary()` считает дыркой только буквальный `transport_failed` в [ssh_run.py:337](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:337).

После этого `batch_show` двигает `done` на `terminal_prefix` в [batch_show.py:277](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:277).

У `transport_failed` уже есть:

- выбор другой ноды через `tried` — [ssh_run.py:278](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:278);
- до трёх попыток — [ssh_run.py:300](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:300);
- вывод ноды из локального пула после первой транспортной ошибки — [ssh_run.py:404](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:404).

Но это только 60-секундный cooldown, не Salad `reallocate`.

## 2. Задания действительно теряются

`input_failed` возникает до создания `jid`, манифеста и рабочего комплекта — [worker.py:150](/home/pakar/igor/remlab/tools/scout/salad/worker.py:150). `apply_repairs` сканирует только уже скачанные `manifest.json` — [apply_repairs.py:144](/home/pakar/igor/remlab/tools/scout/salad/apply_repairs.py:144). Следовательно, он физически не может обнаружить такой отказ.

По текущим артефактам:

- в последней основной пачке из 30 заданий было ровно 6 `input_failed`;
- курсор всё равно перешёл `245 → 275`;
- ни одна из шести пар `(sku, seed)` не находится в [mesh-reseed.json](/home/pakar/igor/remlab/tools/scout/mesh-reseed.json).

То есть шесть конкретных ревизий последней пачки потеряны однозначно.

За весь [mesh-run-progress.jsonl](/home/pakar/igor/remlab/tools/scout/mesh-run-progress.jsonl):

- 43 строки `input_failed`, 39 уникальных SKU;
- 30 строк принадлежат `35b10e39`;
- 15 попыток позже сопровождались `ok/cached`;
- у 28 строк, 27 уникальных SKU, более позднего успеха нет;
- 9 уникальных SKU не имеют вообще никакого локального манифеста.

Утверждение «потеряны ровно все 30 SKU» недоказуемо. Журнал не пишет `seed`, `job_key`, индекс задания и полный instance id — [ssh_run.py:391](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:391). Часть SKU имела другие seed или прежние результаты.

`mesh-reseed.json` — неправильное место для таких повторов: reseed означает «получили геометрию, меняем seed». Сетевой отказ надо повторять с тем же job key и seed. В проекте уже есть подходящее состояние `mesh_jobs.retry_wait` — [mesh_queue.py:69](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:69).

### Ещё одна независимая потеря

`batch_show` считает `total=len(raw jobs)=1465` — [batch_show.py:242](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:242). Но `ssh_run` разворачивает seeds и потом фильтрует роли — [ssh_run.py:225](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:225).

Фактический размер:

- 1515 заданий после разворачивания seeds;
- 1503 после исключения 12 ковров;
- `batch_show` завершится на 1465.

Значит последние 38 mesh-eligible заданий вообще не будут запрошены. `total`, `skip` и `limit` обязаны вычисляться из одного канонического плоского списка.

## 3. Правильный node breaker

### Контракт результата

Воркер должен возвращать структурированно:

```json
{
  "status": "input_failed",
  "phase": "fetch",
  "disposition": "retryable",
  "fault_scope": "node",
  "error_code": "enetunreach"
}
```

Минимальная классификация:

- `HTTP 404/410` → `terminal_job`, `job`;
- битое изображение/неподдерживаемый формат → `terminal_job`, `job`;
- `ENETUNREACH`, `EHOSTUNREACH`, временный DNS → `retryable`, вероятно `node`;
- timeout, SSL EOF, HTTP 429/5xx → `retryable`, но первоначально `unknown/shared_infra`, не автоматически node;
- `bad_cutout` → `terminal_job`, `job`;
- `flat_shape`, `slab_suspect` → `terminal_job`, `job`;
- sink `507` → `retryable`, `shared_infra`, с запуском drain;
- sink `401/403` → `shared_infra/code`, остановить волну;
- CUDA OOM → `retryable`, но сначала другая нода; виновность зависит от GPU и повторяемости SKU;
- произвольный `failed` нельзя классифицировать одним статусом.

Сейчас все четыре `failed` в журнале — `ValueError: пустой файл: source.jpg`. Комментарий называет повторную загрузку source «best-effort» — [worker.py:178](/home/pakar/igor/remlab/tools/scout/salad/worker.py:178), но пустой файл затем включается в комплект — [worker.py:212](/home/pakar/igor/remlab/tools/scout/salad/worker.py:212), а storage отклоняет его — [storage.py:30](/home/pakar/igor/remlab/tools/scout/salad/storage.py:30). Это дефект кода, не основание снимать ноду.

### Счётчик

На каждый полный `(group, instance_id)`:

1. `node_fault` → задание requeue, `streak += 1`.
2. `ok/cached` либо доказательство успешной работы ноды (`bad_cutout`, `flat_shape`, честный 404) → `streak = 0`.
3. При `streak == 3`:
   - пометить ноду `retired` под `nodes_lock`;
   - вернуть текущее задание в очередь;
   - отпустить lock;
   - вызвать Salad `reallocate`;
   - завершить поток ноды.

API нельзя вызывать под `nodes_lock`: это до 30 секунд сети и заблокирует supervisor. Также нельзя одновременно держать `Jobs.cv` и `nodes_lock`; текущий порядок раздельный, его надо сохранить.

Состояния в `nodes` достаточно только внутри одного `ssh_run`. Между пачками запускается новый процесс, поэтому серия `2+2+2` никогда не достигнет трёх. Нужен либо:

- один долгоживущий `ssh_run` на всю волну — предпочтительно;
- либо долговечный `node_health`/event log с `instance_id`, `machine_id`, временем, классом ошибки и TTL.

Текущий прогресс с восьмизначным id для этого недостаточен.

### Предохранители

- Общий бюджет с медленными downloads: не более 2 пересадок за тик и 6/час.
- Бюджет должен быть межпроцессным. `_CULL_LOG` сейчас живёт только в памяти конкретного процесса — [batch_show.py:99](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:99); родитель `batch_show` и дочерний `ssh_run` имеют разные журналы.
- Если одинаковый сетевой класс появился на ≥3 разных нодах или более чем на половине тёплого пула за 5 минут — открыть fleet circuit, приостановить раздачу, не переаллоцировать весь парк.
- После первого сетевого сбоя полезен дешёвый egress-canary к контролируемому URL. Он отличит неисправность ноды от падения конкретного CDN.
- Старый instance помечать `retired`, иначе supervisor через минуту снова подключит его.
- Проверить отдельно, что endpoint `reallocate` разрешён для `running`: текущий код вызывает его только для `state=downloading` — [batch_show.py:193](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:193).

## 4. Гонки и краевые случаи

- После reallocate новый образ обычно греется 25–35 минут, а `STALL_S=1800`. `wait_all()` может объявить остаток нерешённым ровно перед прогревом замены — [ssh_run.py:314](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:314). Активность supervisor/состояние `downloading` должны обновлять таймер ожидания либо приводить к контролируемому `EXIT_NO_CAPACITY`.
- При SSH timeout удалённая генерация может продолжаться. Немедленный retry способен запустить тот же job параллельно. `complete.json` предотвращает повтор только после завершения, но не даёт in-flight lease.
- `warmup()` записывает `warm=True` даже при `warmup_error` — [worker.py:102](/home/pakar/igor/remlab/tools/scout/salad/worker.py:102). `probe_warm` такую ноду примет. Фатальная ошибка прогрева должна делать её dispatch-ineligible.
- Счётчик `closed` увеличивается на каждую попытку, поэтому лог показывает `[256/252]`; это число попыток, не завершённых заданий.
- Терминальный товарный отказ можно пропускать курсором только после долговечной записи причины. Иначе `bad_cutout` тоже исчезает молча, хотя это уже не потеря GPU-задачи, а потеря диагностики.

## 5. Простой и OOM постобработки

Сейчас курсор записывается до постобработки, затем семь команд идут синхронно — [batch_show.py:287](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:287). Их ненулевой код только печатается, цикл продолжает работу — [batch_show.py:289](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:289). Поэтому одновременно:

- оплачиваемые ноды стоят;
- локальные шаги не заканчиваются;
- durable backlog постобработки отсутствует.

Системный порядок:

1. Один непрерывный удалённый producer генерирует задания.
2. Отдельный локальный consumer периодически забирает только завершённые комплекты.
3. Приёмка, ориентация и top-view имеют собственные курсоры и retry-состояния.
4. Когда удалённая очередь пуста — Salad-группа гасится немедленно; локальная работа продолжается уже бесплатно.

Параллельный drain допустим: receiver публикует `complete.json` строго последним — [receiver.py:167](/home/pakar/igor/remlab/tools/scout/salad/receiver.py:167), а `drain.sh` копирует только такие каталоги — [drain.sh:23](/home/pakar/igor/remlab/tools/scout/salad/drain.sh:23). Нужен один файловый lock на drain/ingest.

Для 11 ГБ RAM:

- `orient_worker --limit 200` снизить сначала до 10–20; он передаёт весь batch одному subprocess — [orient_worker.py:262](/home/pakar/igor/remlab/tools/scout/orient_worker.py:262).
- `topview` начать с одного процесса, не четырёх — [topview_render.py:329](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:329).
- Каждый микробатч запускать отдельным процессом, чтобы память гарантированно вернулась ОС.
- Ограничить consumer через cgroup/systemd `MemoryMax≈3G`; OOM consumer не должен убивать лёгкий SSH-supervisor.
- Ошибка шага должна оставлять запись `pending/retry_wait`, а не просто строку `СБОЙ`.

Останавливать и снова запускать группу между этими шагами хуже: теряется тёплый пул и начинается 25–35-минутная загрузка образа.

## Рекомендованный порядок

1. P0: исправить единую плоскую нумерацию заданий; вернуть шесть точно пропущенных ревизий последней пачки.
2. P0: ввести `disposition/fault_scope/phase/error_code`; `input_failed` больше не терминален автоматически.
3. P0: retryable-результаты писать в существующий `mesh_jobs.retry_wait`, не в `mesh-reseed`.
4. P1: node breaker на три последовательных node-fault с общей долговечной квотой reallocate.
5. P1: добавить тесты: три node-fault; два fault + success; три 404; глобальный timeout; sink 507; исчерпание попыток; рестарт между вторым и третьим fault.
6. P1: отделить удалённую генерацию от локального consumer и ограничить память микробатчей.

Свидетельство, которое изменило бы вывод: если те же `ENETUNREACH/timeout` синхронно наблюдались на большинстве разных нод и разных физических машин, это не дефект `35b10e39`, а общая сеть/CDN — тогда нужен fleet pause без reallocate. Для точного восстановления всех потерянных jobs необходим новый журнал с `run_id`, `job_key`, `seed`, полным instance/machine id и disposition.