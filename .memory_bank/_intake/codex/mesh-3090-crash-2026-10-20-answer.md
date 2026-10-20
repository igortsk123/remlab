Короткий вердикт: вероятнее всего это не «жёсткий cgroup только на 3090», а регрессия/нестабильность WSL-хоста под сильным memory pressure после rollout WSL 3.0.3. ОЗУ вашего пайплайна — усилитель проблемы, но не объясняет резкий перелом 13–16.10 само по себе.

### 1. Что живёт на пике

- Две Hunyuan-модели одновременно штатно не держатся: shape удаляется до создания paint — [`pipeline.py:524`](/home/pakar/igor/remlab/tools/scout/salad/pipeline.py:524), paint загружается на [`pipeline.py:528`](/home/pakar/igor/remlab/tools/scout/salad/pipeline.py:528) и удаляется после экспорта на [`pipeline.py:553`](/home/pakar/igor/remlab/tools/scout/salad/pipeline.py:553).

- mmap формы уже сделан: 6,9-ГБ checkpoint читается с `mmap=True` — [`Dockerfile.mmap:3`](/home/pakar/igor/remlab/tools/scout/salad/Dockerfile.mmap:3), [`Dockerfile.mmap:25`](/home/pakar/igor/remlab/tools/scout/salad/Dockerfile.mmap:25). Ещё один generic mmap-фикс — не первый кандидат.

- После `_unload('shape')` всё ещё живёт локальный `mesh` из [`pipeline.py:483`](/home/pakar/igor/remlab/tools/scout/salad/pipeline.py:483); paint затем повторно грузит GLB. Дешёвый фикс: `del mesh` сразу после экспорта/shape-проверок перед строкой 524.

- Первый реальный job тяжелее warmup: warmup не запускает preprocess/BiRefNet и использует `5 steps / octree 128` — [`worker.py:115`](/home/pakar/igor/remlab/tools/scout/salad/worker.py:115); job сначала навсегда загружает BiRefNet — [`preprocess.py:31`](/home/pakar/igor/remlab/tools/scout/salad/preprocess.py:31), затем идёт с `50 / 380` — [`pipeline.py:472`](/home/pakar/igor/remlab/tools/scout/salad/pipeline.py:472). Поэтому «warmup прошёл, первый job умер» совместимо с memory pressure.

- Paint прочитывает ~6,4 ГБ весов и 4,55 ГБ DINO — [`Dockerfile.localpaint:3`](/home/pakar/igor/remlab/tools/scout/salad/Dockerfile.localpaint:3), [`Dockerfile.dino:7`](/home/pakar/igor/remlab/tools/scout/salad/Dockerfile.dino:7). Плюс mesh/raster buffers, normal/position views, копии albedo/MR, 2048² render и 4096² texture buffers — [upstream `textureGenPipeline.py`](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/blob/main/hy3dpaint/textureGenPipeline.py).

- 35 ГБ Salad могут включать не только anonymous RSS, но и page cache прочитанных весов; cgroup `memory.stat` разделяет это на `anon`, `file`, `file_mapped`. [Документация cgroup v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)

Дешёвые правки: `del mesh`; unload обеих моделей в `finally`; проба `malloc_trim(0)`. Надёжнее — shape и paint отдельными subprocess: модели и allocator гарантированно исчезают при exit. Сейчас модели и так перезагружаются на каждый SKU, поэтому дополнительная цена мала.

### 2. Как доказать причину смерти

Расширить [`mem_probe.py:28`](/home/pakar/igor/remlab/tools/scout/salad/mem_probe.py:28) и отправлять телеметрию наружу каждые 1–2 секунды, а не пытаться записать её после смерти:

- `memory.events.local`, `memory.oom.group`, `memory.stat`, `memory.current/peak/max`, `memory.swap.current/max`, `memory.pressure`;
- `MemAvailable`, `SwapFree`, `/proc/pressure/{memory,io,cpu}`;
- RSS/RssAnon/RssFile/Swap и `smaps_rollup` процессов;
- `nvidia-smi` с временем выполнения и exit code;
- фаза: `shape_load/infer/export/unload`, `paint_load/diffusion/upscale/bake/export`.

