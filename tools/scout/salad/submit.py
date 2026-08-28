#!/usr/bin/env python3
"""Постановка заданий пилота в очередь SaladCloud и учёт денег. Запускается ЛОКАЛЬНО.

Считает не «цену за генерацию», а фактические расходы: в знаменатель идут только годные
ассеты, в числитель — ВСЕ попытки, включая неуспешные и повторы после прерывания ноды.
Иначе получается красивая цифра $0.006, за которой прячется 40% брака.

Жёсткий лимит заданий — предохранитель: пилот не должен незаметно превратиться в полный
прогон, если где-то зациклится добор.

  ~/venvs/scout/bin/python submit.py --dry-run          # что будет отправлено, без отправки
  ~/venvs/scout/bin/python submit.py --submit           # поставить задания
  ~/venvs/scout/bin/python submit.py --collect          # собрать результаты и посчитать деньги
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, '..', 'mesh-pilot-sample.json')
RESULTS = os.path.join(HERE, '..', 'mesh-pilot-results.json')

MAX_JOBS = 600            # предохранитель: 500 товаров + повторы на seed, ни задания сверх
ORG = os.environ.get('SALAD_ORG', '')
PROJECT = os.environ.get('SALAD_PROJECT', '')
QUEUE = os.environ.get('SALAD_QUEUE', 'mesh-hunyuan')
API = 'https://api.salad.com/api/public'

# Тарифы batch-приоритета, сверены по API 28.08 (`GET /organizations/<org>/gpu-classes`).
# ВАЖНО для бенча: сравнивать карты можно только на ОДНОМ приоритете — на high те же 4090
# стоят $0.30, и «карта дороже» окажется артефактом тарифа, а не железа.
RATE_PER_HOUR = {'RTX 4090': 0.16, 'RTX 5090': 0.25, 'RTX 3090': 0.09,
                 'RTX A5000': 0.09, 'RTX 5090 Laptop': 0.10, 'RTX 3090 Ti': 0.10}


def _req(method: str, url: str, body: dict | None = None) -> dict:
    key = os.environ.get('SALAD_API_KEY')
    if not key:
        sys.exit('нет SALAD_API_KEY (см. .memory_bank/_secrets/ACCESS.md)')
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Salad-Api-Key': key,
                                          'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        sys.exit(f'{method} {url} → {e.code}: {e.read()[:400].decode(errors="replace")}\n'
                 f'СВЕРЬ ФОРМУ ЗАПРОСА С ПОРТАЛОМ: схема Job Queue API проверялась по докам, '
                 f'а не на живом аккаунте.')


def jobs_from_sample() -> list[dict]:
    """Одно задание на (товар, seed): прерывание не должно убивать сразу три прогона."""
    s = json.load(open(SAMPLE, encoding='utf-8'))
    out = []
    for j in s['jobs']:
        for seed in j['seeds']:
            out.append({'sku': j['sku'], 'role': j['role'], 'image_url': j['image_url'],
                        'dims_cm': j['dims_cm'], 'seed': seed, 'strata': j['strata'],
                        'params': {}})
    if len(out) > MAX_JOBS:
        sys.exit(f'ПРЕДОХРАНИТЕЛЬ: заданий {len(out)} > лимита {MAX_JOBS}')
    return out


def submit(jobs: list[dict]) -> None:
    url = f'{API}/organizations/{ORG}/projects/{PROJECT}/queues/{QUEUE}/jobs'
    sent = []
    for i, job in enumerate(jobs, 1):
        r = _req('POST', url, {'input': job})
        sent.append({'job_id': r.get('id'), 'sku': job['sku'], 'seed': job['seed'],
                     'role': job['role']})
        if i % 25 == 0:
            print(f'  поставлено {i}/{len(jobs)}', flush=True)
        time.sleep(0.05)
    json.dump({'submitted': sent, 'at': time.time()}, open(RESULTS, 'w'), ensure_ascii=False)
    print(f'поставлено заданий: {len(sent)} → {RESULTS}')


def collect() -> None:
    url = f'{API}/organizations/{ORG}/projects/{PROJECT}/queues/{QUEUE}/jobs'
    state = json.load(open(RESULTS, encoding='utf-8'))
    rows, gpu_s, attempts = [], 0.0, 0
    for s in state['submitted']:
        r = _req('GET', f'{url}/{s["job_id"]}')
        out = r.get('output') or {}
        attempts += 1 + int(r.get('retry_count') or 0)
        t = (out.get('timings_s') or {}).get('total')
        gpu = (out.get('gpu') or {}).get('name', '?')
        if t:
            gpu_s += float(t) * (1 + int(r.get('retry_count') or 0))
        rows.append({**s, 'status': out.get('status', r.get('status')), 'total_s': t,
                     'gpu': gpu, 'prefix': out.get('prefix'), 'error': out.get('error')})

    ok = [r for r in rows if r['status'] in ('ok', 'cached')]
    by_gpu: dict[str, float] = {}
    for r in rows:
        if r['total_s']:
            by_gpu[r['gpu']] = by_gpu.get(r['gpu'], 0.0) + r['total_s']
    cost = sum(sec / 3600 * RATE_PER_HOUR.get(g, 0.16) for g, sec in by_gpu.items())

    state['results'] = rows
    state['cost'] = {'gpu_seconds': round(gpu_s), 'by_gpu_seconds': by_gpu,
                     'usd_total': round(cost, 3), 'attempts': attempts,
                     'generated': len(ok),
                     'usd_per_generated': round(cost / max(len(ok), 1), 4)}
    json.dump(state, open(RESULTS, 'w'), ensure_ascii=False, indent=1)

    print(f'заданий {len(rows)}, попыток {attempts}, сгенерировано {len(ok)}')
    print(f'GPU-секунд {round(gpu_s)}, потрачено ${cost:.2f}, '
          f'${cost / max(len(ok), 1):.4f} за генерацию')
    print('ВНИМАНИЕ: это цена за ГЕНЕРАЦИЮ. Цена за ГОДНЫЙ ассет считается после приёмки '
          '(mesh_gate + mesh_gate_pbr) — она и есть ответ пилота.')
    fails: dict[str, int] = {}
    for r in rows:
        if r['status'] not in ('ok', 'cached'):
            fails[r['role']] = fails.get(r['role'], 0) + 1
    if fails:
        print(f'отказы по ролям: {fails}')


def main() -> None:
    jobs = jobs_from_sample()
    if '--dry-run' in sys.argv:
        roles: dict[str, int] = {}
        for j in jobs:
            roles[j['role']] = roles.get(j['role'], 0) + 1
        print(f'заданий к отправке: {len(jobs)} (лимит {MAX_JOBS})')
        print(json.dumps(roles, ensure_ascii=False, indent=1))
        print(f'\nпример:\n{json.dumps(jobs[0], ensure_ascii=False, indent=1)}')
    elif '--submit' in sys.argv:
        submit(jobs)
    elif '--collect' in sys.argv:
        collect()
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
