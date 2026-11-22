#!/usr/bin/env python3
"""ПРОБА SALAD «КАМЕРА ПО ФОТО» (T-184/1, очередь 2): pose_fit + camera_check на дешёвом классе БЕЗ нужды в видеокарте. Драйвер — на общем наборе (`kit_driver.run_probe`): деньги, потолок,
гашение и проверка «0 нод» — там; здесь только «что отправить и как забрать». Один «пакет» = все товары пробы одним заданием `pack`: воркер считает до POSE_PROCS штук параллельно.

Запуск (платный, только под heavy-slot --prio 2, по ОДНОЙ группе, потолок $1):
  heavy-slot.sh t184-pose-probe --prio 2 -- python pose_trial.py --image ghcr.io/…/mesh-pose-trial@sha256:… --skus a,b,c,d,e --apply
Без --apply — только разбор: тело группы без секретов, проверка образа (группа НЕ создаётся). `--stop-only --suffix X` — погасить группу X и проверить «0 нод».
`--local` — БЕСПЛАТНАЯ сверка: тот же воркер на этой машине (без Salad), те же submit/poll; код цепочки — как в образе (`--code <папка из stage_pose_code.py>`).
Вход: `<glb-dir>/<glb-name>` и `<photo-dir>/<photo-name>` (по умолчанию формы TRELLIS.2 HD и их фото). Выход: `<out>/<sku>/…` (распакованный результат воркера, sha256 сверен).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import time
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, SALAD)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'render_gpu')))       # bench_run (group_state/instances/stop_and_verify)
import kit_driver as KD  # noqa: E402
import kit_worker as KW  # noqa: E402
from kit_driver import Gateway, say  # noqa: E402

WORK_TYPE = 'pose_camera'                                         # профиль ресурсов: rules/salad-resources.json (T-186/1) — карта, vCPU, RAM, диск, shm, тариф только оттуда
CARD = KD.resource_profile(WORK_TYPE)['card']
PORT = 8000
WORKER = os.path.join(HERE, 'worker_pose.py')
RULES = os.path.normpath(os.path.join(HERE, '..', '..', 'rules', 'salad-pose.json'))
NEED = ('pose.json', '04-camera/check.json')               # без этих файлов результат не принимаем


def load_rules() -> dict:
    return json.load(open(RULES, encoding='utf-8'))


def worker_command(path: str | None = None) -> tuple[list[str], str]:
    return KW.bundle(path or WORKER)


def build_body(name: str, image: str, tier: str, class_id: str, auth: dict, life_s: int, idle_s: int, procs: int, omp: int, worker_z: str | None = None) -> dict:
    env = {'PORT': str(PORT), 'MAX_LIFETIME_S': str(life_s), 'IDLE_S': str(idle_s), 'POSE_PROCS': str(procs), 'POSE_OMP': str(omp),
           'POSE_FIT_TIMEOUT_S': str(load_rules()['fit_timeout_s']), 'POSE_CHECK_TIMEOUT_S': str(load_rules()['check_timeout_s']), 'DEPLOYMENT_EPOCH': f'20261122-{name}'}
    command = None
    if worker_z:
        command, env['KIT_WORKER_Z'] = worker_command()[0], worker_z
    return KD.group_body(name, image, tier, class_id, PORT, env, auth, command, work_type=WORK_TYPE, card=CARD)


def paths(a, sku: str) -> tuple[str, str]:
    return os.path.join(a.glb_dir, a.glb_name.format(sku=sku)), os.path.join(a.photo_dir, a.photo_name.format(sku=sku))


def job_id(sku: str, a, glb: bytes, photo: bytes) -> str:
    """Идемпотентный id: товар + хеш входа + параметры — повтор после вытеснения ноды не плодит дубль."""
    h = hashlib.sha256(glb + photo + json.dumps([a.px, a.n_fit, a.topk], sort_keys=True).encode()).hexdigest()[:12]
    return f'{sku}-{h}'.replace('_', '-')[:150]


def submit_pack(gw, a, skus: list[str], t: float) -> tuple[dict | None, dict]:
    """Отправить все товары пакета (POST /jobs по одному, GLB — zlib+base64). Любой не принят → отказ пакета с причиной."""
    ids: dict[str, str] = {}
    for sku in skus:
        gp, pp = paths(a, sku)
        glb, photo = open(gp, 'rb').read(), open(pp, 'rb').read()
        jid = job_id(sku, a, glb, photo)
        body = {'job_id': jid, 'glb_z': base64.b64encode(zlib.compress(glb, 6)).decode(), 'photo_b64': base64.b64encode(photo).decode(), 'px': a.px, 'n_fit': a.n_fit, 'topk': a.topk}
        c, r, _tinfo = KD.post_job(gw, '/jobs', body, f'/jobs/{jid}', say_fn=say)         # общий вход набора: таймаут по размеру тела, «нет ответа» → спросить воркера
        if c == -1:                                                                       # воркер задания не видит; job_id идемпотентен — один повтор, дубля не будет
            say(f'товар {sku}: POST без ответа, воркер задания не видит — повтор один раз')
            c, r, _tinfo = KD.post_job(gw, '/jobs', body, f'/jobs/{jid}', say_fn=say)
        say(f'товар {sku}: POST /jobs → {c} (тело ≈{len(json.dumps(body)) / 2 ** 20:.1f} МБ)', str(r)[:120] if c != 202 else '')
        if c != 202:
            return None, {'http': c, 'detail': r, 'sku': sku, 'accepted': list(ids)}
        ids[sku] = jid
    return {'key': 'pack', 'id': f'pack-{int(t)}', 't0': t, 'ids': ids, 'got': {}}, {}


def safe_extract(data: bytes, dest: str) -> list[str]:
    """zip → папка; пути только внутрь `dest` (абсолютные и `..` — отказ)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    root = os.path.realpath(dest)
    names = []
    for n in z.namelist():
        tgt = os.path.realpath(os.path.join(dest, n))
        if os.path.isabs(n) or not (tgt == root or tgt.startswith(root + os.sep)):
            raise ValueError(f'путь в архиве вне папки: {n}')
        names.append(n)
    z.extractall(dest)
    return names


