#!/usr/bin/env python3
"""ЗАМЕР КАРТЫ НА SALAD (T-20261117-22): своя группа `render-bench-<карта>` (меш-группы не трогает), 1 машина, тариф high, образ замера.

    ~/venvs/scout/bin/python bench_run.py --card 3090 --image <digest>            # разбор: печатает тело группы без секретов, ничего не создаёт
    ~/venvs/scout/bin/python bench_run.py --card 3090 --image <digest> --apply    # создать (остановленной), запустить, следить, собрать, ПОГАСИТЬ
    ~/venvs/scout/bin/python bench_run.py --card 3090 --stop-only                 # просто /stop и проверка stopped

Деньги (потолок T-22 — $5 на весь замер, стоп при $4): цена — по классу карты и тарифу из rules/salad-groups.json (`prices_by_class_usd_h`);
начисления считаем по времени `running` инстанса (платим за running, ADR-0135) + запас на отставание счёта; `--spent-before` — уже
потраченное на прежних карточках этого замера. Предохранители: бюджет карточки `--cap`, общий `--total-cap` (4.0), максимум времени `--max-min`.
Журнал переходов состояний (время до running, образ, готовность) — `<out>/timeline.jsonl`. После замера — /stop и проверка `stopped` без машин.
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'salad'))
import migrate_groups as MG  # noqa: E402
import salad_groups as SG    # noqa: E402

CARDS = {
    '3090': {'class_name': 'RTX 3090 (24 GB)', 'class_id': 'a5db5c50-cbcb-4596-ae80-6a0c8090d80f'},
    '4090': {'class_name': 'RTX 4090 (24 GB)', 'class_id': 'ed563892-aacd-40f5-80b7-90c9be6c759b'},
}
SERVER = ['ssh', '-o', 'ConnectTimeout=10', '-o', 'BatchMode=yes', '-p', '22222', 'root@89.167.127.0']
SINK_ROOT = '/opt/remlab/meshes'     # каталог приёмника на сервере (проверено ls перед замером)
DONOR = 'mesh-q-low-1'              # только за адресом приёмника и токеном (не печатаются) и образцом сети


def now():
    return time.time()


def say(*a):
    print(time.strftime('%H:%M:%S', time.gmtime()), *a, flush=True)


def build_body(name, card, image, donor, run_id, plan, cpu, mem_mb, tier='high', countries=()):
    denv = (donor.get('container') or {}).get('environment_variables') or {}
    env = {'RUN_ID': run_id, 'MESH_SINK_URL': denv['MESH_SINK_URL'], 'MESH_SINK_TOKEN': denv['MESH_SINK_TOKEN'],
           'BENCH_PLAN': plan, 'BENCH_SAMPLES': '64', 'BENCH_PCT': '75', 'IMAGE_NOTE': image.split('@')[-1][:19],
           'DEPLOYMENT_EPOCH': f'20261117-{name}', 'NVIDIA_DRIVER_CAPABILITIES': 'all'}
    return {
        'name': name, 'display_name': name,
        'container': {
            'image': image,
            'resources': {'cpu': cpu, 'memory': mem_mb, 'gpu_classes': [CARDS[card]['class_id']],
                          'storage_amount': 10 * 2 ** 30, 'shm_size': 256},
            'priority': tier,
            'environment_variables': env,
            'image_caching': True,
            'registry_authentication': MG.ghcr_auth(),
        },
        'autostart_policy': False,
        'restart_policy': 'never',
        'replicas': 1,
        'priority': tier,
        'country_codes': list(countries),
    }


def safe_print(body):
    b = json.loads(json.dumps(body))
    b['container'].pop('registry_authentication', None)
    for k in list(b['container']['environment_variables']):
        if any(s in k for s in ('TOKEN', 'KEY', 'SECRET', 'PASS')):
            b['container']['environment_variables'][k] = '<скрыто>'
    print(json.dumps(b, ensure_ascii=False, indent=1))


def instances(name):
    code, d = MG.api(f'/{name}/instances')
    return code, (d.get('instances') or [])


def group_state(name):
    code, g = MG.api(f'/{name}')
    if code != 200:
        return code, None, None
    st = g.get('current_state') or {}
    return code, st.get('status'), st.get('instance_status_counts') or {}


def sink_events(run_id):
    """events.json приёмника (в .staging или в постоянном каталоге) — по ssh на сервер, только чтение."""
    p = f'{SINK_ROOT}/renderbench-1117/{run_id}'
    r = subprocess.run(SERVER + [f'cat {p}/.staging/events.json 2>/dev/null || cat {p}/events.json 2>/dev/null'], capture_output=True, text=True, timeout=40)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def stop_and_verify(name, timeout_s=300):
    code, _ = MG.api(f'/{name}/stop', 'POST')
    say('stop', name, 'HTTP', code)
    t0 = now()
    while now() - t0 < timeout_s:
        c, st, cnt = group_state(name)
        n = sum(int(cnt.get(k, 0) or 0) for k in ('allocating_count', 'creating_count', 'running_count', 'stopping_count'))
        if st == 'stopped' and n == 0:
            say('СТОП ПОДТВЕРЖДЁН:', name, st, cnt)
            return True
        time.sleep(10)
    say('!! НЕ ПОДТВЕРДИЛ ОСТАНОВКУ', name, group_state(name))
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--card', required=True, choices=list(CARDS))
    ap.add_argument('--image')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--stop-only', action='store_true')
    ap.add_argument('--plan', default='living:auto:3,bedroom:auto:2,living:cuda:1')
    ap.add_argument('--cpu', type=int, default=8)
    ap.add_argument('--mem-mb', type=int, default=16384)
    ap.add_argument('--cap', type=float, default=1.5, help='потолок начислений по этой карточке, $')
    ap.add_argument('--spent-before', type=float, default=0.0, help='уже потрачено на прежних карточках замера, $')
    ap.add_argument('--total-cap', type=float, default=4.0, help='стоп при общих начислениях, $')
    ap.add_argument('--max-min', type=int, default=75, help='предел времени работы машины, мин')
    ap.add_argument('--no-events-s', type=int, default=240, help='стоп, если столько секунд после running нет events.json')
    ap.add_argument('--tier', default='high', choices=['batch', 'low', 'medium', 'high'], help='priority группы Salad (рычаг T-24/3; цена — по классу и тарифу)')
    ap.add_argument('--countries', default='', help='country_codes через запятую (рычаг «место»); пусто — любые')
    ap.add_argument('--suffix', default='', help='суффикс имени группы (b — повтор в новой группе)')
    ap.add_argument('--start-existing', action='store_true', help='группа уже создана (остановлена) — запустить как есть')
    ap.add_argument('--reuse', action='store_true', help='группа уже есть и остановлена: обновить образ/RUN_ID (PATCH) и запустить')
    ap.add_argument('--out', default=os.path.expanduser('~/remlab-logs/t22-1117'))
    a = ap.parse_args()
    MG.env_from_file()
    name = f'render-bench-{a.card}{a.suffix}'
    if a.stop_only:
        sys.exit(0 if stop_and_verify(name) else 1)
    if not a.image:
        sys.exit('нужен --image <digest>')
    code, donor = MG.api(f'/{DONOR}')
    if code != 200:
        sys.exit(f'образец {DONOR}: HTTP {code}')
    run_id = f'{a.card}{a.suffix}-{time.strftime("%H%M%S", time.gmtime())}'      # суффикс группы и секунды: параллельные замеры не делят каталог на приёмнике (T-24/3: коллизия id)
    body = build_body(name, a.card, a.image, donor, run_id, a.plan, a.cpu, a.mem_mb, a.tier, [c for c in a.countries.split(',') if c])
    try:      # цена — по классу карты И тарифу запуска (рычаг priority меняет цену)
        price = json.load(open(SG.RULES_FILE if hasattr(SG, 'RULES_FILE') else os.path.join(HERE, '..', 'rules', 'salad-groups.json'), encoding='utf-8'))['prices_by_class_usd_h'][CARDS[a.card]['class_name']][a.tier]
    except (OSError, KeyError, ValueError):
        price = SG.price(name) or SG.price(f'render-bench-{a.card}')      # повторы в новых группах (суффикс) — цена той же карты
    say('группа', name, 'карта', CARDS[a.card]['class_name'], 'тариф', a.tier, 'цена $/ч', price, 'run', run_id)
    if not a.apply:
        safe_print(body)
        return
    # 0. нет ли живых групп НЕ меш/render — по списку проекта
    code, d = MG.api('')
    live = [g['name'] for g in d.get('items', [])
            if (g.get('current_state') or {}).get('status') not in ('stopped', 'failed', None) and not g['name'].startswith(('mesh-', 'render-'))]
    if live:
        sys.exit(f'живые группы не mesh-/render-: {live} — стоп')
    if price is None:
        sys.exit('цены группы нет в rules/salad-groups.json — стоп (деньги без цены не считаем)')
    code, g = MG.api(f'/{name}')
    if code == 200 and a.start_existing and (g.get('current_state') or {}).get('status') == 'stopped':
        say('группа уже создана и остановлена — запускаю как есть (образ и env из неё)')
        run_id = (g['container'].get('environment_variables') or {}).get('RUN_ID', run_id)
    elif code == 200 and a.reuse and (g.get('current_state') or {}).get('status') == 'stopped':
        # повторный замер на той же (остановленной) группе: новый образ и RUN_ID — PATCH контейнера, группу не удаляем
        import urllib.error
        import urllib.request
        _rq = urllib.request.Request(f'{MG.API}/{name}', method='PATCH', headers={
            'Salad-Api-Key': os.environ['SALAD_API_KEY'], 'User-Agent': 'remlab-mesh/1.0', 'Content-Type': 'application/merge-patch+json'},
            data=json.dumps({'container': {k: body['container'][k] for k in ('image', 'environment_variables', 'registry_authentication')}}).encode())
        try:
            with urllib.request.urlopen(_rq, timeout=60) as _r:
                code, resp = _r.status, {}
        except urllib.error.HTTPError as _e:
            code, resp = _e.code, _e.read().decode()[:200]
        say('PATCH контейнера', code, str(resp)[:200] if code >= 300 else 'ok')
        if code >= 300:
            sys.exit(1)
    elif code == 200:
        sys.exit(f'группа {name} уже есть ({(g.get("current_state") or {}).get("status")}) — не пересоздаю молча (--reuse: обновить остановленную)')
    else:
        code, resp = MG.api('', 'POST', body)
        say('POST создание', code, str(resp)[:200] if code >= 300 else 'ok')
        if code >= 300:
            sys.exit(1)
    for _ in range(120):                       # создание группы Salad иногда идёт 2–10 мин (pending)
        c, st, cnt = group_state(name)
        if st == 'stopped':
            break
        time.sleep(5)
    say('группа создана, статус', st)
    tl = open(os.path.join(a.out, f'timeline-{run_id}.jsonl'), 'a', encoding='utf-8')
    t_start = now()
    code, _ = MG.api(f'/{name}/start', 'POST')
    say('start HTTP', code, '— отсчёт', time.strftime('%H:%M:%S', time.gmtime(t_start)))
    seen, run_since, paid_s, last_ev = {}, None, 0.0, None
    stopped_by = None
    try:
        while True:
            t = now()
            c, st, cnt = group_state(name)
            code_i, ins = instances(name)
            snap = {'t': round(t - t_start, 1), 'epoch': round(t, 1), 'status': st, 'counts': cnt,
                    'instances': [{k: i.get(k) for k in ('instance_id', 'machine_id', 'state', 'ready', 'started', 'version', 'update_time')} for i in ins]}
            key = json.dumps([st, cnt, [(i.get('instance_id'), i.get('state'), i.get('ready')) for i in ins]], sort_keys=True)
            if seen.get('k') != key:
                seen['k'] = key
                tl.write(json.dumps(snap, ensure_ascii=False) + '\n')
                tl.flush()
                say(f't+{snap["t"]:.0f}s', st, cnt, [(i.get('state'), i.get('ready')) for i in ins])
            running = any(i.get('state') == 'running' for i in ins)
            if running and run_since is None:
                run_since = t
                say('первый running: t+%.0f с от /start' % (t - t_start))
            if run_since is not None:
                paid_s = t - run_since
            cost = a.spent_before + paid_s / 3600.0 * price
            ev = sink_events(run_id) if int(t - t_start) % 30 < 10 else last_ev
            if ev:
                last_ev = ev
            if run_since is not None and not last_ev and t - run_since > a.no_events_s:
                say(f'!! за {a.no_events_s} с после running данных на приёмнике нет — гашу (бенч идёт ~3 мин; причина — в журнале контейнера)')
                stopped_by = 'no-events'
                break
            if last_ev and last_ev.get('result'):
                say('бенч сообщил результат:', last_ev['result'], '— собираю и гашу')
                stopped_by = 'result'
                break
            if cost >= a.total_cap or (cost - a.spent_before) >= a.cap:
                say(f'!! ПОТОЛОК ДЕНЕГ: начислено ≈${cost:.2f} (карточка ${cost - a.spent_before:.2f}) — гашу')
                stopped_by = 'money'
                break
            if run_since is not None and (t - run_since) > a.max_min * 60:
                say(f'!! предел времени {a.max_min} мин — гашу')
                stopped_by = 'time'
                break
            if run_since is None and (t - t_start) > 60 * 60:
                say('!! за час машина не вышла в running — гашу (платили 0)')
                stopped_by = 'no_machine'
                break
            time.sleep(10)
    finally:
        ok = stop_and_verify(name)
        tl.close()
    cost_now = a.spent_before + paid_s / 3600.0 * price
    summary = {'group': name, 'run_id': run_id, 'card': a.card, 'price_usd_h': price, 'running_s': round(paid_s, 1),
               'cost_usd_est': round(paid_s / 3600.0 * price, 3), 'stopped_by': stopped_by, 'stop_verified': ok,
               'to_first_running_s': round(run_since - t_start, 1) if run_since else None}
    json.dump(summary, open(os.path.join(a.out, f'summary-{run_id}.json'), 'w'), indent=1, ensure_ascii=False)
    if last_ev:
        json.dump(last_ev, open(os.path.join(a.out, f'events-{run_id}.json'), 'w'), indent=1, ensure_ascii=False)
    say('ИТОГ', json.dumps(summary, ensure_ascii=False))
    say(f'общие начисления замера ≈ ${cost_now:.2f}')


if __name__ == '__main__':
    main()
