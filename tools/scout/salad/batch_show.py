#!/usr/bin/env python3
"""Конвейер показа: генерим пачками по N, после каждой — свежая галерея владельцу.

Просьба владельца 30.08: «показывай пачками по 5, я проверяю и говорю правки по ходу —
тогда сразу берём все 500». Поэтому цикл: 5 заданий → стащить с exit-fi → пересобрать
галерею (свежие СВЕРХУ) → опубликовать на тот же адрес. Владелец просто обновляет страницу.
Правки между пачками — меняем параметры/код и продолжаем с места: сделанное не перегоняется
(идемпотентность по complete.json).

  SALAD_API_KEY=... ~/venvs/scout/bin/python batch_show.py --batch 5          # весь план
  SALAD_API_KEY=... ~/venvs/scout/bin/python batch_show.py --batch 5 --max 50 # первые 50
"""
import concurrent.futures as cf
import datetime
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.environ.get('MESH_SAMPLE') or os.path.join(HERE, '..', 'mesh-pilot-sample.json')
# КУРСОР — ПО ИМЕНИ СНИМКА (05.09, план mesh-owner-audit). Позиционный `done` осмыслен только для
# того файла, по которому шёл: общий `mesh-batch-progress.json` после пересборки очереди указывал
# бы в другой порядок и повторно гнал бы уже сделанное (регламент rules/mesh-priority.json
# §identity). Старый общий файл читается один раз — для снимка v1, по которому он и был набит.
DONE = SAMPLE + '.progress.json'
LEGACY_DONE = os.path.join(HERE, '..', 'mesh-batch-progress.json')


def load_cursor() -> int:
    if os.path.exists(DONE):
        return int(json.load(open(DONE)).get('done', 0))
    if os.path.basename(SAMPLE) == 'mesh-queue-v1.json' and os.path.exists(LEGACY_DONE):
        return int(json.load(open(LEGACY_DONE)).get('done', 0))
    return 0
PY = os.path.expanduser('~/venvs/scout/bin/python')
NO_CAPACITY = 75   # код ssh_run «нет тёплых нод» — ждём и повторяем, это не авария
# 75 = EX_TEMPFAIL: «сейчас не смог, повтори позже». Тот же смысл у drain.sh, когда замок
# занят другим процессом: работа НЕ сделана, но это не поломка (маркер DRAIN_BUSY).
BUSY = 75

# Сборка и публикация галереи — по флагу (владелец 31.08: ночью не нужна, соберу утром руками).
# Данные при этом копятся как обычно: стаскивание, реестр, ремонт, ориентация, топ-вью работают.
SHOW_GALLERY = os.environ.get('MESH_SHOW_GALLERY', '0') == '1'
SHOW_STEPS = ((
    ('галерея', f'GALLERY_SRC=$HOME/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2 {PY} {HERE}/gallery_build.py'),
    # ПУБЛИКУЕМ ТОЛЬКО НОВОЕ (01.09). `scp -r ...gallery/*` гнал ВЕСЬ каталог заново — 1.6 ГБ и
    # многие минуты на каждую пачку, при том что меняются единицы моделей. rsync есть на обеих
    # машинах; он сверяет размер и время и льёт только изменившееся.
    ('публикую', 'rsync -a --info=stats1 -e "ssh -p 22222 -o BatchMode=yes" '
                 '$HOME/scout-scenes/mesh-pilot-gallery/ '
                 'root@89.167.127.0:/opt/remlab/test/mesh-pilot10/'),
    # каталог мешей — НАКОПИТЕЛЬНЫЙ: scp выше уже положил локальный index поверх
    # прода, поэтому сразу за ним доливаем то, что там было (см. publish_merge.py).
    ('индекс-слияние', f'{PY} {HERE}/publish_merge.py $HOME/scout-scenes/mesh-pilot-gallery/mesh-index.json https://remont-lab.online/test/mesh-pilot10/mesh-index.json root@89.167.127.0:/opt/remlab/test/mesh-pilot10/mesh-index.json'),
) if SHOW_GALLERY else ())


def sh(cmd, timeout=3600):
    """Шаг оболочки. Таймаут не роняет конвейер исключением (иначе `finale()` не отработает и
    группа останется тарифицироваться) и НЕ оставляет сирот — вся механика в `proc_run`."""
    return PR.run_step(cmd, timeout)


def run_summary(out: str) -> dict | None:
    """Машинно-читаемый итог прогона (ssh_run печатает RUN_SUMMARY {...}).

    По нему двигаем курсор `done`. Раньше он рос на ВЕСЬ размер пачки независимо от того,
    сколько заданий реально закрыто, — провалившиеся терялись молча (31.08)."""
    for line in reversed(out.splitlines()):
        if line.startswith('RUN_SUMMARY '):
            try:
                return json.loads(line[len('RUN_SUMMARY '):])
            except json.JSONDecodeError:
                return None
    return None


# Состояния Salad, при которых группа УЖЕ поднята и /start ей не нужен. Список положительный:
# наблюдались `running`, `deploying`, `stopped`; остальные взяты из документации Salad. Всё, чего
# тут нет (включая None «не смогли узнать»), считается поводом попробовать поднять — молча
# записывать незнакомое состояние в живые нельзя, иначе группу не поднимет никто.
GROUP_UP = ('running', 'deploying', 'pending', 'allocating', 'starting', 'downloading')


def group_states() -> dict:
    """Состояние КАЖДОЙ группы: {имя: 'running'|'stopped'|...|None}. None — не смогли узнать.

    ЧЕРЕЗ CURL, А НЕ urllib: WAF Salad режет python-UA, и запрос молча падал в None
    (ADR-0137). На этом 04.09 погорела проверка состояния после старта — она показала
    «состояние None» у живой группы. А ещё от неё зависит распознавание «кончился баланс»,
    то есть молчание тут стоит денег.
    """
    import json as _j
    out = {}
    for grp in SG.groups_from_env():
        try:
            r = subprocess.run(
                ['curl', '-sS', '--max-time', '30', '-H', f'Salad-Api-Key: {os.environ["SALAD_API_KEY"]}',
                 f'https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers/{grp}'],
                capture_output=True, text=True, timeout=45)
            if r.returncode != 0:   # молчаливый curl оставлял состояние None без причины
                print(f'группа {grp}: curl rc={r.returncode} {r.stderr.strip()[:80]}', flush=True)
            out[grp] = (_j.loads(r.stdout).get('current_state') or {}).get('status')
        except Exception as e:  # noqa: BLE001 — но НЕ молча: None здесь маскирует и «нет денег»
            print(f'группа {grp}: состояние не узнать ({type(e).__name__})', flush=True)
            out[grp] = None
    return out


