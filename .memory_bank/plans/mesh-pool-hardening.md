---
workstream: mesh-pipeline
slug: mesh-pool-hardening
title: Работа над ошибками пула мешей — приёмник, стопоры, транспорт, OOM, цена
status: in_progress
created: 2026-09-04
updated: 2026-09-04
completed:
---

## Context

За двое суток (02–04.09) пул генерации мешей на SaladCloud вышел с 22 мешей/сутки на 100 мешей/час,
но каждую ночь останавливался — по НАШЕЙ вине, не платформы:

- **Приёмник переполнился** (`receiver.py` → 507 на PUT): 135 тегов `ghcr.io/…/remlab-app:<sha>` от
  CI-деплоев съели диск; ноды считали меши (GPU оплачен) и роняли отправку — 104 `failed`
  «`EOF occurred in violation of protocol`». Сторож погасил пул **молча** → 10 ч простоя. Утром я
  проверил приёмник ПУСТЫМ файлом (404 = «ок»), снял запрет, пул сжёг ещё 385 нодо-минут.
  Диагноз дала только загрузка 15 МБ → 507.
- **Batch-группы поднимались вне окна**: `batch_show.group_status()` при смешанном состоянии
  отдаёт статус ПЕРВОЙ группы, а `ensure_group_started()` стартует ВСЕ группы при любом «нет
  тёплых нод». Погашенные кроном в 15:00 UTC batch-группы поднялись вечером: 57 машин прогрелось,
  0 мешей, 134 ₽ впустую (доля успеха batch: 09–14ч 51–81%, 15–19ч 0–9%).
- **Три стопора не знают друг о друге**: `money_guard.py` (стоп-файл), `idle_guard.sh` (cron */10,
  гасит всё без `batch_show.py`), `batch_window.sh` (cron 09/15 UTC).
- **Транспорт**: `ssh_run.run_job()` делает вторую SSH-попытку ВСЕГДА (двойной `/generate` при
  обрыве посреди генерации); stderr/returncode выбрасываются; 328× «нет маркера» с пустым stdout.
- **OOM на dev-VM**: `topview_render.py` (10 ГБ) и `apply_repairs.py` снимает earlyoom каждый цикл —
  trimesh +100 МБ/меш в одном процессе; `|| exit $?` обрывает проходы. Виды сверху не строятся.
- **Цена меша врёт вдвое**: `tier_compare` считает по секундам генерации (0.75 ₽), по оплаченным
  нодо-часам 1.54–2.45 ₽; `paid_node_min` никто не читает; `RATE=0.16` хардкод.
- **Мины**: Caddy-маршрут `/mesh-sink` и контейнер `mesh-receiver` живут только на сервере;
  `deploy.sh:30` копирует репо-Caddyfile поверх (грабля `/test/*` 07.08). `alert.sh` всегда
  возвращает 0. `remlab-app` (прод, 1 ГБ): 11 рестартов, 6 OOM/неделю.

Цель: пул не сжигает деньги молча, не поднимает дешёвый тариф вне окна, не теряет GPU-время на
полный приёмник, шаги разбора не умирают, цена меша считается по оплаченному времени.

**Решения владельца (04.09):** ребилд образа — да, одной пересборкой; `remlab-app` — только
наблюдение и тревога; Caddyfile `/mesh-sink` в репо И `mesh-receiver` в compose — да, оба.

## Источник задачи
Владелец 04.09: «сделай комплексный план по работе над ошибками и исправь все комплексно».
Разведка: 3 Explore-агента + Plan-агент (нашёл `group_status`/`sts[0]` и безусловную 2-ю
SSH-попытку); критика Codex — раздел в конце.

## Скоуп — что НЕ входит
- Перенос приёмника в S3/R2 или на отдельный диск (Codex): владелец уже отклонял (загрузка внутри
  `running` оплачивается, закачка образа — нет); один диск у провайдера. Записать как долг.
- Единый control-plane с lease вместо трёх стопоров (Codex): перестройка ради трёх скриптов —
  вместо неё свод правил + singleton-lock конвейера (P0-2, P1-9).
