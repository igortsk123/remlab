# Рендер Cycles на видеокарте Salad — образ и замер (T-20261117-22)

План: `.memory_bank/plans/photo-render-first-01.md` § «Видеокарта». Здесь — образ рендера Blender, проверка готовности и замер скорости.

## Что где
- `Dockerfile.render` — слои `base` (Ubuntu 22.04 + Blender 5.3.0, как на DEV) → `code` (render_cycles.py, ready_probe.py, bench.py, `data/flat3d/wall-art.json`) → `bench` (две сцены /demo для замера). Боевой образ = цель `code`. Секретов нет.
- `build_render.sh [bench|code]` — сборка, push, гейт по СЖАТОМУ размеру (3 ГБ), digest amd64 в `~/remlab-logs/t22-1117/image-<цель>.digest`.
  Пока образ лежит тегом в уже существующем пакете `ghcr.io/igortsk123/mesh-hunyuan:cycles-5.3.0-<цель>` (токен DEV не может создать НОВЫЙ пакет `render-blender`; меш-группы закреплены по digest и не затронуты).
- `ready_probe.py` — «/ready»: устройство (OptiX → CUDA → CPU, `--require-gpu`) + малый настоящий Cycles-проход с OIDN. Код 3 — GPU не поднялся.
- `bench.py` — внутри контейнера: описание машины → ready → план прогонов `BENCH_PLAN` (`сцена:устройство:повторов[:выборки:persistent:потоки]`) → кадры и `events.json` на приёмник `…/mesh-sink` (`renderbench-1117/<RUN_ID>/`). Данные уходят после каждого шага.
- `bench_run.py --card 3090|4090 [--suffix b] --image <digest> [--apply]` — создаёт группу `render-bench-<карта><суффикс>` (high, 1 реплика), запускает, считает деньги (потолок $1,5 на карту, всего $4), гасит и проверяет `stopped`; без `--apply` только печатает тело. Предохранители: нет данных на приёмнике через 240 с после `running` → стоп.
- `salad_look.py` — только чтение: группы, классы GPU.
- Сторож `infra/server/salad-deadman.py` рендер-группы (`render-*`) не гасит — только `mesh-*` (`MESH_DEADMAN_PREFIXES`).

## Урок по грабли (17.11)
1. Рендер-образ обязан содержать `data/flat3d/wall-art.json` (сторож картин в `render_cycles.py` читает его от корня: `/app/../../../data`).
2. python из Blender не знает CA-сертификатов образа → `ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt`, иначе выгрузка по https падает `CERTIFICATE_VERIFY_FAILED`.
3. PATCH остановленной группы Salad не применяется (версия «pending», запускается прежняя) — повтор замера = НОВАЯ группа.
4. Создание группы Salad бывает долгим (pending до 10 мин; `/start` в это время 400).
5. Blender завершается кодом 0 даже при упавшем скрипте → `--python-exit-code 1`, число кадров проверяется.

## Результаты замера (17.11, тариф high; рендер пары C1+C2 в одном процессе, 1536×1116, 64 выб. + OIDN)
| Карта | Нода (CPU) | Кадр, с | Пара, с | Видеокарта, средняя загрузка |
|---|---|---|---|---|
| 3090 | i7-12700K (20 пот.) | 5,6 | 13,0 | 31 % |
| 3090 | Xeon E5-1660v4 (16) | 7,0 | 17,8 | — |
| 3090 | i7-6700 (8) | 7,0 | 17,6 | 51 % |
| 3090 | Xeon E5-2680v4 (12) | 11,5 | 29 | 31 % |
| 4090 | i7-13700K (24) | 3,0 | 7,7 | 50 % |
Спальня — примерно 0,8× от гостиной. OptiX на нодах Salad недоступен (драйвер без graphics) — рендер идёт на CUDA. CPU DEV, 8 ядер: 185 с на кадр.
Цена: 3090 $0,17/ч, 4090 $0,33/ч (в 1,94× дороже); ускорение 4090 на сопоставимых нодах 1,87× < 2,2× → 4090 не выгоднее.
Накладные расходы (3090, i7-6700): при 8 выб. кадр 3,2 с, при 64 — 7,0 с → ≈ 2,7 с на кадр не зависит от выборок. `--persistent 1` (render.use_persistent_data): второй кадр пары 7,0 → 5,3 с (−24 %), картинка та же (разница 0,02 из 255). Потоки 16 вместо 8 ничего не дают.
Кадры GPU и CPU совпадают (средняя разница 0,3 из 255; 4090 и 3090 — 0,02).

