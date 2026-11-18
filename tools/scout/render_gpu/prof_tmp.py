import json, os, sys, time, shutil, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..')); sys.path.insert(0, HERE)
import render_exec as RE, render_snapshot as RS
data = json.load(open(os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json'), encoding='utf-8'))
snap = RS.canonicalize(data, {'v': 1, 'variant_id': sys.argv[1] if len(sys.argv) > 1 else 'set1'}, 'demo')
ex = RE.SaladGpuExecutor({})
pr = RE.preset()
job = os.path.expanduser('~/remlab-logs/t24-1117/prof-job'); shutil.rmtree(job, ignore_errors=True); os.makedirs(job)
t = {}
ex._prepare(snap, job, os.path.join(job, 'run.log'), pr, lambda *a: None, t)
print('timing', t)
tot = collections.Counter(); cnt = collections.Counter()
for dp, _, fs in os.walk(job):
    for f in fs:
        p = os.path.join(dp, f); rel = os.path.relpath(p, job)
        k = rel.split('/')[0] + '/' + (os.path.splitext(f)[1] or f)
        tot[k] += os.path.getsize(p); cnt[k] += 1
for k, v in sorted(tot.items(), key=lambda x: -x[1])[:14]:
    print(f'{v/2**20:8.1f} МБ {cnt[k]:4d} файлов  {k}')
print('всего', round(sum(tot.values())/2**20, 1), 'МБ')
# повторы по содержимому: одинаковые текстуры?
import hashlib
h = collections.defaultdict(list)
for dp, _, fs in os.walk(os.path.join(job, 'scene')):
    for f in fs:
        if f.endswith('.png'):
            p = os.path.join(dp, f); h[hashlib.sha256(open(p, 'rb').read()).hexdigest()].append(os.path.getsize(p))
print('текстур', sum(len(v) for v in h.values()), 'уникальных', len(h))
