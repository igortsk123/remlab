#!/usr/bin/env python3
"""Проба моделей разметки частей на Salad (Ш5 / T-183, T-20261121-179) НА ОБЩЕМ НАБОРЕ (kit_driver.run_probe + kit_worker, T-178/2).
ОДНА группа = ОДНА нода (4090) = один образ (p3sam | partllm); задание = один меш × один вариант параметров. Здесь только то, что знает модель: тело группы, что послать, как принять
и проверить результат. Охрана денег, ожидание образа, сторож докачки образа (PullGuard), сторож «завис» по ходу задания (JobStall: шаг тот же и GPU < 5 % > --stuck-min), 429 «занят»,
гашение с проверкой «0 нод», учёт в общий ledger — в kit_driver.
Без --apply — только разбор (тело без секретов, группа НЕ создаётся). С --apply — платное: запускать ТОЛЬКО под `tools/ops/heavy-slot.sh <метка> --prio 2 …`.
Результат на задание: <out>/<tag>/<sid>/faces.npy (int32[F], порядок граней входного glb, -1 без метки), meta.json (+ faces_class.npy у PartLLM); в meta.extra — таблица стадий
(секунды, устройство gpu/cpu, средняя загрузка GPU и ядер CPU). Наша проверка БЕСПЛАТНО: число меток = граней и согласие соседних граней против перемешанных (order_ok).
Плановый стоп: --max-meshes N, --stop-file, «по средней длительности не успеет до потолка», первый провал (платное впустую не шлём)."""
import argparse
import base64
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, SALAD)
sys.path.insert(0, os.path.abspath(os.path.join(SALAD, '..', 'render_gpu')))          # bench_run (group_state/instances/stop_and_verify)
import kit_driver as KD  # noqa: E402
import kit_worker as KW  # noqa: E402

say = KD.say
MODELS = ('p3sam', 'partllm')
CARD = 'RTX 4090 (24 GB)'
CUDA_ARCHS = ('8.0', '8.6', '8.9')                                   # TORCH_CUDA_ARCH_LIST образа (Dockerfile.p3sam)
PORT = 8000
WORKER = os.path.join(HERE, 'worker_parts.py')


def build_body(name, class_id, auth, a):
    env = {'MODEL': a.model, 'HF_HOME': '/data/hf', 'OUT_DIR': '/data/out', 'PORT': str(PORT), 'NVIDIA_DRIVER_CAPABILITIES': 'all', 'DEPLOYMENT_EPOCH': f'20261121-{name}',
           'MAX_LIFETIME_S': str(min(a.max_min * 60 + 600, 3 * 3600)), 'IDLE_S': '1200', 'IMAGE_NOTE': a.image.split('@')[-1][:19]}
    cmd, z = KW.bundle(WORKER)                                        # код воркера — в env группы (KIT_WORKER_Z), образ не пересобирается
    env['KIT_WORKER_Z'] = z
    resources = {'cpu': a.cpu, 'memory': a.mem_mb, 'storage_amount': 40 * 2 ** 30, 'shm_size': 2048}
    return KD.group_body(name, a.image, a.tier, class_id, PORT, env, resources, auth, command=cmd)


def check_faces(glb_path, faces_path):
    """БЕСПЛАТНО на нашей стороне: число меток = граней; согласие смежных граней против перемешанных меток (ловит «грани в другом порядке»)."""
    import numpy as np
    import trimesh
    f = np.load(faces_path)
    m = trimesh.load(glb_path, force='mesh', process=False)
    n = int(len(m.faces))
    r = {'n_faces_glb': n, 'n_labels': int(f.shape[0]), 'count_ok': bool(f.shape == (n,)), 'dtype': str(f.dtype)}
    if not r['count_ok']:
        return r
    mm = m.copy()
    mm.merge_vertices()
    adj = mm.face_adjacency
    a, b = f[adj[:, 0]], f[adj[:, 1]]
    ok = (a >= 0) & (b >= 0)
    agree = float((a[ok] == b[ok]).mean()) if ok.any() else 0.0
    rng = np.random.default_rng(0)
    g = rng.permutation(f)
    ga, gb = g[adj[:, 0]], g[adj[:, 1]]
    okg = (ga >= 0) & (gb >= 0)
    shuf = float((ga[okg] == gb[okg]).mean()) if okg.any() else 0.0
    r.update(adj_pairs=int(len(adj)), adj_agree=round(agree, 4), adj_agree_shuffled=round(shuf, 4), n_parts=int(len([x for x in np.unique(f) if x >= 0])),
             share_unlabeled=round(float((f < 0).mean()), 4), order_ok=bool(agree >= 0.85 and agree > shuf + 0.2))
    return r