def group_status(states: dict | None = None) -> str | None:
    """'stopped' только если ВСЕ группы остановлены (мультигруппы через запятую)."""
    sts = list((group_states() if states is None else states).values())
    if sts and all(s == 'stopped' for s in sts):
        return 'stopped'
    # 04.09: раньше возвращался `sts[0]` — статус ПЕРВОЙ группы. Первой в SALAD_GROUP стояла
    # mesh-batch-1, которую крон гасит в 15:00 UTC, и любое «нет тёплых нод» после этого читалось
    # как «пул остановлен» → повторный /start ВСЕМ группам, включая погашенную намеренно. Итог
    # вечера 03.09: 57 машин дешёвого тарифа прогрелись, 0 мешей, 134 ₽. Смешанное состояние —
    # это состояние ЖИВОЙ части пула.
    live = [s for s in sts if s and s != 'stopped']
    return live[0] if live else (sts[0] if sts else None)


HALT = os.path.expanduser('~/scout-scenes/mesh-group-halt.json')
# ГОРЯЧИЙ ПЕРЕЗАПУСК (04.09, Codex №3). Любой перезапуск конвейера через finale() гасил группы, а
# `kill -9` оставлял сироту ssh_run, и новый конвейер раздал бы те же задания второй раз. Теперь:
# файл DRAINING = «доделай текущую пачку и выйди, группы НЕ гаси»; замок LOCK = конвейер один.
DRAINING = os.path.expanduser('~/scout-scenes/mesh-draining')
LOCK = os.path.expanduser('~/scout-scenes/.batch_show.lock')
_lock_fh = None
_STARTED = False          # finale() гасит группы только у конвейера, который их реально вёл


def acquire_singleton() -> None:
    """Второй конвейер рядом с первым — двойная раздача одних и тех же заданий. Замок держится
    до конца процесса; занят — выходим сразу с понятным текстом."""
    global _lock_fh
    import fcntl
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    _lock_fh = open(LOCK, 'w')
    try:
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit(f'конвейер уже работает (замок {LOCK}) — для перезапуска: touch {DRAINING}, '
                         f'дождись выхода старого, запусти новый')
    _lock_fh.write(str(os.getpid()))
    _lock_fh.flush()
    global _STARTED
    _STARTED = True


def wait_orphans(timeout_s: float = 1500) -> None:
    """Сироты прошлого конвейера (ssh_run, drain, шаги разбора) должны доработать: их результаты
    лягут в журнал, курсор они не двигают, пачка повторится как `cached`. Ждём, а не убиваем."""
    pat = r'[s]sh_run\.py|[d]rain\.sh|[t]opview_render|[a]pply_repairs|[o]rient_worker|[r]eceiver_purge'
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        r = subprocess.run(['pgrep', '-fa', pat], capture_output=True, text=True)
        alive = [ln for ln in r.stdout.splitlines() if str(os.getpid()) not in ln.split()[:1]]
        if not alive:
            return
        print(f'жду сирот прошлого конвейера ({len(alive)}): {alive[0][:90]}', flush=True)
        time.sleep(30)
    print('сироты не завершились за отведённое время — продолжаю; повторы вернутся как cached', flush=True)


def save_cursor(done: int) -> None:
    """Курсор пачек — атомарно: прямой `json.dump(open(..., 'w'))` при падении посреди записи
    оставлял пустой файл, и конвейер начинал с нуля."""
    tmp = DONE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'done': done, 'at': time.time()}, f)
    os.replace(tmp, DONE)