- Микробатчинг стадий, `MALLOC_ARENA_MAX`, зеркалирование фото, поднятие `mem_limit` `remlab-app`,
  расписание по переписи (нужна неделя данных).

---

## P0 — останавливает сжигание денег / ломает прод

### P0-1. Приёмник: проверка ДО GPU, монитор во время, текст ошибки — только повод для проверки
**Причина.** `receiver.py:120-124` даёт 507 только на PUT; `GET /health` (`:89-91`, без токена)
никто не зовёт; мой тест пустым файлом = 404 = ложное «ок». Пачка идёт до 2 ч — раз в пачку мало
(Codex №4). Текст `EOF` бывает и у CDN фото, и у SSH-шлюза (Codex №5).
**Правка.**
- `tools/scout/salad/sink_health.py`: `check()` → GET `MESH_SINK_HEALTH_URL` (умолч.
  `…/mesh-sink/health`, 2 попытки, 15 с); `ok = free_gb ≥ 5+MARGIN(2) и dir_gb ≤ max_dir−1`
  (лестница purge<8/6 → пред-проверка<7/7 → приёмник 507<5/8 — в комментарии). `canary()` —
  авторизованный PUT 1 МБ в `staging/_canary/…` + DELETE: проверяет Caddy/TLS/токен/запись, не
  только чтение (ровно то, что поймало бы 507 утром). `alert_throttled()` — раз в час.
- `ssh_run.run()` первой строкой: `check()` + `canary()`; отказ → печать, alert,
  `return EXIT_NO_CAPACITY` (75 — «нет ёмкости», `batch_show` уже ждёт 3 мин и возвращает спул).
  В ветку 75 `batch_show` добавить немедленный `drain.sh --keep` + `receiver_purge.py --apply`,
  не ждать фонового тика.
- **Монитор в супервизоре** (`ssh_run.supervisor`, уже крутится каждые `POLL_S`=45 с): `check()`
  → модульный флаг `SINK_OK`; воркер перед **каждым** заданием читает флаг (без сети) — красный →
  не берёт, ждёт. Один опрос на процесс, не на поток.
- `failed` с текстом `http error 507` / `eof occurred in violation of protocol` / `remote end
  closed` (ТОЛЬКО статус `failed`, не `input_failed`) — **повод**, не диагноз: воркер форсирует
  внеочередной `check()`; приёмник красный → `js.close_rest('приёмник')`, результат 75, ноду не
  винить, серию не растить (`node_health.classify` → `FAULT_INFRA` только при красном приёмнике);
  зелёный → обычный повтор на другой ноде, пул не гасить.
- `money_guard.main()`: `check()` в тик; красный → alert (дроссель) и `'kind': 'shared_infra'`
  в стоп-файле. `failure_burst()` группирует по `err_class` для `ssh/*`, `infra/*`.
- Приёмник (в паузу фазы C, вместе с compose): `GET /ready` O(1) — размер каталога считается
  инкрементально на PUT/complete/DELETE, плюс байты активных PUT (резерв), `ok:false` когда PUT
  получит 507; гейт места и запись под одним замком (Codex №4: сейчас `os.walk` на каждый вызов и
  несколько PUT проходят гейт разом). `sink_health` переключается на `/ready`, если он есть.
**Проверка.** Стенд `case_preflight_sink_full`, `case_infra_closes_rest`, `case_sink_flag_blocks_take`.
Вручную: `MESH_SINK_MARGIN_GB=100 python ssh_run.py --limit 1` → 75 + TG; канарейка видна в логе приёмника.

### P0-2. Три стопора — один свод правил
**Причина.** `group_status` → `sts[0]`; `ensure_group_started` стартует всех; `idle_guard` не знает
окна и стоп-файла; `SALAD_GROUP` парсится в 7 местах с умолчаниями `mesh-run3`/`mesh-run10`.
**Правка.** `tools/scout/rules/salad-groups.json` (`prices_usd_h`, `usd_rub`, `groups: {name: {tier,
window_utc?}}`) + `salad_groups.py` (`tier`, `price`, `allowed_now(g, now)`, `groups_from_env()` —
без умолчания, пусто → `SystemExit` с подсказкой).

