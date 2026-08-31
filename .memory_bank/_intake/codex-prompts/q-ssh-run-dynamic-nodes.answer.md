## 1. Вывод

Нужен не периодический повтор `warm_ports()`, а долгоживущий супервизор двух состояний:

- реестр нод: `candidate → probing → active → suspect/dead → cooldown`;
- реестр заданий: `pending → inflight → terminal` либо `retry_wait → pending`.

Одна активная нода — один worker и одно задание одновременно. Новые инстансы обнаруживаются весь прогон и подключаются, пока остаются `pending`. При транспортном сбое задание не считается выполненным, нода выводится из пула, задание после безопасной задержки возвращается в очередь.

Простой «раз в минуту вызвать `warm_ports()` и добавить потоки» недостаточен: он сохраняет потерю заданий, риск двойной генерации и гонки при публикации.

Текущий живой прогон безопасно расширить нельзя: промежуточного реестра `pending/inflight` нет. Второй `ssh_run` с тем же файлом может одновременно запустить тот же текущий job. Лучше дать ему закончиться; исправление применить к следующей волне.

## 2. Доказательства из кода

Критические дефекты:

1. `warm_ports()` вызывается только один раз перед созданием очереди: [ssh_run.py:191](</home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:191>), [ssh_run.py:223](</home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:223>).

2. При `transport_failed` job записывается как результат и не возвращается в очередь: [ssh_run.py:208](</home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:208>), [ssh_run.py:214](</home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:214>).

3. Мёртвая нода продолжает брать следующие задания и может быстро превратить весь хвост в `transport_failed`: цикл не выводит worker из эксплуатации после ошибки транспорта — [ssh_run.py:208](</home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:208>).

4. `ssh_run` всё равно выходит с кодом 0: после отчёта нет проверки неполных/транспортных результатов — [ssh_run.py:229](</home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:229>).

5. Поэтому `batch_show` безусловно увеличивает `done` на размер пачки: [batch_show.py:137](</home/pakar/igor/remlab/tools/scout/salad/batch_show.py:137>), [batch_show.py:154](</home/pakar/igor/remlab/tools/scout/salad/batch_show.py:154>). Это уже фактическая потеря заданий, а не только проблема масштабирования.

6. Результаты сохраняются только после завершения всех потоков: [ssh_run.py:229](</home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:229>). Падение процесса стирает знание о выполненном и `inflight`.

7. Идемпотентность действует только после появления `complete.json`: [receiver.py:99](</home/pakar/igor/remlab/tools/scout/salad/receiver.py:99>), [receiver.py:179](</home/pakar/igor/remlab/tools/scout/salad/receiver.py:179>). Атомарного `claim/lease` до GPU нет. Две одновременные попытки одного prefix обе начнут генерацию.

8. Публикация одного prefix двумя нодами не защищена общей блокировкой: `_lock` используется при проверке места в PUT, но не вокруг финализации staging — [receiver.py:121](</home/pakar/igor/remlab/tools/scout/salad/receiver.py:121>), [receiver.py:151](</home/pakar/igor/remlab/tools/scout/salad/receiver.py:151>).

9. `batch_show.sh()` не ловит `TimeoutExpired`: [batch_show.py:25](</home/pakar/igor/remlab/tools/scout/salad/batch_show.py:25>). `finale()` не находится в `finally`, поэтому исключение способно оставить группу тарифицироваться: [batch_show.py:171](</home/pakar/igor/remlab/tools/scout/salad/batch_show.py:171>), [batch_show.py:207](</home/pakar/igor/remlab/tools/scout/salad/batch_show.py:207>).

## 3. Рекомендуемое устройство

### Супервизор нод

- API discovery каждые 20–30 секунд.
- Идентичность: `(group, instance.id)`, не один `ssh_port`; порт может быть переиспользован.
- SSH `/health` только для новой ноды или после cooldown, не для всех активных нод каждый цикл.
- Не более одного worker на instance.
- После `transport_failed` worker прекращает брать задания; нода становится `suspect`, повторная health-проба через 30–60 секунд.
- Сбой API не удаляет уже работающие ноды из реестра.

`warm_ports()` в нынешнем виде нельзя вызывать целиком при каждом poll: десять последовательных проб × 50 секунд могут занять до 500 секунд.

### Ограничение SSH-стартов

Нужен единый rate limiter начала всех SSH-сессий — health и generate, например минимум 5 секунд между стартами. Замок не должен удерживаться на протяжении двухминутной генерации.

Сейчас health защищён `_ssh_gate`, а `run_job` — нет; динамический poll добавит новые столкновения с рабочими SSH-сессиями.

### Жизненный цикл job

- `transport_failed` → `retry_wait`, а не terminal.
- Максимум, например, 3 транспортные попытки и минимум 2 разных instance ID.
- Между неопределённым обрывом и повтором — grace 60–120 секунд.
- Содержательные ответы `bad_cutout`, `flat_shape`, `slab_suspect`, `input_failed`, `failed`, `not_generator_eligible` — terminal attempt; их лечит другой слой.
- Worker ждёт через blocking queue/condition, а не выходит немедленно по `get_nowait()`: иначе он может завершиться за мгновение до возврата job из `retry_wait`.