def halt_reason() -> str:
    """Почему группу запрещено поднимать. Пусто — запрета нет.

    СТОП-ФАЙЛ СИЛЬНЕЕ АВТОСТАРТА (03.09). Ночью сторож денег честно погасил группу на 125
    нодо-минутах молчания — а через минуту `ensure_group_started` поднял её обратно, потому что
    «остановлена» он трактует как «надо стартовать». Дальше сторож (одноразовый) уже вышел, и
    семь часов ноды крутились без единого меша за наши деньги. Два процесса с противоположными
    целями обязаны иметь старшинство: намеренная остановка — это решение, а не сбой.
    Снимает запрет ЧЕЛОВЕК (удалить файл) — после того, как разобрался, почему не было мешей.
    """
    try:
        with open(HALT, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:  # noqa: BLE001 — нет файла или битый: запрета нет
        return ''
    return str(d.get('why') or 'без причины')


def _no_credits_alert() -> None:
    """Одно сообщение в час: пул не поднимется, пока владелец не пополнит баланс."""
    import sink_health as SH
    SH.alert_throttled('Меши: на Salad КОНЧИЛСЯ БАЛАНС (no_credits_available) — группы не '
                       'поднимаются, мешей нет. Пополни баланс; конвейер поднимет группы сам.')


def ensure_group_started():
    """Группа на Salad может СОЗДАТЬСЯ остановленной (ловили дважды: pool5, mesh-run3) —
    и ожидание тёплой ноды у выключенной группы длится вечно. Стартуем явно; 400 = уже
    стартует, это не ошибка."""
    import urllib.error
    import urllib.request
    why = halt_reason()
    if why:
        print(f'!! группу поднимать ЗАПРЕЩЕНО: {why}\n'
              f'   снять запрет: rm {HALT} (сперва разберись, почему не было мешей)', flush=True)
        return False
    ok = False
    # ГРУППУ ВНЕ ОКНА НЕ ПОДНИМАЕТ НИКТО (04.09, свод правил стопоров). Окно живёт в
    # rules/salad-groups.json; у low-групп окна нет — они круглосуточные. Пропущенные печатаем,
    # чтобы в логе было видно, что это решение, а не сбой.
    skipped = [g for g in SG.groups_from_env() if not SG.allowed_now(g)]
    if skipped:
        print(f'группы вне окна, не поднимаю: {", ".join(skipped)}', flush=True)
    # УЖЕ ПОДНЯТУЮ ГРУППУ НЕ СТАРТУЕМ ПОВТОРНО (05.09). Salad на /start живой группы отвечает
    # `400 replicas_quota_exceeded` (квота 50 реплик уже разобрана ею же). Это не отказ, но в
    # логе он неотличим от настоящей беды — а `no_credits_available` приходит тем же кодом 400
    # (урок 404). Спрашиваем состояние и трогаем только то, что реально лежит.
    # Список УЖЕ ПОДНЯТЫХ — положительный (`GROUP_UP`), а не «всё, кроме stopped/failed»: при
    # отрицательном списке незнакомое терминальное состояние молча считалось бы живым, и группу
    # не поднял бы никто (замечание Codex 05.09). Незнакомое и нечитаемое состояние — повод
    # ПОПРОБОВАТЬ поднять и сказать об этом в лог: пул, стоящий из-за сбоя API, дороже лишней
    # строки 400 в логе.
    states = group_states()
    allowed = [g for g in SG.groups_from_env() if SG.allowed_now(g)]
    up = [g for g in allowed if states.get(g) in GROUP_UP]
    odd = [g for g in allowed if g not in up and states.get(g) not in ('stopped', 'failed')]
    if up:
        print(f'уже подняты, старт не нужен: {", ".join(f"{g} ({states[g]})" for g in up)}', flush=True)
        ok = True
    if odd:
        print('состояние не пойму, всё равно пробую поднять: '
              f'{", ".join(f"{g} ({states.get(g)})" for g in odd)}', flush=True)
    started = []
    for grp in [g for g in allowed if g not in up]:
      try:
        req = urllib.request.Request(
            f"https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers/{grp}/start",
            data=b'', method='POST',
            headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'],
                     'User-Agent': 'remlab-mesh/1.0'})
        urllib.request.urlopen(req, timeout=60).read()
        print(f'группа {grp}: start отправлен', flush=True)
        started.append(grp)
        ok = True
      except urllib.error.HTTPError as e:
        body = e.read()[:300].decode(errors='replace')
        if 'no_credits_available' in body:
            # КОНЧИЛСЯ БАЛАНС (04.09): раньше это выглядело как «start → HTTP Error 400» и
            # догадка «похоже, кончился баланс». Теперь — прямым текстом и в телеграм (раз в час),
            # потому что без пополнения ничего не поднимется, а конвейер молча ждал бы вечно.
            print(f'группа {grp}: НЕТ КРЕДИТОВ на Salad (no_credits_available) — нужно пополнение', flush=True)
            _no_credits_alert()
        else:
            print(f'группа {grp}: start → HTTP {e.code} {body[:80]}', flush=True)
      except Exception as e:  # noqa: BLE001 — сеть не должна валить конвейер
        print(f'группа {grp}: start → {str(e)[:80]}', flush=True)
    # ПРОВЕРЯЕМ, А НЕ ПРЕДПОЛАГАЕМ. Раньше 400 трактовался как «уже запущена», но он же
    # приходит, когда группа ещё СОЗДАЁТСЯ и стартовать нечего: 01.09 новая группа так и
    # осталась stopped, конвейер час ждал тёплых нод, а заметил это владелец в портале.
    after = group_states()
    st = group_status(after)
    if st in ('stopped', 'failed'):
        print(f'!! группа в состоянии {st} — ПОВТОРЯЮ запуск', flush=True)
        # ПОВТОРЯЕМ ТОЛЬКО ПО ЛЕЖАЩИМ И ТОЛЬКО ПО НЕТРОНУТЫМ. Живой группе повторный /start
        # вернёт то же `400 replicas_quota_exceeded`; а группа, которой мы только что послали
        # start, ещё не успела сменить состояние — API согласуется не мгновенно, и повтор здесь
        # был бы гонкой с самим собой (замечание Codex 05.09).
        for grp in [g for g in SG.groups_from_env()
                    if SG.allowed_now(g) and g not in started
                    and after.get(grp) in ('stopped', 'failed', None)]:
            try:
                import urllib.request as _u
                _u.urlopen(_u.Request(
                    f'https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers/{grp}/start',
                    data=b'', method='POST',
                    headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'],
                             'User-Agent': 'remlab-mesh/1.0'}), timeout=60).read()
                ok = True
            except Exception as e2:  # noqa: BLE001
                print(f'группа {grp}: повторный start → {str(e2)[:80]}', flush=True)
        st = group_status()
    print(f'группа: состояние {st}', flush=True)
    return ok


_PULL_HIST: dict = {}     # instance_id → наблюдения за закачкой образа
# Бюджет пересадок и счётчик сбоев нод переехали в `node_health` — ОДИН файл на все процессы
# прогона. Раньше журнал жил в памяти, а пересадку зовут двое (этот супервизор и `ssh_run`
# каждой пачки): два независимых бюджета вдвоём могли выкосить весь пул (Codex 01.09).

# ПРАВИЛО СНЯТИЯ МЕДЛЕННОЙ НОДЫ (владелец 31.08, переформулировано после разбора).
# Считаем не «скорость за окно», а ВОЗРАСТ и ОСТАТОК. Прошлая формула («<15% за 5 мин»)
# брала базовую точку один раз и не обновляла её, поэтому средняя скорость с ростом возраста
# падала и правило снимало ноды на 83% и 90% — замена начинала с нуля (поймано 31.08).
# Здоровая машина забирает наш образ за 25–35 мин, отсюда ступени.
# Пороги ужаты вдвое (владелец 31.08: «зарежь вдвое все эти минуты»).
# ПОРОГИ ПО ЗАМЕРУ, А НЕ ПО ПАМЯТИ О ПРОШЛОМ ОБРАЗЕ (02.09).
# Прежние ступени (5 мин→5%, 10→25%, 20→60%) считались от «здоровая машина берёт образ за
# 25-35 мин». Замер 01-02.09 на боевом образе 20.7 ГБ: реальная скорость 0.25-1% в минуту,
# то есть полная закачка 100-400 минут. При старых ступенях здоровая машина к пятой минуте
# имеет 1-5% и объявляется браком — так мы трижды за сутки выкосили пул, в том числе ноду
# на 70%. Ступени растянуты вчетверо и проверены по наблюдаемой скорости.
STAGES = [(1200.0, 0.05), (2400.0, 0.25), (4800.0, 0.60)]  # 20 мин→5%, 40 мин→25%, 80 мин→60%
# БЕЗ ДВИЖЕНИЯ — 15 МИНУТ, НЕ 5 (02.09). Прежние пять минут сняли за час две ноды
# («нет движения 5 мин», «нет движения 8 мин»), а каждая уносила уже скачанные гигабайты:
# замена начинала 26 ГБ с нуля, и пул не мог наполниться. `pulling_progress` у Salad
# приблизителен и на распаковке крупного слоя честно стоит на месте — это не поломка.
STALL_S = float(os.environ.get('MESH_PULL_STALL_S', '900'))           # без движения 15 мин
STALL_MIN = float(os.environ.get('MESH_PULL_STALL_MIN', '0.01'))      # прирост <1% = стоит
FINISH_GUARD = float(os.environ.get('MESH_FINISH_GUARD', '0.80'))     # выше — судим по ОСТАТКУ
# В зоне финиша не «терпим бесконечно», а требуем уложиться в бюджет, пропорциональный
# остатку (владелец: «терпение к скорости повысить, динамически смотря сколько осталось»).
# Ступени задают норму ~3%/мин; у почти доехавшей требуем хотя бы половину этого темпа.
FINISH_RATE_MIN = float(os.environ.get('MESH_FINISH_RATE', '0.015'))  # доля образа в минуту
# Сколько нод должно РАБОТАТЬ, чтобы пересадка отстающего вообще имела смысл.
MIN_WORKING_TO_CULL = int(os.environ.get('MESH_MIN_WORKING_TO_CULL', '2'))
sys.path.insert(0, HERE)
import node_health as NH  # noqa: E402 — общий бюджет пересадок и здоровье нод
import proc_run as PR     # noqa: E402 — запуск шага без сирот (ОДИН на batch_show и ssh_run)
import ssh_run as SR      # noqa: E402 — канонический плоский список заданий (`plan_jobs`)
import salad_groups as SG  # noqa: E402 — тариф/окно группы: ОДИН источник (rules/salad-groups.json)