| Правило | Где |
|---|---|
| Группу вне окна не поднимает никто | `ensure_group_started()` — только `allowed_now(g)`; `group_status()` — `stopped` только если ВСЕ stopped, иначе первый НЕ-stopped; `heal_wave` через ту же функцию |
| Подъём по будильнику — только при живом конвейере | `batch_window.sh up`: после HALT — `pgrep -f '[b]atch_show.py' \|\| { alert; exit 0; }`; при HALT — alert |
| Нет конвейера → гасим всё, стоп-файл НЕ пишем | `idle_guard.sh`: ловить `[b]atch_show.py\|[s]sh_run.py`; убрать умолчание; alert после гашения. Чехарды нет: поднимает группы только живой конвейер, а он singleton (P1-9) |
| `SALAD_GROUP` читается в одном месте | `ssh_run.GROUPS = salad_groups.groups_from_env()` (в `main()`); `batch_show` 5 повторов → `SR.GROUPS`; `money_guard.groups()` → тот же вызов |

**Проверка.** Стенд `case_window_gate`, `case_group_status_mixed`; вручную `batch_window.sh up` без
конвейера → «не поднимаю» + TG.

### P0-3. Оповещение умеет сказать «не доставлено»; суточный пульс
**Правка.** `alert.sh`: успех → `alert-sent.log`, `exit 0`; провал → `refresh-alert.log`, `exit 1`;
нет конфига → `exit 2`. Все вызовы под `set -e` — `alert … || true` (Codex №14: недоставка не
отменяет защитное действие; проверить `refresh_daily.sh`, `enrich_*.sh`). `money_guard.notify()
-> bool` печатает результат, действие идёт независимо. Пульс в 08 UTC: ok/cached за сутки,
оплачено по группам ($/₽), приёмник free/dir, запрет.
**Проверка.** `bash alert.sh тест; echo $?` → 0; `TG_BOT_TOKEN=bad …` → 1; стенд `case_notify_reports`.

### P0-4. Сервер: диск, `.staging`, Caddyfile, compose, наблюдение `remlab-app`
Только `/opt/remlab/*` и docker-объекты `remlab*`/`ghcr.io/igortsk123/remlab-app`. **Никогда**
`docker system prune`, iptables, `remnanode`. `deploy.sh` на dev-VM не запускать. SSH 22222.
- **a) `infra/server/cleanup.sh`** под `flock /opt/remlab/.deploy.lock`: держать image ID **всех**
  работающих контейнеров (`docker ps --format '{{.ImageID}}'`), `remlab-app:latest/prev`; остальные
  теги `ghcr.io/igortsk123/remlab-app:*` → `docker rmi`. CI `deploy.yml`: cleanup **до** `docker
  compose pull` (место нужно до pull — Codex №4) и после smoke, под тем же flock. `deploy.sh:25`
  — тот же гейт места до `docker load`.
- **b) `disk-watchdog.sh`** ежечасно: `≥THRESH` → cleanup → перемерить → Telegram через
  `/opt/remlab/catalog-watchdog/.env` (дроссель 6 ч); `df`, `du /opt/remlab/meshes`, число `.staging`.
- **c) `.staging`** в `receiver_purge.py`: удалять только при возрасте >6 ч **и** неизменном размере
  в двух последовательных прогонах (файл состояния `~/scout-scenes/.staging-seen.json`; mtime
  каталога не движется при долгой записи файла — Codex №7). Плюс в приёмнике при 507 —
  `rmtree(staging)` этого префикса (фаза C).
- **d) `receiver_purge.free_gb()`** — оставить `df /` (приёмник судит по тому же диску); `tight`
  также при `Σ size > MESH_RECV_DIR_TIGHT_GB(6)`.
- **e) Caddyfile**: снять серверный блок (`diff`), перенести `/mesh-sink` в репо с комментарием-
  уроком; предохранитель в `deploy.sh` перед `:30` (серверные строки не в репо → FATAL). CI
  Caddyfile не копирует (Codex №5) — репо-копия защищает ручной деплой и даёт паритет; копию в CI
  добавить только после подтверждённого паритета (follow-up).