## Контроллер машины рендера (T-20261117-24/1)
Один держатель желаемого состояния — `render_machine.py` на DEV (pakardev). Состояние — `~/remlab-logs/render-machine/state.json` (вне репо), всё под `flock`.
Параметры и предохранители — данными в `rules/salad-groups.json` → `render_machine` (группа `render-3090`, образ-digest цели `agent`, `idle_stop_min` 20,
`max_run_min` 240, `day_cap_usd` 2, `warmup_max_min` 15, `degraded_stop_min` 10, `guard_stale_min` 10). Образ сменили → НОВОЕ имя группы (PATCH остановленной не применяется), старую не удалять без владельца.

| Команда (на pakardev; с common/algor — `r '…'`) | Что делает | Что печатает (RU; `--lang en` — пара) |
|---|---|---|
| `render_machine.py on --by <кто>` | создаёт группу, если её нет, `/start`; идемпотентно (живую не трогает) | «Включаю машину рендера — прогреется за 2–4 минуты, я напишу.» / «Машина уже включена (running) — второй не запускаю.» / «Не включаю: дневной потолок … исчерпан …» / «…в Salad группа … с другим образом…» |
| `render_machine.py off --by <кто>` | `/stop` и проверка `stopped` | «Машина рендера выключена (остановка подтверждена). Сегодня потрачено $…» / «…уже выключена…» |
| `render_machine.py status [--json]` | одна строка | «Машина рендера выключена. Сегодня потрачено $0.00 из $2.00. Включить — /render_on.» / «Машина включается (deploying), уже N мин.» / «Машина прогрелась и работает (N мин), фото считается ~15–30 с. До автостопа M мин простоя…» |
| `render_machine.py pulse --by <кто>` | «работа идёт» — зовёт воркер/маршрутизатор при старте и конце КАЖДОЙ пары: сбрасывает автостоп | `ok` |
| `render_machine.py tick` | раз в минуту (крон): прогрелась? деградация? автостоп/потолок/предел/прогрев? отметка для сторожа | одна строка про состояние |

Кнопки ботов (ставит директор): `/render_on` → `r 'python3 /home/pakar/igor/remlab/tools/scout/render_gpu/render_machine.py on --by tg-<машина>'`,
`/render_off` → `… off …`, `/render_status` → `… status`; ответ бота — напечатанная строка как есть (одна строка, без трассировки: любая ошибка тоже одной строкой).
Крон DEV (ставит директор), раз в минуту: `* * * * * /home/pakar/venvs/scout/bin/python /home/pakar/igor/remlab/tools/scout/render_gpu/render_machine.py tick >> /home/pakar/remlab-logs/render-machine/tick.log 2>&1`.

«Прогрелась» = группа `running` И `rendermachine/ready.json` на приёмнике свежий (по времени файла на сервере, ≤120 с), позже старта запуска и `ready:true`
(пишет `machine_agent.py`, цель образа `agent`: GPU + малый настоящий Cycles-проход, потом отметка раз в 30 с; боевой воркер T-24/2 обязан писать тот же файл).
Владельцу через готовый `tools/scout/alert.sh` (`/home/pakar/igor/remlab/tools/scout/alert.sh`, токены не читаем): «прогрелась» — ОДНО за запуск; деградация — одно на эпизод; стоп по предохранителю — одно.
Сухо (в журнал вместо Telegram): `RENDER_MACHINE_DRY=1`. Числа на проверку вживую: `RENDER_MACHINE_OVERRIDE='{"idle_stop_min": 3}'`.

Сторож сервера — `infra/server/render-guard.py` (только `render-*`; меш-группы не трогает, тест в `--selftest`): контроллер не отмечался (`controller.json`, пишет `tick`) > 10 мин → `/stop` живых render-групп и сообщение владельцу.
Выложить: скопировать в `/opt/remlab/scripts/render-guard.py`, `RENDER_GUARD_DRY=1 python3 … ` для сухой проверки, крон `* * * * * root /usr/bin/python3 /opt/remlab/scripts/render-guard.py >> /var/log/render-guard.log 2>&1`.
Отключить на время ручной работы: файл `/opt/remlab/render-guard-off-until` с временем UNIX.

Тесты: `python3 tools/scout/render_gpu/tests_render_machine.py` (чистая `plan()` + команды на подмене Salad) и `python3 infra/server/render-guard.py --selftest`.