Завершение: все исходные job имеют terminal response, `pending/retry_wait/inflight` пусты. Появившуюся после этого ноду ждать не требуется.

### Защита от двойной генерации

Нужен атомарный lease на стороне receiver:

- `POST /claim/<job-prefix>` → acquired / already_complete / in_progress;
- lease имеет owner и TTL больше максимальной shape+paint генерации;
- `/complete` атомарно завершает lease;
- повтор после TTL может его перехватить.

Без этого ретрай после оборванного SSH остаётся at-least-once и может параллельно сжечь две GPU-генерации.

### Прогресс и exit code

После каждой попытки писать атомарный checkpoint или append-only JSONL: client job key, node ID, attempt, status, timestamp. Финальный `mesh-pilot-results.json` — только сводка.

Контракт CLI:

- `0`: каждый входной job получил terminal response;
- отдельный код временного отсутствия capacity, например `75`;
- ненулевой код: остались unresolved transport jobs либо внутренняя ошибка.

`batch_show` должен двигать `done` только по машинно читаемому `terminal_count == requested_count`, а не по самому коду 0 или тексту stdout.

## 4. Риски и легко пропускаемые случаи

- Оборвался только ответ, а GPU продолжает работу: немедленный retry создаёт дубликат.
- Порт Salad переиспользован новым instance: реестр по одному порту отправит job не той ноде.
- Нода умерла после публикации, но до RLEND: результат уже готов; повтор должен получить `cached`.
- Очередь временно пуста, потому что всё `inflight`: workers не должны завершаться до общего terminal condition.
- Несколько групп могут вернуть повторяющийся порт — нужна дедупликация по instance ID.
- `started=true`, но `ssh_port` отсутствует: сейчас значение не проверяется.
- `cull_slow_pulls()` исполняется только пока `batch_show` не заблокирован внутри `ssh_run`. При живой одной ноде остальные девять зависших downloads не будут пересаживаться. Эту логику нужно перенести в общий capacity-supervisor.
- Расчёт стоимости в `ssh_run` использует GPU-seconds, хотя Salad тарифицирует всё время `running`: [ssh_run.py:240](</home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:240>). После динамического подключения отчёт ещё сильнее занизит фактическую стоимость.
- После timeout/исключения `batch_show` группы могут остаться включёнными. Нужен `try/finally` вокруг всего прогона.
- В `heal_wave` иной ненулевой код просто прерывает retry-цикл, после чего всё равно запускаются drain/repair/gallery: [batch_show.py:185](</home/pakar/igor/remlab/tools/scout/salad/batch_show.py:185>). Ошибка должна останавливать волну явно.

## 5. Альтернативы

1. **Минимальный poll + новые threads.** Быстро внедрить, но без job states, lease и checkpoint он опасен. Не рекомендую как финальное решение.

2. **Запуск второго `ssh_run` для поздних нод.** Сейчас неприемлем: нет общей очереди и видимого `inflight`, возможны дубликаты.

3. **Короткие волны по 5–10 заданий.** Подхватывают новые ноды между волнами, но не внутри длинной healing wave и увеличивают orchestration overhead.

4. **Центральная pull-очередь: ноды сами берут job через HTTPS.** Архитектурно лучше всего: leases, heartbeat и динамические ноды возникают естественно, SSH нужен только для диагностики. Но это более крупная переделка receiver/worker и требует аутентификации очереди. Для production после пилота это предпочтительное направление.

## 6. Приоритет правок

Сейчас, до следующего прогона:

1. Не продвигать `done` при `transport_failed`; возвращать job в очередь и выводить ноду из пула.
2. Динамический node supervisor с discovery и единым SSH launch limiter.
3. Промежуточный checkpoint после каждого job.
4. Корректные exit codes и проверка terminal count в `batch_show`.
5. `try/finally` для гарантированного `stop_group()`.

Следующим шагом:

6. Receiver-side claim/lease и синхронизация публикации одного prefix.
7. Общий capacity-модуль для discovery и `cull_slow_pulls`.
8. Учёт фактически оплаченного времени нод, а не только GPU-seconds.

## 7. Допущения и что изменило бы вывод

Вывод предполагает, что:

- обрыв SSH не гарантирует отмену `/generate`;
- Salad сохраняет стабильный `instance.id` в течение жизни ноды;
- receiver доступен нодам до начала генерации и может выполнять claim;
- одна нода безопасно обслуживает только один GPU-job одновременно.

Вывод изменился бы, если Salad гарантирует отмену серверной генерации при разрыве SSH либо уже предоставляет атомарные job leases/managed queue. Также нужен фактический пример JSON `/instances`: без него нельзя окончательно выбрать поля идентичности и переходы состояний.