- **f) `mesh-receiver` в compose** — в паузу фазы C: `docker inspect` (токен не печатать) → сервис
  (`MESH_SINK_TOKEN` из `.env`, `MESH_SINK_BIND=0.0.0.0`, том `/opt/remlab/meshes`, `mem_limit:
  128m`, `remlab-net`); `docker rm -f mesh-receiver && docker compose up -d mesh-receiver`; откат —
  прежняя `docker run`. **Только при `draining`** (Codex №3): обрыв PUT = потерянный оплаченный меш.
- **g) `remlab-app`** — наблюдение: `RestartCount`, `OOMKilled`, `docker stats` в
  `/opt/remlab/backups/app-mem.log`; рост рестартов → Telegram. Кандидат после недели:
  `NODE_OPTIONS=--max-old-space-size=640`.
**Деплой серверных файлов (руками, с бэкапом):** `cp -a /opt/remlab/scripts scripts.bak-<дата>`
→ `scp -P 22222 infra/server/{cleanup,disk-watchdog}.sh …/scripts/`, таймер → `daemon-reload` →
`disk-watchdog.sh 1` (ветка cleanup+TG). Откат — `cp -a scripts.bak-<дата>/. scripts/`.
**Проверка.** `docker images 'ghcr.io/igortsk123/remlab-app' | wc -l` ≤ 3; `df /` < 60%; TG от
watchdog; `.staging` = 0 после двух циклов; `git diff` Caddyfile против сервера пуст.

### P0-5. Транспорт: диагноз в ошибке, вторая попытка без двойной генерации
**Причина.** `ssh_run.py:224-236` — вторая попытка всегда; stderr/rc выбрасываются; `TimeoutExpired`
теряет вывод; `error[:120]`. Codex №1: пустой stdout НЕ доказывает, что `/generate` не стартовал.
**Правка.** `node_health.transport_class(stdout, stderr, rc)` → `empty | container_id | set_user |
mid_generation | other`; `error_class()` → `ssh/<kind>` (fleet_wide по подклассу). `run_job`: error
`f'ssh/{kind} rc={rc}: {stdout[-100:]} | err: {stderr[-100:]}'`; `TimeoutExpired` → хвост `e.stdout`;
`checkpoint` `error[:200]`. Повтор: при `mid_generation`/`container_id`/`set_user` — сразу
`transport_failed` (перезаезд через `RETRY_GRACE_S`, `already_done` подхватит опубликованное);
при `empty` — **до ребилда** как сейчас (второй заход после 8 с; остаточный риск двойной
генерации признан и записан), **после ребилда** — воркер держит `inflight` по `job_id` и
`GET /job/<id>` → `inflight|done|unknown`: второй заход сперва спрашивает статус и при `inflight`
ждёт результата, а не шлёт `/generate` (Codex №1 — идемпотентность вместо угадывания).
**Проверка.** Стенд `case_no_double_generate` (длинный stdout без маркера → 1 вызов), `case_transport_class`;
через сутки `grep -o '"error": "ssh/[a-z_]*' … | sort | uniq -c`.

---

## P1 — пропускная способность и правда о цене

