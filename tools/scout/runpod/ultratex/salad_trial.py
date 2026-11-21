#!/usr/bin/env python3
"""ДРАЙВЕР ПРОБЫ UltraTex НА SALAD, карта RTX 5090 (32 ГБ) — T-20261121-178/1 (владелец TG 841: «запускают и на 16 ГБ»; директор: Salad 5090, потолок $1 на пробу, $4 всего, prio 2).
Одна ВРЕМЕННАЯ группа `trial-ultratex-<метка>` (1 нода, образ `…/mesh-ultratex-trial:ultratex-bw`, воркер с `ULTRATEX_OFFLOAD=swap`): форма + фото → GLB с текстурой UltraTex.

    salad_trial.py --image <тег|digest> --jobs <ключ>[,<ключ>…] --shape-dir … --inputs … --out …                 # разбор: тело группы без секретов, группа НЕ создаётся
    salad_trial.py … --apply                                                                                    # создать, прогнать по очереди, ПОГАСИТЬ и проверить 0 нод
    salad_trial.py --stop-only --suffix <метка>

ПРЕДОХРАНИТЕЛИ (в коде): потолок `--probe-cap` ($1) действует, пока первое задание не готово; после первого успеха — общий `--cap` ($4). Деньги — по времени `running` × ЖИВАЯ цена класса карты (+60 с запаса);
`--running-min` на выдачу ноды, `--health-min` без /health, `--ready-min` на прогрев (докачка ≈36 ГБ + загрузка в обычную память), `--job-min` на задание, 2 неудачи подряд — стоп; ИТОГ и «стоп с проверкой stopped» — всегда (finally).
Бесплатная проверка допуска к закрытым весам FLUX.2 (HEAD с токеном) — ДО создания группы. Ключи Salad и HF — из `~/scout-scenes/salad.env` (в печать и журнал не попадают). Боевые `mesh-`/`render-` группы не трогаем.
В метриках задания (из воркера): `vram_peak_gb`, `vram_phases_gb` (пик по фазам: VAE / энкодер / DiT / декод), `sample_s`, `offload_moves_s`, `sparse` (включено ли разреженное внимание), `total_s`.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.abspath(os.path.join(HERE, '..', '..', 'salad'))
sys.path.insert(0, SALAD)

CARD_NAME = 'RTX 5090 (32 GB)'
PORT = 8000
MODEL_HEADS = (
    'https://huggingface.co/black-forest-labs/FLUX.2-klein-base-9B/resolve/main/flux-2-klein-base-9b.safetensors',
    'https://huggingface.co/black-forest-labs/FLUX.2-dev/resolve/main/ae.safetensors',
)
SEC_KEYS = ('SALAD_API_KEY', 'HF_TOKEN')
READINESS = {'http': {'path': '/health', 'port': PORT, 'scheme': 'http', 'headers': []}, 'initial_delay_seconds': 30, 'period_seconds': 10, 'timeout_seconds': 5,
             'success_threshold': 1, 'failure_threshold': 3}
STARTUP = {'http': {'path': '/health', 'port': PORT, 'scheme': 'http', 'headers': []}, 'initial_delay_seconds': 10, 'period_seconds': 60, 'timeout_seconds': 5,
           'success_threshold': 1, 'failure_threshold': 20}                                 # API Salad: failure_threshold ≤ 20


def say(*a) -> None:
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def cost_usd(running_s: float, price: float, reserve_s: float = 60.0) -> float:
    """Начисления по времени `running` + запас на отставание счёта (платим с момента running)."""
    return max(0.0, running_s + (reserve_s if running_s > 0 else 0.0)) / 3600.0 * price


def effective_cap(first_done: bool, probe_cap: float, cap: float) -> float:
    """До первого готового задания потолок пробы, после — общий."""
    return cap if first_done else min(probe_cap, cap)


def build_body(name: str, image: str, tier: str, class_id: str, cpu: int, mem_mb: int, auth: dict, hf_token: str, life_s: int, idle_s: int) -> dict:
    env = {'ULTRATEX_OFFLOAD': 'swap', 'ULTRATEX_SPARSE': 'auto', 'ULTRATEX_ROOT': '/workspace/ultratex', 'PORT': str(PORT), 'HF_TOKEN': hf_token,
           'MAX_LIFETIME_S': str(life_s), 'IDLE_S': str(idle_s), 'NVIDIA_DRIVER_CAPABILITIES': 'all', 'DEPLOYMENT_EPOCH': f'20261121-{name}'}
    return {
        'name': name, 'display_name': name,
        'container': {'image': image,
                      'resources': {'cpu': cpu, 'memory': mem_mb, 'gpu_classes': [class_id], 'storage_amount': 80 * 2 ** 30, 'shm_size': 2048},     # 80 ГиБ: веса ≈36 + запас
                      'priority': tier, 'environment_variables': env, 'image_caching': True, 'registry_authentication': auth},
        'autostart_policy': False, 'restart_policy': 'never', 'replicas': 1, 'priority': tier, 'country_codes': [],
        'networking': {'protocol': 'http', 'port': PORT, 'auth': True, 'load_balancer': 'round_robin', 'single_connection_limit': False,
                       'client_request_timeout': 100000, 'server_response_timeout': 100000},
        'readiness_probe': READINESS, 'startup_probe': STARTUP,
    }


def safe_print(body: dict) -> None:
    b = json.loads(json.dumps(body))
    b['container'].pop('registry_authentication', None)
    for k in list(b['container']['environment_variables']):
        if any(s in k for s in ('TOKEN', 'KEY', 'SECRET', 'PASS')):
            b['container']['environment_variables'][k] = '<скрыто>'
    print(json.dumps(b, ensure_ascii=False, indent=1))


def lookup_class(MG, name: str, tier: str) -> tuple[str | None, float | None]:
    try:
        url = MG.API.split('/projects/')[0] + '/gpu-classes'
        req = urllib.request.Request(url, headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'], 'User-Agent': 'remlab-mesh/1.0'})
        with urllib.request.urlopen(req, timeout=60) as r:
            for c in json.loads(r.read()).get('items') or []:
                if c.get('name') == name and c.get('id'):
                    price = None
                    for x in c.get('prices') or []:
                        if str(x.get('priority')).lower() == tier:
                            price = float(x['price'])
                    return c['id'], price
    except Exception:  # noqa: BLE001 — нет сети/ключа/формата: класс не найден, группу не создаём
        pass
    return None, None


def head(url: str, token: str = '') -> int:
    h = {'User-Agent': 'remlab-mesh/1.0'}
    if token:
        h['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(url, method='HEAD', headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return -1


class Gateway:
    """HTTP к ноде через шлюз группы (`https://<dns>`) с ключом Salad; без падения на сетевых сбоях (код -1)."""

    def __init__(self, base: str, key: str):
        self.base, self.key = base.rstrip('/'), key

    def call(self, method: str, path: str, body: dict | None = None, timeout: int = 60, raw: bool = False):
        data = json.dumps(body).encode() if body is not None else None
        h = {'Salad-Api-Key': self.key, 'User-Agent': 'remlab-mesh/1.0'}
        if data is not None:
            h['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
                return r.status, (b if raw else (json.loads(b) if b else {}))
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b'{}')
            except ValueError:
                return e.code, {}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return -1, {}


def parse_jobs(spec: str) -> list[str]:
    return [x.strip() for x in spec.split(',') if x.strip()]


def run(a, MG, BR, gw_factory=Gateway, sleep=time.sleep, clock=time.time, head_fn=head) -> int:
    jobs = parse_jobs(a.jobs)
    name = f'trial-ultratex-{a.suffix}'
    MG.env_from_file()
    tier = a.tier
    class_id, price = lookup_class(MG, CARD_NAME, tier)
    if class_id is None:
        say(f'класс карты «{CARD_NAME}» не найден у Salad — стоп, денег не потрачено')
        return 3
    hf = os.environ.get('HF_TOKEN', '')
    life_s = min(a.max_min * 60 + 600, 3 * 3600)
    body = build_body(name, a.image, tier, class_id, a.cpu, a.mem_mb, MG.ghcr_auth(), hf, life_s, a.idle_s)
    say('группа', name, CARD_NAME, 'тариф', tier, 'цена $/ч', price, 'задания', jobs, f'потолок пробы ${a.probe_cap}, общий ${a.cap}')
    if not a.apply:
        safe_print(body)
        return 0
    if price is None:
        say('цены класса нет — стоп (деньги без цены не считаем)')
        return 2
    missing = [k for k in jobs for p in (os.path.join(a.shape_dir, a.shape_name.format(key=k)), os.path.join(a.inputs, f'{k}.rgba.png')) if not os.path.exists(p)]
    if missing:
        say('нет входных файлов:', missing[:4], '— стоп')
        return 3
    bad = [(u.split('/resolve')[0].split('huggingface.co/')[1], c) for u in MODEL_HEADS for c in [head_fn(u, hf)] if c not in (200, 302)]
    say('допуск к закрытым весам FLUX.2 (бесплатно):', 'есть' if not bad else f'НЕТ {bad}')
    if bad:
        say('группу НЕ создаю, денег не потрачено')
        return 3
    code, d = MG.api('')
    live = [g['name'] for g in d.get('items', []) if (g.get('current_state') or {}).get('status') not in ('stopped', 'failed', None) and not g['name'].startswith(('mesh-', 'render-', 'trial-'))]
    if live:
        say(f'живые чужие группы {live} — стоп')
        return 2
    code, g = MG.api(f'/{name}')
    if code == 200:
        say(f'группа {name} уже есть — не пересоздаю молча (другая --suffix)')
        return 2
    code, resp = MG.api('', 'POST', body)
    say('POST создание', code, str(resp)[:200] if code >= 300 else 'ok')
    if code >= 300:
        return 1
    os.makedirs(a.out, exist_ok=True)
    summary = {'group': name, 'image': a.image, 'tier': tier, 'price_usd_h': price, 'cap_usd': a.cap, 'probe_cap_usd': a.probe_cap, 'jobs': {}, 'failed': 0,
               'stop_verified': False, 'stopped_by': None}
    run_since = None
    gw = None
    ready_at = None
    ever_ok = False
    first_done = False
    streak = 0
    pending = list(jobs)
    cur = None                                                     # {'key','id','t0'}
    last_say = 0.0
    try:
        for _ in range(120):
            _, st, _c = BR.group_state(name)
            if st == 'stopped':
                break
            sleep(5)
        t_start = clock()
        code, _ = MG.api(f'/{name}/start', 'POST')
        say('start HTTP', code)
        while True:
            t = clock()
            _, st, _cnt = BR.group_state(name)
            _, ins = BR.instances(name)
            if any(i.get('state') == 'running' for i in ins) and run_since is None:
                run_since = t
                summary['to_first_running_s'] = round(t - t_start, 1)
                say(f'первый running: t+{t - t_start:.0f} с от /start')
            running_s = (t - run_since) if run_since is not None else 0.0
            cost = cost_usd(running_s, price)
            summary['cost_usd_est'] = round(cost, 3)
            cap_now = effective_cap(first_done, a.probe_cap, a.cap)
            why = None
            if cost >= cap_now:
                why = 'money' if first_done else 'probe_cap'
            elif run_since is not None and running_s > a.max_min * 60:
                why = 'time'
            elif run_since is None and (t - t_start) > a.running_min * 60:
                why = 'no_machine'
            if why:
                say(f'!! стоп по причине «{why}» (≈${summary["cost_usd_est"]}, потолок ${cap_now}) — гашу')
                summary['stopped_by'] = why
                break
            if t - last_say >= 60:
                last_say = t
                i0 = ins[0] if ins else {}
                say(f'мин: группа {st} · экземпляр {i0.get("state")} · ≈${summary["cost_usd_est"]:.2f} из ${cap_now}')
            if run_since is not None and gw is None:
                dns = ((MG.api(f'/{name}')[1].get('networking') or {}).get('dns') or '')
                if dns:
                    gw = gw_factory(f'https://{dns}', os.environ['SALAD_API_KEY'])
                    summary['gateway'] = dns
                    say('шлюз группы получен')
            if gw is not None and ready_at is None:
                c, h = gw.call('GET', '/health', timeout=20)
                if c == 200:
                    ever_ok = True
                    if h.get('phase') == 'broken' or h.get('error'):
                        say('!! воркер сломан:', h.get('error'), f'(фаза {h.get("phase")})')
                        summary['stopped_by'] = 'warm_failed'
                        summary['warm_error'] = h.get('error')
                        break
                    if h.get('phase') == 'ready':
                        ready_at = t
                        summary['to_ready_s'] = round(t - t_start, 1)
                        summary['health'] = {k: h.get(k) for k in ('version', 'offload', 'sparse')}
                        say(f'нода готова: t+{t - t_start:.0f} с от /start', summary['health'])
                if run_since is not None and not ever_ok and running_s > a.health_min * 60:
                    say(f'!! {a.health_min} мин после running воркер не отвечает — гашу')
                    summary['stopped_by'] = 'no_health'
                    break
                if run_since is not None and ready_at is None and running_s > a.ready_min * 60:
                    say(f'!! {a.ready_min} мин после running модель не прогрелась — гашу')
                    summary['stopped_by'] = 'not_ready'
                    break
            if ready_at is not None:
                if cur is None and pending:
                    k = pending.pop(0)
                    glb = open(os.path.join(a.shape_dir, a.shape_name.format(key=k)), 'rb').read()
                    png = open(os.path.join(a.inputs, f'{k}.rgba.png'), 'rb').read()
                    jid = f'{k}-{int(t)}'.replace('_', '-')[:150]
                    c, r = gw.call('POST', '/generate', {'job_id': jid, 'image_b64': base64.b64encode(png).decode(), 'glb_b64': base64.b64encode(glb).decode(),
                                                          'resolution': a.resolution, 'steps': a.steps, 'seed': a.seed, 'texture_size': a.texture}, timeout=120)
                    say(f'задание {k}: POST /generate → {c}', str(r)[:120] if c != 202 else '')
                    if c == 202:
                        cur = {'key': k, 'id': jid, 't0': t}
                    else:
                        streak += 1
                        summary['jobs'][k] = {'status': 'not_accepted', 'http': c, 'detail': r}
                elif cur is not None:
                    c, r = gw.call('GET', f'/result/{cur["id"]}', timeout=30)
                    if c == 200 and r.get('status') == 'done':
                        c2, data = gw.call('GET', f'/result/{cur["id"]}/glb', timeout=300, raw=True)
                        if c2 == 200 and data:
                            path = os.path.join(a.out, f'{cur["key"]}.ultratex.glb')
                            open(path, 'wb').write(data)
                            summary['jobs'][cur['key']] = {'status': 'done', 'wall_s': round(t - cur['t0'], 1), 'glb': path, 'bytes': len(data), 'metrics': r.get('metrics')}
                            json.dump(r.get('metrics'), open(os.path.join(a.out, f'{cur["key"]}.metrics.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                            say(f'задание {cur["key"]}: ГОТОВО за {t - cur["t0"]:.0f} с', json.dumps(r.get('metrics') or {}, ensure_ascii=False)[:400])
                            first_done = True
                            streak = 0
                        else:
                            streak += 1
                            summary['jobs'][cur['key']] = {'status': 'glb_not_received', 'http': c2}
                        cur = None
                    elif c == 200 and r.get('status') == 'failed':
                        streak += 1
                        summary['jobs'][cur['key']] = {'status': 'failed', 'error': r.get('error'), 'trace': r.get('trace')}
                        say(f'задание {cur["key"]}: ОШИБКА', r.get('error'))
                        cur = None
                    elif t - cur['t0'] > a.job_min * 60:
                        streak += 1
                        summary['jobs'][cur['key']] = {'status': 'timeout'}
                        say(f'задание {cur["key"]}: дольше {a.job_min} мин — снимаю')
                        cur = None
                summary['failed'] = sum(1 for v in summary['jobs'].values() if v.get('status') != 'done')
                if streak >= 2:
                    summary['stopped_by'] = 'fail_streak'
                    say('!! 2 задания подряд не удались — гашу (чинить в коде)')
                    break
                if cur is None and not pending:
                    summary['stopped_by'] = 'done' if first_done and summary['failed'] == 0 else ('first_failed' if not first_done else 'done_with_failures')
                    break
            sleep(10)
    finally:
        ok_stop = BR.stop_and_verify(name)
        summary['stop_verified'] = ok_stop
        summary['running_s'] = round((clock() - run_since), 1) if run_since is not None else 0.0
        summary['cost_usd_est'] = round(cost_usd(summary['running_s'], price), 3)
        json.dump(summary, open(os.path.join(a.out, f'summary-{name}.json'), 'w'), ensure_ascii=False, indent=1, default=str)
        say('ИТОГ', json.dumps({k: summary.get(k) for k in ('group', 'stopped_by', 'stop_verified', 'failed', 'running_s', 'cost_usd_est')}, ensure_ascii=False))
    return 0 if summary['stop_verified'] and summary['stopped_by'] == 'done' else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--image', help='образ группы: тег или digest с именем репозитория')
    ap.add_argument('--jobs', default='', help='ключи товаров через запятую (форма: <shape-dir>/<shape-name>; фото: <inputs>/<ключ>.rgba.png)')
    ap.add_argument('--shape-dir', default='')
    ap.add_argument('--shape-name', default='{key}.prep.glb')
    ap.add_argument('--inputs', default='')
    ap.add_argument('--out', default=os.path.expanduser('~/remlab-logs/t178-1121/salad-out'))
    ap.add_argument('--tier', default='high', choices=['batch', 'low', 'medium', 'high'])
    ap.add_argument('--cpu', type=int, default=8)
    ap.add_argument('--mem-mb', type=int, default=49152)
    ap.add_argument('--resolution', type=int, default=2048)
    ap.add_argument('--steps', type=int, default=25)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--texture', type=int, default=4096)
    ap.add_argument('--probe-cap', type=float, default=1.0, help='потолок денег, пока не готово первое задание, $')
    ap.add_argument('--cap', type=float, default=4.0, help='общий потолок после первого успеха, $')
    ap.add_argument('--max-min', type=int, default=120)
    ap.add_argument('--running-min', type=int, default=30, help='минут от /start до running (нода выдана)')
    ap.add_argument('--health-min', type=int, default=8)
    ap.add_argument('--ready-min', type=int, default=75, help='минут от running до «готов» (докачка весов + загрузка в обычную память)')
    ap.add_argument('--job-min', type=int, default=30)
    ap.add_argument('--idle-s', type=int, default=900)
    ap.add_argument('--suffix', default=time.strftime('%m%d%H%M', time.gmtime()))
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--stop-only', action='store_true')
    a = ap.parse_args()
    import bench_run as BR
    import migrate_groups as MG
    if a.stop_only:
        MG.env_from_file()
        return 0 if BR.stop_and_verify(f'trial-ultratex-{a.suffix}') else 1
    if not a.jobs or not a.image or not a.shape_dir or not a.inputs:
        sys.exit('нужны --image, --jobs, --shape-dir, --inputs')
    return run(a, MG, BR)


if __name__ == '__main__':
    sys.exit(main())