Интерпретация:

- вырос `oom_kill` + child получил SIGKILL/137 — доказанный OOM;
- `oom_kill=0`, MemAvailable→0, PSI растёт и вся VM исчезает — global WSL/host pressure или kernel panic;
- RAM спокойна, сначала зависает/падает `nvidia-smi` — GPU-PV/driver;
- instance остаётся в API и heartbeat продолжает идти — внешний SSH/network.

Лучше запускать model runner дочерним процессом под маленьким supervisor. Но если `memory.oom.group=1` или умерла вся WSL-VM, supervisor тоже погибнет — поэтому последние samples должны уже быть на вашем receiver.

Дополнительно брать Salad System Events: `Exited:137` и `Interrupted (Node Offline)` — разные исходы. [Salad System Events](https://docs.salad.com/container-engine/explanation/container-groups/system-events) Для Xid нужен host kernel/Windows event log; NVIDIA пишет Xid именно туда, поэтому Salad support должен дать события по machine ID и времени. [NVIDIA Xid](https://docs.nvidia.com/deploy/xid-errors/introduction.html)

### 3. Что делать с 3090

- Сейчас убрать 3090 из production — рационально: потери слишком велики. A5000 оставить на 24 ГБ.
- Не переводить весь пул на 48 ГБ: у GPU Salad RAM-request мягкий, превышение 100% допустимо и зависит от ноды; это прямо описано Salad. [CPU and RAM Utilization](https://docs.salad.com/container-engine/explanation/container-groups/resource-utilization)
- Сделать отдельную 3090-canary на 48 ГБ, не на 40: наблюдаемый sample уже 35 ГБ, а минутная метрика пропускает короткий пик. 20–30 первых jobs, обязательно группировать результат по `uname -r`, MemTotal и machine ID.
- Кодовый memory-fix всё равно нужен, но он не может быть первичным объяснением перелома: образ и workload не менялись.

### 4. Что вероятнее после новой хронологии

Порядок вероятностей:

1. **WSL 3.0.3 / kernel 6.18.54.1 + memory pressure.** Официальный WSL 3.0.3 вышел 9.10 и принёс именно kernel 6.18.54.1. [WSL releases](https://github.com/microsoft/WSL/releases) Есть свежий отчёт: после перехода на 3.0.3 VM набирает память до cap и зависает; 16→48 ГБ не помогает, rollback на 2.7.14/6.18.33.2 стабилен. Это пользовательский отчёт, не подтверждённый Microsoft RCA, но совпадение по версии и датам сильное. [WSL issue #41931](https://github.com/microsoft/WSL/issues/41931)

2. **Изменение host mix/аллокатора Salad:** 3090 чаще попадают на домашние машины с малой RAM. Это объясняет корреляцию с MemTotal, но не перелом без изменения планировщика/rollout.

3. **GPU-PV/NVIDIA driver:** реально возможно; в октябре есть отчёты о WSL GPU-PV/TDR и падениях VM. Но это не специфично для 3090: 16.10 журнал содержит такой же обрыв у 4090 и 3090 Ti — [`mesh-run-progress.jsonl:6448`](/home/pakar/igor/remlab/tools/scout/mesh-run-progress.jsonl:6448), [`mesh-run-progress.jsonl:6449`](/home/pakar/igor/remlab/tools/scout/mesh-run-progress.jsonl:6449).

4. **SSH/keep-alive или обычная сеть — маловероятно.** Уже стоит `ServerAliveInterval=30` — [`ssh_run.py:377`](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:377). `RemoteDisconnected` возникает внутри удалённого `urllib` к `127.0.0.1:8000` — [`ssh_run.py:368`](/home/pakar/igor/remlab/tools/scout/salad/ssh_run.py:368); исчезновение instance из Salad API сетью клиента не объясняется.

Публичного Salad advisory именно про RTX 3090 за октябрь не нашёл; официальная status page не показывает incident за последние семь дней. Это не исключает rollout WSL/host agent, потому что status page отражает платформенные сервисы, а не дефекты отдельных домашних нод. [Salad status](https://cloud-status.salad.com/en)