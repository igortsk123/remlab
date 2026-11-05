#!/usr/bin/env python3
"""ОБЩИЕ ЧИСТЫЕ ФУНКЦИИ СБОРЩИКОВ НАБОРОВ (план onb-06 Т3, вариант Б): цвет товара по фото, палитра, акцентные пары стиля.

Вынесены из `compose2.py` БЕЗ изменений (живой банк гостиной до/после выноса — побайтно равен, отчёт T-20261105-31).
Импорт лёгкий: каталог и сборка не запускаются (у `compose2.py` импорт исполняет полную сборку — урок «import-ловушка scout»),
поэтому сборщик спальни `compose_bedroom.py` берёт их отсюда, а не из `compose2`.
"""
import colorsys
import concurrent.futures as cf
import io
import math
import os
import re
import urllib.request

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
THUMBS = os.path.join(HERE, 'thumbs')

# акцентная пара под стиль (из дизайнерских гармоний PAIRS ниже)
STYLE_PAIR={'сканди':('terra','green'),'современный':('blue','yellow'),'минимализм':('green','yellow'),
            'лофт':('terra','cyan'),'неоклассика':('blue','yellow'),'джапанди':('terra','green')}


def thumb_path(mid,eid): return os.path.join(THUMBS, f"{mid}-{re.sub(r'[^A-Za-z0-9]','_',eid)[:40]}.png")
def get_thumb(url,mid,eid):
    p=thumb_path(mid,eid)
    if os.path.exists(p): return p
    try:
        small=url.replace('/big.jpg','/small.jpg').replace('/big.png','/small.png')
        if small.startswith('//'): small='https:'+small
        req=urllib.request.Request(small,headers={'User-Agent':'Mozilla/5.0'})
        data=urllib.request.urlopen(req,timeout=20).read()
        im=Image.open(io.BytesIO(data)).convert('RGB'); im.thumbnail((110,82)); im.save(p,'PNG')
        return p
    except Exception: return None

# ---------- Ф2: цвет — ДВА кластера + температура ----------
def dominant2(p):
    try:
        im=Image.open(p).convert('RGB'); w,h=im.size
        px=list(im.getdata())
        bw=max(2,int(min(w,h)*0.10))
        border=[px[y*w+x] for y in range(h) for x in range(w) if x<bw or x>=w-bw or y<bw or y>=h-bw]
        bq=Image.new('RGB',(len(border),1)); bq.putdata(border)
        bq=bq.quantize(3).convert('RGB')
        bc={}
        for c in bq.getdata(): bc[c]=bc.get(c,0)+1
        bg=[c for c,n in bc.items() if n>=len(border)*0.18]
        def near_bg(c):
            if c[0]>232 and c[1]>232 and c[2]>232: return True
            return any(abs(c[0]-b[0])+abs(c[1]-b[1])+abs(c[2]-b[2])<95 for b in bg)
        inner=[px[y*w+x] for y in range(int(h*.12),int(h*.88)) for x in range(int(w*.12),int(w*.88))]
        obj=[c for c in inner if not near_bg(c)]
        if len(obj)<len(inner)*0.06 or len(obj)<30:
            obj=[c for c in inner if not (c[0]>225 and c[1]>225 and c[2]>225)] or inner
        q=Image.new('RGB',(len(obj),1)); q.putdata(obj)
        q=q.quantize(5).convert('RGB')
        counts={}
        for c in q.getdata(): counts[c]=counts.get(c,0)+1
        top=sorted(counts,key=counts.get,reverse=True)[:2]
        return top[0], (top[1] if len(top)>1 else top[0])
    except Exception: return None,None