def poll_pack(gw, a, cur: dict, t: float) -> tuple[str, dict]:
    """Все задания пакета закончились? Готовые забираем (sha256 сверяем, обязательные файлы проверяем), счёт отказов с причинами ведём. Пока кто-то идёт — 'running'."""
    items, running = {}, 0
    for sku, jid in cur['ids'].items():
        if sku in cur['got']:
            items[sku] = cur['got'][sku]
            continue
        c, v = gw.call('GET', f'/jobs/{jid}', timeout=30)
        if c != 200:
            running += 1                                   # шлюз моргнул — не провал; зависание ловят потолок денег и сторож хода
            continue
        if v.get('status') in ('queued', 'running'):
            running += 1
            continue
        if v.get('status') == 'failed':
            cur['got'][sku] = items[sku] = {'status': 'failed', 'error': v.get('error'), 'wall_s': v.get('wall_s')}
            continue
        c2, data = gw.call('GET', f'/jobs/{jid}/result', timeout=300, raw=True)
        if c2 != 200 or not data:
            running += 1
            continue
        rec = {k: v.get(k) for k in ('wall_s', 'fit_s', 'check_s', 'cpu_s', 'queue_s', 'metrics', 'bytes', 'sha256')}
        got = hashlib.sha256(data).hexdigest()
        if got != v.get('sha256'):
            cur['got'][sku] = items[sku] = {'status': 'failed', 'error': f'sha256 не сошёлся: ждали {v.get("sha256")}, получили {got}', **rec}
            continue
        out = os.path.join(a.out, sku)
        os.makedirs(out, exist_ok=True)
        open(os.path.join(a.out, f'{sku}.result.zip'), 'wb').write(data)
        names = safe_extract(data, out)
        miss = [n for n in NEED if n not in names]
        cur['got'][sku] = items[sku] = {'status': 'failed', 'error': f'в результате нет {miss}', **rec} if miss else {'status': 'done', 'files': len(names), **rec}
    if running:
        return 'running', {}
    fails = {k: v for k, v in items.items() if v['status'] != 'done'}
    info = {'items': items, 'ok': len(items) - len(fails), 'total': len(items), 'metrics': {'ok': len(items) - len(fails), 'total': len(items), 'failed': {k: v.get('error') for k, v in fails.items()}}}
    json.dump(items, open(os.path.join(a.out, 'items.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return ('failed', {'status': 'failed', 'error': f'отказов {len(fails)} из {len(items)}: {[k for k in fails]}', **info}) if fails else ('done', info)


def make_spec(a) -> KD.Spec:
    skus = [s for s in a.skus.split(',') if s]

    def build(name, class_id, auth):
        return build_body(name, a.image, a.tier, class_id, auth, min(a.max_min * 60 + 600, 3 * 3600), a.idle_s, a.procs, a.omp,
                          worker_z=None if getattr(a, 'worker_from_image', False) else worker_command()[1])

    def preflight():
        miss = [p for s in skus for p in paths(a, s) if not os.path.isfile(p)]
        if miss:
            return False, f'нет входных файлов: {miss[:4]}'
        return True, f'входы на месте: {len(skus)} товаров'

    return KD.Spec(prefix='trial-pose', card=CARD, model='pose-cpu', jobs=['pack'], build_body=build, work_type=WORK_TYPE, submit=lambda gw, k, t: submit_pack(gw, a, skus, t),
                   poll=lambda gw, cur, t: poll_pack(gw, a, cur, t), preflight=preflight, ready_keys=('version', 'libs', 'cpu_model', 'cpus', 'procs'), z_keys=('KIT_WORKER_Z',),
                   worker_file=WORKER)


# ---------------------------------------------------------------- бесплатная локальная сверка
class LocalGateway(Gateway):
    """Тот же вызов, что к Salad, но на локальный воркер (без ключа)."""

    def __init__(self, port: int):
        super().__init__(f'http://127.0.0.1:{port}', '')


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def run_local(a, sleep=time.sleep, clock=time.time) -> int:
    """Воркер на этой машине (`--code` — папка как в образе), те же submit_pack/poll_pack. Не платит и ничего не создаёт, кроме `--out` и временной папки воркера в `--out/_work`."""
    skus = [s for s in a.skus.split(',') if s]
    port = free_port()
    os.makedirs(a.out, exist_ok=True)
    env = dict(os.environ, PORT=str(port), POSE_CODE=os.path.join(a.code, 'tools/scout/salad/trellis'), POSE_WORK=os.path.join(a.out, '_work'), POSE_PROCS=str(a.procs), POSE_OMP=str(a.omp),
               MAX_LIFETIME_S=str(a.max_min * 60), IDLE_S='900')
    env.pop('PYTHONPATH', None)
    logf = open(os.path.join(a.out, 'worker.log'), 'wb')
    p = subprocess.Popen([a.python, '-I', WORKER], env=env, stdout=logf, stderr=subprocess.STDOUT, cwd=a.out)
    gw = LocalGateway(port)
    t0 = clock()
    rc = 1
    try:
        while True:
            c, h = gw.call('GET', '/health', timeout=10)
            if c == 200 and h.get('phase') == 'ready':
                say('воркер готов:', {k: h.get(k) for k in ('version', 'libs', 'cpu_model', 'cpus', 'procs')})
                break
            if c == 200 and h.get('phase') == 'broken':
                say('воркер broken:', h.get('error'))
                return 3
            if clock() - t0 > 120 or p.poll() is not None:
                say('воркер не поднялся за 2 мин')
                return 3
            sleep(1)
        cur, info = submit_pack(gw, a, skus, clock())
        if cur is None:
            say('пакет не принят:', info)
            return 2
        last = 0.0
        while True:
            status, res = poll_pack(gw, a, cur, clock())
            if clock() - last >= 60:
                last = clock()
                c, h = gw.call('GET', '/health', timeout=10)
                say('ход:', json.dumps((h or {}).get('job'), ensure_ascii=False)[:300], (h or {}).get('pool'))
            if status != 'running':
                say('ИТОГ', status, json.dumps({k: v for k, v in res.items() if k != 'items'}, ensure_ascii=False)[:400])
                for k, v in (res.get('items') or {}).items():
                    say(' ', k, {x: v.get(x) for x in ('status', 'wall_s', 'fit_s', 'check_s', 'cpu_s', 'queue_s', 'error')})
                rc = 0 if status == 'done' else 1
                break
            sleep(10)
    finally:
        gw.call('POST', '/shutdown', {}, timeout=10)
        try:
            p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            p.kill()
    return rc


def fallback_tier(tier: str, stopped_by: str) -> str | None:
    """Правило владельца (TG 1456/1457, 22.11): batch не берём; тариф low, нет машин → medium; выше НЕ поднимаем. Переход — только при no_machine (нода не выдана, платить не за что)."""
    return 'medium' if tier == 'low' and stopped_by == 'no_machine' else None


def stopped_by(a) -> str:
    try:
        return json.load(open(os.path.join(a.out, f'summary-trial-pose-{a.suffix}.json'), encoding='utf-8')).get('stopped_by') or ''
    except (OSError, ValueError):
        return ''


def run(a, MG, BR, **kw) -> int:
    rc = KD.run_probe(a, MG, BR, make_spec(a), **kw)
    nxt = fallback_tier(a.tier, stopped_by(a))
    if nxt:
        say(f'нет машин на тарифе {a.tier} — переход на {nxt} (выше не поднимаем, правило владельца)')
        a.tier, a.suffix = nxt, a.suffix + 'm'
        rc = KD.run_probe(a, MG, BR, make_spec(a), **kw)
    return rc


def main() -> int:
    r = load_rules()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--image', help='образ группы: имя@sha256:digest (по тегу — отказ, ADR-0137)')
    ap.add_argument('--skus', default='', help='ключи товаров через запятую (список — аргументом, в код не зашит)')
    ap.add_argument('--glb-dir', default=os.path.expanduser('~/remlab-logs/t178-forms-1122/forms-out'))
    ap.add_argument('--glb-name', default='{sku}-hd.glb')
    ap.add_argument('--photo-dir', default=os.path.expanduser('~/remlab-logs/t178-forms-1122/forms-inputs'))
    ap.add_argument('--photo-name', default='{sku}.hd.rgba.png')
    ap.add_argument('--out', default=os.path.expanduser('~/remlab-logs/t184-1122/pose-out'))
    ap.add_argument('--tier', default='low', choices=['low', 'medium'], help='low; нет машин → medium (автоматически); batch и high запрещены правилом владельца 22.11')
    ap.add_argument('--procs', type=int, default=r['procs'], help='процессов расчёта на ноде (по ядру)')
    ap.add_argument('--omp', type=int, default=r['omp_threads'])
    ap.add_argument('--px', type=int, default=None)
    ap.add_argument('--n-fit', type=int, default=None)
    ap.add_argument('--topk', type=int, default=None)
    ap.add_argument('--probe-cap', type=float, default=1.0, help='потолок денег, пока не готово первое задание, $')
    ap.add_argument('--cap', type=float, default=1.0, help='общий потолок, $')
    ap.add_argument('--max-min', type=int, default=90)
    ap.add_argument('--running-min', type=int, default=30)
    ap.add_argument('--health-min', type=int, default=8)
    ap.add_argument('--start-min', type=int, default=20)
    ap.add_argument('--ready-min', type=int, default=30)
    ap.add_argument('--stall-min', type=int, default=5)
    ap.add_argument('--stall-gb', type=float, default=0.05)
    ap.add_argument('--job-min', type=int, default=0)
    ap.add_argument('--idle-s', type=int, default=900)
    ap.add_argument('--worker-from-image', action='store_true')
    ap.add_argument('--suffix', default=time.strftime('%m%d%H%M', time.gmtime()))
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--stop-only', action='store_true')
    ap.add_argument('--local', action='store_true', help='бесплатная сверка: воркер на этой машине')
    ap.add_argument('--code', default='', help='--local: папка кода как в образе (stage_pose_code.py)')
    ap.add_argument('--python', default=sys.executable, help='--local: интерпретатор воркера (venv с теми же версиями библиотек)')
    a = ap.parse_args()
    if a.local:
        if not a.skus or not a.code:
            sys.exit('--local: нужны --skus и --code')
        return run_local(a)
    import bench_run as BR
    import migrate_groups as MG
    if a.stop_only:
        MG.env_from_file()
        return 0 if KD.stop_and_verify(BR, f'trial-pose-{a.suffix}') else 1
    if not a.skus or not a.image:
        sys.exit('нужны --image и --skus')
    return run(a, MG, BR)


if __name__ == '__main__':
    sys.exit(main())
