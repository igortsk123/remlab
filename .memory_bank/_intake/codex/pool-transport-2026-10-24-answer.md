Короткий вывод: направление «убрать SSH из data plane» верное, но диагноз «точно Salad/NAT» пока преждевременен — сначала надо исключить одну локальную ошибку.

### 1. Что именно сломано в SSH

- API возвращает пару `ssh_ip` + `ssh_port`, а текущий код игнорирует `ssh_ip`: один адрес жёстко задан в [`ssh_run.py:35`](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:35), из API сохраняется только порт в [`ssh_run.py:116`](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:116). Официальная схема инстанса содержит `ssh_ip`, `ssh_port`, fingerprint и `machine_id`; Portal тоже показывает команду с `<hostname> -p <port>`. Поэтому первым делом нужно сравнить `ssh_ip` отвечавших и молчавших машин и всегда использовать адрес из того же ответа API, что и порт. [List Container Group Instances](https://docs.salad.com/reference/saladcloud-api/container-groups/list-container-group-instances), [SSH & Terminal Access](https://docs.salad.com/container-engine/explanation/container-groups/ssh-and-terminal).

- Если `ssh_ip` у всех действительно был `195.181.163.241`, данные очень сильно указывают на дефект terminal/control path Salad, привязанный к физической машине. Но говорить именно о NAT нельзя: внутренняя схема SSH-туннеля в документации не раскрыта. Salad прямо признаёт узлы без terminal access и советует reallocate на другой node. [Troubleshooting: Web Terminal / SSH](https://docs.salad.com/container-engine/how-to-guides/troubleshooting).

- Признака `terminal_available` в документированном API нет. Наличие `ssh_port` означает, что endpoint выдан, но не доказывает его работоспособность; endpoint вообще может появиться позже состояния Running. `ready` — состояние workload probe, не SSH. Поэтому надёжно отсеять такие машины до начала тарификации нельзя. [SSH & Terminal Access](https://docs.salad.com/container-engine/explanation/container-groups/ssh-and-terminal).

- Временное лечение разумно, но одного `MESH_SILENT_ZOMBIE_S=240` мало:

  - сейчас порог 600 с — [`ssh_run.py:168`](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:168);
  - `machine_id` выбрасывается при чтении API — [`ssh_run.py:116`](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:116);
  - карантин ключуется по `group/instance_id`, а не физической машине — [`ssh_run.py:1099`](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:1099);
  - при ≥50% одинаково молчащих узлов пересадка специально отменяется — [`ssh_run.py:1128`](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:1128);
  - общий лимит пересадок всего 6/ч — [`node_health.py:24`](/home/pakar/igor/remlab/tools/scout/salad/node_health.py:24).

  Для временного SSH-режима: фактическая пара `ssh_ip:ssh_port`, 240 с и ≥2 последовательные пробы, карантин `machine_id` хотя бы на сутки/волну; `нет ответа по SSH` исключить из правила «общая беда», оставив отдельный ограниченный бюджет пересадок.

### 2. Чем заменить транспорт

| Вариант | Оценка |
|---|---|
| **Salad Job Queues** | **Рекомендую первым** |
| Свой pull по HTTPS | Запасной вариант, больше своего кода |
| Container Gateway | Для нынешней генерации не подходит |

**Salad Job Queues.** Queue Worker работает внутри контейнера, получает задание и передаёт JSON на заданные `port/path`; текущий `/generate` уже соответствует этому контракту — [`worker.py:156`](/home/pakar/igor/remlab/tools/scout/salad/worker.py:156). Результаты-файлы по-прежнему уходят прямо в существующий sink, а Job Queue получает только маленький JSON-ответ.

Важная находка: прежний неудачный опыт в [`submit.py:4`](/home/pakar/igor/remlab/tools/scout/salad/submit.py:4) полностью согласуется с нынешней документацией — queue connection задаётся **только при создании новой container group**; PATCH существующей группы её не добавляет. [Creating a Job Queue](https://docs.salad.com/container-engine/how-to-guides/job-processing/creating-a-job-queue), [Job Queues](https://docs.salad.com/container-engine/explanation/job-processing/job-queues).

Без пересборки образа возможно: новая группа получает `command`, который скачивает фиксированную версию `salad-http-job-queue-worker`, проверяет SHA-256 и запускает его рядом с `python -u /app/worker.py`. В образе уже есть `wget` и Python — [`Dockerfile:55`](/home/pakar/igor/remlab/tools/scout/salad/Dockerfile:55), исходный CMD — [`Dockerfile:146`](/home/pakar/igor/remlab/tools/scout/salad/Dockerfile:146). Salad допускает расширенный entrypoint, но `command` полностью заменяет Docker CMD/ENTRYPOINT, поэтому нужен аккуратный supervisor/`wait -n`. [Job Queue Worker](https://docs.salad.com/container-engine/how-to-guides/job-processing/queue-worker), [Specifying a command](https://docs.salad.com/container-engine/how-to-guides/specifying-a-command).

Настройки группы:

- `queue_connection`: port `8000`, path `/generate`;
- readiness probe: **`/ready`**, не `/health`: `/health` всегда 200 даже во время прогрева — [`worker.py:49`](/home/pakar/igor/remlab/tools/scout/salad/worker.py:49), `/ready` честно отдаёт 503 — [`worker.py:65`](/home/pakar/igor/remlab/tools/scout/salad/worker.py:65);
- использовать новый group, не `migrate_groups.py` как есть: его body сейчас вообще не переносит `queue_connection` — [`migrate_groups.py:94`](/home/pakar/igor/remlab/tools/scout/salad/migrate_groups.py:94).

Ограничения Queue:

- 3 ретрая, то есть 4 попытки; без backoff, иногда на том же инстансе;
- interruption обнаруживается после истечения lease, несколько минут;
- ответ ≤10 MB;
- отмена не останавливает уже начатую работу;
- точного максимума входного JSON и времени job документация не публикует; «очень длинные» задачи прямо названы плохим случаем. Ваш вход маленький, ответ маленький, но реальное время генерации обязательно проверить canary. [Job Queue limits](https://docs.salad.com/container-engine/explanation/job-processing/job-queues), [job statuses](https://docs.salad.com/container-engine/how-to-guides/job-processing/using-queues).

Ещё одна оговорка: `worker.py` возвращает HTTP 200 даже при логическом `status:"failed"` — [`worker.py:273`](/home/pakar/igor/remlab/tools/scout/salad/worker.py:273). Queue сочтёт такую попытку успешной. Поэтому collector обязан разбирать `output.status` и переносить `failed/input_failed` в нынешнюю политику повторов; автоматическим ретраям Salad доверять только для транспортного обрыва. Идемпотентность уже есть через `job_id` и `complete.json` — [`worker.py:193`](/home/pakar/igor/remlab/tools/scout/salad/worker.py:193).

Отдельная цена Job Queue публично не указана. Документация тарифицирует работающие container instances посекундно; allocation/download/start бесплатны. Не стоит утверждать, что сама Queue гарантированно бесплатна без подтверждения Salad, но отдельного тарифа в документации нет. [SCE Billing](https://docs.salad.com/container-engine/explanation/billing-pricing/billing).

**Свой pull.** Технически также можно без rebuild: startup command запускает текущий worker и скачанный poller. Но queue endpoint должен быть публичным HTTPS с lease/ack/visibility-timeout и идемпотентной выдачей:

- DEV за NAT непосредственно не подходит;
- tunnel до DEV добавит ещё одну транспортную зависимость;
- exit-fi использовать не следует: это публичный транзитный sink рядом с VPN, что уже зафиксировано в [`drain.sh:2`](/home/pakar/igor/remlab/tools/scout/salad/drain.sh:2);
- значит нужен отдельный маленький VPS/managed queue. По надёжности и объёму изменений это второй вариант после Salad Queue.

**Container Gateway.** Это групповой inbound load balancer, не адресация конкретного инстанса. Есть round-robin/least-connections и режим один активный запрос на instance, но server response timeout максимум 100 секунд; ваши вызовы допускают до 1100 секунд — [`ssh_run.py:374`](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:374). Кроме того, этот путь уже давал 503 — [`ssh_run.py:1`](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:1). [Container Gateway networking](https://docs.salad.com/container-engine/explanation/infrastructure-platform/networking), [timeouts/load balancing](https://docs.salad.com/container-engine/explanation/gateway/load-balancer-options). Его исключаю.

### 3. Минимальная безопасная проверка

1. **Бесплатно, без инстанса:**

   - добавить тест на сохранение и использование пары `ssh_ip:ssh_port`;
   - подготовить отдельные `queue-canary` и `mesh-queue-canary` с `autostart=false`;
   - создать очередь и остановленную новую группу, затем GET-проверкой убедиться, что `queue_connection` реально записана;
   - положить одно тестовое job: оно должно остаться `pending`;
   - локально проверить startup-wrapper, checksum и остановку обоих процессов. Сам Queue Worker локально не заработает: он зависит от Salad IMDS, это документированное ограничение. [Job Queue Worker](https://docs.salad.com/container-engine/how-to-guides/job-processing/queue-worker).

2. **Короткий платный canary:**

   - сначала существующий `sink_health`/canary;
   - старт одной реплики;
   - одно уже идемпотентное реальное задание;
   - критерий: `pending → running → succeeded`, `output.status in {ok,cached}`, `complete.json` появился в sink, SSH ни разу не использовался;
   - немедленно stop; затем один reallocate и повтор на второй физической машине.

Итого: **целевой транспорт — Salad Job Queues через новую группу; временно — исправить `ssh_ip`, затем 240-секундный machine-level quarantine.** Container Gateway исключить, свой pull оставить планом B.