## Исполнитель `salad-gpu` и воркер машины (T-20261117-24/2)
**Поток одной пары.** `Fallback(salad-gpu → local-cpu)` (`RENDER_EXECUTOR=salad-gpu,local-cpu`): ① `gate` — `state.json` контроллера: включена, прогрелась в этом
запуске, нет деградации, контроллер жив (≤5 мин) — иначе сразу `ExecutorUnavailable` (`gpu_off|gpu_warming|gpu_degraded`, пара RU/EN) и пара считается на CPU DEV;
② `pulse --busy` (заказ = событие, пока пара в работе — «занято»); ③ сцена на DEV тем же `SceneExecutor._prepare`, что у `local-cpu` (меши → `export_scene`,
декор → `demo_scene_dump`); ④ пакет `bundle-<sha>.tgz` (сцена + декор + `render_cycles.py` + `wall-art.json` + карты из `scene-export.json`; воспроизводимый) →
`renderjobs/<задание>/`, последним `job.json`; ⑤ воркер в контейнере (`render_worker.py`) берёт задание, ОДИН Blender считает C1,C2 (`--persistent 1`, `--device auto`),
кладёт `C1.png`, `C2.png`, последним `result.json`; ход — `progress.json` (стадии scene → C1 → C2 → save → те же `progress()`, что у CPU); ⑥ исполнитель качает кадры,
`_finish` (JPEG + `meta.json`, `executor: salad-gpu`); ⑦ `pulse(0)` — конец пары, автостоп 20 мин с этого момента.
**Откат на CPU — данными:** не взяли за `pickup_s` (90), не уложились в `pair_max_s` (900), машину выключили в ожидании, GPU не взялся (воркер видит `DEVICE_USED CPU`),
Blender упал, хранилище не приняло/не отдало — `ExecutorUnavailable` + `cancel.json`; параметры — `rules/salad-groups.json → render_machine.executor`.
**Автостоп** — от ПОСЛЕДНЕГО события (заказ или готовая пара), и никогда, пока пара в работе (`busy_until` обновляет ждущий исполнитель; умер — метка истекает сама,
остаются потолки 4 ч и $/сутки). **Хранилище:** только префикс `renderjobs/`; приёмник отдаёт `GET /files/renderjobs/<задание>/<имя>` и `GET /ls/renderjobs[/<задание>]`
(токен обязателен, потоком, `..`/симлинки/`.part`/скрытые — 404, чужие префиксы — 404; список — `MESH_SERVE_PREFIXES`, потолок PUT пакета — `MESH_SERVE_MAX_MB`, 200).
**Кэш на машине:** пакеты по sha, ≤3 штук и ≤1,5 ГБ (`CACHE_N`, `CACHE_GB`). **Образ:** цель `worker` (`build_render.sh worker`), digest — в `render_machine.image`.
**Токен приёмника для исполнителя:** `RENDER_SINK_TOKEN` | `MESH_SINK_TOKEN` | из окружения группы-донора (`sink_health.sink_token()`).
**Уборка:** `jobs_purge.py --apply` (задания старше 24 ч; через `DELETE /prefix/` приёмника). Крон (ставит директор):
`17 * * * *  ~/venvs/scout/bin/python <репо>/tools/scout/render_gpu/jobs_purge.py --apply >> ~/remlab-logs/renderjobs-purge.log 2>&1`
**Приёмник — как выложить и перезапустить:** скопировать `tools/scout/salad/receiver.py` на сервер туда, откуда он запускается (то же место, что сейчас), и перезапустить
сервис приёмника (счётчик каталога пересчитается при старте); проверка — `curl -H "Authorization: Bearer …" https://remont-lab.online/mesh-sink/ls/renderjobs` (200, `{"dirs": []}`),
чужой префикс (`/ls/<любой меш>`) → 404. Тесты безопасности — `salad/tests_sink_serve.py` (в CI).
Тесты: `render_gpu/tests_render_executor.py` (исполнитель ↔ воркер ↔ хранилище в памяти, Blender — `fake_blender.py`), `tests_render_machine.py`, `jobs_purge.py --selftest`.

