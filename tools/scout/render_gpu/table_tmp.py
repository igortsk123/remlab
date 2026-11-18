import glob, json, os, sys
D = os.path.expanduser(sys.argv[1])
rows = []
for sf in sorted(glob.glob(D + '/summary-*.json')):
    s = json.load(open(sf))
    rid = s['run_id']
    ev = {}
    try:
        ev = json.load(open(f'{D}/events-{rid}.json'))
    except OSError:
        pass
    tl = [json.loads(l) for l in open(f'{D}/timeline-{rid}.jsonl') if l.strip()] if os.path.exists(f'{D}/timeline-{rid}.jsonl') else []
    ph = {}
    for r in tl:
        ins = r['instances'] if isinstance(r.get('instances'), list) else []
        st = ins[0]['state'] if ins else r['status']
        ph.setdefault(st, r['t'])
    m = ev.get('machine') or {}
    steps = [x for x in (ev.get('steps') or []) if x.get('device_arg') == 'auto']
    pair = [round(sum(f['sec'] for f in x['frames']), 1) for x in steps]
    wall = [x['wall_s'] for x in steps]
    rows.append((rid, s['group'][len('render-bench-'):], s['price_usd_h'], ph.get('downloading'), ph.get('creating'), ph.get('running'), s['to_first_running_s'],
                 s['running_s'], s['cost_usd_est'], m.get('nproc'), (m.get('cpu') or '')[:28], pair, wall))
print('run | группа | $/ч | →download | →creating | →running | до running | работал с | ≈$ | nproc | CPU | пара кадров (сек, прогоны) | wall прогона')
for r in rows:
    print(' | '.join(str(x) for x in r))
