#!/usr/bin/env python3
"""ПРОБА «StableGen на RunPod» (T-20261119-90/6; владелец TG 2115 «ок»). Тот же образ `stablegen-0460-cuda` и тот же воркер (`worker_sg.py`, едет в env), что на Salad, но машина — под RunPod (REST v2, api.runpod.io):
один под с RTX 4090, порт 8000 наружу через прокси RunPod (`https://<id>-8000.proxy.runpod.net`, без ключа). Blender с аддоном крутится ЗДЕСЬ (`sg_drive.py`), к поду ходит через `sg_relay.py`.

    python3 sg_runpod.py --image <digest> --runs <ключ:вариант,…>             # разбор: тело запроса без секретов, под НЕ создаётся
    ... --apply                                                                # создать, прогнать по очереди, УДАЛИТЬ с проверкой
    ... --stop-only --pod <id>                                                 # просто удалить под и проверить

ПРЕДОХРАНИТЕЛИ (как у sg_salad.py): потолок денег `--cap` $ на ВЕСЬ замер (платим с создания пода — на RunPod тянущийся образ тоже тарифицируется); предел жизни `--max-min`; нет ответа /health через
`--health-min` после RUNNING — удаляем; нет RUNNING за `--no-machine-min` — удаляем; 2 прогона подряд упали — удаляем; ИТОГ и УДАЛЕНИЕ С ПРОВЕРКОЙ — всегда (finally); веса — HEAD по HF до денег; ключ RunPod читается из
`_secrets/ACCESS.md` в памяти процесса и НИКОГДА не печатается и не пишется в журнал; на Salad этот скрипт ничего не трогает (кто первый «готов» — тот работает; второго гасит человек/директор)."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import sg_salad as S  # noqa: E402  — общие части: варианты, веса, конфиг драйвера, цена, HEAD по HF, строки хода

API = 'https://api.runpod.io'
ACCESS = '/home/pakar/igor/remlab/.memory_bank/_secrets/ACCESS.md'
PORT = 8000
RELAY_PORT = 18191
# порядок попыток: нужна 24+ ГБ и хост с CUDA ≥ 12.8 (torch cu128 в образе); 3090/A5000 (CUDA 12.4) не годятся
CANDIDATES = [('NVIDIA GeForce RTX 4090', 'COMMUNITY'), ('NVIDIA GeForce RTX 4090', 'SECURE'), ('NVIDIA RTX A6000', 'COMMUNITY'), ('NVIDIA RTX PRO 4000 Blackwell', 'COMMUNITY')]
SG_HOME = S.SG_HOME


def say(*a) -> None:
    print(time.strftime('%H:%M:%S', time.gmtime()), *a, flush=True)


def load_key() -> str:
    m = re.search(r'^RUNPOD_API_KEY=(\S+)', open(ACCESS, encoding='utf-8').read(), re.M)
    if not m:
        raise RuntimeError('в _secrets/ACCESS.md нет RUNPOD_API_KEY')
    return m.group(1)


class Api:
    def __init__(self, key: str):
        self._key = key

    def call(self, method: str, path: str, body: dict | None = None, timeout: int = 60):
        req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={'Authorization': 'Bearer ' + self._key, 'Content-Type': 'application/json', 'User-Agent': 'remlab-mesh/1.0'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
                return r.status, (json.loads(b) if b else {})
        except urllib.error.HTTPError as e:
            raw = e.read()[:400].decode('utf-8', 'replace')
            return e.code, {'error': raw.replace(self._key, '<ключ>')}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            return -1, {'error': str(e).replace(self._key, '<ключ>')}


def public_get(url: str, timeout: int = 20):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'remlab-mesh/1.0'}), timeout=timeout) as r:
            b = r.read()
            return r.status, (json.loads(b) if b else {})
    except urllib.error.HTTPError as e:
        return e.code, {}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return -1, {}


def pod_body(name: str, image: str, gpu: str, cloud: str, weights: str, disk_gb: int, min_ram: int) -> dict:
    sb = S.build_body(name, image, 'high', weights, 8, 32768, {})
    env = dict(sb['container']['environment_variables'])
    env.update({'PYTHONUNBUFFERED': '1'})
    return {'name': name, 'cloud': cloud, 'gpu': {'id': gpu, 'count': 1, 'minRamPerGpu': min_ram}, 'image': image, 'ports': [f'{PORT}/http'], 'disk': disk_gb,
            'env': env, 'entrypoint': sb['container']['command']}


def safe_print(body: dict) -> None:
    b = json.loads(json.dumps(body))
    for k in list(b['env']):
        if any(s in k for s in ('TOKEN', 'KEY', 'SECRET', 'PASS')):
            b['env'][k] = '<скрыто>'
        elif k == 'TRIAL_WORKER_Z':
            b['env'][k] = f'<код воркера, {len(b["env"][k])} знаков>'
    b['entrypoint'] = [x if len(x) < 120 else x[:60] + '…' for x in b['entrypoint']]
    print(json.dumps(b, ensure_ascii=False, indent=1))


def terminate(api: Api, pod_id: str) -> bool:
    """Удалить под и убедиться, что он ушёл (TERMINATED/404/нет в списке). До 12 попыток."""
    for i in range(12):
        c, d = api.call('POST', f'/v2/pods/{pod_id}/action', {'action': 'terminate'})
        c2, d2 = api.call('GET', f'/v2/pods/{pod_id}')
        st = d2.get('status') if c2 == 200 else None
        say(f'удаление пода {pod_id}: action HTTP {c}, статус после: {st or c2}')
        if c2 == 404 or st == 'TERMINATED':
            say(f'УДАЛЕНИЕ ПОДТВЕРЖДЕНО: {pod_id}')
            return True
        time.sleep(5)
    c, d = api.call('DELETE', f'/v2/pods/{pod_id}')
    c2, d2 = api.call('GET', f'/v2/pods/{pod_id}')
    ok = c2 == 404 or d2.get('status') == 'TERMINATED'
    say(('УДАЛЕНИЕ ПОДТВЕРЖДЕНО (DELETE): ' if ok else '!! ПОД НЕ УДАЛЁН, ПРОВЕРЬ ВРУЧНУЮ: ') + pod_id)
    return ok


def run(a, api: Api, sleep=time.sleep, clock=time.time, popen=subprocess.Popen) -> int:
    runs = S.parse_runs(a.runs)
    spec = S.weights_for(runs)
    urls = S.weight_urls(spec, S.load_weights_catalog())
    name = f'trial-sg-rp-{a.suffix}'
    cand = [(a.gpu, a.cloud)] if a.gpu else CANDIDATES
    say('под', name, 'кандидаты', cand, 'прогонов', len(runs), 'потолок $', a.cap, 'веса:', spec)
    if not a.apply:
        safe_print(pod_body(name, a.image, cand[0][0], cand[0][1], spec, a.disk, a.min_ram))
        return 0
    bad = [(u.split('/resolve')[0].split('huggingface.co/')[1], c) for u in urls for c in [S.hf_head(u)] if c not in (200, 302)]
    say('проверка весов на Hugging Face (бесплатно):', 'все доступны' if not bad else f'НЕДОСТУПНЫ {bad}')
    if bad:
        return 3
    pod, price, t_create = None, None, None
    for gpu, cloud in cand:
        c, d = api.call('POST', '/v2/pods', pod_body(name, a.image, gpu, cloud, spec, a.disk, a.min_ram))
        say(f'создание пода {gpu} {cloud}: HTTP {c}', '' if c < 300 else str(d)[:260])
        if c < 300 and d.get('id'):
            pod, price, t_create = d['id'], float(d.get('cost') or 0), clock()
            say(f'под создан: {pod} · {gpu} {cloud} · ${price}/ч · статус {d.get("status")}')
            break
    if not pod:
        say('ни один вариант машины не выдан — стоп, денег не потрачено')
        return 2
    if not price or price > a.max_price:
        say(f'!! цена ${price}/ч выше допустимых ${a.max_price}/ч — удаляю')
        terminate(api, pod)
        return 2
    summary = {'pod': pod, 'image': a.image, 'price_usd_h': price, 'cap_usd': a.cap, 'weights': spec, 'runs': [], 'failed': 0, 'stopped_by': None, 'terminated': False}
    os.makedirs(a.out, exist_ok=True)
    base = f'https://{pod}-{PORT}.proxy.runpod.net'
    relay, cur, running_at, ready_at, last_minute, last_say, fail_streak = None, None, None, None, 0.0, 0.0, 0
    pending = list(runs)
    try:
        while True:
            t = clock()
            cost = S.cost_usd(t - t_create, price)
            summary['cost_usd_est'] = round(cost, 3)
            why = 'money' if cost >= a.cap else 'time' if t - t_create > a.max_min * 60 else None
            c, d = api.call('GET', f'/v2/pods/{pod}')
            st = d.get('status') if c == 200 else f'HTTP{c}'
            if st == 'RUNNING' and running_at is None:
                running_at = t
                summary['to_running_s'] = round(t - t_create, 1)
                say(f'RUNNING: t+{t - t_create:.0f} с от создания')
            if st in ('ERROR', 'TERMINATED', 'EXITED') and ready_at is None:
                say(f'!! под в состоянии {st} до готовности')
                summary['stopped_by'] = f'pod_{st}'
                break
            if not why and running_at is None and t - t_create > a.no_machine_min * 60:
                why = 'no_running'
            if not why and running_at is not None and ready_at is None and t - running_at > a.health_min * 60:
                why = 'no_health'
            if why:
                say(f'!! стоп по причине «{why}» (≈${cost:.2f}, потолок ${a.cap}) — удаляю')
                summary['stopped_by'] = why
                break
            hc, h = (public_get(base + '/health') if st == 'RUNNING' else (-1, {}))
            if t - last_minute >= 60:
                last_minute = t
                p = (h.get('progress') or {}) if hc == 200 else {}
                say(f'мин: под {st} · /health {hc} {h.get("phase") if hc == 200 else ""} hf_gb={p.get("hf_gb")} · ≈${cost:.2f}')
            if hc == 200 and ready_at is None:
                if h.get('error') or h.get('phase') in ('failed', 'child_dead'):
                    say('!! прогрев упал:', h.get('error'), (h.get('comfy_log_tail') or [])[-5:])
                    summary['stopped_by'] = 'warm_failed'
                    break
                if h.get('warm'):
                    ready_at = t
                    summary['to_ready_s'] = round(t - t_create, 1)
                    summary['timings'] = h.get('timings')
                    say(f'НОДА RUNPOD ГОТОВА: t+{t - t_create:.0f} с, веса {h.get("weights_gb")} ГБ')
                    salad_ready = any('нода готова' in ln for f in a.salad_logs for ln in (open(f, encoding='utf-8', errors='replace') if os.path.exists(f) else []))
                    if salad_ready:
                        say('Salad УЖЕ была готова раньше — RunPod гашу (правило директора: первый готовый работает)')
                        summary['stopped_by'] = 'salad_first'
                        break
                    say('RUNPOD ПЕРВЫЙ — Salad-группу надо погасить вручную (sg_salad.py --stop-only)')
                    relay = popen([a.relay_python, os.path.join(HERE, 'sg_relay.py'), '--listen', str(RELAY_PORT), '--target', base],
                                  env={**os.environ, 'PYTHONPATH': a.relay_deps}, stdout=open(os.path.join(a.out, f'relay-rp-{a.suffix}.log'), 'ab'), stderr=subprocess.STDOUT)
                    sleep(3)
            if ready_at is not None:
                if cur is None and pending:
                    key, var = pending.pop(0)
                    odir = os.path.join(a.out, f'{key}-{var}-rp-{time.strftime("%H%M%S", time.gmtime())}')
                    os.makedirs(odir, exist_ok=True)
                    cfg = S.build_cfg(key, var, os.path.join(odir, 'blender'), f'127.0.0.1:{RELAY_PORT}', a.cameras, a.texture, a.seed, a.job_timeout * 60)
                    cfg_path = os.path.join(odir, 'cfg.json')
                    json.dump(cfg, open(cfg_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                    cmd = [os.path.join(SCOUT, '..', 'ops', 'heavy-slot.sh'), f't90-sg-{var}', '--prio', '1', '--cores', '3', '--min-gb', '6', '--timeout', str(a.job_timeout * 60), '--', os.path.join(HERE, 'sg_run.sh'), cfg_path]
                    proc = popen(cmd, env={**os.environ, 'SG_HOME': SG_HOME}, stdout=open(os.path.join(odir, 'run.log'), 'ab'), stderr=subprocess.STDOUT)
                    cur = {'key': key, 'variant': var, 'label': S.VARIANTS[var]['label'], 'dir': odir, 'proc': proc, 'started': t, 'last_say': t}
                    say('прогон', key, var, '→', odir)
                elif cur is not None:
                    rc = cur['proc'].poll()
                    if rc is None and t - cur['last_say'] >= 600:
                        cur['last_say'] = t
                        stp = os.path.join(cur['dir'], 'blender', 'status.json')
                        stage = json.load(open(stp, encoding='utf-8')).get('stage') if os.path.exists(stp) else 'старт Blender'
                        say(S.progress_line(f'{cur["key"]} {cur["variant"]}: {stage}', cost, a.cap))
                    if rc is None and t - cur['started'] > a.job_timeout * 60:
                        cur['proc'].terminate()
                        say(f'!! прогон не закончился за {a.job_timeout} мин — прерываю')
                        rc = -1
                    if rc is not None:
                        glb = os.path.join(cur['dir'], 'blender', 'painted.glb')
                        ok = rc == 0 and os.path.exists(glb)
                        summary['runs'].append({'key': cur['key'], 'variant': cur['variant'], 'label': cur['label'], 'dir': cur['dir'], 'rc': rc, 'ok': ok, 'seconds': round(t - cur['started'], 1), 'glb': glb if ok else None})
                        fail_streak = 0 if ok else fail_streak + 1
                        summary['failed'] += not ok
                        say('прогон', cur['key'], cur['variant'], 'ГОТОВО' if ok else f'УПАЛ (rc={rc}, {cur["dir"]}/run.log)', f'{summary["runs"][-1]["seconds"]} с')
                        cur = None
                        if fail_streak >= S.FAIL_STREAK:
                            say(f'!! {S.FAIL_STREAK} прогона подряд упали — удаляю под')
                            summary['stopped_by'] = 'failures'
                            break
                if cur is None and not pending:
                    summary['stopped_by'] = 'done'
                    break
            sleep(10)
    finally:
        for p in ([relay] if relay else []) + ([cur['proc']] if cur else []):
            try:
                p.terminate()
            except Exception:  # noqa: BLE001
                pass
        summary['terminated'] = terminate(api, pod)
        summary['alive_s'] = round(clock() - t_create, 1)
        summary['cost_usd_est'] = round(S.cost_usd(summary['alive_s'], price), 3)
        json.dump(summary, open(os.path.join(a.out, f'summary-{name}.json'), 'w'), ensure_ascii=False, indent=1)
        say('ИТОГ', json.dumps({k: summary.get(k) for k in ('pod', 'stopped_by', 'terminated', 'failed', 'alive_s', 'cost_usd_est')}, ensure_ascii=False))
    return 0 if summary['terminated'] and summary['stopped_by'] == 'done' else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--image', help='образ пода: digest или тег с именем репозитория')
    ap.add_argument('--runs', default='112923_13224664101879413845:q2509q5')
    ap.add_argument('--gpu', default=None, help='один тип карты вместо списка кандидатов')
    ap.add_argument('--cloud', default='COMMUNITY', choices=['COMMUNITY', 'SECURE'])
    ap.add_argument('--disk', type=int, default=80, help='диск контейнера, ГБ (веса ≈ 25–45)')
    ap.add_argument('--min-ram', type=int, default=32, help='минимум ОЗУ хоста на карту, ГБ')
    ap.add_argument('--cameras', type=int, default=8)
    ap.add_argument('--texture', type=int, default=2048)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--cap', type=float, default=3.0, help='потолок денег на ВЕСЬ замер, $ (директор, T-90/6: $3)')
    ap.add_argument('--max-price', type=float, default=1.0, help='выше этой цены за час под не берём')
    ap.add_argument('--max-min', type=int, default=150)
    ap.add_argument('--no-machine-min', type=int, default=20)
    ap.add_argument('--health-min', type=int, default=12)
    ap.add_argument('--job-timeout', type=int, default=40)
    ap.add_argument('--suffix', default=time.strftime('%m%d%H%M', time.gmtime()))
    ap.add_argument('--out', default=os.path.expanduser('~/remlab-logs/t90-1119/sg/runpod'))
    ap.add_argument('--relay-python', default='/usr/bin/python3')
    ap.add_argument('--relay-deps', default=os.path.join(SG_HOME, 'fake-deps'))
    ap.add_argument('--salad-logs', nargs='*', default=[], help='журналы Salad-запуска: если в них уже «нода готова» — RunPod гасим')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--stop-only', action='store_true')
    ap.add_argument('--pod')
    a = ap.parse_args()
    api = Api(load_key())
    if a.stop_only:
        return 0 if a.pod and terminate(api, a.pod) else 1
    if not a.image or ('@' not in a.image and ':' not in a.image):
        sys.exit('нужен --image: digest или тег с именем репозитория')
    return run(a, api)


if __name__ == '__main__':
    sys.exit(main())