### P1-6. Шаги разбора не умирают от earlyoom
**Причина.** `topview_render.py:296-320` — `trimesh.load` и `cabinet_front.front_by_depth` в
родителе на каждый новый меш; воркеры пула живут всю пачку; `TOPVIEW_LIMIT=120`×6 с `|| exit $?`
и `skip` с нуля при каждом запуске → потолок 600 просмотров и голодание хвоста (Codex №9);
`apply_repairs`: `ACCEPT_CAP=20`, 4–5 загрузок на меш, перестановка по PID.
**Правка.** `topview_render.py`: весь анализ одного SKU (extents + `cabinet_front`) — в дочернем
процессе (образец `mesh_dims.extents`, `tools/scout/mesh_dims.py:80-101`; `cabinet_front.py
--front-by-depth <glb>` → JSON); `TOPVIEW_WORKERS` умолч. **1** на 11 ГБ (Codex №8),
`max_tasks_per_child=4`; вместо `skip/limit`-проходов — **отбор по состоянию**: процесс проходит
всё, рендерит не больше `TOPVIEW_NEW_CAP=20` НОВЫХ (кэш готовых стоит копейки), выходит; обёртка
в `batch_show` повторяет, пока проход рендерит >0 новых или до дедлайна 2400 с; `|| fails+=1`.
`apply_repairs.py`: `ACCEPT_CAP` 20→5, самоцикл ×4, порядок — детерминированный (старейший
mtime без вердикта первым) вместо `shuffle(PID)`.
**Проверка.** `/usr/bin/time -v topview_render.py` → RSS < 2 ГБ; `journalctl -k | grep earlyoom`
пуст за сутки; `топ-вью: ok`, `приёмка: ok`; число `topview.png` растёт у новых мешей.

### P1-7. ОДИН ребилд образа: фото, `/ready`+`phase`, `inflight`, типизированные ошибки, alien
**Правка (тонкий слой поверх `cu124-localpaint`, паттерн `Dockerfile.localpaint`).**
- `preprocess.fetch()`: 3 попытки 2/5/10 с (404/410 НЕ повторять), браузерный UA + `Accept:
  image/*`; байты из `prepare` передаются дальше — второй закачки для `source.jpg` нет
  (`worker.py:186`; Codex №13 — идентичность входа).
- `worker.py`: `STATE['phase'] = warming|ready|failed`; `warm` при ошибке **False** (Codex №12);
  `GET /ready` → 200 только при `ready`; `/health` не трогать. **Одновременно** в `ssh_run`:
  зомби — по `warmup_fault(h)` или `phase=='failed'` независимо от `warm` (иначе после ребилда
  зомби перестанут ловиться). `inflight` по `job_id` + `GET /job/<id>` (P0-5).
- `storage.py`: типизированные ошибки — в ответ `failed` добавляются `stage: sink_put |
  sink_complete | shape | paint`, `http_status`, `host` (Codex №5) → `node_health` судит по стадии,
  не по тексту.
- `cut_alien_debris` → `(n_suspect, err)` → `manifest.json`; `model.glb.alien_suspect` в набор.
- Раскатка: `cu124-localpaint2`, новая группа на группу (PATCH образа молчит, ADR-0154), по одной
  с `mesh-low-2`, в 15:00 UTC.
**Проверка.** На ноде `fetch(url)` через `ssh_text`; `/ready` и `/job/<id>` через пробу; через сутки
доля `input_failed` timeout/SSL ↓; `grep alien_suspect …/manifest.json | wc -l`.

### P1-8. Цена — по оплаченным нодо-минутам (оценка, не бухгалтерия)
**Правка.** Цены/тарифы из `salad-groups.json` везде. Оплаченное время — из переписи
`mesh-pool-census.jsonl`: `paid_h[g] = Σ running×Δt`, Δt до следующей строки той же группы;
разрыв >2 тиков → `unknown`, не экстраполировать (Codex №11); сторож пишет финальную строку при
остановке групп; `paid_node_min` переживает смену состава. `tier_compare` печатает нижнюю (по
секундам) и оплаченную цену в $ и ₽ + долю `unknown`. `ssh_run.report()`: цена по группе, подпись
«нижняя граница»; `RATE` удалить.
**Проверка.** `tier_compare --hours 24`: оплаченная ≥ по-секундной; сумма за сутки сходится с
панелью Salad ±10%.

### P1-9. Горячий перезапуск конвейера — через `draining`, не `kill -9`
**Причина.** `finale()` гасит группы при любом перезапуске; `kill -9` оставляет сироту `ssh_run`, а
новый конвейер возьмёт тот же `--skip` (Codex №3: «подождать сирот» без замка недостаточно);
курсор пишется `json.dump(open(...,'w'))` — при падении остаётся пустой файл.
**Правка.** Singleton-`flock` `~/scout-scenes/.batch_show.lock`; флаг `~/scout-scenes/mesh-draining`
→ не начинать новую пачку, дождаться текущего `ssh_run`, `finale()` при флаге не гасит группы и
снимает флаг; курсор — temp + `os.replace`. Перезапуск = поставить флаг → дождаться выхода →
запустить новый (замок гарантирует одного).
**Проверка.** Стенд `case_draining_flag`, `case_cursor_atomic`; вручную по процедуре фазы B.

