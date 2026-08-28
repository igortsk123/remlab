"""Сколько в каталоге фото-коллажей: выборка пропорционально долям магазинов."""
import io, json, random, sys, urllib.request
sys.path.insert(0, '.')
import numpy as np
from PIL import Image
from collage import is_collage
from concurrent.futures import ThreadPoolExecutor
import collections

items = list(json.load(open('/home/pakar/igor/remlab/tools/scout/candidates-index.json'))['items'].values())
items = [x for x in items if x.get('img')]
random.seed(7); random.shuffle(items)
SAMPLE = items[:400]
UA = {'User-Agent': 'remlab-bench/1.0'}

def one(x):
    u = x['img']; u = 'https:' + u if u.startswith('//') else u
    try:
        raw = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25).read()
        im = Image.open(io.BytesIO(raw)).convert('RGB')
    except Exception as e:
        return x['shop'], 'bad', None
    v, why, f = is_collage(np.asarray(im))
    kind = 'collage' if v else ('scene' if f['bg_spread'] > 0.12 else 'card')
    return x['shop'], kind, why

res = []
with ThreadPoolExecutor(max_workers=12) as ex:
    for r in ex.map(one, SAMPLE):
        res.append(r)
tot = collections.Counter(k for _, k, _ in res if k != 'bad')
n = sum(tot.values())
print(f'проверено {n} из {len(SAMPLE)} (не скачалось {sum(1 for _,k,_ in res if k=="bad")})')
for k, name in (('card', 'карточка на ровном фоне'), ('scene', 'сцена/интерьер'), ('collage', 'КОЛЛАЖ-баннер')):
    print(f'  {name:26} {tot[k]:4} ({100*tot[k]/max(n,1):.1f}%)')
print('\nпо магазинам (доля коллажей):')
per = collections.defaultdict(collections.Counter)
for s, k, _ in res:
    if k != 'bad': per[s][k] += 1
for s, c in sorted(per.items(), key=lambda kv: -sum(kv[1].values())):
    m = sum(c.values())
    print(f'  {s:18} всего {m:4}  коллажей {c["collage"]:3} ({100*c["collage"]/m:.0f}%)  сцен {c["scene"]:3}')