def classify(rgb):
    if rgb is None: return 'unknown'
    r,g,b=[x/255 for x in rgb]; h,s,v=colorsys.rgb_to_hsv(r,g,b); hue=h*360
    if s<0.13:
        return 'neutral_light' if v>0.72 else ('neutral_dark' if v<0.3 else 'neutral_grey')
    if 15<=hue<=50 and s<0.55:
        return 'wood_light' if v>0.55 else 'wood_dark'
    for name,(lo,hi) in {'terra':(5,30),'yellow':(30,70),'green':(70,165),'cyan':(165,205),
                          'blue':(205,255),'violet':(255,300),'pink':(300,345),'red':(345,365)}.items():
        if lo<=hue<hi or (name=='red' and hue<5): return 'accent_'+name
    return 'accent_other'
def temperature(rgb):
    if rgb is None: return 'mid'
    r,g,b=rgb
    return 'warm' if r>b+10 else ('cold' if b>r+10 else 'mid')
NEUTRALS={'neutral_light','neutral_grey','neutral_dark','wood_light','wood_dark','unknown'}
# дизайнерские акцентные ПАРЫ (60-30-10: два дружащих акцента на сет)
PAIRS=[('terra','green'),('blue','yellow'),('green','yellow'),('terra','cyan'),
       ('pink','green'),('violet','yellow'),('cyan','terra')]
def palette_score(cls1,cls2,pair,set_temp,rgb1):
    s=0.0
    ac={'accent_'+p for p in pair}
    for cls in (cls1,cls2):
        if cls in NEUTRALS: s+=1.0
        elif cls in ac: s+=1.6
        else: s-=2.2          # чужой акцент — главный источник «пестроты»
    if cls1 in ('neutral_light','neutral_grey') and set_temp!='mid':
        t=temperature(rgb1)
        s+= 0.8 if t==set_temp or t=='mid' else -1.2   # тёплые и холодные нейтрали не смешивать
    return s


# ---------- общие чистые функции сборщиков комнат (вынесены из `compose_bedroom.py` без изменений, T-20261105-48) ----------
def num(v):
    try:
        f = float(v)
        return f if f > 0 and math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def side(it: dict, k: str):
    """Сторона товара для полосы: w/d/h, у ковра — длинная (`long`; в фидах `w` бывает короткой)."""
    if k == 'long':
        a, b = num(it.get('w')), num(it.get('d'))
        return max(a, b) if a and b else (a or b)
    return num(it.get(k))


def band_of(slot: dict, tol: tuple) -> dict:
    """Полоса слота: {сторона: [lo, hi]} по `band` и идеалу, допуск tol = (0.8, 1.1)."""
    lo, hi = tol
    return {k: [round(slot['ideal'][k] * lo, 1), round(slot['ideal'][k] * hi, 1)] for k in slot.get('band', [])}


def tier_range(prices: list, q: tuple) -> tuple:
    """Квантили цены тира (как `compose2.tier_band`): q = (низ, верх) доли."""
    ps = sorted(prices)
    if not ps:
        return (0, 10 ** 9)

    def pc(p):
        return ps[max(0, min(len(ps) - 1, int(p * len(ps))))]
    return (pc(q[0]), pc(q[1]))


def dominated(it: dict, cands: list) -> set:
    """Не встал предмет Ш×Г — не встанут и все, что не меньше по обеим сторонам (спальня 2, 13,2 м²: 12 попыток подряд
    на кроватях 220–230 в глубину, ячейка пустела, хотя 213 встаёт). Отсекаем их разом, а не по одной."""
    return {c['sid'] for c in cands if c['w'] >= it['w'] and c['d'] >= it['d']} | {it['sid']}


def palette(items: list) -> None:
    """Цвет по фото (`compose_common`): маленькая картинка в кэш thumbs/, два доминанта и класс — в товар."""
    os.makedirs(THUMBS, exist_ok=True)

    def one(it):
        p = get_thumb(it['img'], it['mid'], it['eid']) if it.get('img') else None
        d1, d2 = dominant2(p) if p else (None, None)
        return it, d1, d2
    with cf.ThreadPoolExecutor(8) as ex:
        for it, d1, d2 in ex.map(one, [i for i in items if 'cls' not in i]):
            it['rgb'], it['cls'], it['cls2'] = (list(d1) if d1 else None), classify(d1), classify(d2)
