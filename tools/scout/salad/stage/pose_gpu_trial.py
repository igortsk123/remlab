#!/usr/bin/env python3
"""ПРОБА SALAD «ЭТАП 04 — КАМЕРА ПО ФОТО НА ВИДЕОКАРТЕ» (T-185/1): `pose_fit --device cuda` + `camera_check` на ноде по профилю `pose_camera_gpu` (rules/salad-resources.json: RTX 3090, тариф low → medium).
Воркер тот же, что у этапов 06/07 (`worker_stage.py`, команда `pose_job`), драйвер — на общем наборе (`kit_driver.run_probe`: деньги, потолок, гашение, «0 нод»). Образ — только среда (python + torch CUDA);
код этапа едет в задании по SHA (`code_tar.py`, как у stage_trial.py). Одна группа, один проход: задание на товар → забираем `<out>/<товар>/` — ТОЧНО в раскладке нашего прогона (pose.json, stage_loss.json,
stages/…, 04-camera/check.json), чтобы `tools/scout/salad/pose/compare_pose.py` сверил её с эталоном без правок.

Запуск (платный, только под heavy-slot --prio 2, одна группа на пакет, потолок $1):
  heavy-slot.sh t185-gpu-probe --prio 2 -- python pose_gpu_trial.py --image ghcr.io/…/mesh-stagegpu-trial@sha256:… --inputs inputs.json --apply
Без --apply — только разбор: тело группы без секретов, срез кода, входы (группа НЕ создаётся). `--stop-only --suffix X` — погасить группу X и проверить «0 нод».
Входы — файл `inputs.json`: {"<товар>": {"glb": путь формы, "photo": путь RGBA-вырезки}} (список — аргументом, в код не зашит). Тариф: low; нет машин → medium (автоматически); batch и high запрещены.
Выход: `<out>/<товар>/…`, `<out>/items-pose.json` (время задания, пик памяти, код выхода, вердикт, code_sha).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import sys
import time
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stage_trial as ST  # noqa: E402  (кладёт в sys.path набор Salad и каталог воркера)
import kit_driver as KD  # noqa: E402
import worker_stage as WS  # noqa: E402
import code_tar as CT  # noqa: E402
from kit_driver import say  # noqa: E402

WORK_TYPE = 'pose_camera_gpu'                                  # профиль ресурсов: карта, vCPU, RAM, диск, shm, тариф — только оттуда
PREFIX = 'trial-posegpu'
PORT = ST.PORT
STAGE = 'pose_job'                                             # команда воркера (whitelist)
KEY = 'pose'                                                   # ключ прохода в наборе


def card_name() -> str:
    return KD.resource_profile(WORK_TYPE)['card']


def build_body(name: str, image: str, tier: str, class_id: str, auth: dict, life_s: int, idle_s: int, procs: int, threads: int, timeout_s: int, worker_z: str | None = None) -> dict:
    env = {'PORT': str(PORT), 'MAX_LIFETIME_S': str(life_s), 'IDLE_S': str(idle_s), 'STAGE_PROCS': str(procs), 'STAGE_FILL_PROCS': '1', 'STAGE_THREADS': str(threads),
           'STAGE_TIMEOUT_S': str(timeout_s), 'DEPLOYMENT_EPOCH': f'20261122-{name}'}
    command = None
    if worker_z:
        command, env['KIT_WORKER_Z'] = ST.worker_command()[0], worker_z
    return KD.group_body(name, image, tier, class_id, PORT, env, auth, command, work_type=WORK_TYPE)


def load_inputs(path: str) -> dict[str, dict]:
    return json.load(open(path, encoding='utf-8'))


def input_problems(inputs: dict[str, dict]) -> list[str]:
    bad = []
    for sku, v in inputs.items():
        for k in ('glb', 'photo'):
            if not v.get(k) or not os.path.isfile(v[k]):
                bad.append(f'{sku}: нет файла {k} ({v.get(k)})')
    return bad


def pose_args(device: str) -> list[str]:
    return ['--glb', '@in/model.glb', '--photo', '@in/photo.png', '--out-run', '@out', '--device', device]


def input_zip(v: dict, code_tar: bytes | None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        z.write(v['glb'], 'model.glb')
        z.write(v['photo'], 'photo.png')
        if code_tar:
            z.writestr('code.tar', code_tar)
    return buf.getvalue()


def job_id(sku: str, data: bytes, a) -> str:
    h = hashlib.sha256(data + json.dumps([STAGE, a.device, a.threads], sort_keys=True).encode()).hexdigest()[:12]
    return f'pose-{sku}-{h}'.replace('_', '-')[:150]


def submit(gw, a, inputs: dict, t: float) -> tuple[dict | None, dict]:
    """По заданию на товар (POST /jobs; zip входа — zlib+base64). Идемпотентный job_id: повтор после вытеснения ноды не плодит дубль."""
    ids: dict[str, str] = {}
    code = getattr(a, 'code', None) or {}
    for sku, v in inputs.items():
        data = input_zip(v, code.get('tar'))
        jid = job_id(sku, data, a)
        body = {'job_id': jid, 'stage': STAGE, 'sku': sku, 'input_z': base64.b64encode(zlib.compress(data, 6)).decode(), 'body_only': False,
                'code_sha': code.get('sha', ''), 'code_tar_sha256': code.get('tar_sha256', ''), 'args': pose_args(a.device)}
        c, r, _t = KD.post_job(gw, '/jobs', body, f'/jobs/{jid}', say_fn=say)
        if c == -1:
            say(f'товар {sku}: POST без ответа, воркер задания не видит — повтор один раз')
            c, r, _t = KD.post_job(gw, '/jobs', body, f'/jobs/{jid}', say_fn=say)
        say(f'товар {sku}: POST /jobs → {c} (тело ≈{len(json.dumps(body)) / 2 ** 20:.1f} МБ)', str(r)[:120] if c != 202 else '')
        if c != 202:
            return None, {'http': c, 'detail': r, 'sku': sku, 'accepted': list(ids)}
        ids[sku] = jid
    if not ids:
        return None, {'detail': 'нечего отправлять'}
    return {'key': KEY, 'id': f'pose-{int(t)}', 't0': t, 'ids': ids, 'skipped': {}, 'got': {}}, {}


def poll(gw, a, cur: dict, t: float) -> tuple[str, dict]:
    """Все задания закончились? Готовые забираем (sha256 и code_sha сверяем), распаковываем в `<out>/<товар>/`. «Камера не прошла» (metrics.passed=false) — результат, не отказ."""
    items, running = {}, 0
    want_sha = (getattr(a, 'code', None) or {}).get('sha')
    for sku, jid in cur['ids'].items():
        if sku in cur['got']:
            items[sku] = cur['got'][sku]
            continue
        c, v = gw.call('GET', f'/jobs/{jid}', timeout=30)
        if c != 200 or v.get('status') in ('queued', 'running'):
            running += 1
            continue
        if v.get('status') == 'failed':
            cur['got'][sku] = items[sku] = {'status': 'failed', 'error': v.get('error'), 'wall_s': v.get('wall_s'), 'run_s': v.get('run_s'), 'peak_gb': v.get('peak_gb')}
            continue
        c2, data = gw.call('GET', f'/jobs/{jid}/result', timeout=300, raw=True)
        if c2 != 200 or not data:
            running += 1
            continue
        rec = {k: v.get(k) for k in ('wall_s', 'run_s', 'queue_s', 'peak_gb', 'metrics', 'bytes', 'sha256', 'files', 'code_sha', 'code_tar_sha256', 'cmd')}
        if want_sha and v.get('code_sha') != want_sha:
            cur['got'][sku] = items[sku] = {'status': 'failed', 'error': f'code_sha не сошёлся: отправлен {want_sha}, посчитано на коде {v.get("code_sha")}', **rec}
            continue
        got = hashlib.sha256(data).hexdigest()
        if got != v.get('sha256'):
            cur['got'][sku] = items[sku] = {'status': 'failed', 'error': f'sha256 не сошёлся: ждали {v.get("sha256")}, получили {got}', **rec}
            continue
        out = os.path.join(a.out, sku)
        os.makedirs(out, exist_ok=True)
        try:
            names = WS.safe_extract(data, out)
        except ValueError as exc:
            cur['got'][sku] = items[sku] = {'status': 'failed', 'error': f'результат не распаковался: {exc}', **rec}
            continue
        cur['got'][sku] = items[sku] = {'status': 'done', 'unpacked': len(names), **rec}
    if running:
        return 'running', {}
    fails = {k: v for k, v in items.items() if v['status'] == 'failed'}
    ok = sum(1 for v in items.values() if v['status'] == 'done')
    info = {'items': items, 'ok': ok, 'total': len(items), 'metrics': {'ok': ok, 'total': len(items), 'failed': {k: v.get('error') for k, v in fails.items()}}}
    os.makedirs(a.out, exist_ok=True)
    json.dump(items, open(os.path.join(a.out, 'items-pose.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return ('failed', {'status': 'failed', 'error': f'отказов {len(fails)} из {len(items)}: {list(fails)}', **info}) if fails else ('done', info)


def make_spec(a, inputs: dict) -> KD.Spec:
    def build(name, class_id, auth):
        return build_body(name, a.image, a.tier, class_id, auth, min(a.max_min * 60 + 600, 3 * 3600), a.idle_s, a.procs, a.threads, a.job_timeout_s,
                          worker_z=None if getattr(a, 'worker_from_image', False) else ST.worker_command()[1])

    def preflight():
        try:
            a.code = CT.build(getattr(a, 'repo', '') or ST.ROOT, getattr(a, 'code_ref', '') or 'HEAD')
        except CT.CodeTarError as exc:
            return False, f'код задания не собран: {exc}'
        if not getattr(a, 'no_code_check', False):
            why = CT.selfcheck(a.code['tar'], a.code['entries'])
            if why:
                return False, f'срез кода {a.code["sha"][:8]} неполон: {why}'
        say(f'код задания: SHA {a.code["sha"]}, tar {len(a.code["tar"]) / 1024:.0f} КБ, {len(a.code["files"])} файлов, sha256 {a.code["tar_sha256"][:16]}…')
        if not any(f.endswith('/pose_gpu.py') for f in a.code['files']):
            return False, 'в срезе кода нет pose_gpu.py — --device cuda на ноде не заработает'
        bad = input_problems(inputs)
        if bad:
            return False, f'входы не готовы: {bad[:4]}'
        return True, f'входы на месте: {len(inputs)} товаров'

    return KD.Spec(prefix=PREFIX, card=card_name(), model='pose-gpu', jobs=[KEY], build_body=build, submit=lambda gw, k, t: submit(gw, a, inputs, t),
                   poll=lambda gw, cur, t: poll(gw, a, cur, t), preflight=preflight, ready_keys=('version', 'libs', 'procs'), z_keys=('KIT_WORKER_Z',),
                   worker_file=ST.WORKER, work_type=WORK_TYPE)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--image', help='образ группы: имя@sha256:digest (по тегу — отказ, ADR-0137)')
    ap.add_argument('--inputs', default='', help='inputs.json: {товар: {glb, photo}}')
    ap.add_argument('--device', choices=('cpu', 'cuda'), default='cuda', help='cuda — боевой путь на ноде; cpu — только для отладки (быстрее numpy не будет)')
    ap.add_argument('--code-ref', default='HEAD', help='SHA/ветка, чей код едет в задании (code.tar из git archive; по умолчанию HEAD дерева драйвера)')
    ap.add_argument('--repo', default=ST.ROOT)
    ap.add_argument('--no-code-check', action='store_true')
    ap.add_argument('--out', default=os.path.expanduser('~/remlab-logs/t185-1122/salad-out'))
    ap.add_argument('--tier', default='low', choices=['low', 'medium'], help='low; нет машин → medium (автоматически); batch и high запрещены правилом владельца 22.11')
    ap.add_argument('--procs', type=int, default=4, help='заданий одновременно на ноде (профиль: 4 vCPU — Нелдер–Мид на процессоре, ядро на процесс)')
    ap.add_argument('--threads', type=int, default=1)
    ap.add_argument('--job-timeout-s', type=int, default=900)
    ap.add_argument('--probe-cap', type=float, default=1.0, help='потолок денег, пока не готово первое задание, $')
    ap.add_argument('--cap', type=float, default=1.0, help='общий потолок, $')
    ap.add_argument('--max-min', type=int, default=60)
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
    if not a.image or not a.inputs:
        sys.exit('нужны --image и --inputs')
    inputs = load_inputs(a.inputs)
    if not inputs:
        sys.exit('нет товаров для пакета')
    return KD.run_probe(a, MG, BR, make_spec(a, inputs))


if __name__ == '__main__':
    sys.exit(main())