# ОРИЕНТАЦИЯ МИКРОПАЧКАМИ (01.09). Один заход на `--limit 200` вырастал до 8.6 ГБ и его
# убивал earlyoom — шаг не «тормозил», а НЕ ДОДЕЛЫВАЛ работу, и пачка оставалась без
# разметки. Гоняем несколько коротких заходов: память возвращается ОС между процессами.
ORIENT_LIMIT = int(os.environ.get('MESH_ORIENT_LIMIT', '20'))
ORIENT_PASSES = int(os.environ.get('MESH_ORIENT_PASSES', '4'))
ORIENT_CMD = (f'for i in $(seq {ORIENT_PASSES}); do '
              f'{PY} {os.path.join(HERE, "..", "orient_worker.py")} '
              f'--run --limit {ORIENT_LIMIT} --vlm || exit $?; done')

# ТОП-ВЬЮ — ПРОХОДАМИ «ПОКА ЕСТЬ НОВЫЕ» (04.09). Прежние шесть проходов по TOPVIEW_LIMIT=120
# со сдвигом считали ПРОСМОТРЕННЫЕ, а память растёт от НОВЫХ: 120 новых в одном процессе — это
# ~10 ГБ (trimesh +100 МБ/меш) и earlyoom каждый цикл, виды сверху не строились вовсе. К тому же
# `|| exit $?` обрывал остальные проходы на первом же упавшем, а сдвиг с нуля при каждом запуске
# не давал очереди дойти до хвоста каталога. Теперь каждый проход — отдельный процесс, берёт не
# больше TOPVIEW_NEW_CAP новых (печатает `TOPVIEW_NEW N`), обёртка повторяет, пока N>0, до
# общего дедлайна; упавший проход считается, но не останавливает остальные.
POST_EVERY_S = float(os.environ.get('MESH_POST_EVERY_S', '900'))   # разбор каждые 15 мин
TOPVIEW_NEW_CAP = int(os.environ.get('MESH_TOPVIEW_NEW_CAP', '20'))
# Дедлайн ВНУТРЕННЕГО цикла проходов. Держим заметно ниже таймаута шага (2700 с в `_run_post`):
# 04.09 при 2400 последний проход не успевал завершиться в оставшиеся пять минут, и шаг падал
# «топ-вью: СБОЙ ТАЙМАУТ 2700с», а весь разбор растягивался на 75 минут. Один проход — до 420 с
# (TOPVIEW_BUDGET_S), поэтому запас берём с двумя проходами: 1800 + 420 < 2700.
TOPVIEW_DEADLINE_S = int(os.environ.get('MESH_TOPVIEW_DEADLINE_S', '1800'))
TOPVIEW_CMD = (f'fails=0; passes=0; t0=$SECONDS; '
               f'while [ $((SECONDS - t0)) -lt {TOPVIEW_DEADLINE_S} ]; do '
               f'  out=$(TOPVIEW_NEW_CAP={TOPVIEW_NEW_CAP} TOPVIEW_BUDGET_S=420 {PY} {HERE}/topview_render.py 2>&1); rc=$?; '
               f'  echo "$out" | tail -4; passes=$((passes+1)); '
               f'  [ $rc -ne 0 ] && fails=$((fails+1)); '
               f'  n=$(echo "$out" | sed -n "s/^TOPVIEW_NEW //p" | tail -1); '
               f'  [ "${{n:-0}}" -gt 0 ] || break; '
               f'  [ $fails -ge 3 ] && break; '
               f'done; echo "топ-вью: проходов $passes, с ошибкой $fails"; '
               f'[ $fails -lt $passes ] || [ $passes -eq 0 ]')


def iso_age_s(ts: str | None, now: float) -> float | None:
    """Возраст состояния по часам платформы (`update_time` инстанса).

    Нужен потому, что наш собственный отсчёт обнуляется при каждом перезапуске конвейера:
    31.08 нода качала 22 минуты на 4%, а правило считало её «только что увиденной» и ждало
    свою десятую минуту заново. Часы Salad переживают наши перезапуски."""
    if not ts:
        return None
    try:
        head, tz = (ts[:-6], ts[-6:]) if ('+' in ts[10:] or ts.endswith('Z')) else (ts, '')
        head = head[:26]                      # у Salad 7 знаков после точки — datetime берёт 6
        age = now - datetime.datetime.fromisoformat(
            head + ('+00:00' if tz in ('', 'Z') else tz)).timestamp()
    except Exception:  # noqa: BLE001 — формат времени не должен ломать конвейер
        return None
    return age if 0 <= age < 86400 else None


def _rate_per_min(obs: list) -> float | None:
    """Скорость закачки по наблюдениям последних минут (доля образа в минуту).

    Меньше трёх минут наблюдений — None: судить не по чему, ноду не трогаем."""
    if len(obs) < 2:
        return None
    (t0, p0), (t1, p1) = obs[0], obs[-1]
    return (p1 - p0) / ((t1 - t0) / 60) if t1 - t0 >= 180 else None


def cull_verdict(age_s: float, progress: float, since_move_s: float,
                 rate_per_min: float | None = None) -> str | None:
    """Снимать ли ноду. Чистая функция — её и проверяет стенд.

    `rate_per_min` — измеренная скорость закачки (доля образа в минуту); нужна только в зоне
    финиша, где решает не возраст, а успеет ли нода доехать. Возвращает причину или None."""
    if since_move_s >= STALL_S:
        return f'нет движения {int(since_move_s / 60)} мин'
    if progress >= FINISH_GUARD:
        # Осталось немного: считаем ETA по факту. Замена стартует с нуля, поэтому терпим,
        # пока нода держит хотя бы половину нормального темпа.
        if rate_per_min is not None and 0 <= rate_per_min < FINISH_RATE_MIN:
            eta = (1 - progress) / rate_per_min if rate_per_min > 0 else 999
            return f'{progress:.0%}, темп {rate_per_min:.1%}/мин → ещё {min(eta, 999):.0f} мин'
        return None
    for stage_s, need in STAGES:
        if age_s >= stage_s and progress < need:
            return f'{progress:.0%} к {int(stage_s / 60)}-й минуте (норма {need:.0%})'
    return None


