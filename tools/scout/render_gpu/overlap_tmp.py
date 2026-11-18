import json, os, sys, shutil, hashlib, struct, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..')); sys.path.insert(0, HERE)
import render_exec as RE, render_snapshot as RS
data = json.load(open(os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json'), encoding='utf-8'))
ex = RE.SaladGpuExecutor({'RENDER_WORK': os.path.expanduser('~/remlab-logs/t24-1117/ovl-work')}); pr = RE.preset()
res = {}
for v in data['variants']:
    vid = v['id']
    snap = RS.canonicalize(data, {'v': 1, 'variant_id': vid}, 'demo')
    job = ex._job_dir('gjob-', snap); os.makedirs(job)
    t = {}
    try:
        ex._prepare(snap, job, os.path.join(job, 'run.log'), pr, lambda *a: None, t)
    except Exception as e:
        print(vid, 'ОШИБКА', repr(e)[:100]); shutil.rmtree(job, ignore_errors=True); continue
    tex = {}
    for dp, _, fs in os.walk(os.path.join(job, 'scene')):
        for f in fs:
            p = os.path.join(dp, f)
            if f.endswith('.png'):
                tex[hashlib.md5(open(p, 'rb').read()).hexdigest()[:10]] = os.path.getsize(p)
    glb = open(os.path.join(job, 'dump', 'demo_nodes.glb'), 'rb').read()
    l = struct.unpack('<I', glb[12:16])[0]; j = json.loads(glb[20:20 + l]); bv = j['bufferViews']
    off = 20 + l + 8
    imgs = {}
    for i in j.get('images', []):
        b = bv[i['bufferView']]; imgs[hashlib.md5(glb[off + b.get('byteOffset', 0):off + b.get('byteOffset', 0) + b['byteLength']]).hexdigest()[:10]] = b['byteLength']
    npz = sum(os.path.getsize(os.path.join(job, 'scene', f)) for f in os.listdir(os.path.join(job, 'scene')) if f.endswith('.npz'))
    res[vid] = {'tex': tex, 'img': imgs, 'npz': npz, 'glb': len(glb), 'timing': t}
    print(vid, 'tex', len(tex), round(sum(tex.values()) / 2**20, 1), 'МБ; glb-картин', len(imgs), round(sum(imgs.values()) / 2**20, 1), 'МБ; npz', round(npz / 2**20, 1), 'МБ', t, flush=True)
    shutil.rmtree(job, ignore_errors=True)
allt = collections.Counter(); alli = collections.Counter(); sz = {}
for v in res.values():
    for h, s in {**v['tex'], **v['img']}.items(): sz[h] = s
    for h in v['tex']: allt[h] += 1
    for h in v['img']: alli[h] += 1
tot_all = sum(sz[h] for h in set(allt) | set(alli))
print('УНИКАЛЬНЫХ текстур (сцена)', len(allt), 'картин в GLB', len(alli), 'суммарно', round(tot_all / 2**20, 1), 'МБ; без повторов')
print('суммарно по вариантам (как шлём сейчас):', round(sum(sum(v['tex'].values()) + sum(v['img'].values()) for v in res.values()) / 2**20, 1), 'МБ')
