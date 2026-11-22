#!/usr/bin/env python3
"""T-20261119-03/2 (из скриптов партий T-20261118-52/5): ПУТЬ ПЕРЕКРАСКИ НА ЖИВОЕ — проверки, бэкап, окно без волны, выкладка. Данные — файл заданий, не код.

Файл заданий (JSON-список): [{"sku": "mid:eid", "k": номер, "new": "<перекрашенный.glb>", "gen": "<живое поколение, необязательно>",
"role": "...", "result": "<results-N.json recolor_lp, необязательно>"}]. `new` — выход `recolor_lp.py run` (`<папка>/glb/<k>_<sid>.glb`).
Везде сухо по умолчанию; запись/запуск шагов — только с `--apply`. Рабочая папка `--work` (журналы шагов, списки) — вне репо и вне git.

  recolor_window.py pre     <задания> --work <папка>                          # проверки, ничего не пишет: поколение, файл, гейт вариантов, перенос ориентации «copy»
  recolor_window.py backup  <задания> --work <папка> --to <НОВАЯ папка>       # копии v2-model/manifest, галереи, лёгких копий (папка должна быть пустой/новой)
  recolor_window.py window  <задания> --work <папка> --backup <папка> [--apply]   # запись v2 (с гейтом) → ingest_registry → carry → room_bindings --build
  recolor_window.py publish <задания> --work <папка> [--manifest <копия runtime-meshes.json>] [--apply]   # gallery_build → rsync -c → sha на проде → runtime_mesh (+ -lite) → copy_problems
Окно (`window`): перед КАЖДЫМ шагом проверка `ps` — идёт волна/шаг цепочки → СТОП (код 4/5): запись v2 уже сделана → решает директор.
`publish` — другой список занятости (галерея/публикация/демо); `/rt/`, `publish_demo`, туры не трогает (это ночной `refresh_daily`).
Откат одной модели — `recolor_rollback.sh`. Гейт вариантов (`recolor_variants_gate.py`) считается в `pre` и при записи; отказавшие — пропуск, остальные идут."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import recolor_put_v2 as PUT  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
SCOUT = os.path.join(REPO, 'tools', 'scout')
CARRY = os.path.join(HERE, 'recolor_carry_orientation.py')
V2 = PUT.V2
GALLERY = os.path.expanduser('~/scout-scenes/mesh-pilot-gallery')
RT = os.path.expanduser('~/scout-scenes/flat3d-rt')
HOST, PROD = 'root@89.167.127.0', '/opt/remlab/test/mesh-pilot10'
WINDOW_BUSY = 'mesh_wave_start|batch_show|ingest_registry|orient_worker|room_bindings|gallery_build|mesh_publish'
PUBLISH_BUSY = 'gallery_build|mesh_publish|runtime_mesh|publish_demo|refresh_daily'


def sid_of(sku: str) -> str:
    return sku.replace(':', '_')


def busy(pattern: str, ps=None) -> str:
    """Строки `ps`, где идёт шаг цепочки мешей (пусто — окно свободно). ps — подмена для теста."""
    out = ps() if ps else subprocess.run(['ps', '-eo', 'args'], capture_output=True, text=True).stdout
    import re
    me = f'recolor_window.py|recolor_rollback|grep|{os.path.basename(__file__)}'
    return '\n'.join(l for l in out.splitlines() if re.search(pattern, l) and not re.search(me, l)).strip()


def load_jobs(path: str) -> list:
    jobs = json.load(open(path, encoding='utf-8'))
    for j in jobs:
        assert j.get('sku') and j.get('new') and 'k' in j, f'в задании нужны sku, k, new: {j}'
    return jobs


def carry_dry(sku: str, old_glb: str, new_glb: str) -> dict:
    r = subprocess.run([sys.executable, CARRY, sku, old_glb, new_glb], capture_output=True, text=True)
    try:
        js = json.loads(r.stdout.split('\n}\n')[0] + '\n}')
    except Exception:  # noqa: BLE001
        js = {'action': '?', 'why': (r.stdout + r.stderr)[-200:]}
    return js


def pre(jobs: list, work: str, gate_fn=None, carry_fn=None) -> list:
    """Проверки каждого задания без записи → список {job, skip: причина|None, gate, carry}."""
    out = []
    for j in jobs:
        i = {'sku': j['sku'], 'k': j['k'], 'role': j.get('role', ''), 'skip': None}
        try:
            gd = PUT.pick_generation(j['sku'], j.get('gen'))
        except (AssertionError, FileNotFoundError) as e:
            i['skip'] = f'поколение: {e}'
            out.append(i)
            continue
        i['gen_dir'] = gd
        if not os.path.exists(j['new']):
            i['skip'] = 'нет файла перекраски ' + j['new']
        elif os.path.exists(f'{gd}/model.orig.glb'):
            i['skip'] = 'уже есть model.orig.glb — уже перекрашен'
        else:
            res = PUT.put(j['sku'], j['new'], j['k'], j.get('gen'), j.get('result'), apply=False, gate_fn=gate_fn)
            i['gate'] = {k: res['gate'].get(k) for k in ('ok', 'n_variants', 'reasons')} if res.get('gate') else None
            if res['refused']:
                i['skip'] = 'гейт вариантов: ' + '; '.join(res['gate'].get('reasons') or ['не посчитан'])
            else:
                c = (carry_fn or carry_dry)(j['sku'], f'{gd}/model.glb', j['new'])
                i['carry'] = {k: c.get(k) for k in ('action', 'why', 'geometry_sha')}
                if c.get('action') != 'copy':
                    i['skip'] = f"перенос ориентации: {c.get('action')} — {c.get('why')}"
        out.append(i)
        print(f"{'OK  ' if not i['skip'] else 'ПРОП'} k={j['k']} {j.get('role', ''):10s} {j['sku']}  {i['skip'] or ''}", flush=True)
    os.makedirs(work, exist_ok=True)
    json.dump(out, open(f'{work}/pre.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('к записи:', sum(1 for i in out if not i['skip']), 'из', len(out))
    return out


def backup(jobs: list, dst: str) -> None:
    """Копии для отката и для переноса ориентации (старый v2-model.glb) — в НОВУЮ папку (непустую не принимаем)."""
    assert not (os.path.isdir(dst) and os.listdir(dst)), f'папка бэкапа не пуста: {dst} — нужна новая'
    for j in jobs:
        sid = sid_of(j['sku'])
        try:
            gd = PUT.pick_generation(j['sku'], j.get('gen'))
        except (AssertionError, FileNotFoundError):
            continue
        d = f'{dst}/{sid}'
        os.makedirs(d, exist_ok=True)
        for src, nm in ((f'{gd}/model.glb', 'v2-model.glb'), (f'{gd}/manifest.json', 'v2-manifest.json'),
                        (f'{GALLERY}/{sid}/model.glb', 'gallery-model.glb'), (f'{RT}/{sid}.glb', 'rt.glb'), (f'{RT}/{sid}-lite.glb', 'rt-lite.glb')):
            if os.path.exists(src):
                shutil.copy2(src, f'{d}/{nm}')
        print('backup', sid, sorted(os.listdir(d)))


def window(jobs: list, work: str, bk: str, apply: bool, ps=None, runner=None, gate_fn=None) -> int:
    """Окно без волны. Коды: 0 — готово; 4 — занято до начала; 5 — волна встала посреди; 6 — шаг упал. runner(cmd) → (rc, stdout) — подмена для теста."""
    runner = runner or (lambda cmd: (lambda r: (r.returncode, r.stdout + r.stderr))(subprocess.run(cmd, capture_output=True, text=True)))
    b = busy(WINDOW_BUSY, ps)
    if b:
        print('ЗАНЯТО, не начинаю:\n' + b)
        return 4
    done = []
    os.makedirs(work, exist_ok=True)
    for j in jobs:
        res = PUT.put(j['sku'], j['new'], j['k'], j.get('gen'), j.get('result'), apply=apply, gate_fn=gate_fn)
        tag = 'ОТКАЗ' if res['refused'] else ('PUT ' if apply else '(сухо)')
        print(tag, sid_of(j['sku']), '; '.join((res.get('gate') or {}).get('reasons') or []) if res['refused'] else '', flush=True)
        if not res['refused']:
            done.append(j)
    json.dump([j['sku'] for j in done], open(f'{work}/window-done.json', 'w'), indent=1)
    if not apply:
        print('(сухо) дальше: ingest_registry → carry (по каждой) → room_bindings --build; записано бы:', len(done))
        return 0
    steps = [('ingest_registry', [sys.executable, f'{SCOUT}/salad/ingest_registry.py'])]
    for step, cmd in steps:
        if busy(WINDOW_BUSY, ps):
            print('ВОЛНА встала посреди окна перед', step, '— СТОП (запись v2 уже сделана; решать директору)')
            return 5
        rc, out = runner(cmd)
        print(step, 'rc', rc, out.strip()[-200:], flush=True)
        if rc:
            return 6
    for j in done:
        if busy(WINDOW_BUSY, ps):
            print('ВОЛНА встала посреди окна перед carry', j['sku'], '— СТОП')
            return 5
        sid = sid_of(j['sku'])
        gd = PUT.pick_generation(j['sku'], j.get('gen'))
        rc, out = runner([sys.executable, CARRY, j['sku'], f'{bk}/{sid}/v2-model.glb', f'{gd}/model.glb', '--apply'])
        try:
            js = json.loads(out.split('\n}\n')[0] + '\n}')
        except Exception:  # noqa: BLE001
            js = {}
        print('carry', sid, js.get('action'), 'записано' if js.get('written') else '', js.get('why'), flush=True)
        if js.get('action') not in ('copy', 'already'):
            print('СТОП-флаг: перенос ориентации не вышел — привязка этой модели будет orientation_missing; решать директору')
    if busy(WINDOW_BUSY, ps):
        print('ВОЛНА встала перед room_bindings — СТОП')
        return 5
    rc, out = runner([sys.executable, f'{SCOUT}/room_bindings.py', '--build'])
    print('room_bindings rc', rc, [l for l in out.split('\n') if l.startswith('снимок')][:1], flush=True)
    return 6 if rc else 0


def publish(jobs: list, work: str, manifest: str | None, apply: bool, ps=None, sh=None) -> int:
    """Выкладка после окна: только записанные в `window-done.json`. Коды: 0, 4 занято, 5 gallery_build упал, 7 sha на проде не совпало."""
    sh = sh or (lambda cmd: (lambda r: (r.returncode, r.stdout, r.stderr))(subprocess.run(cmd, shell=True, capture_output=True, text=True)))
    done = json.load(open(f'{work}/window-done.json'))
    sids = [sid_of(s) for s in done]
    print('к выкладке:', sids)
    if not apply:
        print('(сухо) gallery_build GALLERY_ONLY → rsync -c по папке → sha на проде → runtime_mesh (1024 и -lite, если были) → copy_problems')
        return 0
    b = busy(PUBLISH_BUSY, ps)
    if b:
        print('ЗАНЯТО:\n' + b)
        return 4
    lst = f'{work}/only-publish.txt'
    open(lst, 'w').write('\n'.join(done) + '\n')
    rc, out, err = sh(f"cd {SCOUT} && GALLERY_ONLY={lst} GALLERY_SRC={V2} {sys.executable} salad/gallery_build.py")
    print('gallery_build rc', rc, (out.strip().split('\n') or [''])[-1][:120], flush=True)
    if rc:
        print(err[-300:])
        return 5
    bad = 0
    for s in sids:
        gsha = hashlib.sha256(open(f'{GALLERY}/{s}/model.glb', 'rb').read()).hexdigest()
        rc, _, _ = sh(f"rsync -a -c -e 'ssh -p 22222 -o BatchMode=yes' {GALLERY}/{s}/ {HOST}:{PROD}/{s}/")
        p = sh(f"ssh -p 22222 -o BatchMode=yes {HOST} sha256sum {PROD}/{s}/model.glb")[1].split()[:1]
        ok = bool(p) and p[0] == gsha and not rc
        bad += not ok
        print('rsync', s, {'gallery': gsha[:16], 'prod': p[0][:16] if p else None, 'rsync_rc': rc}, 'OK' if ok else 'ОШИБКА', flush=True)
    sys.path.insert(0, f'{REPO}/tools/assets')
    import runtime_mesh as RM
    for s in sids:
        for extra, suf in (('', ''), ('--size 512 --suffix=-lite', '-lite')):
            f = f'{RT}/{s}{suf}.glb'
            if not os.path.exists(f):          # в наборе лёгких копий этой модели не было — набор не расширяю
                print('runtime', s, suf or '1024', 'пропуск: копии не было', flush=True)
                continue
            rc, _, _ = sh(f"cd {REPO} && {sys.executable} tools/assets/runtime_mesh.py --id {s} --force " + (f'--manifest {manifest} ' if manifest else '') + extra)
            print('runtime', s, suf or '1024', 'rc', rc, 'размер', os.path.getsize(f), 'copy_problems', RM.copy_problems(f, expect_texture=True), flush=True)
    return 7 if bad else 0


def main() -> int:
    a = sys.argv[1:]
    if len(a) < 2 or a[0] not in ('pre', 'backup', 'window', 'publish'):
        print(__doc__)
        return 2

    def opt(name):
        return a[a.index(name) + 1] if name in a else None
    cmd, jobs, work = a[0], load_jobs(a[1]), opt('--work')
    assert work, '--work <папка журналов> обязательна'
    apply = '--apply' in a
    if cmd == 'pre':
        pre(jobs, work)
        return 0
    if cmd == 'backup':
        assert opt('--to'), '--to <новая папка>'
        backup(jobs, opt('--to'))
        return 0
    if cmd == 'window':
        assert opt('--backup'), '--backup <папка бэкапа>'
        return window(jobs, work, opt('--backup'), apply)
    return publish(jobs, work, opt('--manifest'), apply)


if __name__ == '__main__':
    sys.exit(main())
