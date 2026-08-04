#!/usr/bin/env python3
"""Автосборка сетов гостиной: справка владельца (composition.json) + цвета миниатюр (локально, PIL).
7 метражей × 3 тира = 21 сет. Бесплатно: без внешних API.
Выход: sets.json + preview.html (фото, цены, ссылки)."""
import subprocess, re, io, os, sys, json, math, colorsys, urllib.request, concurrent.futures as cf
from PIL import Image

HERE=os.path.dirname(os.path.abspath(__file__))
THUMBS=os.path.join(HERE,'thumbs'); os.makedirs(THUMBS,exist_ok=True)
COMP=json.load(open(os.path.join(HERE,'composition.json')))
PSQL=["docker","exec","-i","remlab-devdb","psql","-U","remlab","-d","remlab","-q","-v","ON_ERROR_STOP=1","-t","-A","-F","\x1f"]
def rows(q):
    r=subprocess.run(PSQL,input=q,capture_output=True,text=True)
    if r.returncode!=0: print(r.stderr[:400]); sys.exit(1)
    return [l.split('\x1f') for l in r.stdout.strip().split('\n') if l]

STOP=re.compile(r'\b(беж\w*|сер\w*|син\w*|зел[её]н\w*|коричн\w*|ч[её]рн\w*|бел\w*|графит\w*|латте|мокко|изумруд\w*|горчичн\w*|пудр\w*|роз\w*|голуб\w*|фиолет\w*|бордо\w*|венге|дуб\s?\w*|орех\w*|ясень|сонома|капучино|шоколад\w*|молочн\w*|крем\w*|песочн\w*|терракот\w*|оливк\w*|мятн\w*|лаванд\w*|карбон|антрацит|жемчужн\w*|сливов\w*|вельвет\w*|велюр\w*|шенилл\w*|рогожк\w*|экокож\w*|микровелюр\w*|правый|левый|угол|бархат\w*|тёмн\w*|темн\w*|светл\w*|глосс|люкс|найс|плюш\w*)\b', re.I)
def model_key(name):
    n=STOP.sub(' ', name.lower()); n=re.sub(r'[^а-яa-z0-9 ]',' ',n)
    return ' '.join(re.sub(r'\s+',' ',n).strip().split()[:6])

# ---------- цвета (локально) ----------
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
def dominant(p):
    """Доминантный цвет ПРЕДМЕТА при любом фоне (белый, брендовый паттерн...):
    1) фон = доминирующие кластеры по РАМКЕ картинки; 2) вычесть похожие на фон пиксели
    по всей картинке; 3) кластеризовать остаток. Фолбэк — центр-кроп без белого."""
    try:
        im=Image.open(p).convert('RGB'); w,h=im.size
        px=list(im.getdata())
        bw=max(2,int(min(w,h)*0.10))
        border=[px[y*w+x] for y in range(h) for x in range(w)
                if x<bw or x>=w-bw or y<bw or y>=h-bw]
        bq=Image.new('RGB',(len(border),1)); bq.putdata(border)
        bq=bq.quantize(3).convert('RGB')
        bc={}
        for c in bq.getdata(): bc[c]=bc.get(c,0)+1
        bg=[c for c,n in bc.items() if n>=len(border)*0.18]  # фоновые кластеры (до 3)
        def near_bg(c):
            if c[0]>232 and c[1]>232 and c[2]>232: return True
            return any(abs(c[0]-b[0])+abs(c[1]-b[1])+abs(c[2]-b[2])<95 for b in bg)
        inner=[px[y*w+x] for y in range(int(h*.12),int(h*.88)) for x in range(int(w*.12),int(w*.88))]
        obj=[c for c in inner if not near_bg(c)]
        if len(obj)<len(inner)*0.06 or len(obj)<30:  # фон съел всё — фолбэк
            obj=[c for c in inner if not (c[0]>225 and c[1]>225 and c[2]>225)] or inner
        q=Image.new('RGB',(len(obj),1)); q.putdata(obj)
        q=q.quantize(5).convert('RGB')
        counts={}
        for c in q.getdata(): counts[c]=counts.get(c,0)+1
        return max(counts,key=counts.get)
    except Exception: return None
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
NEUTRALS={'neutral_light','neutral_grey','neutral_dark','wood_light','wood_dark','unknown'}
def harmonious(cls, accent):
    return cls in NEUTRALS or cls=='accent_'+accent

# ---------- каталог ----------
ROLES=['диван','кресло','пуф','столик','тв-тумба','комод','стеллаж','витрина','стенка',
 'стол обеденный','стул','камин','кашпо','торшер','ковёр','лампа','люстра','ваза','статуэтка',
 'плед','подушка','растение','зеркало','полка','часы','шторы','бра']
print("Загружаю каталог...",flush=True)
raw=rows("""select role, shop_mid, external_id, name, w_cm, d_cm, len_cm, dia_cm, h_cm,
 price_rub, shop, image_url, replace(replace(replace(substring(url from 'goto=([^&]+)'),'%3A',':'),'%2F','/'),'%3F','?')
 from lr_roles where role is not null and price_rub is not null and image_url is not null order by price_rub""")
