import json, glob, os
D = os.path.expanduser('~/remlab-logs/t22-1117')
for f in sorted(glob.glob(D + '/timeline-*.jsonl')):
    rows = [json.loads(l) for l in open(f) if l.strip()]
    print('==', os.path.basename(f), len(rows), 'снимков')
    prev = None
    for r in rows:
        st = [(i.get('state'), i.get('ready'), i.get('started'), (i.get('update_time') or '')[11:19]) for i in (r.get('instances') if isinstance(r.get('instances'), list) else [])]
        key = (r['status'], tuple((s[0], s[1]) for s in st))
        if key != prev:
            print(f"  t+{r['t']:>6.0f}s {r['status']:<10} {st}")
            prev = key
    summ = glob.glob(f.replace('timeline-', 'summary-').replace('.jsonl', '.json'))
    if summ:
        s = json.load(open(summ[0]))
        print('  итог: до running', s.get('to_first_running_s'), 'с; работал', s.get('running_s'), 'с; стоп', s.get('stopped_by'))
