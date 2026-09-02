## Вывод

Ваш диагноз по RAM, DINOv2 и агрессивному reallocate в основном верен. Но «25 ГБ образа — корень всего» — неполный вывод. Размер объясняет долгий `downloading`, но не объясняет ноды со статусом Running, `uptime=279 мин`, `done=0`.

Сейчас ещё три системных дефекта:

1. Фатально упавший прогрев оставляет оплачиваемую ноду живой, но оркестратор её никогда не использует.
2. Прогретые ноды ищутся последовательными SSH-пробами до 50 секунд каждая.
3. `batch_show` по умолчанию всё ещё выдаёт только 5 заданий, хотя реплик заявлено 10.

## P0 — что исправлять первым

### 1. Убрать «живые зомби» после провала прогрева

`warmup()` ловит любое исключение, записывает `warmup_error`, но в `finally` всё равно выставляет `warm=true` — [worker.py](/home/pakar/igor/remlab/tools/scout/salad/worker.py:75). `/health` всегда отвечает 200 — [worker.py](/home/pakar/igor/remlab/tools/scout/salad/worker.py:43). Наш `probe_warm()` такую ноду правильно отвергает — [ssh_run.py](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:145), но Salad продолжает считать её Running, а culler рассматривает только `downloading`.

Это прямой механизм для девяти часов простоя.

Нужны разные состояния:

- `/live`: процесс жив, 200;
- `/ready`: 200 только после успешного полного прогрева;
- фатальный `warmup_error`: нода выводится из пула и переаллоцируется;
- одинаковый `warmup_error` на нескольких нодах: circuit breaker — остановить группу, а не устраивать массовый reallocate.

