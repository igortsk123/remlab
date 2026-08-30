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


def sh(cmd, timeout=3600):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)[-1500:]


def ensure_group_started():
    """Группа на Salad может СОЗДАТЬСЯ остановленной (ловили дважды: pool5, mesh-run3) —
    и ожидание тёплой ноды у выключенной группы длится вечно. Стартуем явно; 400 = уже
    стартует, это не ошибка."""
    import urllib.request
    grp = os.environ.get('SALAD_GROUP', 'mesh-run3')
    try:
        req = urllib.request.Request(
            f"https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers/{grp}/start",
            data=b'', method='POST',
            headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'],
                     'User-Agent': 'remlab-mesh/1.0'})
        urllib.request.urlopen(req, timeout=60).read()
        print(f'группа {grp}: start отправлен', flush=True)
    except Exception as e:  # noqa: BLE001 — 400 «уже идёт» и сеть не должны валить конвейер
        print(f'группа {grp}: start → {str(e)[:80]} (обычно уже запущена)', flush=True)


def main():
    ensure_group_started()
    batch = int(sys.argv[sys.argv.index('--batch') + 1]) if '--batch' in sys.argv else 5
    mx = int(sys.argv[sys.argv.index('--max') + 1]) if '--max' in sys.argv else None
    jobs = json.load(open(SAMPLE, encoding='utf-8'))['jobs']
    total = len(jobs) if mx is None else min(mx, len(jobs))
    done = json.load(open(DONE))['done'] if os.path.exists(DONE) else 0
    print(f'план {total}, уже пройдено {done}, пачка {batch}', flush=True)

    PAUSE = os.path.expanduser('~/scout-scenes/mesh-batch.PAUSE')
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
        if code != 0:
            print(f'!! пачка упала (код {code}) — стоп, разбор руками', flush=True)
            break
        done += n
        json.dump({'done': done, 'at': time.time()}, open(DONE, 'w'))
        for step, cmd in (('стаскиваю', f'bash {HERE}/drain.sh --keep'),
                          ('ремонт', f'{PY} {HERE}/apply_repairs.py'),
                          ('галерея', f'GALLERY_SRC=$HOME/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2 {PY} {HERE}/gallery_build.py'),
                          ('публикую', f'scp -P 22222 -o BatchMode=yes -r $HOME/scout-scenes/mesh-pilot-gallery/* root@89.167.127.0:/opt/remlab/test/mesh-pilot10/')):
            c, o = sh(cmd, timeout=900)
            print(f'  {step}: {"ok" if c == 0 else "СБОЙ " + o[-200:]}', flush=True)
        print(f'== показано {done}/{total} — страница обновлена ==', flush=True)

    # ВОЛНА ЛЕЧЕНИЯ: перегон другим seed того, что приёмка завернула (слой 4 системы).
    RESEED = os.path.join(HERE, '..', 'mesh-reseed.json')
    if done >= total and os.path.exists(RESEED) and not os.path.exists(PAUSE):
        rs = json.load(open(RESEED, encoding='utf-8'))
        todo = [r for r in rs]
        if todo:
            print(f'== волна лечения: {len(todo)} перегонов ==', flush=True)
            c, o = sh(f'{PY} {HERE}/ssh_run.py --jobs-file {RESEED} --keep-alive',
                      timeout=len(todo) * 420 + 600)
            print(o, flush=True)
            for step, cmd in (('стаскиваю', f'bash {HERE}/drain.sh --keep'),
                              ('ремонт', f'{PY} {HERE}/apply_repairs.py'),
                              ('галерея', f'GALLERY_SRC=$HOME/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2 {PY} {HERE}/gallery_build.py'),
                              ('публикую', f'scp -P 22222 -o BatchMode=yes -r $HOME/scout-scenes/mesh-pilot-gallery/* root@89.167.127.0:/opt/remlab/test/mesh-pilot10/')):
                c, o = sh(cmd, timeout=900)
                print(f'  {step}: {"ok" if c == 0 else "СБОЙ " + o[-200:]}', flush=True)

    # сервер чистим ОДИН раз в конце: в цикле drain --keep, иначе умирает кэш «уже сделано»
    sh(f'bash {HERE}/drain.sh', timeout=1200)
    # конец или падение — группу гасим В ЛЮБОМ СЛУЧАЕ (деньги)
    c, o = sh(f'{PY} - <<P\nimport sys; sys.path.insert(0,"{HERE}")\nimport ssh_run; ssh_run.stop_group()\nP', timeout=120)
    print(o, flush=True)


if __name__ == '__main__':
    main()
