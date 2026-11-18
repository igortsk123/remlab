#!/usr/bin/env python3
"""ЗАМЕР ГЕНЕРАТОРА МЕШЕЙ НА SALAD (T-20261118-91, план `mesh-models-trial-01`): своя ВРЕМЕННАЯ группа `trial-<модель>-<метка>` (4090, 1 нода), без очереди
и БЕЗ приёмника на проде — результат забирается по HTTP через шлюз группы. Боевые группы и очередь мешей не трогает.

    ~/venvs/scout/bin/python trellis_trial.py --model trellis2 --image <digest|тег> --inputs <папка inputs/> \\
        --skus 112923:13224664101879413845 [...] --plan 1024:1,1536:1            # разбор: печатает тело группы без секретов, ничего не создаёт
    ... --apply                                                                    # создать, запустить, прогнать план, забрать GLB, ПОГАСИТЬ
    ... --stop-only --suffix <метка>                                               # просто /stop и проверка stopped

ПРЕДОХРАНИТЕЛИ (все — в этом файле, а не «по памяти»):
  • деньги: потолок `--cap` $ (по умолчанию 3,0 на ВЕСЬ замер, холодные старты включены), цена — по классу карты и тарифу из `rules/salad-groups.json`; начисления
    считаем по времени `running` инстанса (платим за running) + запас на отставание счёта; при потолке — стоп;
  • время: `--max-min` (по умолчанию 90) на жизнь ноды; за час без `running` — стоп (платили 0); без «готов» за `--ready-min` после running — стоп;
  • отказы: счётчик заданий упавших/не дождавшихся; 2 подряд упавших — стоп (чинить в коде, не жечь деньги);
  • СТОП С ПРОВЕРКОЙ `stopped` — всегда (finally), в том числе при исключении и Ctrl-C;
  • бесплатная проверка закрытых весов ПЕРЕД созданием группы: HEAD к `facebook/dinov3-…/config.json` с токеном — не 200 → не запускаем (решение директора 18.11);
  • токен Hugging Face и ключ Salad — из `~/scout-scenes/salad.env` через готовые функции, в журнал/печать не попадают (`safe_print` скрывает);
  • только RTX 4090 (приказ директора 18.11); боевые `mesh-`/`render-` группы и чужие живые группы не трогаем (чужая живая — отказ).
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
SCOUT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(SCOUT, 'salad'))
sys.path.insert(0, os.path.join(SCOUT, 'render_gpu'))
sys.path.insert(0, HERE)

CARD = {'class_name': 'RTX 4090 (24 GB)', 'class_id': 'ed563892-aacd-40f5-80b7-90c9be6c759b'}
HF_GATED = {'trellis2': 'facebook/dinov3-vitl16-pretrain-lvd1689m/resolve/main/config.json'}      # закрытые веса, без которых модель не поднимется
PORT = 8000
READINESS = {'http': {'path': '/ready', 'port': PORT, 'scheme': 'http', 'headers': []},
             'initial_delay_seconds': 30, 'period_seconds': 10, 'timeout_seconds': 5, 'success_threshold': 1, 'failure_threshold': 3}
STARTUP = {'http': {'path': '/health', 'port': PORT, 'scheme': 'http', 'headers': []},
           'initial_delay_seconds': 10, 'period_seconds': 10, 'timeout_seconds': 5, 'success_threshold': 1, 'failure_threshold': 180}   # 30 мин на докачку весов
NO_FAIL_STREAK = 2


def say(*a) -> None:
    print(time.strftime('%H:%M:%S', time.gmtime()), *a, flush=True)


def parse_plan(plan: str) -> list[dict]:
    """`1024:1,1536:1` → [{'res': 1024, 'n': 1}, …]; допустимо 512 / 1024 / 1536 (pipeline_type цепочки TRELLIS.2: 512, 1024_cascade, 1536_cascade)."""
    out = []
    for part in [p for p in plan.split(',') if p.strip()]:
        res, _, n = part.partition(':')
        if int(res) not in (512, 1024, 1536):
            raise ValueError(f'разрешение {res}: допустимы 512, 1024, 1536')
        out.append({'res': int(res), 'n': int(n or 1)})
    return out


def pipeline_type(res: int) -> str:
    return {512: '512', 1024: '1024_cascade', 1536: '1536_cascade'}[res]


def build_jobs(skus: list[str], plan: list[dict], inputs: dict, seed: int = 42) -> list[dict]:
    """Список заданий: для каждого товара — по плану (разрешение × повторов). `inputs` — `inputs.json` (адрес фото, sha вырезки)."""
    jobs = []
    for sku in skus:
        if sku not in inputs or 'input_png_sha256' not in inputs[sku]:
            raise ValueError(f'{sku}: нет вырезки в inputs.json — сперва make_inputs.py')
        for step in plan:
            for k in range(step['n']):
                jobs.append({'sku': sku, 'res': step['res'], 'rep': k, 'seed': seed, 'job_id': f'{sku.replace(":", "_")}-{step["res"]}-{seed}-{k}'})
    return jobs


def price_usd_h(tier: str) -> float | None:
    """Цена 4090 по тарифу из `rules/salad-groups.json` (`prices_by_class_usd_h`); нет — None (деньги без цены не считаем)."""
    try:
        d = json.load(open(os.path.join(SCOUT, 'rules', 'salad-groups.json'), encoding='utf-8'))
        return float(d['prices_by_class_usd_h'][CARD['class_name']][tier])
    except (OSError, KeyError, ValueError, TypeError):
        return None


def cost_usd(running_s: float, price: float, reserve_s: float = 60.0) -> float:
    """Начисления по времени `running` + запас на отставание счёта (платим с момента running, ADR-0135)."""
    return max(0.0, running_s + (reserve_s if running_s > 0 else 0.0)) / 3600.0 * price


def build_body(name: str, image: str, tier: str, model: str, hf_token: str, cpu: int, mem_mb: int, run_note: str, auth: dict) -> dict:
    """Тело группы Salad. `auth` — доступ к приватному реестру (`migrate_groups.ghcr_auth()`); приёмника на проде (`MESH_SINK_*`) в окружении НЕТ."""
    env = {'MODEL': model, 'IMAGE_NOTE': run_note, 'HF_TOKEN': hf_token, 'HF_HOME': '/data/hf', 'OUT_DIR': '/data/out',
           'NVIDIA_DRIVER_CAPABILITIES': 'all', 'DEPLOYMENT_EPOCH': f'20261118-{name}'}
    return {
        'name': name, 'display_name': name,
        'container': {
            'image': image,
            'resources': {'cpu': cpu, 'memory': mem_mb, 'gpu_classes': [CARD['class_id']], 'storage_amount': 60 * 2 ** 30, 'shm_size': 1024},
            'priority': tier, 'environment_variables': env, 'image_caching': True, 'registry_authentication': auth,
        },
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


class Gateway:
    """HTTP к ноде через шлюз группы (`https://<dns>`) с ключом Salad. Всё — с таймаутами и без падения на сетевых сбоях (код -1)."""

    def __init__(self, base: str, key: str):
        self.base, self.key = base.rstrip('/'), key

    def call(self, method: str, path: str, body: dict | None = None, timeout: int = 60, raw: bool = False):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            'Salad-Api-Key': self.key, 'User-Agent': 'remlab-mesh/1.0', 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
                return r.status, (b if raw else (json.loads(b) if b else {}))
        except urllib.error.HTTPError as e:
            b = e.read()
            try:
                return e.code, (b if raw else json.loads(b))
            except ValueError:
                return e.code, {'detail': b[:200].decode(errors='replace')}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return -1, {}


def run(a, MG, BR, gw_factory=Gateway, sleep=time.sleep, clock=time.time, hf_head=None) -> int:
    """Весь замер. `MG` — `migrate_groups` (API Salad), `BR` — `bench_run` (состояние группы, остановка с проверкой). Подмена обоих + `gw_factory`/`sleep`/`clock`/`hf_head` — тесты."""
    inputs = json.load(open(os.path.join(a.inputs, 'inputs.json'), encoding='utf-8'))
    jobs = build_jobs(a.skus, parse_plan(a.plan), inputs, a.seed)
    name = f'trial-{a.model}-{a.suffix}'
    price = price_usd_h(a.tier)
    MG.env_from_file()
    hf = os.environ.get('HF_TOKEN', '')
    body = build_body(name, a.image, a.tier, a.model, hf, a.cpu, a.mem_mb, a.image.split('@')[-1][:19], MG.ghcr_auth())
    say('группа', name, CARD['class_name'], 'тариф', a.tier, 'цена $/ч', price, 'заданий', len(jobs), 'потолок $', a.cap)
    if not a.apply:
        safe_print(body)
        for j in jobs:
            print('  задание', j['job_id'])
        return 0
    if price is None:
        say('цены группы нет в rules/salad-groups.json — стоп (деньги без цены не считаем)')
        return 2
    gated = HF_GATED.get(a.model)
    if gated:                                           # БЕСПЛАТНО, до создания группы
        if hf_head is None:
            import hf_access
            hf_head = hf_access.head
        code = hf_head(gated, hf) if hf else 0
        say('проверка закрытых весов', gated.split('/resolve')[0], '→ HTTP', code or 'нет HF_TOKEN')
        if code not in (200, 302):
            say('закрытые веса недоступны — группу НЕ создаю, денег не потрачено')
            return 3
    code, d = MG.api('')
    live = [g['name'] for g in d.get('items', []) if (g.get('current_state') or {}).get('status') not in ('stopped', 'failed', None)
            and not g['name'].startswith(('mesh-', 'render-', 'trial-'))]
    if live:
        say(f'живые чужие группы {live} — стоп')
        return 2
    code, g = MG.api(f'/{name}')
    if code == 200:
        say(f'группа {name} уже есть ({(g.get("current_state") or {}).get("status")}) — не пересоздаю молча (другая --suffix)')
        return 2
    code, resp = MG.api('', 'POST', body)
    say('POST создание', code, str(resp)[:200] if code >= 300 else 'ok')
    if code >= 300:
        return 1
    ok_stop = False
    summary = {'group': name, 'model': a.model, 'image': a.image, 'tier': a.tier, 'price_usd_h': price, 'cap_usd': a.cap, 'jobs': [], 'failed': 0,
               'stop_verified': False, 'stopped_by': None}
    os.makedirs(a.out, exist_ok=True)
    t_start = run_since = None
    try:
        for _ in range(120):                              # создание группы Salad иногда идёт 2–10 минут
            _, st, _c = BR.group_state(name)
            if st == 'stopped':
                break
            sleep(5)
        t_start = clock()
        code, _ = MG.api(f'/{name}/start', 'POST')
        say('start HTTP', code)
        gw, ready_at, fail_streak = None, None, 0
        pending = list(jobs)
        inflight = None
        while True:
            t = clock()
            _, st, cnt = BR.group_state(name)
            _, ins = BR.instances(name)
            if any(i.get('state') == 'running' for i in ins) and run_since is None:
                run_since = t
                summary['to_first_running_s'] = round(t - t_start, 1)
                say(f'первый running: t+{t - t_start:.0f} с от /start')
            running_s = (t - run_since) if run_since is not None else 0.0
            cost = cost_usd(running_s, price)
            summary['cost_usd_est'] = round(cost, 3)
            if cost >= a.cap:
                say(f'!! ПОТОЛОК ДЕНЕГ: ≈${cost:.2f} ≥ ${a.cap} — гашу')
                summary['stopped_by'] = 'money'
                break
            if run_since is not None and running_s > a.max_min * 60:
                say(f'!! предел времени {a.max_min} мин — гашу')
                summary['stopped_by'] = 'time'
                break
            if run_since is None and (t - t_start) > 3600:
                say('!! за час нода не вышла в running — гашу (платили 0)')
                summary['stopped_by'] = 'no_machine'
                break
            if run_since is not None and gw is None:
                g2 = MG.api(f'/{name}')[1]
                dns = ((g2.get('networking') or {}).get('dns') or '')
                if dns:
                    gw = gw_factory(f'https://{dns}', os.environ['SALAD_API_KEY'])
                    say('шлюз группы получен')
            if gw is not None and ready_at is None:
                c, h = gw.call('GET', '/health', timeout=20)
                if c == 200:
                    summary['health'] = h
                    if h.get('error') or h.get('phase') == 'failed':
                        say('!! прогрев упал:', h.get('error'), '— гашу')
                        summary['stopped_by'] = 'warm_failed'
                        break
                    if h.get('warm'):
                        ready_at = t
                        summary['to_ready_s'] = round(t - t_start, 1)
                        summary['timings'] = h.get('timings')
                        c2, info = gw.call('GET', '/info', timeout=30)
                        summary['info'] = info if c2 == 200 else None
                        say(f'нода готова: t+{t - t_start:.0f} с от /start', (summary.get('info') or {}).get('gpu'))
                if run_since is not None and ready_at is None and running_s > a.ready_min * 60:
                    say(f'!! {a.ready_min} мин после running модель не прогрелась — гашу')
                    summary['stopped_by'] = 'not_ready'
                    break
            if ready_at is not None:
                if inflight is None and pending:
                    j = pending.pop(0)
                    png = open(os.path.join(a.inputs, f'{j["sku"].replace(":", "_")}.rgba.png'), 'rb').read()
                    pl = {'job_id': j['job_id'], 'image_b64': base64.b64encode(png).decode(), 'pipeline_type': pipeline_type(j['res']), 'seed': j['seed'],
                          'decimation_target': a.decimation, 'texture_size': a.texture}
                    c, r = gw.call('POST', '/generate', pl, timeout=90)
                    inflight = {**j, 'submitted': t, 'http': c}
                    say('задание', j['job_id'], '→ HTTP', c)
                    if c not in (202, 409):
                        inflight.update(status='failed', error=f'POST {c} {str(r)[:120]}')
                elif inflight is not None:
                    if inflight.get('status') != 'failed':
                        c, r = gw.call('GET', '/job/' + inflight['job_id'], timeout=30)
                        if c == 200 and r.get('status') in ('done', 'failed'):
                            inflight.update(status=r['status'], metrics=r.get('metrics'), error=r.get('error'), trace=r.get('trace'))
                            if r['status'] == 'done':
                                cg, glb = gw.call('GET', '/glb/' + inflight['job_id'], timeout=300, raw=True)
                                if cg == 200:
                                    fp = os.path.join(a.out, inflight['job_id'] + '.glb')
                                    open(fp, 'wb').write(glb)
                                    inflight['glb_path'] = fp
                                    inflight['glb_bytes'] = len(glb)
                                else:
                                    inflight.update(status='failed', error=f'GLB не скачался: HTTP {cg}')
                        elif t - inflight['submitted'] > a.job_timeout * 60:
                            inflight.update(status='failed', error=f'задание не закончилось за {a.job_timeout} мин')
                    if inflight.get('status') in ('done', 'failed'):
                        inflight['seconds'] = round(t - inflight['submitted'], 1)
                        summary['jobs'].append(inflight)
                        fail_streak = fail_streak + 1 if inflight['status'] == 'failed' else 0
                        summary['failed'] += inflight['status'] == 'failed'
                        say('задание', inflight['job_id'], inflight['status'], inflight.get('error') or '', f'{inflight["seconds"]} с')
                        inflight = None
                        if fail_streak >= NO_FAIL_STREAK:
                            say(f'!! {NO_FAIL_STREAK} задания подряд упали — гашу (чинить в коде, не жечь деньги)')
                            summary['stopped_by'] = 'failures'
                            break
                if inflight is None and not pending:
                    summary['stopped_by'] = 'done'
                    break
            sleep(10)
    finally:
        ok_stop = BR.stop_and_verify(name)
        summary['stop_verified'] = ok_stop
        summary['running_s'] = round((clock() - run_since), 1) if run_since is not None else 0.0
        summary['cost_usd_est'] = round(cost_usd(summary['running_s'], price), 3)
        json.dump(summary, open(os.path.join(a.out, f'summary-{name}.json'), 'w'), ensure_ascii=False, indent=1)
        say('ИТОГ', json.dumps({k: summary.get(k) for k in ('group', 'stopped_by', 'stop_verified', 'failed', 'running_s', 'cost_usd_est')}, ensure_ascii=False))
    return 0 if summary['stop_verified'] and summary['stopped_by'] == 'done' else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', default='trellis2', choices=['trellis2'])
    ap.add_argument('--image', help='образ группы: тег или digest в ghcr.io/igortsk123/mesh-hunyuan')
    ap.add_argument('--inputs', default=os.path.expanduser('~/remlab-logs/mesh-models-1118/trellis/inputs'))
    ap.add_argument('--skus', nargs='*', default=[])
    ap.add_argument('--plan', default='1024:1', help='разрешения × повторов: 1024:1,1536:1')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--decimation', type=int, default=500000)
    ap.add_argument('--texture', type=int, default=2048)
    ap.add_argument('--tier', default='high', choices=['batch', 'low', 'medium', 'high'])
    ap.add_argument('--cpu', type=int, default=8)
    ap.add_argument('--mem-mb', type=int, default=32768)
    ap.add_argument('--cap', type=float, default=3.0, help='потолок денег на ВЕСЬ замер, $')
    ap.add_argument('--max-min', type=int, default=90)
    ap.add_argument('--ready-min', type=int, default=40, help='сколько минут после running ждать прогрева модели')
    ap.add_argument('--job-timeout', type=int, default=15)
    ap.add_argument('--suffix', default=time.strftime('%m%d%H%M', time.gmtime()))
    ap.add_argument('--out', default=os.path.expanduser('~/remlab-logs/mesh-models-1118/trellis'))
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--stop-only', action='store_true')
    a = ap.parse_args()
    import bench_run as BR
    import migrate_groups as MG
    if a.stop_only:
        MG.env_from_file()
        return 0 if BR.stop_and_verify(f'trial-{a.model}-{a.suffix}') else 1
    if not a.image or not a.skus:
        sys.exit('нужны --image и --skus')
    if '@' not in a.image and ':' not in a.image:
        sys.exit('--image: тег или digest с именем репозитория')
    return run(a, MG, BR)


if __name__ == '__main__':
    sys.exit(main())