def cull_slow_pulls() -> None:
    """АВТО-ПЕРЕСАДКА МЕДЛЕННЫХ НОД (владелец 31.08: «автоматом отрубай машины, если
    скорость оч низкая»). Решение — `cull_verdict`; здесь опрос API, история наблюдений
    и предохранители от бесконечной чехарды."""
    import json as _j
    import urllib.request as _u
    now = time.time()
    seen = set()
    for grp in SG.groups_from_env():
        base = f'https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers/{grp}'
        try:
            req = _u.Request(base + '/instances',
                             headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'],
                                      'User-Agent': 'remlab-mesh/1.0'})
            with _u.urlopen(req, timeout=30) as r:
                ins = _j.load(r).get('instances') or []
        except Exception:  # noqa: BLE001 — сеть не валит конвейер И не стирает историю
            return
        cands = []
        for i in ins:
            iid = i.get('id')
            raw = i.get('pulling_progress')
            if not iid or i.get('state') != 'downloading' or raw is None:
                continue             # прогресс неизвестен — не судим
            seen.add(iid)
            prog = float(raw)
            h = _PULL_HIST.setdefault(iid, {'first': now, 'best': prog, 'moved': now,
                                            'obs': [(now, prog)]})
            if prog < h['best'] - 0.10:          # откат >10 п.п. = загрузка началась заново
                h.update(first=now, best=prog, moved=now, obs=[(now, prog)])
            else:
                if prog > h['best'] + STALL_MIN:
                    h.update(best=prog, moved=now)
                h['obs'] = [(t, p) for t, p in h['obs'] + [(now, prog)] if now - t <= 900]
            age = max(now - h['first'], iso_age_s(i.get('update_time'), now) or 0)
            why = cull_verdict(age, h['best'], now - h['moved'], _rate_per_min(h['obs']))
            if why:
                cands.append((h['best'], iid, why))
        # ПОКА НИКТО НЕ РАБОТАЕТ — НЕ ТРОГАЕМ НИКОГО (01.09, дважды за день).
        # Пересадка имеет смысл, только если есть кем работать, пока замена качает. Если
        # работающих нод НЕТ, замена отстающего — чистый убыток: он качал полчаса, новый
        # начнёт с нуля, а на тарифе batch машину могут и не дать. Так мы убили ноду на 70%
        # («58% к 20-й минуте при норме 60%») и остались с пустым пулом.
        running = sum(1 for i in ins if i.get('state') == 'running')
        if running < MIN_WORKING_TO_CULL:
            if cands:
                print(f'  работающих нод {running} — отстающих не трогаю, заменять некем '
                      f'(кандидатов было {len(cands)})', flush=True)
            continue
        # ЕСЛИ НИЖЕ НОРМЫ ПОЧТИ ВЕСЬ ПУЛ — НЕВЕРНА НОРМА, А НЕ МАШИНЫ (01.09).
        # Пороги настраивались, когда образ был разослан по сети Salad и качался за 25-35 мин.
        # После смены образа кэш холодный: машина на 1-2% к пятой минуте — это норма, а не
        # брак. Мы же пересаживали таких, замена начинала с нуля, и круг повторялся — 8 слотов
        # из 10 застряли в «выделении». Тот же принцип уже стоит на отказах заданий
        # (`node_health.fleet_wide`): общая беда лечится не заменой машин.
        pulling = [i for i in ins if i.get('state') == 'downloading']
        if pulling and len(cands) >= max(2, len(pulling) * 0.5):
            print(f'  медленно качают {len(cands)} из {len(pulling)} — это образ или сеть, '
                  f'а не машины: пересадку пропускаю', flush=True)
            continue
        for prog, iid, why in sorted(cands):            # сперва самые безнадёжные
            # Слот берём ПОШТУЧНО и прямо перед пересадкой: бюджет общий с предохранителем
            # битой ноды (файл `node_health`), и резервировать его впрок значит отнимать
            # пересадки у того, кому они нужнее. Пусто — на этом тике больше не пересаживаем.
            if not NH.take_cull_slot():
                break
            print(f'нода {iid[:8]} ({grp}): {why} — ПЕРЕСАЖИВАЮ (reallocate)', flush=True)
            NH.reallocate(grp, iid, why)
            _PULL_HIST.pop(iid, None)
    for iid in [k for k in _PULL_HIST if k not in seen]:
        _PULL_HIST.pop(iid, None)


ZOMBIE_MIN_MIN = float(os.environ.get('MESH_ZOMBIE_MIN_MIN', '10'))