---

## P2 — гигиена
- **P2-10** `money_guard`: `cached` — доказательство живого транспорта в `failure_burst` (в `good`),
  но **не** новый меш для `last_mesh_at` (Codex №10: иначе платный пул крутит старые задания без
  прироста; текущий код здесь верен). Удалить `container-group.json`; сторож при старте пишет
  `~/scout-scenes/salad-groups-snapshot.json` и предупреждает, если `priority` API ≠ `tier` JSON.
- **P2-11** README (`sink_health`, `salad_groups`, JSON, таблица стопоров, деплой скриптов); ADR:
  «окно тарифа — одно правило для всех стартёров», «507 до GPU, инфра ≠ вина ноды», «цена по переписи».
- **Долг (записать, не делать):** приёмник на отдельный том/объектное хранилище — single point of
  failure на общем диске с продом (Codex №2).

## Файлы к изменению
- [x] новые: `tools/scout/salad/sink_health.py`, `salad_groups.py`, `tools/scout/rules/salad-groups.json`, `Dockerfile.patch`
- [x] `tools/scout/salad/ssh_run.py`, `node_health.py`, `batch_show.py`, `money_guard.py`, `receiver.py`
- [x] `idle_guard.sh`, `batch_window.sh`, `receiver_purge.py`, `tier_compare.py`, `pool_hours.py`
- [x] `topview_render.py`, `cabinet_front.py`, `apply_repairs.py`; `tools/scout/alert.sh`
- [x] ребилд: `preprocess.py`, `worker.py`, `pipeline.py`, `storage.py`
- [x] `infra/server/cleanup.sh`, `disk-watchdog.sh`, `systemd/remlab-watchdog.timer`; `.github/workflows/deploy.yml`; `deploy.sh`; `caddy/Caddyfile`; `docker-compose.yml`
- [x] `tests_pool.py` (+12 случаев), `README.md`; удалить `container-group.json`
- [x] `.memory_bank/`: план → `plans/mesh-pool-hardening.md`, ADR, `core/mesh-pipeline.md`, `deployment.md`

## Критерии приёмки
- [x] Стенд «ВСЁ ЗЕЛЁНОЕ» с новыми случаями; `py_compile` всех .py; `bash -n` скриптов
- [x] Канарейка + проба 15 МБ → 200; при `MESH_SINK_MARGIN_GB=100` конвейер не раздаёт (75), шлёт TG, запускает drain+purge
- [ ] В 15:00 UTC batch-группы гаснут и НЕ поднимаются до 09:00 (лог `ensure_group_started` — только low)
- [x] `alert.sh` → 1 при плохом токене; пульс пришёл в 08 UTC
- [ ] За сутки `earlyoom` пуст; `топ-вью: ok`, `приёмка: ok`; виды сверху у новых мешей
- [ ] `tier_compare --hours 24` — оплаченная цена, сходится с панелью ±10%
- [x] `ghcr…remlab-app` ≤ 3 образов; `df /` < 60%; `.staging` = 0 после двух циклов
- [ ] Ребилд: `input_failed` timeout/SSL ↓; `/ready`, `/job/<id>` отвечают; `alien_suspect` в манифестах
- [ ] Не задеты: `remnanode`, чужие правки (`hub_page.py`, `scene_mesh.py`), VPN