def make_plan(items, variants):
    """[(ключ, меш, вариант)] — меш за мешом, внутри каждого все варианты подряд; ключ = <sid>__<tag> (или sid без вариантов)."""
    out = []
    for it in items:
        for v in (variants or [{}]):
            tag = v.get('tag', '')
            out.append((f'{it["sid"]}__{tag}' if tag else str(it['sid']), it, v))
    return out


def stage_digest(meta: dict) -> list:
    """Короткая строка по стадиям для журнала: «имя сек устройство»."""
    st = ((meta or {}).get('extra') or {}).get('stage_table') or []
    return [f'{r.get("stage")} {r.get("sec")}с {r.get("device") or "?"}' for r in st if (r.get('sec') or 0) >= 1.0]


def make_spec(a, plan, price_ref):
    by_key = {k: (it, v) for k, it, v in plan}
    base_params = json.loads(a.params)
    done_durs: list = []
    state = {'sent': 0, 'failed': 0, 'done': 0, 'last_health': 0.0}

    def preflight():
        miss = [it['path'] for _k, it, _v in plan if not os.path.isfile(os.path.expanduser(it['path']))]
        return (False, f'нет файлов: {miss[:3]}') if miss else (True, f'{len(plan)} заданий, входы на месте')

    def submit(gw, key, t):
        it, v = by_key[key]
        glb = open(os.path.expanduser(it['path']), 'rb').read()
        jid = f'{a.model}-{key}'
        body = {'job_id': jid, 'items': [{'sid': key, 'glb_b64': base64.b64encode(glb).decode()}], 'params': {**base_params, **v.get('params', {})}}
        c, r = gw.call('POST', '/run', body, timeout=90)
        if c != 202:
            return None, {'http': c, 'detail': r}
        state['sent'] += 1
        say('задание', key, '→ HTTP 202', f'{len(glb) / 1e6:.1f} МБ')
        return {'key': key, 'id': jid, 't0': t, 'path': os.path.expanduser(it['path']), 'tag': v.get('tag', ''), 'sid': str(it['sid'])}, {}

    def poll(gw, cur, t):
        c, r = gw.call('GET', '/job/' + cur['id'], timeout=30)
        if c != 200 or r.get('state') != 'done':
            if t - state['last_health'] >= 60:                        # воркер сломан (фатальная CUDA/OOM) — ждать нечего
                state['last_health'] = t
                hc, hb = gw.call('GET', '/health', timeout=20)
                if hc == 200 and (hb or {}).get('phase') == 'broken':
                    state['failed'] += 1
                    return 'failed', {'status': 'worker_broken', 'error': f'воркер сломан: {(hb or {}).get("error")}'}
            return 'running', {}
        res = (r.get('results') or [{}])[0]
        od = os.path.join(a.out, cur['tag'], cur['sid']) if cur['tag'] else os.path.join(a.out, cur['sid'])
        os.makedirs(od, exist_ok=True)
        for fn in ('meta.json', 'faces.npy', 'faces_class.npy'):
            cf, raw = gw.call('GET', f'/file/{cur["id"]}/{cur["key"]}/{fn}', timeout=120, raw=True)
            if cf == 200:
                open(os.path.join(od, fn), 'wb').write(raw)
        if res.get('rc') != 0:
            state['failed'] += 1
            return 'failed', {'status': 'failed', 'error': res.get('error') or r.get('error'), 'meta': {k: res.get(k) for k in ('sec_cold', 'sec_warm', 'peak_vram_gb')}}
        try:
            chk = check_faces(cur['path'], os.path.join(od, 'faces.npy'))
        except Exception as e:  # noqa: BLE001
            chk = {'count_ok': False, 'error': f'{type(e).__name__}: {e}'[:200]}
        if not (chk.get('count_ok') and chk.get('order_ok')):
            state['failed'] += 1
            return 'failed', {'status': 'failed', 'error': f'проверка граней: {chk}'}
        sec = res.get('sec_cold') or res.get('sec_warm')
        done_durs.append(time.time() - cur['t0'])
        state['done'] += 1
        metrics = {'sec': sec, 'n_parts': res.get('n_parts'), 'adj_agree': chk.get('adj_agree'), 'peak_smi_gb': res.get('peak_smi_gb'), 'peak_torch_reserved_gb': res.get('peak_torch_reserved_gb'),
                   'stages': stage_digest(res)}
        return 'done', {'metrics': metrics, 'check': chk, 'meta': res}

    def before_job(key, cost, cap):
        if state['failed'] and not state['done']:
            return '!first_failed'                                    # первый же прогон не прошёл — платное впустую не шлём, чинить в коде
        if a.max_meshes and state['sent'] >= a.max_meshes:
            return f'--max-meshes {a.max_meshes} достигнут'
        if a.stop_file and os.path.exists(os.path.expanduser(a.stop_file)):
            return f'есть файл-стоп {a.stop_file}'
        if done_durs and price_ref[0]:
            mean = sum(done_durs) / len(done_durs)
            if cost + mean * 1.05 / 3600 * price_ref[0] > cap:
                return f'по средней длительности ({mean:.0f} с) не уложится в потолок ${cap}'
        return None

    return KD.Spec(prefix=f'trial-parts-{a.model}', card=CARD, model=f'parts-{a.model}', jobs=[k for k, _i, _v in plan], build_body=lambda n, c, auth: build_body(n, c, auth, a),
                   submit=submit, poll=poll, preflight=preflight, health_keys=('phase', 'root_gb', 'weights', 'cuda', 'error', 'load_s'), ready_keys=('version', 'model', 'load_s'),
                   z_keys=('KIT_WORKER_Z',), worker_file=WORKER, cuda_archs=CUDA_ARCHS, before_job=before_job)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model', required=True, choices=MODELS)
    ap.add_argument('--image', required=True, help='ghcr.io/igortsk123/mesh-parts-trial@sha256:…')
    ap.add_argument('--items', required=True, help='JSON [{"sid","path"}] — меши по порядку (первый проверяется сразу)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--suffix', default=time.strftime('%m%d%H%M', time.gmtime()))
    ap.add_argument('--tier', default='high', choices=['batch', 'low', 'medium', 'high'])
    ap.add_argument('--cpu', type=int, default=8)
    ap.add_argument('--mem-mb', type=int, default=32768)
    ap.add_argument('--cap', type=float, default=0.5, help='общий потолок денег на группу, $')
    ap.add_argument('--probe-cap', type=float, default=None, help='потолок до первого готового задания, $ (по умолчанию = --cap)')
    ap.add_argument('--max-min', type=int, default=45, help='предел минут после running')
    ap.add_argument('--running-min', type=int, default=60, help='минут от /start до running (нода выдана)')
    ap.add_argument('--start-min', type=int, default=20)
    ap.add_argument('--health-min', type=int, default=8)
    ap.add_argument('--ready-min', type=int, default=30)
    ap.add_argument('--stall-min', type=int, default=5)
    ap.add_argument('--stall-gb', type=float, default=0.05)
    ap.add_argument('--job-min', type=int, default=0, help='срезать задание дольше N мин (0 = только потолок пробы и сторож завис)')
    ap.add_argument('--stuck-min', type=float, default=4.0, help='шаг задания не меняется и GPU меньше 5 процентов дольше N мин → зависло, гашу (0 = выкл)')
    ap.add_argument('--max-realloc', type=int, default=3, help='пересадок медленно качающей образ ноды (общий бюджет node_health); 0 = не пересаживать')
    ap.add_argument('--pre', default='', help='зарезервировано: заплатка к образу не поддерживается набором — менять образ или код воркера')
    ap.add_argument('--max-meshes', type=int, default=0, help='после N отправленных заданий новые не отправлять (0 = без ограничения); дождаться текущего и погасить')
    ap.add_argument('--stop-file', default='', help='если файл существует — новые задания не отправлять (текущее дожидаемся, потом гасим)')
    ap.add_argument('--variants', default='', help='JSON-файл [{"tag","params"}]: каждый меш — по всем вариантам подряд; результаты в <out>/<tag>/<sid>/')
    ap.add_argument('--params', default='{}', help='JSON параметров модели (POST /run params)')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--stop-only', action='store_true')
    a = ap.parse_args()
    if a.pre:
        sys.exit('--pre не поддерживается на kit: заплатка к образу = пересборка образа или правка воркера (он едет в env группы)')
    if a.probe_cap is None:
        a.probe_cap = a.cap
    a.pull_guard = a.max_realloc > 0
    import bench_run as BR
    import migrate_groups as MG
    name = f'trial-parts-{a.model}-{a.suffix}'
    if a.stop_only:
        MG.env_from_file()
        return 0 if BR.stop_and_verify(name) else 1
    items = json.load(open(a.items))
    variants = json.load(open(a.variants)) if a.variants else []
    plan = make_plan(items, variants)
    price_ref = [None]
    spec = make_spec(a, plan, price_ref)
    MG.env_from_file()
    _cid, price = KD.gpu_class(MG, CARD, a.tier)
    price_ref[0] = price

    def pg(group):
        return KD.PullGuard(group, max_culls=a.max_realloc)               # общий бюджет пересадок node_health подключает сам PullGuard

    return KD.run_probe(a, MG, BR, spec, pull_guard=pg)


if __name__ == '__main__':
    sys.exit(main())
