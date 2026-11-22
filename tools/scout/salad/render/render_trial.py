#!/usr/bin/env python3
"""ПРОБА SALAD «КАДРЫ ФОРМ» (T-184/1, очередь 3): кадры приёмки форм (виды × свет, глина) Blender-ом на видеокарте ноды. Драйвер — на общем наборе (`kit_driver.run_probe`): деньги, потолок,
гашение и проверка «0 нод» — там; здесь только «что отправить и как забрать». Один «пакет» = все товары пробы одним заданием `pack`: воркер рисует до RENDER_PROCS форм параллельно.
Виды и свет берём из `tools/ops/forms_render.py` (`accept_views(роль)`, `ACCEPT_LIGHTS`) — ту же таблицу, что у нашего локального счёта; отдельной копии нет.

Запуск (платный, только под heavy-slot --prio 2, по ОДНОЙ группе на пакет, потолок $1):
  heavy-slot.sh t184-render-probe --prio 2 -- python render_trial.py --image ghcr.io/…/mesh-render-trial@sha256:… --skus a,b,c,d,e --seats c,d --apply
Без --apply — только разбор: тело группы без секретов, проверка образа (группа НЕ создаётся). `--stop-only --suffix X` — погасить группу X и проверить «0 нод».
Тариф: low; нет машин → medium (автоматически); batch и high запрещены (владелец 22.11, TG 1456/1457).
Вход: `<glb-dir>/<glb-name>`; роль «сидячий» (диван/кресло/стул/кушетка → добавляется низкий боковой вид) — списком `--seats`. Выход: `<out>/<sku>/NN_<вид>_clay[_graze].png`, sha256 сверен.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.abspath(os.path.join(HERE, '..'))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, SALAD)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'render_gpu')))       # bench_run (group_state/instances/stop_and_verify)
sys.path.insert(0, os.path.join(SALAD, 'pose'))
import kit_driver as KD  # noqa: E402
import kit_worker as KW  # noqa: E402
import pose_trial as PT  # noqa: E402  — общие куски пакетной пробы: безопасная распаковка, правило тарифа
import worker_render as WR  # noqa: E402
from kit_driver import Gateway, say  # noqa: E402

WORK_TYPE = 'forms_render'                                        # профиль ресурсов: rules/salad-resources.json (T-186/1) — карта, vCPU, RAM, диск, shm, тариф только оттуда
CARD = KD.resource_profile(WORK_TYPE)['card']
PORT = 8000
WORKER = os.path.join(HERE, 'worker_render.py')
RULES = os.path.normpath(os.path.join(HERE, '..', '..', 'rules', 'salad-render.json'))
SEAT_ROLE = 'диван'                                             # любая из SEAT_ROLES: у forms_render.accept_views сидячая роль → + низкий боковой вид
PREFIX = 'trial-forms'


def load_rules() -> dict:
    return json.load(open(RULES, encoding='utf-8'))


def forms_render():
    """Таблицы видов и света — из forms_render.py репозитория (на драйвере; в образе — тот же файл)."""
    return WR.load_forms_render({'code': ROOT, 'blender': ''})


def views_for(fr, sku: str, seats: set[str]) -> tuple:
    return fr.accept_views(SEAT_ROLE if sku in seats else '')


def worker_command(path: str | None = None) -> tuple[list[str], str]:
    return KW.bundle(path or WORKER)


def build_body(name: str, image: str, tier: str, class_id: str, auth: dict, life_s: int, idle_s: int, procs: int, threads: int, worker_z: str | None = None) -> dict:
    env = {'PORT': str(PORT), 'MAX_LIFETIME_S': str(life_s), 'IDLE_S': str(idle_s), 'RENDER_PROCS': str(procs), 'RENDER_THREADS': str(threads), 'RENDER_DEVICE': 'GPU',
           'RENDER_TIMEOUT_S': str(load_rules()['frame_timeout_s']), 'DEPLOYMENT_EPOCH': f'20261122-{name}'}
    command = None
    if worker_z:
        command, env['KIT_WORKER_Z'] = worker_command()[0], worker_z
    return KD.group_body(name, image, tier, class_id, PORT, env, auth, command, work_type=WORK_TYPE, card=CARD)


def glb_path(a, sku: str) -> str:
    return os.path.join(a.glb_dir, a.glb_name.format(sku=sku))


def job_id(sku: str, a, glb: bytes, views, lights) -> str:
    """Идемпотентный id: товар + хеш входа + параметры — повтор после вытеснения ноды не плодит дубль."""
    h = hashlib.sha256(glb + json.dumps([list(views), list(lights), a.samples, a.shade], sort_keys=True).encode()).hexdigest()[:12]
    return f'{sku}-{h}'.replace('_', '-')[:150]


def submit_pack(gw, a, skus: list[str], seats: set[str], t: float) -> tuple[dict | None, dict]:
    """Отправить все товары пакета (POST /jobs по одному через общий post_job, GLB — zlib+base64). Любой не принят → отказ пакета с причиной."""
    fr = forms_render()
    ids: dict[str, str] = {}
    expect: dict[str, list[str]] = {}
    for sku in skus:
        glb = open(glb_path(a, sku), 'rb').read()
        views, lights = views_for(fr, sku, seats), tuple(fr.ACCEPT_LIGHTS)
        jid = job_id(sku, a, glb, views, lights)
        body = {'job_id': jid, 'glb_z': base64.b64encode(zlib.compress(glb, 6)).decode(), 'views': list(views), 'lights': list(lights), 'samples': a.samples, 'shade': a.shade}
        c, r, _tinfo = KD.post_job(gw, '/jobs', body, f'/jobs/{jid}', say_fn=say)
        if c == -1:                                                                       # воркер задания не видит; job_id идемпотентен — один повтор, дубля не будет
            say(f'товар {sku}: POST без ответа, воркер задания не видит — повтор один раз')
            c, r, _tinfo = KD.post_job(gw, '/jobs', body, f'/jobs/{jid}', say_fn=say)
        say(f'товар {sku}: POST /jobs → {c} (тело ≈{len(json.dumps(body)) / 2 ** 20:.1f} МБ, видов {len(views)}, света {len(lights)})', str(r)[:120] if c != 202 else '')
        if c != 202:
            return None, {'http': c, 'detail': r, 'sku': sku, 'accepted': list(ids)}
        ids[sku] = jid
        expect[sku] = fr.frame_names(views, lights)
    return {'key': 'pack', 'id': f'pack-{int(t)}', 't0': t, 'ids': ids, 'expect': expect, 'got': {}}, {}


def poll_pack(gw, a, cur: dict, t: float) -> tuple[str, dict]:
    """Все задания пакета закончились? Готовые забираем (sha256 сверяем, все кадры проверяем по списку), счёт отказов с причинами ведём. Пока кто-то идёт — 'running'."""
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
        rec = {k: v.get(k) for k in ('wall_s', 'render_s', 'queue_s', 'metrics', 'bytes', 'sha256')}
        got = hashlib.sha256(data).hexdigest()
        if got != v.get('sha256'):
            cur['got'][sku] = items[sku] = {'status': 'failed', 'error': f'sha256 не сошёлся: ждали {v.get("sha256")}, получили {got}', **rec}
            continue
        out = os.path.join(a.out, sku)
        os.makedirs(out, exist_ok=True)
        open(os.path.join(a.out, f'{sku}.result.zip'), 'wb').write(data)
        names = PT.safe_extract(data, out)
        miss = [n for n in cur['expect'][sku] if n not in names]
        cur['got'][sku] = items[sku] = {'status': 'failed', 'error': f'в результате нет кадров {miss}', **rec} if miss else {'status': 'done', 'files': len(names), **rec}
    if running:
        return 'running', {}
    fails = {k: v for k, v in items.items() if v['status'] != 'done'}
    info = {'items': items, 'ok': len(items) - len(fails), 'total': len(items), 'metrics': {'ok': len(items) - len(fails), 'total': len(items), 'failed': {k: v.get('error') for k, v in fails.items()}}}
    json.dump(items, open(os.path.join(a.out, 'items.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return ('failed', {'status': 'failed', 'error': f'отказов {len(fails)} из {len(items)}: {[k for k in fails]}', **info}) if fails else ('done', info)


def make_spec(a) -> KD.Spec:
    skus = [s for s in a.skus.split(',') if s]
    seats = {s for s in a.seats.split(',') if s}

    def build(name, class_id, auth):
        return build_body(name, a.image, a.tier, class_id, auth, min(a.max_min * 60 + 600, 3 * 3600), a.idle_s, a.procs, a.threads,
                          worker_z=None if getattr(a, 'worker_from_image', False) else worker_command()[1])

    def preflight():
        miss = [glb_path(a, s) for s in skus if not os.path.isfile(glb_path(a, s))]
        if miss:
            return False, f'нет входных файлов: {miss[:4]}'
        if not seats <= set(skus):
            return False, f'--seats: товаров нет в --skus: {sorted(seats - set(skus))}'
        return True, f'входы на месте: {len(skus)} товаров, сидячих {len(seats)}'

    return KD.Spec(prefix=PREFIX, card=CARD, model='forms-render', jobs=['pack'], build_body=build, work_type=WORK_TYPE, submit=lambda gw, k, t: submit_pack(gw, a, skus, seats, t),
                   poll=lambda gw, cur, t: poll_pack(gw, a, cur, t), preflight=preflight, ready_keys=('version', 'blender', 'cuda', 'device', 'procs'), z_keys=('KIT_WORKER_Z',),
                   worker_file=WORKER)


def stopped_by(a) -> str:
    try:
        return json.load(open(os.path.join(a.out, f'summary-{PREFIX}-{a.suffix}.json'), encoding='utf-8')).get('stopped_by') or ''
    except (OSError, ValueError):
        return ''


def run(a, MG, BR, **kw) -> int:
    rc = KD.run_probe(a, MG, BR, make_spec(a), **kw)
    nxt = PT.fallback_tier(a.tier, stopped_by(a))                # правило владельца: low → medium только при no_machine; выше не поднимаем
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
    ap.add_argument('--seats', default='', help='из --skus: сидячие (диван/кресло/стул/кушетка) — им добавляется низкий боковой вид')
    ap.add_argument('--glb-dir', default=os.path.expanduser('~/remlab-logs/t178-forms-1122/forms-out'))
    ap.add_argument('--glb-name', default='{sku}-hd.glb')
    ap.add_argument('--out', default=os.path.expanduser('~/remlab-logs/t184-1122/render-out'))
    ap.add_argument('--tier', default='low', choices=['low', 'medium'], help='low; нет машин → medium (автоматически); batch и high запрещены правилом владельца 22.11')
    ap.add_argument('--procs', type=int, default=r['procs'], help='форм одновременно на ноде')
    ap.add_argument('--threads', type=int, default=r['threads'], help='потоков процессора на одну форму (разбор сцены)')
    ap.add_argument('--samples', type=int, default=r['samples'], help='как у нашего локального счёта (forms_render --samples по умолчанию)')
    ap.add_argument('--shade', default='orig', choices=['orig', 'recalc', 'flat'])
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
    a = ap.parse_args()
    import bench_run as BR
    import migrate_groups as MG
    if a.stop_only:
        MG.env_from_file()
        return 0 if KD.stop_and_verify(BR, f'{PREFIX}-{a.suffix}') else 1
    if not a.skus or not a.image:
        sys.exit('нужны --image и --skus')
    return run(a, MG, BR)


if __name__ == '__main__':
    sys.exit(main())
