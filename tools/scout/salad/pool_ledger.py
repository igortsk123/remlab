#!/usr/bin/env python3
"""Учёт пула ПО МАШИНЕ из событий Salad — только чтение, бесплатно (план mesh-17 п.6, T-20261024-01).

Census сторожа денег (`mesh-pool-census.jsonl`) — суммы по группе раз в 5 минут: простой там виден только оценкой.
Здесь — факт по каждому инстансу за окно: когда стал running и чем кончился (события `instance_controller`),
прогрелся ли (строка `Models Loaded` в выводе контейнера), видел ли его раздатчик и сколько он сделал (журнал прогона),
сколько он стоил (цена класса карты Salad на тарифе группы — она полная, CPU и ОЗУ включены).

Ночь 23→24.10 так нашла главную утечку: 108 прогретых инстансов раздатчик не видел (SSH молчит) — 54 % оплаты;
молчание — свойство физической машины (`machine_id`), Salad выдаёт такие машины снова.

  pool_ledger.py --since 8h [--until …] [--groups g1,g2] [--journal журнал.jsonl] [--out файл.json]   # сводка + файл
  pool_ledger.py --selftest

Ключ — `SALAD_API_KEY` (как у прочих скриптов пула: `set -a; . ~/scout-scenes/salad.env; set +a`). Страница журнала
Salad — не больше 100 записей, время страницы — `YYYY-MM-DDTHH:MM:SSZ`, без User-Agent API отвечает 403.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
API = 'https://api.salad.com/api/public/organizations/prodstore'
PROJECT = 'dmodel'
JOURNAL = os.path.join(HERE, '..', 'mesh-run-progress.jsonl')
USD_RUB = 86.89          # тот же курс, что rules/salad-groups.json
END_MARKS = ('Interrupted', 'Reallocated', 'Exited')
WARM_MARK = 'Models Loaded'      # pipeline печатает после загрузки моделей (прогрев воркера)
PAGE = 100


def _req(path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(f'{API}/{path}', method='POST' if body is not None else 'GET',
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'], 'User-Agent': 'remlab-mesh/1.0',
                                          'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b'{}')


def ts(s: str) -> float:
    m = re.match(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?', s)
    return dt.datetime.fromisoformat(m.group(1) + '+00:00').timestamp() + float(m.group(2) or 0)


def iso(t: float) -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t))


def log_entries(query: str, since: float, until: float, req=_req) -> list[dict]:
    """Все записи журнала Salad за окно, по возрастанию. Страница по 100; следующая — с секунды последней записи
    (повторы той же секунды отсеиваются). Страница без новых записей — конец, иначе бесконечный круг."""
    out, seen, cur = [], set(), since
    for _ in range(500):
        items = req('log-entries', {'start_time': iso(cur), 'end_time': iso(until), 'query': query,
                                    'page_size': PAGE, 'sort_order': 'asc'}).get('items') or []
        new = [x for x in items if json.dumps(x, sort_keys=True) not in seen]
        seen.update(json.dumps(x, sort_keys=True) for x in new)
        out += new
        if len(items) < PAGE or not new:
            break
        cur = int(max(ts(x['time']) for x in items))
        time.sleep(0.3)
    return out


def prices(groups: list[str], req=_req) -> dict:
    """(группа, класс карты) → $/ч по тарифу группы. Класс — по имени, как в событии `Instance Allocated`."""
    cls = req('gpu-classes').get('items') or []
    out = {}
    for g in groups:
        tier = (req(f'projects/{PROJECT}/containers/{g}').get('priority') or 'low').lower()
        for c in cls:
            p = {x['priority']: float(x['price']) for x in c.get('prices') or []}
            if tier in p:
                out[(g, c['name'])] = p[tier]
    return out


def journal(since: float, until: float, path: str = JOURNAL) -> dict:
    """instance → счётчики статусов журнала прогона за окно (с запасом 10 мин: запись задания идёт после события)."""
    out: dict = collections.defaultdict(collections.Counter)
    with open(path, encoding='utf-8') as f:
        for ln in f:
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get('instance') and since <= float(r.get('at') or 0) <= until + 600:
                out[r['instance']][r.get('status') or '?'] += 1
    return out


def ledger(events: list[dict], warm: list[dict], jr: dict, price: dict, until: float) -> dict:
    """Строка на инстанс и на машину. Оплачено = running → первое событие конца (или конец окна)."""
    by: dict = collections.defaultdict(list)
    for x in events:
        lab = x['resource']['labels']
        by[lab.get('instance_id')].append((ts(x['time']), (x.get('json_log') or {}).get('message') or x.get('text_log') or '',
                                           lab.get('machine_id'), lab.get('container_group_name'),
                                           (x.get('json_log') or {}).get('gpu_class_name')))
    warm_at: dict = {}
    for x in warm:
        i = x['resource']['labels'].get('instance_id')
        warm_at[i] = min(warm_at.get(i, 1e18), ts(x['time']))
    rows = []
    for iid, ev in by.items():
        ev.sort()
        run = [t for t, n, *_ in ev if n == 'Instance Running']
        if not iid or not run:
            continue
        end = [(t, n) for t, n, *_ in ev if t > run[0] and any(m in n for m in END_MARKS)]
        t_end, how = end[0] if end else (until, 'конец окна')
        mid = next((m for _, _, m, *_ in ev if m), None)
        grp = next((g for *_, g, _ in ev if g), None)
        gpu = next((c for *_, c in ev if c), None)
        st = jr.get(iid) or collections.Counter()
        w = warm_at.get(iid)
        warmed = w is not None and w < t_end
        if st.get('ok'):
            k = 'сделал меш'
        elif st.get('node_reject'):
            k = 'отказ раздатчика (ОЗУ/магазин)'
        elif st:
            k = 'видели, меша нет'
        elif warmed:
            k = 'прогрелся, раздатчик не видел'
        elif t_end - run[0] < 300:
            k = 'жил < 5 мин'
        else:
            k = 'не прогрелся'
        paid_min = (t_end - run[0]) / 60
        usd = price.get((grp, gpu))
        rows.append({'instance': iid, 'machine': mid, 'group': grp, 'gpu': gpu, 'running_at': round(run[0]),
                     'paid_min': round(paid_min, 1), 'end': how, 'warm_min': round((w - run[0]) / 60, 1) if warmed else None,
                     'kind': k, 'meshes': int(st.get('ok', 0)), 'drops': int(st.get('transport_failed', 0)),
                     'rub': round(paid_min / 60 * usd * USD_RUB, 2) if usd is not None else None})
    machines: dict = collections.defaultdict(lambda: {'instances': 0, 'unseen_warm': 0, 'meshes': 0, 'paid_min': 0.0, 'gpu': None})
    for r in rows:
        m = machines[r['machine']]
        m['instances'] += 1
        m['unseen_warm'] += r['kind'] == 'прогрелся, раздатчик не видел'
        m['meshes'] += r['meshes']
        m['paid_min'] = round(m['paid_min'] + r['paid_min'], 1)
        m['gpu'] = m['gpu'] or r['gpu']
    silent = sorted((k for k, m in machines.items() if m['unseen_warm'] >= 2 and not m['meshes']),
                    key=lambda k: -machines[k]['paid_min'])
    return {'instances': rows, 'machines': dict(machines), 'silent_machines': silent}


def summary(led: dict) -> list[str]:
    rows = led['instances']
    paid = sum(r['paid_min'] for r in rows) or 1.0
    rub = [r['rub'] for r in rows if r['rub'] is not None]
    meshes = sum(r['meshes'] for r in rows)
    lines = [f'инстансов {len(rows)}, оплачено {paid:.0f} нодо-мин'
             + (f', ≈{sum(rub):.0f} ₽ по цене класса карты' if rub else '')
             + (f', мешей {meshes} → {sum(rub) / meshes:.2f} ₽/меш' if rub and meshes else f', мешей {meshes}')]
    kinds: dict = collections.defaultdict(lambda: [0, 0.0])
    for r in rows:
        kinds[r['kind']][0] += 1
        kinds[r['kind']][1] += r['paid_min']
    for k, (n, m) in sorted(kinds.items(), key=lambda z: -z[1][1]):
        lines.append(f'  {k:32s} инстансов {n:4d}  нодо-мин {m:6.0f} ({m / paid:4.0%})')
    life = sorted(r['paid_min'] for r in rows)
    if life:
        lines.append(f'  жизнь running: медиана {life[len(life) // 2]:.1f} мин; концы: '
                     + ', '.join(f'{k} {v}' for k, v in collections.Counter(r['end'] for r in rows).most_common(4)))
    s = led['silent_machines']
    lines.append(f'  молчащих машин (прогрелись ≥2 раз, ни одного меша): {len(s)}'
                 + (f' — первые: {", ".join(str(x)[:8] for x in s[:5])}' if s else ''))
    return lines


def _since(arg: str, now: float) -> float:
    m = re.fullmatch(r'(\d+)([hd])', arg or '')
    return now - int(m.group(1)) * (3600 if m.group(2) == 'h' else 86400) if m else ts(arg)


def main(argv: list[str]) -> int:
    if '--selftest' in argv:
        return selftest()
    arg = lambda k, d=None: argv[argv.index(k) + 1] if k in argv else d   # noqa: E731
    now = time.time()
    since, until = _since(arg('--since', '8h'), now), (ts(arg('--until')) if arg('--until') else now)
    gs = [g for g in (arg('--groups') or os.environ.get('SALAD_GROUP', '')).split(',') if g.strip()]
    if not gs:
        print('нет групп: --groups или SALAD_GROUP', flush=True)
        return 2
    gq = ' OR '.join(f'resource.labels.container_group_name = "{g}"' for g in gs)
    ev = log_entries(f'resource.type = "instance_controller" AND ({gq})', since, until)
    warm = log_entries(f'resource.type = "container" AND ({gq}) AND log contains "{WARM_MARK}"', since, until)
    led = ledger(ev, warm, journal(since, until, arg('--journal', JOURNAL)), prices(gs), until)
    for ln in summary(led):
        print(ln, flush=True)
    out = arg('--out')
    if out:
        json.dump({'since': iso(since), 'until': iso(until), 'groups': gs, **led}, open(out, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print(f'по инстансам и машинам: {out}', flush=True)
    return 0


def selftest() -> int:
    """Без сети: разбор событий, классы инстансов, цена по классу, молчащие машины, постраничное чтение."""
    import tempfile
    bad = []

    def ok(name: str, cond: bool) -> None:
        print(('  ✓ ' if cond else '  ✗ ') + name, flush=True)
        if not cond:
            bad.append(name)
    T = 1792773600.0

    def e(t, msg, iid, mid='m1', gpu=None, kind='instance_controller'):
        j = {'message': msg, **({'gpu_class_name': gpu} if gpu else {})}
        return {'time': iso(T + t)[:-1] + '.123+00:00', 'json_log': j,
                'resource': {'type': kind, 'labels': {'instance_id': iid, 'machine_id': mid, 'container_group_name': 'g'}}}
    ev = [e(0, 'Instance Allocated', 'A', gpu='RTX 4060 Ti (16 GB)'), e(60, 'Instance Running', 'A'),
          e(60 + 720, 'Instance Interrupted (Priority)', 'A'),
          e(0, 'Instance Allocated', 'B', 'm2', 'RTX 4060 Ti (16 GB)'), e(30, 'Instance Running', 'B', 'm2'),
          e(30 + 840, 'Instance Interrupted (Priority)', 'B', 'm2'),
          e(900, 'Instance Allocated', 'C', 'm2', 'RTX 4060 Ti (16 GB)'), e(960, 'Instance Running', 'C', 'm2'),
          e(960 + 600, 'Instance Reallocated by User', 'C', 'm2'),
          e(0, 'Instance Allocated', 'D', 'm3', 'RTX 4060 Ti (16 GB)'), e(10, 'Instance Running', 'D', 'm3')]
    warm = [e(130, WARM_MARK, 'A', kind='container'), e(100, WARM_MARK, 'B', 'm2', kind='container'),
            e(1030, WARM_MARK, 'C', 'm2', kind='container'), e(1040, WARM_MARK, 'C', 'm2', kind='container')]
    with tempfile.TemporaryDirectory() as d:
        jp = os.path.join(d, 'j.jsonl')
        with open(jp, 'w', encoding='utf-8') as f:
            for st in ('warmup', 'ok', 'ok', 'transport_failed'):
                f.write(json.dumps({'instance': 'A', 'status': st, 'at': T + 300}) + '\n')
            f.write('не json\n')
        jr = journal(T - 60, T + 3600, jp)
    led = ledger(ev, warm, jr, {('g', 'RTX 4060 Ti (16 GB)'): 0.10}, T + 1800)
    r = {x['instance']: x for x in led['instances']}
    ok('оплачено = running → конец (A 12 мин, D до конца окна)', r['A']['paid_min'] == 12.0 and r['D']['paid_min'] == 29.8)
    ok('A сделал 2 меша, 1 обрыв; цена по классу карты', r['A']['kind'] == 'сделал меш' and r['A']['meshes'] == 2
       and r['A']['drops'] == 1 and r['A']['rub'] == round(12 / 60 * 0.10 * USD_RUB, 2))
    ok('B и C прогрелись, раздатчик не видел; прогрев C — по первой строке', r['B']['kind'] == r['C']['kind']
       == 'прогрелся, раздатчик не видел' and r['C']['warm_min'] == 1.2)
    ok('D без прогрева — «не прогрелся», конец — «конец окна»', r['D']['kind'] == 'не прогрелся' and r['D']['end'] == 'конец окна')
    ok('машина m2 (два прогретых невидимых) — в молчащих, m1 — нет', led['silent_machines'] == ['m2'])
    s = summary(led)
    ok('сводка: ₽/меш и доля невидимых', '₽/меш' in s[0] and any('прогрелся, раздатчик не видел' in x for x in s))
    pages = [[e(i, 'x', f'I{i}') for i in range(PAGE)], [e(PAGE - 1, 'x', f'I{PAGE - 1}')] + [e(PAGE + i, 'x', f'J{i}') for i in range(5)]]
    calls = []

    def fake(path, body):
        calls.append(body['start_time'])
        return {'items': pages[len(calls) - 1] if len(calls) <= len(pages) else []}
    keep = time.sleep
    time.sleep = lambda _s: None
    try:
        got = log_entries('q', T, T + 3600, req=fake)
    finally:
        time.sleep = keep
    ok('журнал Salad: 2 страницы, повтор на стыке отсеян, время страницы — до секунды с Z',
       len(got) == PAGE + 5 and len(calls) == 2 and calls[1] == iso(T + PAGE - 1))
    print('учёт пула по машине: ' + ('ВСЁ ЗЕЛЁНОЕ' if not bad else f'ПРОВАЛОВ {len(bad)}'), flush=True)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
