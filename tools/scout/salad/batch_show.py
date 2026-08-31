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
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, '..', 'mesh-pilot-sample.json')
DONE = os.path.join(HERE, '..', 'mesh-batch-progress.json')
PY = os.path.expanduser('~/venvs/scout/bin/python')
NO_CAPACITY = 75   # код ssh_run «нет тёплых нод» — ждём и повторяем, это не авария


def sh(cmd, timeout=3600):
    """Таймаут не должен ронять конвейер исключением: иначе finale() не отработает и группа
    останется тарифицироваться (деньги)."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f'ТАЙМАУТ {timeout}с: {cmd[:120]}'
    return r.returncode, (r.stdout + r.stderr)[-1500:]


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


def group_status() -> str | None:
    """'stopped' только если ВСЕ группы остановлены (мультигруппы через запятую)."""
    import json as _j
    import urllib.request as _u
    sts = []
    for grp in [g.strip() for g in os.environ.get('SALAD_GROUP', 'mesh-run3').split(',') if g.strip()]:
        try:
            req = _u.Request(f'https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers/{grp}',
                             headers={'Salad-Api-Key': os.environ['SALAD_API_KEY']})
            with _u.urlopen(req, timeout=30) as r:
                sts.append((_j.load(r).get('current_state') or {}).get('status'))
        except Exception:  # noqa: BLE001
            sts.append(None)
    if sts and all(s == 'stopped' for s in sts):
        return 'stopped'
    return sts[0] if sts else None


def ensure_group_started():
    """Группа на Salad может СОЗДАТЬСЯ остановленной (ловили дважды: pool5, mesh-run3) —
    и ожидание тёплой ноды у выключенной группы длится вечно. Стартуем явно; 400 = уже
    стартует, это не ошибка."""
    import urllib.request
    ok = False
    for grp in [g.strip() for g in os.environ.get('SALAD_GROUP', 'mesh-run3').split(',') if g.strip()]:
      try:
        req = urllib.request.Request(
            f"https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers/{grp}/start",
            data=b'', method='POST',
            headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'],
                     'User-Agent': 'remlab-mesh/1.0'})
        urllib.request.urlopen(req, timeout=60).read()
        print(f'группа {grp}: start отправлен', flush=True)
        ok = True
      except Exception as e:  # noqa: BLE001 — 400 «уже идёт» и сеть не должны валить конвейер
        print(f'группа {grp}: start → {str(e)[:80]} (обычно уже запущена)', flush=True)
    return ok


_PULL_HIST: dict = {}     # instance_id → наблюдения за закачкой образа
_CULL_LOG: list = []      # моменты наших пересадок: предохранитель от чехарды

# ПРАВИЛО СНЯТИЯ МЕДЛЕННОЙ НОДЫ (владелец 31.08, переформулировано после разбора).
# Считаем не «скорость за окно», а ВОЗРАСТ и ОСТАТОК. Прошлая формула («<15% за 5 мин»)
# брала базовую точку один раз и не обновляла её, поэтому средняя скорость с ростом возраста
# падала и правило снимало ноды на 83% и 90% — замена начинала с нуля (поймано 31.08).
# Здоровая машина забирает наш образ за 25–35 мин, отсюда ступени.
DEADMAN_AGE_S = float(os.environ.get('MESH_DEADMAN_AGE_S', '600'))    # 10 мин
DEADMAN_MIN = float(os.environ.get('MESH_DEADMAN_MIN', '0.05'))       # …и меньше 5%
STAGES = [(1200.0, 0.25), (2100.0, 0.60)]   # 20 мин → 25%, 35 мин → 60%
STALL_S = float(os.environ.get('MESH_PULL_STALL_S', '600'))           # без движения 10 мин
STALL_MIN = float(os.environ.get('MESH_PULL_STALL_MIN', '0.01'))      # прирост <1% = стоит
FINISH_GUARD = float(os.environ.get('MESH_FINISH_GUARD', '0.80'))     # выше — не трогаем
MAX_CULL_PER_TICK = int(os.environ.get('MESH_MAX_CULL_TICK', '2'))
MAX_CULL_PER_HOUR = int(os.environ.get('MESH_MAX_CULL_HOUR', '6'))
CULL_FREEZE_S = float(os.environ.get('MESH_CULL_FREEZE_S', '1800'))   # пауза после чехарды


def cull_verdict(age_s: float, progress: float, since_move_s: float) -> str | None:
    """Снимать ли ноду. Чистая функция — её и проверяет стенд.

    Возвращает причину (для лога) или None, если ноду оставляем."""
    if progress >= FINISH_GUARD:
        # Почти доехала: даже ползком быстрее, чем замена с нуля. Снимаем только если ВСТАЛА.
        return 'застой у финиша' if since_move_s >= STALL_S * 2 else None
    if since_move_s >= STALL_S:
        return f'нет движения {int(since_move_s / 60)} мин'
    if age_s >= DEADMAN_AGE_S and progress < DEADMAN_MIN:
        return f'мертвяк: {progress:.0%} за {int(age_s / 60)} мин'
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
    _CULL_LOG[:] = [t for t in _CULL_LOG if now - t < 3600]
    if len(_CULL_LOG) >= 3 and now - _CULL_LOG[-1] < CULL_FREEZE_S and len(_CULL_LOG) >= MAX_CULL_PER_HOUR:
        return                       # медленная вся сеть — менять шило на мыло бессмысленно
    seen, budget = set(), min(MAX_CULL_PER_TICK, MAX_CULL_PER_HOUR - len(_CULL_LOG))
    if budget <= 0:
        return
    for grp in [g.strip() for g in os.environ.get('SALAD_GROUP', 'mesh-run3').split(',') if g.strip()]:
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
            h = _PULL_HIST.setdefault(iid, {'first': now, 'best': prog, 'moved': now})
            if prog < h['best'] - 0.10:          # откат >10 п.п. = загрузка началась заново
                h.update(first=now, best=prog, moved=now)
            elif prog > h['best'] + STALL_MIN:
                h.update(best=prog, moved=now)
            why = cull_verdict(now - h['first'], h['best'], now - h['moved'])
            if why:
                cands.append((h['best'], iid, why))
        for prog, iid, why in sorted(cands)[:budget]:   # сперва самые безнадёжные
            try:
                req = _u.Request(f'{base}/instances/{iid}/reallocate', data=b'', method='POST',
                                 headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'],
                                          'User-Agent': 'remlab-mesh/1.0'})
                _u.urlopen(req, timeout=30).read()
                print(f'нода {iid[:8]} ({grp}): {why} — ПЕРЕСАЖИВАЮ (reallocate)', flush=True)
                _CULL_LOG.append(now)
                budget -= 1
            except Exception as e:  # noqa: BLE001
                print(f'нода {iid[:8]}: reallocate → {str(e)[:80]}', flush=True)
            _PULL_HIST.pop(iid, None)
    for iid in [k for k in _PULL_HIST if k not in seen]:
        _PULL_HIST.pop(iid, None)


def main():
    """Конвейер показа. finale() (гашение групп) — в finally: любая ошибка внутри цикла
    раньше оставляла ноды включёнными, а тарифицируется состояние, а не работа."""
    try:
        _main()
    finally:
        finale()


def _main():
    ensure_group_started()
    batch = int(sys.argv[sys.argv.index('--batch') + 1]) if '--batch' in sys.argv else 5
    mx = int(sys.argv[sys.argv.index('--max') + 1]) if '--max' in sys.argv else None
    jobs = json.load(open(SAMPLE, encoding='utf-8'))['jobs']
    total = len(jobs) if mx is None else min(mx, len(jobs))
    done = json.load(open(DONE))['done'] if os.path.exists(DONE) else 0
    print(f'план {total}, уже пройдено {done}, пачка {batch}', flush=True)

    PAUSE = os.path.expanduser('~/scout-scenes/mesh-batch.PAUSE')
    if os.environ.get('WAVE_FIRST') == '1':
        heal_wave(PAUSE)
    while done < total:
        if os.path.exists(PAUSE):
            # Пауза владельца: глушим группу (деньги!) и выходим. Продолжение — удалить файл
            # и перезапустить: сделанное вернётся как cached, перегона не будет.
            print('ПАУЗА (файл mesh-batch.PAUSE) — гашу группу и выхожу', flush=True)
            break
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
                print('группа остановлена и не стартует — ПОХОЖЕ, КОНЧИЛСЯ БАЛАНС Salad, нужно пополнение', flush=True)
            else:
                print('нет тёплых нод — жду 3 мин и пробую снова', flush=True)
            cull_slow_pulls()
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
            time.sleep(180)
            continue
        done += step_done
        json.dump({'done': done, 'at': time.time()}, open(DONE, 'w'))
        for step, cmd in (('стаскиваю', f'bash {HERE}/drain.sh --keep'),
                          ('реестр', f'{PY} {HERE}/ingest_registry.py'),
                          ('ремонт', f'{PY} {HERE}/apply_repairs.py'),
                          # ОРИЕНТАЦИЯ КАЖДОМУ НОВОМУ МЕШУ (владелец 31.08: «вся разметка
                          # должна быть корректная»): боевой каскад по pending, затем виды
                          # сверху (кэш — быстро) и публикация orient.json для 3D-сцены
                          ('ориентация', f'{PY} {os.path.join(HERE, "..", "orient_worker.py")} --run --limit 200 --vlm'),
                          ('топ-вью', f'{PY} {HERE}/topview_render.py'),
                          ('галерея', f'GALLERY_SRC=$HOME/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2 {PY} {HERE}/gallery_build.py'),
                          ('публикую', f'scp -P 22222 -o BatchMode=yes -r $HOME/scout-scenes/mesh-pilot-gallery/* root@89.167.127.0:/opt/remlab/test/mesh-pilot10/'),
                          ('ориент-паблиш', f'scp -P 22222 -o BatchMode=yes $HOME/scout-scenes/mesh-topview/topview.json root@89.167.127.0:/opt/remlab/test/mesh-pilot10/orient.json && scp -P 22222 -o BatchMode=yes $HOME/scout-scenes/mesh-topview/*.png root@89.167.127.0:/opt/remlab/test/flat215-demo/topsprites/ 2>/dev/null || true')):
            c, o = sh(cmd, timeout=2700)
            print(f'  {step}: {"ok" if c == 0 else "СБОЙ " + o[-200:]}', flush=True)
        print(f'== показано {done}/{total} — страница обновлена ==', flush=True)

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
            for step, cmd in (('стаскиваю', f'bash {HERE}/drain.sh --keep'),
                          ('реестр', f'{PY} {HERE}/ingest_registry.py'),
                              ('ремонт', f'{PY} {HERE}/apply_repairs.py'),
                              ('ориентация', f'{PY} {os.path.join(HERE, "..", "orient_worker.py")} --run --limit 200 --vlm'),
                              ('топ-вью', f'{PY} {HERE}/topview_render.py'),
                              ('галерея', f'GALLERY_SRC=$HOME/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2 {PY} {HERE}/gallery_build.py'),
                              ('публикую', f'scp -P 22222 -o BatchMode=yes -r $HOME/scout-scenes/mesh-pilot-gallery/* root@89.167.127.0:/opt/remlab/test/mesh-pilot10/'),
                              ('ориент-паблиш', f'scp -P 22222 -o BatchMode=yes $HOME/scout-scenes/mesh-topview/topview.json root@89.167.127.0:/opt/remlab/test/mesh-pilot10/orient.json && scp -P 22222 -o BatchMode=yes $HOME/scout-scenes/mesh-topview/*.png root@89.167.127.0:/opt/remlab/test/flat215-demo/topsprites/ 2>/dev/null || true')):
                c, o = sh(cmd, timeout=2700)
                print(f'  {step}: {"ok" if c == 0 else "СБОЙ " + o[-200:]}', flush=True)


def finale() -> None:
    """Финал прогона — НЕ часть волны: чистка кэша и гашение групп только в самом конце."""
    # сервер чистим ОДИН раз в конце: в цикле drain --keep, иначе умирает кэш «уже сделано»
    sh(f'bash {HERE}/drain.sh', timeout=1200)
    # конец или падение — группу гасим В ЛЮБОМ СЛУЧАЕ (деньги)
    c, o = sh(f'{PY} - <<P\nimport sys; sys.path.insert(0,"{HERE}")\nimport ssh_run; ssh_run.stop_group()\nP', timeout=120)
    print(o, flush=True)


if __name__ == '__main__':
    main()