Salad рекомендует не допускать трафик до прохождения startup/readiness probe. [Startup Probes](https://docs.salad.com/container-engine/explanation/infrastructure-platform/startup-probes)

### 2. Исправить последовательное обнаружение нод

`warm_ports()` последовательно вызывает `probe_warm()` для каждой ноды — [ssh_run.py](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:164), а одна проба имеет timeout 50 секунд — [ssh_run.py](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:125).

Девять неготовых инстансов могут задержать запуск единственной готовой ноды на 7,5 минуты при каждом новом `ssh_run`. То же происходит в супервизоре.

Минимум:

- параллельный bounded probe pool на 3–4 потока;
- кэш последнего вердикта по `instance_id`;
- холодную ноду перепроверять не чаще раза в 2–3 минуты;
- готовую подключать сразу, не дожидаясь проверки остальных.

### 3. Увеличить рабочую волну

Без явного аргумента `batch_show` использует `batch=5` — [batch_show.py](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:435). Даже при 10 тёплых нодах половина останется без задания.

Для постоянной очереди 7414 товаров волна должна быть хотя бы:

```text
batch >= 4–6 × число ожидаемых тёплых нод
```

Для 10 реплик — 50–60 заданий. Постобработка уже вынесена в фон, поэтому прежней причины держать пачку 5 больше нет — [batch_show.py](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:459).

## 1. Чем наполнять пул

Приоритет изменения параметров:

1. Проверить фактически развёрнутую спецификацию.
2. Расширить список совместимых GPU.
3. Убрать избыточные ограничения RAM/диска.
4. Только затем экспериментировать с priority и регионами.

Есть расхождение: в репозитории записано 16 ГБ RAM, 5 реплик, один GPU-класс и 50 ГБ storage — [container-group.json](/home/pakar/igor/remlab/tools/scout/salad/container-group.json:6). Вы описываете 12 ГБ, 10 реплик и список классов. Пока GET фактической группы не сохранён рядом с логом, вы диагностируете не воспроизводимую конфигурацию.

Salad предоставляет API availability именно для сравнения комбинаций GPU/RAM/storage/регионов и отдельно возвращает доступность по уровням priority. Его стоит вызывать перед развёртыванием, а не угадывать. [GPU Availability API](https://docs.salad.com/reference/saladcloud-api/organizations/get-gpu-availability)

Практически:

- Включить все проверенные карты с ≥24 ГБ: 3090, 3090 Ti, 4090, A5000 — если они реально проходят ваш canary.
- Пока нужна ёмкость, не ограничивать страны. Региональные фильтры ускоряют путь до кэша, но уменьшают число подходящих машин.
- RAM держать минимальной только после полного замера `memory.peak` всего задания.
- Не запрашивать лишний диск: это тоже часть фильтра доступности.
- `batch` — самый дешёвый priority, и его могут вытеснять более высокие. High уменьшает прерывания, но не исправит плохой образ или zombie-ready. [Priority Pricing](https://docs.salad.com/container-engine/explanation/billing-pricing/priority-pricing)

Две одинаковые группы по пять не дадут магически больше машин. Они полезны лишь для A/B: разные GPU-классы, priority, регион или версия образа. В проде одна группа проще.

## 2. Выносить ли веса из образа

Нет, стабильные веса Hunyuan и DINO лучше оставить в образе.

Почему:

- `downloading` Salad не тарифицируется; загрузка весов из R2 начнётся уже внутри Running-контейнера и станет оплачиваемым временем. [Billing](https://docs.salad.com/container-engine/explanation/billing-pricing/billing)
- Salad кэширует Docker-слои по сети; для приватных образов это включается `image_caching`, которое у вас уже стоит `true` — [container-group.json](/home/pakar/igor/remlab/tools/scout/salad/container-group.json:27). Кэш может жить до 30 дней, но это не гарантированная привязка к конкретной машине. [Container Registries](https://docs.salad.com/container-engine/explanation/infrastructure-platform/container-registries)
- Провал DINO уже доказал ненадёжность скачивания весов с ноды после запуска.
- После остановки runtime-данные ноды удаляются; постоянного локального тома для R2-кэша нет.

Правильная оптимизация — не вынос весов, а стабильные слои:

```text
CUDA/dependencies
→ Hunyuan weights
→ DINO weights
→ тонкий слой патчей
→ тонкий слой нашего кода
```

Проверьте именно compressed transfer size по manifest, а не размер `docker images`: лимит Salad относится к сжатому образу и сейчас составляет 35 ГБ. [Container Registries](https://docs.salad.com/container-engine/explanation/infrastructure-platform/container-registries)

## 3. Честное правило переаллокации

Фиксированные ступени вроде «5% к двадцатой минуте» для нового digest неверны.

Используйте сравнение ожидаемых времен:

```text
ETA_keep = (1 − progress) / robust_rate
ETA_replace = P50(allocate → ready для того же digest/spec/priority)
```

Пересаживать только если:

```text
ETA_keep > 1.5 × ETA_replace
```

и одновременно:

- нода является выбросом относительно других нод того же digest;
- проблема не fleet-wide;
- работают минимум две другие ноды;
- не пройдено более 80% загрузки;
- есть бюджет максимум 1–2 reallocate за тик и 4–6 в час.

Пока нет хотя бы 10 успешных `allocate → ready` для нового digest, автоматический cull лучше не включать вообще. `pulling_progress` и `creating=99%` приблизительны; Salad прямо предупреждает, что «зависший» creating может продолжать скачивание/распаковку и платформа сама переаллоцирует явных аутсайдеров. [Deployment Lifecycle](https://docs.salad.com/container-engine/explanation/container-groups/deployment-lifecycle)

Текущий `STALL_S=300` слишком короток для 25 ГБ — [batch_show.py](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:153). Пять минут без изменения API-прогресса не доказывают остановку крупного слоя или распаковки.

## 4. Что ещё не закрыто

По приоритету:

- `mmap=True` уменьшает промежуточную копию `torch.load`, но не доказывает, что полный прогрев укладывается в 12 ГБ. При фактическом чтении страницы mmap и page cache могут учитываться cgroup. Нужен `memory.peak` полного `P.generate()`, а не отдельного `torch.load`.
- `/health done=0` означает только отсутствие успешно опубликованных заданий: счётчик увеличивается после `S.publish()` — [worker.py](/home/pakar/igor/remlab/tools/scout/salad/worker.py:235). Это не показатель того, что GPU не использовалась для прогрева.
- Прогрев с `STAGED=1` после себя выгружает обе модели. Поэтому слово «warm» означает «ядра прогнаны», а не «модели остались в VRAM».
- Фото товара всё ещё скачивается с внешнего CDN внутри каждой ноды. После истории с `ENETUNREACH` входы лучше зеркалировать в R2/свой sink до GPU-задания.
- Нужны временные метки: allocated, downloading, creating, running, ready, first_job, warmup stage/error, restart count, image digest, machine_id, GPU, cgroup peak, disk free.
- Стоимость в `ssh_run` захардкожена как тариф 4090 для любых карт — [ssh_run.py](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:39). На наполнение это не влияет, но искажает экономику.

## 5. Оставлять ли `STAGED=1`

На RTX 3090 — пока да.

Суммировать ваши `max_memory_allocated` 8,06 + 13,88 и заключать, что обе модели займут 21,94 ГБ, нельзя:

- это `allocated`, а не `reserved` и не полный NVML-пик;
- одновременно остаются веса, CUDA-контекст, DINO, растеризатор и временные буферы;
- на бытовой 3090 часть VRAM может занимать дисплей;
- апстрим заявляет 29 ГБ для совместного нахождения стадий и 21 ГБ только для paint. [Hunyuan3D 2.1](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1)

`STAGED=0` можно проверить только на одной canary-ноде на 20 разных товарах. Гейт:

- ни одного OOM/restart;
- измерять `max_memory_reserved` и NVML, не только allocated;
- минимум 1,5–2 ГБ свободного пика;
- заметное сокращение wall time, иначе риск бессмысленен.

Лучшее долгосрочное решение для 24 ГБ — не держать обе модели одновременно, а микробатчить стадии:

```text
K товаров shape с одной загруженной shape-моделью
→ выгрузка shape
→ K товаров paint с одной загруженной paint-моделью
```

Это убирает повторную загрузку моделей на каждый SKU, сохраняя VRAM-предел. Для 32-ГБ 5090 можно автоматически использовать `STAGED=0`, для 24-ГБ карт — staged/microbatch.

Главный порядок сейчас: readiness-зомби → параллельные probes → batch 50+ → сверка фактической конфигурации → только потом оптимизация образа и `STAGED`.