cat={}
for r in raw:
    role=r[0]
    if role not in ROLES: continue
    k=(r[10],model_key(r[3]))
    pool=cat.setdefault(role,{})
    if k in pool: continue  # представитель = самый дешёвый (сорт по цене)
    w=float(r[4]) if r[4] else None; d=float(r[5]) if r[5] else (float(r[6]) if r[6] else None)
    dia=float(r[7]) if r[7] else None; h=float(r[8]) if r[8] else None
    fp=None
    if w and d: fp=w*d/10000
    elif dia: fp=math.pi*(dia/200)**2
    elif w and role=='диван': fp=w*1.0/100  # typical глубина 100
    pool[k]=dict(mid=int(r[1]),eid=r[2],name=r[3],w=w,d=d,dia=dia,h=h,fp=fp,
                 price=int(r[9]),shop=r[10],img=r[11],url=r[12])
cat={role:list(p.values()) for role,p in cat.items()}
print({k:len(v) for k,v in sorted(cat.items())},flush=True)
# перцентили цен по роли
import bisect
def tier_band(role,tier):
    ps=sorted(x['price'] for x in cat.get(role,[]))
    if not ps: return (0,10**9)
    def pc(p): return ps[max(0,min(len(ps)-1,int(p*len(ps))))]
    return {'эконом':(pc(.05),pc(.45)),'комфорт':(pc(.35),pc(.80)),'премиум':(pc(.70),pc(.97))}[tier]

def pick(role,m2,share,tier,accent,used_shops,soft=False,qty=1):
    """Кандидат роли: footprint в диапазоне доли, цена в тире, цвет гармоничен."""
    lo,hi=share; plo,phi=tier_band(role,tier)
    tgt_lo,tgt_hi=m2*lo/100/qty, m2*hi/100/qty
    cands=[]
    for it in cat.get(role,[]):
        if it['fp'] is None:
            if role in ('торшер','кашпо','камин') and it['h']: it=dict(it,fp=0.16)
            else: continue
        if not (tgt_lo*0.75<=it['fp']<=tgt_hi*1.25): continue
        if not (plo<=it['price']<=phi) and not soft: continue
        cands.append(it)
    if not cands: return None
    # цвет: качаем миниатюры кандидатов (кэш), классифицируем
    with cf.ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda it: get_thumb(it['img'],it['mid'],it['eid']), cands[:60]))
    best=None;best_s=-1
    for it in cands[:60]:
        p=thumb_path(it['mid'],it['eid'])
        dom=dominant(p) if os.path.exists(p) else None
        cls=classify(dom)
        s=0
        if harmonious(cls,accent): s+=3
        if role in ('диван','стенка','стеллаж','комод','тв-тумба') and cls in NEUTRALS: s+=2
        if role in ('подушка','ваза','плед','кресло') and cls=='accent_'+accent: s+=3
        if it['shop'] in used_shops: s+=1  # стилевая связность магазина
        mid_fp=(tgt_lo+tgt_hi)/2
        s+=max(0,2-abs(it['fp']-mid_fp)/max(mid_fp,.01)*2)
        if s>best_s: best_s=s; best=dict(it,cls=cls,rgb=list(dom) if dom else None)
    return best