def cull_dead_warmups() -> None:
    """ПЕРЕСАДКА «ЖИВЫХ ЗОМБИ» — нод, которые платно висят с намертво упавшим прогревом.

    ЗАЧЕМ (02.09). Воркер выставляет `warm=true` в `finally`, то есть и после провала прогрева
    (`worker.py`). Платформа видит такую ноду как Running и держит её часами, мы её справедливо
    не берём (`ssh_run.probe_warm`) — и слот стоит пустым за наши деньги. В тот день две ноды
    провисели 279 и 76 минут с `done: 0` и `gpu_seconds: 0.0`; за смену 81 отказ прогрева.
    Старая пересадка сюда не смотрела: она судила только тех, кто ещё качает образ.

    ПРЕДОХРАНИТЕЛЬ (совет Codex 02.09, принят): одинаковая ошибка на половине пула — это наша
    беда, а не машин (так было и с DINOv2: пересаживать бесполезно, заменят таким же). Тогда
    только пишем в лог. Тот же принцип уже стоит на отказах заданий (`node_health.fleet_wide`)
    и на медленной закачке.
    """
    import json as _j
    import urllib.request as _u
    for grp in SG.groups_from_env():
        base = f'https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers/{grp}'
        try:
            req = _u.Request(base + '/instances',
                             headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'],
                                      'User-Agent': 'remlab-mesh/1.0'})
            with _u.urlopen(req, timeout=30) as r:
                ins = _j.load(r).get('instances') or []
        except Exception:  # noqa: BLE001 — сеть не валит конвейер
            return
        now = time.time()
        live = [i for i in ins if i.get('state') == 'running' and i.get('id') and i.get('ssh_port')
                # молодую ноду не судим: она может быть в середине прогрева
                and (iso_age_s(i.get('update_time'), now) or 0) >= ZOMBIE_MIN_MIN * 60]
        if not live:
            return
        ports = [int(i['ssh_port']) for i in live]
        with cf.ThreadPoolExecutor(max_workers=min(6, len(ports))) as ex:
            health = dict(zip(ports, ex.map(SR.probe_health, ports)))

        def _fault(inst) -> str:
            h = health.get(int(inst['ssh_port']))
            # НЕМАЯ НОДА — ТОЖЕ МЁРТВАЯ (03.09). В ночь на 03.09 одна нода семь часов была
            # `running` и не отвечала на пробу (`TimeoutExpired`, 51 с): конвейер 71 раз написал
            # «нет тёплых нод — жду 3 мин», а мы за неё платили. Прежняя проверка ловила только
            # тех, кто ОТВЕЧАЕТ и признаётся в ошибке прогрева; молчащая проходила мимо.
            # Ложного срабатывания на молодой ноде нет: uvicorn поднимается ДО прогрева, то есть
            # исправная нода отвечает на `/health` уже через полминуты после старта.
            if not h:
                return 'нет ответа по SSH'
            return SR.warmup_fault(h)

        dead = [(i, _fault(i)) for i in live]
        dead = [(i, why) for i, why in dead if why]
        if not dead:
            return
        kinds = {why for _, why in dead}
        if len(dead) >= max(2, len(live) * 0.5) and len(kinds) == 1:
            print(f'  прогрев упал у {len(dead)} из {len(live)} нод одинаково — это наша беда, '
                  f'не машины: {next(iter(kinds))[:120]}', flush=True)
            continue
        for i, why in dead:
            if not NH.take_cull_slot():
                break
            iid = i['id']
            print(f'нода {iid[:8]} ({grp}): прогрев мёртв — ПЕРЕСАЖИВАЮ: {why[:120]}', flush=True)
            NH.reallocate(grp, iid, f'warmup: {why[:80]}')


def post_steps() -> tuple:
    """Локальный разбор сделанного: стащить, учесть, принять, разметить, показать.

    Все шаги идут ОТ СОСТОЯНИЯ («что ещё не сделано»), а не от списка конкретной пачки —
    поэтому пропущенный запуск не теряет работу: следующий заберёт и её.
    """
    return (('стаскиваю', f'bash {HERE}/drain.sh --keep'),
            ('реестр', f'{PY} {HERE}/ingest_registry.py'),
            ('приёмка', f'{PY} {HERE}/apply_repairs.py'),
            # ПАЙПЛАЙН САМ ПИШЕТ В КАРТОЧКУ ТОВАРА (владелец 01.09): «требуется меш» —
            # когда пройдены все гейты, «вклейка» — коврам/пледам, и ссылка на готовую
            # модель с датой изготовления. Никто больше не выводит это правило у себя.
            ('пометка в базе', f'{PY} {os.path.join(HERE, "..", "mesh_bind.py")}'),
            # ОЧИСТКА ПРИЁМНИКА — СТРОГО ПОСЛЕ ЗАПИСИ В БАЗУ (владелец 01.09: «периодически
            # триггером запускать копирование, запись в базу, сверку и очистку»). exit-fi
            # транзитный: 38 ГБ на весь сервер, там же сайт и база. Раньше чистилось только
            # в самом конце прогона, и 01.09 свободного места осталось 4.7 ГБ.
            ('чистка приёмника', f'{PY} {HERE}/receiver_purge.py --apply'),
            # ОРИЕНТАЦИЯ КАЖДОМУ НОВОМУ МЕШУ (владелец 31.08: «вся разметка должна быть
            # корректная»): боевой каскад по pending, затем виды сверху и публикация
            # orient.json для 3D-сцены
            ('ориентация', ORIENT_CMD),
            ('топ-вью', TOPVIEW_CMD),
            *SHOW_STEPS,
            ('ориент-паблиш', f'{PY} {HERE}/publish_merge.py $HOME/scout-scenes/mesh-topview/topview.json https://remont-lab.online/test/mesh-pilot10/orient.json root@89.167.127.0:/opt/remlab/test/mesh-pilot10/orient.json && scp -P 22222 -o BatchMode=yes $HOME/scout-scenes/mesh-topview/*.png root@89.167.127.0:/opt/remlab/test/buildup/topsprites/ 2>/dev/null || true'))


_post: dict = {'thread': None}


def _run_post(tag) -> None:
    t0 = time.time()
    for step, cmd in post_steps():
        c, o = sh(cmd, timeout=2700)
        if c == BUSY:
            # Не авария и не «сделано»: шаг вообще не начался, потому что его инструмент
            # занят другим процессом. Следующий заход подберёт — шаги идут от состояния.
            print(f'  [разбор {tag}] {step}: занято другим процессом, подберу следующим заходом',
                  flush=True)
            continue
        print(f'  [разбор {tag}] {step}: {"ok" if c == 0 else "СБОЙ " + o[-200:]}', flush=True)
    print(f'== разбор {tag} закончен за {(time.time() - t0) / 60:.0f} мин ==', flush=True)


def start_post(tag) -> None:
    """Запустить разбор фоном. Одновременно — НЕ БОЛЬШЕ ОДНОГО.

    Если предыдущий ещё идёт, новый не ставим и в очередь не копим: шаги работают от
    состояния, поэтому следующий запуск подберёт и эту пачку. Две параллельные постобработки
    подрались бы за память (их и так убивал OOM) и за ориентационный flock.
    """
    th = _post['thread']
    if th is not None and th.is_alive():
        print(f'  разбор предыдущей пачки ещё идёт — {tag} подберёт следующий заход', flush=True)
        return
    th = threading.Thread(target=_run_post, args=(tag,), daemon=True)
    _post['thread'] = th
    th.start()


def post_ticker(stop: threading.Event, every_s: float) -> None:
    """Разбор ПО ТАЙМЕРУ, а не на границах пачек.

    Раньше он запускался только когда пачка закрыта целиком, поэтому размер пачки был
    компромиссом: маленькая — частые простои на ожидании последнего задания, большая —
    результат виден поздно. С таймером одно перестало зависеть от другого: задания идут
    непрерывным потоком, а сделанное разбирается каждые `every_s` независимо от того,
    где сейчас граница. Шаги работают от состояния, поэтому «поймать полпачки» безопасно.
    """
    while not stop.wait(every_s):
        start_post('по таймеру')


def wait_post() -> None:
    """Дождаться фонового разбора. Без этого демон-поток умрёт вместе с процессом, и пачка
    осталась бы стащенной, но не размеченной."""
    th = _post['thread']
    if th is not None and th.is_alive():
        print('жду, пока фоновый разбор доработает', flush=True)
        th.join()