## T-20261117-24/3 — рычаги скорости 4090 и тонкий образ (замер 17.11, ≈$0,16 всего)
Прогрев «от /start до running» (сек), по запускам; кадры пары на 4090 — 5–9 с на любой ноде (разброс от процессора ноды, не от рычага).
| вариант | $/ч | прогрев по запускам | медиана |
|---|---|---|---|
| база: 8 vCPU/16 ГБ, high, образ 1,11 ГБ | 0,33 | 444, 147 | ~295 (2 запуска) |
| 16 vCPU/32 ГБ, high | 0,33 | 102, 145, 123 | 123 |
| 8 vCPU/16 ГБ, medium | 0,273 | 89, 90 (3-й запуск невалиден: общий каталог) | 90 |
| 16 vCPU/32 ГБ, medium | 0,273 | 57, 78 | 68 |
| тонкий образ 0,67 ГБ, 8 vCPU/16 ГБ, high | 0,33 | 45, 34, 57, 68, 111 | 57 |
Выводы: vCPU/ОЗУ кадры не ускоряют (5–9 с везде); прогрев определяет скачивание образа и нода (разброс 35–444 с). Тонкий образ: скачивание ~27 с против ~66 с (без выброса 398 с). Medium не медленнее high, на 17 % дешевле. Кэш образа при втором старте той же группы НЕ работает: каждый старт попадал на другую ноду (CPU разный у всех запусков) — ставка на «ту же ноду» не годится.
Совет: medium + 8 vCPU/16 ГБ + тонкий образ (worker, `RENDER_BASE=thin`; новая группа, digest меш-групп не трогаем).

## T-20261117-24/5 — fmt 2: ассеты по хешу (Э2а)
**Идея:** тяжёлое и неизменное (текстуры сцены PNG, GLB декора целиком, карты отделки `public/*`, `render_cycles.py`/`wall_art.py`/`wall-art.json`) уходит на приёмник ОДИН раз под своим полным sha256 в отдельный префикс `renderassets/<ab>/<sha256>`; заказ — короткий `job.json` (v=2) со ссылками `{path, sha256, size, kind}` и маленький пакет (npz мировых вершин, `scene.json`, `scene-export.json`, `demo_nodes_uuids.json`).
**Порядок исполнителя** (`render_exec.py: _send_fmt2`): хеши ассетов (память по mtime+size) → `POST /have/renderassets` «каких нет» → параллельный PUT недостающих (`upload_par`, по умолчанию 4), пока пакуется маленький пакет → пакет → `job.json` ПОСЛЕДНИМ. Любой сбой (старый приёмник без `/have` — 5 мин не пробуем; ассет не принят; воркер ответил `asset`/`bad_job`) → тот же заказ по fmt 1, дальше CPU; частичного кадра нет.
**Машина** (`render_worker.py: prepare_v2`): ассет берётся из `/work/blobs/<sha>` (проверка sha256 И размера при КАЖДОМ взятии; чужой/битый файл удаляется и качается заново), иначе качается с приёмника (одно скачивание на хеш, временный `.dl-*` → проверка хеша → атомарно, read-only), в каталог задания — жёсткая ссылка. Кэш ассетов ≤ 4 ГБ (`BLOB_GB`), LRU по mtime, ассеты текущего задания не трогаем (диск контейнера 10 ГБ). v=1 и CPU-запас не изменены.
**Приёмник** (`salad/receiver.py`): `renderassets` — свой счётчик/потолок (`MESH_ASSET_MAX_GB`, по умолчанию 1,5), PUT сверяет sha256 тела с именем (чужое → 400, на диске ничего), «уже есть» = успех (existed), уникальное временное имя + атомарная подмена, DELETE одного файла ассета; счётчики мешей и заданий и меш-префиксы не затронуты. **Выложить на сервер** (как и прежде — копия в `/opt/remlab/mesh-receiver.py` + перезапуск `mesh-receiver`); без этого исполнитель сам уходит на fmt 1. Проверка: `POST /mesh-sink/have/renderassets` `{"items":[]}` → `{"missing":[],"have":0}`.
**Уборка** (`jobs_purge.py --apply`, тот же крон :17): задания как раньше; ассеты — старше `ASSET_MAX_AGE_H` по mtime (его двигает `/have`), сверх размера — давние вперёд; ссылки живых (непросроченных) заданий не трогаем.
**Включение:** `rules.render_machine.executor.fmt2` (в репо `false` до живой приёмки; `true` — после), `upload_par`. Образ с воркером fmt 2 — тег `cycles-5.3.0-worker-thin-fmt2`, группа `render-4090m3`.
**Тесты:** `tests_render_executor.py` (§15: fmt 2 сквозной, повтор без выгрузки, битый кэш, пропавший ассет, чужие байты, старый приёмник, старый воркер, флаг, один поток на хеш, строгая validate_job, границы распаковки), `salad/tests_sink_assets.py`, `jobs_purge.py --selftest`.