## Порядок раскатки — пул днём не останавливается
- **Фаза A (сейчас; серверные ПРАВКИ КОНФИГА не трогаем, только скрипты):** P0-3 первым (чтобы всё
  остальное было слышно) → серверные скрипты (cleanup, watchdog, app-mem) + Caddyfile в репо
  (коммит) → `idle_guard.sh`, `batch_window.sh`, `receiver_purge.py`, `apply_repairs.py`,
  `topview_render.py`, `cabinet_front.py` (новые процессы подхватят сами) → `ssh_run.py` +
  `node_health.py` + `sink_health.py` + `salad_groups.py` + JSON (ssh_run стартует свежим на
  пачку; стенд до копирования) → перезапуск сторожа (kill по PID из `ps -eo pid,comm`, НЕ `pkill -f`).
- **Фаза B (`batch_show.py`: P0-2, P1-6 обёртка, P1-9):** через флаг `draining` на границе пачки;
  до внедрения флага — в 15:00 UTC (batch и так гаснут).
- **Фаза C (пауза `draining`, 15:00 UTC):** ребилд P1-7 по одной группе; `mesh-receiver` в compose;
  `/ready` O(1) на приёмнике; CI-cleanup до pull.

## Критика Codex (04.09) — что принято, что отвергнуто
Принято: текст ошибки — только повод для проверки приёмника (№5); монитор в супервизоре + флаг
перед каждым заданием, write-canary при старте, `/ready` O(1) с резервом (№4); повтор при пустом
выводе небезопасен → `inflight`/`GET /job` в ребилде (№1); серверные миграции только в `draining`
(№3); cleanup до pull, под flock, по image ID всех контейнеров (№4, №6); `.staging` по двум
наблюдениям (№7); анализ SKU целиком в дочернем процессе, workers=1 (№8); отбор по состоянию вместо
`skip` (№9); `cached` не новый меш (№10); перепись — оценка с `unknown` (№11); `phase` +
`warm=false` при ошибке и миграция потребителей (№12); байты фото из `prepare` (№13);
`alert || true` под `set -e` (№14); `draining`+singleton+атомарный курсор вместо `kill -9` (№3).
Отвергнуто: S3/R2/отдельный диск (№2 — решение владельца, записано долгом); единый control-plane
с lease (№ порядок) — свод правил + singleton достаточен; ответы на вопросы 1–2 обрезаны —
принято своё: код 75 переиспользуем, но с немедленным drain+purge; idle_guard без стоп-файла
безопасен, потому что группы поднимает только singleton-конвейер.

## Definition of Done — память
- [ ] Копия плана в `.memory_bank/plans/mesh-pool-hardening.md` (status `in_progress` при старте)
- [ ] ADR в `decisions.md`; `core/mesh-pipeline.md`, `deployment.md`, `core/lessons.md`
- [ ] `/memory-check` выполнен, audit «чисто»

## Остаток (на 04.09 вечер) — что НЕ закрыто

1. **Пересадка снимает докачавшую ноду** (урок 402): `нода 674e0d46: 100%, темп 0.9%/мин →
   ещё 0 мин — ПЕРЕСАЖИВАЮ`. Правило темпа должно первым делом проверять терминальное состояние
   (100 % / остаток 0) и не трогать такие машины.
2. **Окно не гасит уже поднятую группу** (урок 400, ADR-0177): `autostart_policy: true` стартует
   группу при создании, `ensure_group_started` решает только за нас. Нужно создавать вне окна с
   `autostart_policy: false` + отдельное правило гашения по окну.
3. **`TOPVIEW_DEADLINE_S` 2400 → 1800** — правка в `batch_show.py` есть, применится при следующем
   старте конвейера.
4. ~~**Чистка приёмника при большом пуле**~~ — ЗАКРЫТО 04.09 вечером (ADR-0178, коммит
   `109aacf`). Оказалось глубже, чем «сократить период»: (а) удаление шло через `ssh rm -rf`
   мимо API приёмника, а тот вычитает байты только в своём `DELETE /prefix/...` — счётчик умел
   лишь расти и показывал 7.37 ГБ при реальных 5.13 (призрак 2.24 ГБ и погасил пул);
   (б) канарейка удаляла по неверному пути и оставляла ~1 МБ за проверку; (в) вся цепочка
   очистки жила внутри `batch_show`, поэтому исчезала ровно тогда, когда была нужнее всего.
   Сделано: удаление через API, `sink_keeper.sh` в кроне `*/15` (молчит, пока конвейер жив),
   ненулевой код при отказе удаления.