def drain_retry_spool() -> None:
    """Прогнать спул повторов — задания, которые курсор уже пропустил, но которые НЕ виноваты.

    Без этого шага спул только копится: курсор ушёл вперёд, и сам по себе эти задания никто
    не запросит — ровно так 01.09 молча пропали товары с битой ноды. Исчерпавшие попытки
    `ssh_run.jobs_from_file` отфильтрует сам, GPU на них больше не тратится.
    """
    spool = SR.RETRY_SPOOL
    if not os.path.exists(spool):
        return
    try:
        todo = SR.jobs_from_file(spool)
    except SystemExit:                       # предохранитель размера — разбираем руками
        print('!! спул повторов больше предохранителя — не трогаю, нужен разбор', flush=True)
        return
    if not todo:
        return
    inflight = spool + '.inflight'
    # Спул забираем целиком: всё, что снова не получится, `ssh_run` допишет заново со
    # счётчиком +1. Иначе одна и та же запись росла бы в файле бесконечно.
    os.replace(spool, inflight)
    print(f'== спул повторов: {len(todo)} заданий ==', flush=True)
    code, out = sh(f'{PY} {HERE}/ssh_run.py --jobs-file {inflight} --keep-alive',
                   timeout=len(todo) * 420 + 600)
    print(out, flush=True)
    if code == NO_CAPACITY or (code != 0 and 'нет прогретых' in out):
        # Нод не было — это не ответ по заданиям: возвращаем спул на место, иначе повторы
        # растворятся в «уже разобранном» файле.
        if not os.path.exists(spool):
            os.replace(inflight, spool)
        print('спул повторов: нет тёплых нод — вернул очередь на место', flush=True)


def main():
    """Конвейер показа. finale() (гашение групп) — в finally: любая ошибка внутри цикла
    раньше оставляла ноды включёнными, а тарифицируется состояние, а не работа."""
    try:
        _main()
    finally:
        finale()


def _main():
    acquire_singleton()
    wait_orphans()
    ensure_group_started()
    batch = int(sys.argv[sys.argv.index('--batch') + 1]) if '--batch' in sys.argv else 5
    mx = int(sys.argv[sys.argv.index('--max') + 1]) if '--max' in sys.argv else None
    # План — из ТОГО ЖЕ плоского списка, по которому режет пачки `ssh_run`. Раньше здесь
    # считались SKU из файла (1465), а прогон работал с развёрнутыми seeds без не-мешевых
    # ролей (1503): конвейер останавливался на 1465 и последние 38 заданий не запрашивал.
    jobs = SR.plan_jobs()
    total = len(jobs) if mx is None else min(mx, len(jobs))
    done = load_cursor()
    print(f'план {total}, уже пройдено {done}, пачка {batch}', flush=True)
    # ПОТРЕБНОСТЬ СЧИТАЕТСЯ, А НЕ ХРАНИТСЯ (владелец 01.09: «конвейер чётко должен работать,
    # надо исключалось и помечалось верно»): ковры/пледы/шторы/зеркала/картины идут плоскостью
    # и в потребность не входят — `mesh_demand.py` берёт это из политики ролей.
    try:
        _d = json.loads(subprocess.run([PY, os.path.join(HERE, 'mesh_demand.py'), '--json'],
                                       capture_output=True, text=True, timeout=180).stdout)
        print(f"потребность: {_d['need_slot_roles']} мешей в ролях слотов "
              f"(всего по каталогу {_d['need_with_dims']} с габаритами; "
              f"исключено плоскостями {_d['excluded_total']}) · готово {_d['have']} · "
              f"осталось {_d['left_slot_roles']}", flush=True)
    except Exception as _e:  # noqa: BLE001 — счётчик не должен мешать прогону
        print(f'потребность не посчитана: {type(_e).__name__}', flush=True)

    # Разбор по таймеру: с ним размер пачки перестаёт быть компромиссом между простоем и
    # свежестью результата. Замер 01.09: загрузка пула 30%, и основная потеря — ожидание
    # последнего задания пачки (видели задание на 585 с при медиане 205 с).
    _post_stop = threading.Event()
    threading.Thread(target=post_ticker, args=(_post_stop, POST_EVERY_S), daemon=True).start()

    PAUSE = os.path.expanduser('~/scout-scenes/mesh-batch.PAUSE')
    if os.environ.get('WAVE_FIRST') == '1':
        heal_wave(PAUSE)
    while done < total:
        if os.path.exists(DRAINING):
            # Горячий перезапуск: пачка закончена, выходим на границе. Группы НЕ гасим (finale
            # увидит флаг), новый конвейер продолжит с курсора. Флаг снимает finale.
            print('ПЕРЕЗАПУСК (файл mesh-draining) — выхожу на границе пачки, группы не гашу', flush=True)
            return
        if os.path.exists(PAUSE):
            # Пауза владельца: глушим группу (деньги!) и выходим. Продолжение — удалить файл
            # и перезапустить: сделанное вернётся как cached, перегона не будет.
            # Группу гасит finale(), и гасит ПЕРВЫМ делом — фоновый разбор доделывается уже
            # без нод, бесплатно. Ждать его здесь значило бы платить за простой.
            print('ПАУЗА (файл mesh-batch.PAUSE) — гашу группу и выхожу', flush=True)
            return
        n = min(batch, total - done)
        # ssh_run сам берёт первые limit заданий; сделанные вернутся как cached мгновенно —
        # поэтому просто наращиваем limit, а не режем список (проще и идемпотентно)
        code, out = sh(f'{PY} {HERE}/ssh_run.py --skip {done} --limit {n} --keep-alive', timeout=n * 420 + 600)
        print(out, flush=True)
        if code == NO_CAPACITY or (code != 0 and 'нет прогретых' in out):
            # ноды переезжают (бытовые ПК) — это не авария: ждём и пробуем снова.
            # НО: группа stopped + отказ старта = похоже, КОНЧИЛСЯ БАЛАНС (30.08 владелец
            # заметил раньше конвейера) — говорим прямо, монитор донесёт.
            st = group_status()
            if st == 'stopped' and not ensure_group_started():
                print('группа остановлена и не стартует — см. причину выше (кредиты / запрет / окно)', flush=True)
            elif 'ПРИЁМНИК' in out:
                # 75 от ssh_run из-за приёмника (нет места / канарейка не прошла): не ждём фонового
                # тика разбора — стаскиваем и чистим СЕЙЧАС, иначе ноды простаивают до 15 минут,
                # пока место уже можно было освободить (04.09).
                print('приёмник не принимает — стаскиваю и чищу немедленно', flush=True)
                for step, cmd in SR.SINK_RELIEF_CHAIN:
                    c, o = sh(cmd, timeout=1800)
                    print(f'  [приёмник] {step}: {"ok" if c == 0 else "СБОЙ " + o[-200:]}', flush=True)
            else:
                print('нет тёплых нод — жду 3 мин и пробую снова', flush=True)
            cull_slow_pulls()
            cull_dead_warmups()   # ноды «Running» с мёртвым прогревом — самый дорогой простой
            time.sleep(180)
            continue
        s = run_summary(out)
        if s is None:
            print(f'!! пачка без итога (код {code}) — стоп, разбор руками', flush=True)
            break
        # Курсор двигаем ТОЛЬКО на подряд закрытые задания: дырка от транспортного сбоя
        # останется в начале следующей пачки и будет перегенерирована, а не потеряна.
        step_done = s.get('terminal_prefix', 0)
        if s.get('unresolved'):
            print(f'   нерешённых по транспорту: {s["unresolved"]} — курсор двигаю на {step_done} из {n}', flush=True)
        if step_done == 0:
            print('   ни одного закрытого задания — жду 3 мин и пробую снова', flush=True)
            cull_slow_pulls()
            cull_dead_warmups()   # ноды «Running» с мёртвым прогревом — самый дорогой простой
            time.sleep(180)
            continue
        done += step_done
        save_cursor(done)
        drain_retry_spool()
        # Постобработка уходит В ФОН: пока она разбирает эту пачку, следующая уже считается
        # на нодах. Раньше 7 шагов шли последовательно с генерацией, и всё это время ноды
        # были тёплые, оплачиваемые и без заданий — 38 минут × ~9 нод ≈ 5,7 GPU-часов
        # вхолостую за одну паузу (замер 01.09). Плюс таймер (см. post_ticker) разбирает
        # сделанное и ВНУТРИ длинной пачки, поэтому пачку можно брать большой.
        start_post(done)
        print(f'== {done}/{total} очереди сгенерировано, разбор идёт фоном ==', flush=True)

    _post_stop.set()
    wait_post()          # волна лечения работает по итогам приёмки — она должна доработать
    heal_wave(PAUSE, guard_done=(done >= total))