ACCENTS=['terra','green','blue','yellow','cyan','pink','violet']
TIERS=['эконом','комфорт','премиум']
QTY={'стул':4,'кресло':1,'подушка':2}
sets=[]
for bi,band in enumerate(COMP['bands']):
    m2=sum(band['m2'])/2
    for ti,tier in enumerate(TIERS):
        accent=ACCENTS[(bi+ti)%len(ACCENTS)]
        chosen={}; used=set(); floor_fp=0
        order=['диван','кресло','стол обеденный','стул','стенка','витрина','стеллаж','комод',
               'тв-тумба','столик','пуф','камин','торшер','кашпо']
        for role in order:
            if role not in band['floor']: continue
            if role=='кресло' and band.get('kreslo_max')==1: q=1
            else: q=QTY.get(role,1)
            it=pick(role,m2,band['floor'][role],tier,accent,used,qty=q)
            if not it: it=pick(role,m2,band['floor'][role],tier,accent,used,soft=True,qty=q)
            if it:
                add=(it['fp'] or 0.16)*q
                if floor_fp+add>m2*COMP['global_floor_cap'][2]/100:
                    continue
                chosen[role]=dict(it,qty=q); used.add(it['shop']); floor_fp+=add
        # добор при пустоте (ниже 28%): большим метражам — второй диван, потом второе кресло
        cap_lo=COMP['global_floor_cap'][0]
        if floor_fp<m2*cap_lo/100:
            if m2>=41 and 'диван' in chosen:
                it2=pick('диван',m2,band['floor']['диван'],tier,accent,used,soft=True)
                if it2 and it2['eid']!=chosen['диван']['eid'] and floor_fp+it2['fp']<=m2*0.40:
                    chosen['диван 2']=dict(it2,qty=1); floor_fp+=it2['fp']
            if floor_fp<m2*cap_lo/100 and 'кресло' in chosen and chosen['кресло']['qty']==1 and not band.get('kreslo_max'):
                chosen['кресло']['qty']=2; floor_fp+=chosen['кресло']['fp']
        # ковёр по % пола
        kv=band.get('kover_pct')
        if kv and cat.get('ковёр'):
            lo,hi=kv; best=None;bs=1e9
            for it in cat['ковёр']:
                if not it['fp'] or 'ассортимент' in it['name'].lower(): continue
                mid=(lo+hi)/2/100*m2
                if abs(it['fp']-mid)<bs: bs=abs(it['fp']-mid); best=it
            if best: chosen['ковёр']=dict(best,qty=1)
        # не-напольные: люстра (диаметр по метражу), плед, подушки, ваза, лампа (если есть комод/тумба)
        dlo,dhi=(45,70) if m2<=20 else ((60,90) if m2<=30 else (60,100))
        lu=[it for it in cat.get('люстра',[]) if it['dia'] and dlo<=it['dia']<=dhi] or cat.get('люстра',[])
        if lu:
            plo,phi=tier_band('люстра',tier)
            lu2=[it for it in lu if plo<=it['price']<=phi] or lu
            chosen['люстра']=dict(lu2[len(lu2)//2],qty=1)
        for role in ('плед','подушка','ваза','лампа','растение'):
            if role=='лампа' and not (chosen.get('комод') or chosen.get('тв-тумба')): continue
            it=pick(role,m2,(0.1,3),tier,accent,used,soft=True,qty=QTY.get(role,1))
            if it: chosen[role]=dict(it,qty=QTY.get(role,1))
        # цвет для предметов, выбранных вне pick (люстра, ковёр, добор)
        for role,it in chosen.items():
            if 'cls' not in it or it.get('rgb') is None:
                p=get_thumb(it['img'],it['mid'],it['eid'])
                dom=dominant(p) if p else None
                it['cls']=classify(dom); it['rgb']=list(dom) if dom else None
        total=sum(it['price']*it['qty'] for it in chosen.values())
        fill=round(floor_fp/m2*100,1)
        sets.append(dict(band=band['band'],m2=m2,tier=tier,accent=accent,fill_pct=fill,
                         total=total,items={r:{k:v for k,v in it.items() if k!='img'} | {'img':it['img']} for r,it in chosen.items()}))
        print(f"{band['band']} м² {tier}: {len(chosen)} предметов, пол {fill}%, итого {total:,} ₽".replace(',',' '),flush=True)
json.dump(sets,open(os.path.join(HERE,'sets.json'),'w'),ensure_ascii=False,indent=1)

# ---------- HTML-превью ----------
def esc(s): return s.replace('&','&amp;').replace('<','&lt;')
H=['<!doctype html><meta charset="utf-8"><title>Сеты гостиной — черновик</title><style>',
'body{font-family:system-ui;margin:20px;background:#faf7f2;color:#222}',
'.set{background:#fff;border:1px solid #ddd;border-radius:12px;padding:16px;margin:18px 0}',
'.items{display:flex;flex-wrap:wrap;gap:10px}',
'.it{width:150px;border:1px solid #eee;border-radius:8px;padding:6px;font-size:11px;background:#fff}',
'.it img{width:100%;height:96px;object-fit:contain;background:#fff}',
'h2{margin:4px 0} .meta{color:#666;font-size:13px} a{color:#b06a4a}',
'.role{font-weight:600;color:#888;text-transform:uppercase;font-size:10px}</style>']
for i,s in enumerate(sets,1):
    H.append(f'<div class=set><h2>Сет {i}: гостиная {s["band"]} м² — {s["tier"].capitalize()}</h2>')
    H.append(f'<div class=meta>акцент: {s["accent"]} · мебель на полу: {s["fill_pct"]}% · итого ≈ {s["total"]:,} ₽</div><div class=items>'.replace(',',' '))
    for role,it in s['items'].items():
        img=it['img'] if not it['img'].startswith('//') else 'https:'+it['img']
        dims=f"{it['w'] or ''}×{it['d'] or it['dia'] or ''}"
        q=f" ×{it['qty']}" if it['qty']>1 else ''
        H.append(f'<div class=it><div class=role>{role}{q}</div><img loading=lazy src="{esc(img)}">'
                 f'<div>{esc(it["name"][:70])}</div><div>{dims} см · <b>{it["price"]:,} ₽</b></div>'.replace(',',' ')
                 +f'<div><a href="{esc(it["url"])}" target=_blank>открыть</a> · {it["shop"]}</div><div style="color:#aaa">{it["mid"]}:{esc(it["eid"])}</div></div>')
    H.append('</div></div>')
open(os.path.join(HERE,'sets-preview.html'),'w').write('\n'.join(H))
print("OK: sets.json + sets-preview.html",flush=True)