5. ~~**Не закоммичено**~~ — ЗАКРЫТО, коммит `9ce0592` (`batch_show.py`, `money_guard.py`,
   `rules/salad-groups.json`, `migrate_groups.py`). Чужое (`hub_page.py`, `scene_mesh.py`) не
   тронуто. Оболочка чинилась не так, как думали: причина — `EDQUOT` (квота `/tmp`), а не
   `pkill`. Поставлен гард `tools/hooks/guard-bash.mjs` (урок 407).

7. **НОВОЕ — приёмка не успевает за генерацией (замер 04.09):** `apply_repairs` проверяет 20
   мешей за прогон (`ACCEPT_CAP` 5 × `ACCEPT_ROUNDS` 4, ≈2.4 мин на раунд) против ~100
   генерируемых в час; в очереди на перегон 623. Удалять с транзита можно только принятое, поэтому
   очередь приёмки = потолок очистки. В стороже поднято до `ACCEPT_ROUNDS=8` (память держит
   `ACCEPT_CAP`, каждый раунд — свежий процесс). Нужен замер, хватает ли этого при живом пуле.
8. **НОВОЕ — пул не встаёт сам после уборки:** `money_guard` метит любой красный приёмник как
   `shared_infra`, а стоп-файл снимает только человек. Нужны различимые причины (`sink_capacity`,
   `sink_unreachable`, `sink_auth`, `silence`, `no_credits`) и автоснятие ТОЛЬКО для ёмкости —
   после успешной уборки, зелёного здоровья и канарейки. Смена контракта безопасности →
   решение владельца (разбор Codex 04.09).
9. **НОВОЕ — `receiver_purge` доказывает не тот факт (Codex):** разрешает удаление по готовности
   SKU, а не по конкретной ревизии префикса — старое `ready` может авторизовать удаление свежей
   незарегистрированной ревизии. Ключи расходятся: реестр `sku|source_sha|v1`, привязка `sku|job`.
10. ~~**Тест держится за живой файл запрета**~~ — ЗАКРЫТО 05.09 (коммит `6b1f5b9`). Оказалось
   хуже, чем «падает не вовремя»: случай ПИСАЛ фальшивый запрет в боевой путь, и пока тот лежал,
   работающий конвейер его читал и не поднимал группы — прогон стенда вмешивался в прод.
   `B.HALT` подменяется временным путём. Тот же класс дефекта закрыт у `case_window_gate`
   (читал живой `salad-groups.json`) и `case_group_status_mixed` (требовал боевой `SALAD_API_KEY`).
6. **Первое чистое сравнение тарифов** — окно 09–15 UTC 05.09 (все прежние замеры загрязнены,
   урок 401).

## Лог выполнения
- 2026-09-04 — план создан (draft); разведка 3 агента + архитектор; критика Codex учтена
- 2026-09-04 — «деплой»: старт фазы A (оповещение → серверные скрипты → локальные скрипты → транспорт)
- 2026-09-04 — фаза A и B выполнены (коммиты be1eefa…0da0fdf): сервер, стопоры, приёмник ДО GPU, транспорт, OOM, цена, горячий перезапуск; образ localpaint2 собран и выгружен (digest f9a9ad6d…); фаза C (миграция приёмника в compose + новые группы) — в окно 15:00 UTC
- 2026-09-04 (вечер) — фаза C выполнена: приёмник переехал в compose (коммит 48bc1eb), группы
  пересозданы на `localpaint2` (`mesh-low-4`, `mesh-low-5`, `mesh-batch-3` — `migrate_groups.py
  --apply`), 21 машина в работе, приёмник вычищен (89 наборов, 15.7 ГБ). Владелец поправил два
  моих вывода: batch не удалять, а держать по окну (ADR-0177), и `mesh-batch-3` работает из-за
  `autostart_policy`, а не вопреки окну. Остаток — выше; статус плана `in_progress` до суточных
  замеров (earlyoom, `tier_compare` против панели, доля `input_failed` после ребилда).