def heal_wave(PAUSE: str, guard_done: bool = True) -> None:
    """ВОЛНА ЛЕЧЕНИЯ: перегон того, что приёмка завернула (слой 4 системы).
    При WAVE_FIRST=1 конвейер зовёт её ДО основной очереди (владелец 30.08: тестовый
    сет — приоритет), с ожиданием тёплых нод, как у пачек."""
    RESEED = os.path.join(HERE, '..', 'mesh-reseed.json')
    if guard_done and os.path.exists(RESEED) and not os.path.exists(PAUSE):
        rs = json.load(open(RESEED, encoding='utf-8'))
        todo = [r for r in rs]
        if todo:
            print(f'== волна лечения: {len(todo)} перегонов ==', flush=True)
            for _try in range(40):
                c, o = sh(f'{PY} {HERE}/ssh_run.py --jobs-file {RESEED} --keep-alive',
                          timeout=len(todo) * 420 + 600)
                print(o, flush=True)
                if c == NO_CAPACITY or (c != 0 and 'нет прогретых' in o):
                    print('волна: нет тёплых нод — жду 3 мин', flush=True)
                    ensure_group_started()
                    cull_slow_pulls()
                    time.sleep(180)
                    continue
                if c != 0:
                    # Нерешённые по транспорту остаются в mesh-reseed.json и уйдут в следующую
                    # волну — но молчать об этом нельзя (раньше волна просто «заканчивалась»).
                    s = run_summary(o) or {}
                    print(f'!! волна закончилась с кодом {c}: закрыто '
                          f'{s.get("terminal", "?")}/{s.get("requested", len(todo))}, '
                          f'нерешённых {s.get("unresolved", "?")}', flush=True)
                break
            # Разбор волны — тот же список шагов, что и у пачек (`post_steps`), одно место.
            # Здесь он идёт НЕ фоном: после волны прогон заканчивается, ждать всё равно нам.
            for step, cmd in post_steps():
                c, o = sh(cmd, timeout=2700)
                print(f'  {step}: {"ok" if c == 0 else "СБОЙ " + o[-200:]}', flush=True)


def finale() -> None:
    """Финал прогона — НЕ часть волны: чистка кэша и гашение групп только в самом конце."""
    if not _STARTED:
        # второй экземпляр, не получивший замок, НЕ должен гасить группы работающего первого
        print('финал: этот процесс конвейер не вёл — группы не трогаю', flush=True)
        return
    if os.path.exists(DRAINING):
        # горячий перезапуск: группы остаются работать, финальный drain — не наш (новый конвейер
        # сделает свой); флаг снимаем, чтобы новый не вышел тут же
        try:
            os.remove(DRAINING)
        except OSError:
            pass
        print('финал при перезапуске: группы НЕ гашу, флаг mesh-draining снят', flush=True)
        wait_post()
        return
    # ГРУППУ ГАСИМ ПЕРВЫМ ДЕЛОМ (деньги): тарифицируется состояние, а финальный drain —
    # работа чисто локальная, комплекты уже лежат на exit-fi. Раньше ноды ждали конца
    # drain'а и жгли деньги за это время. Гасим и при падении — это `finally` в main().
    stop = f'{PY} - <<P\nimport sys; sys.path.insert(0,"{HERE}")\nimport ssh_run; ssh_run.stop_group()\nP'
    c, o = sh(stop, timeout=120)
    print(o, flush=True)
    if c != 0:
        # НЕУДАЧНОЕ ГАШЕНИЕ — ЭТО ДЕНЬГИ (замечание Codex 05.09): раньше ненулевой код просто
        # печатался, конвейер шёл дальше и выходил, а группы оставались тарифицироваться до
        # следующего сторожа. Повторяем один раз и, если снова мимо, кричим в телеграм.
        print(f'!! группы НЕ погашены (код {c}) — повторяю', flush=True)
        c, o = sh(stop, timeout=120)
        print(o, flush=True)
        if c != 0:
            print('!! ГРУППЫ ОСТАЛИСЬ ПОДНЯТЫМИ — гасить руками, идёт тарификация', flush=True)
            subprocess.run(['bash', os.path.join(HERE, '..', 'alert.sh'),
                            'меши: конвейер завершился, а группы Salad НЕ погашены — '
                            'идёт оплата, погасите вручную'], check=False, timeout=60)
    # Фоновый разбор мог ещё идти — два drain'а разом полезли бы в один каталог.
    wait_post()
    # сервер чистим ОДИН раз в конце: в цикле drain --keep, иначе умирает кэш «уже сделано»
    sh(f'bash {HERE}/drain.sh', timeout=1200)


if __name__ == '__main__':
    main()
