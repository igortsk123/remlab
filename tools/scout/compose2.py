#!/usr/bin/env python3
"""Автосборка сетов v2 — «как дизайнер» (план sets-compose-v2):
Ф0 детерминизм, sets2.json (утверждённый sets.json НЕ трогаем);
Ф1 стиль/дерево/металл из названий; Ф2 палитра v2 (2 кластера, температура, акцентные ПАРЫ);
Ф3 пропорции и капсульные правила; Ф4 CLIP-похожесть к дивану-якорю (fastembed, CPU, кэш);
Ф5 топ-3 кандидата, сводный скор, alternates, лог «почему»; Ф7 чёрный список из sets-feedback.json.
Запуск: ~/venvs/scout/bin/python compose2.py"""
import subprocess, re, io, os, sys, json, math, colorsys, urllib.request, concurrent.futures as cf
import numpy as np
from PIL import Image
from style_tags import tag, style_ok
from item_function import fits_role, subtype
import enrich_bridge as EB   # проверенное моделью обогащение каталога (К2): подтип, стиль, качество
from proportions import P as _PROP, check as prop_check
PROP_RULES={r['id']: r['allowed'] for r in _PROP['rules']}

HERE=os.path.dirname(os.path.abspath(__file__))
THUMBS=os.path.join(HERE,'thumbs'); os.makedirs(THUMBS,exist_ok=True)
COMP=json.load(open(os.path.join(HERE,'composition.json')))
# occupancy-rules р.2: динамические шкалы от площади (решение владельца 2026-08-02)
OCC=json.load(open(os.path.join(HERE,'occupancy.json')))['dynamic'] if os.path.exists(os.path.join(HERE,'occupancy.json')) else None
FB=json.load(open(os.path.join(HERE,'sets-feedback.json'))) if os.path.exists(os.path.join(HERE,'sets-feedback.json')) else {"blacklist":[]}
BLACK={tuple(x) for x in FB.get('blacklist',[])}
# --- Ф2 sets-style-v3: --style → сеты ПОД СТИЛЬ (6 стилей × 3 тира, band 14-16) в sets3.json ---
STYLE_MODE='--style' in sys.argv
SPASS=json.load(open(os.path.join(HERE,'styles.json')))
ROLE_W=SPASS['role_weight']; SNAMES6=list(SPASS['styles'])
SS=json.load(open(os.path.join(HERE,'style-scores.json'))) if os.path.exists(os.path.join(HERE,'style-scores.json')) else {}
if STYLE_MODE and not SS: print("нет style-scores.json — сперва style_score.py"); sys.exit(1)
# акцентная пара под стиль (из дизайнерских гармоний PAIRS ниже)
STYLE_PAIR={'сканди':('terra','green'),'современный':('blue','yellow'),'минимализм':('green','yellow'),
            'лофт':('terra','cyan'),'неоклассика':('blue','yellow'),'джапанди':('terra','green')}
# --- Разнообразие сетов (правило владельца 2026-08-02): пересечение по товарам
# между сетами РАЗНЫХ стилей ≤3, между вариантами ОДНОГО стиля ≤5 (попарно) ---
BUILT=[]  # [(style, {keys}, {major_keys})] — уже собранные сеты этого прогона
# --- Разнообразие v2 (решение владельца 2026-08-07, П2: «чтоб не казалось всё одинаково») ---
# Старое грубое правило «≤5 общих внутри стиля / ≤3 между стилями» УДАЛЕНО. Новая механика:
#  1) «ЛИЦО ≤1»: между сетами РАЗНЫХ стилей — не больше 1 общего предмета «лица» (диван/кресло/
#     столик/стол обеденный). Только для обеспеченных стилей (сканди/современный/минимализм)
#     и только для ролей с ≥100 кандидатов в своём тире — дефицит получает поблажку автоматически.
#  2) «СВЯЗКИ»: повторная ПАРА крупной мебели (тот же диван + то же кресло) между ЛЮБЫМИ двумя
#     сетами запрещена — одинаковость глазом ловится именно по связкам; работает и для
#     дефицитных стилей (лофт/неоклассика/джапанди), где жёсткий лимит порвал бы составы.
# Ёмкость снята 07.08: лофт-кресло 6, неокл-стол 0 … — жёсткость там физически невыполнима.
MAJOR_ROLES={'диван','диван 2','кресло','столик','тв-тумба','стеллаж','витрина','стенка','комод','стол обеденный','камин'}
FACE_ROLES={'диван','диван 2','кресло','столик','стол обеденный'}
ASSURED_STYLES={'сканди','современный','минимализм'}
_TIER_BAND_SQL={'эконом':'p.price_rub<=30000','комфорт':'p.price_rub between 20000 and 90000','премиум':'p.price_rub>=60000'}
RICH={}   # (role,tier) -> кандидатов ≥100
_SLOT_MISS={}   # К5 (slots-everywhere): счётчик отбраковок по конверту слота — отчёт «слот не закрыт»
def _load_rich():
    if RICH or not STYLE_MODE: return
    import subprocess as _sp
    q=("select p.cat_role, "
       +", ".join(f"count(*) filter (where {c})" for c in _TIER_BAND_SQL.values())
       +" from products p join product_enrichment e using (shop_mid, external_id)"
       " where p.cat_role is not null and p.status='active' and p.in_stock"
       " and e.payload is not null and e.quality>=0.65 group by 1;")
    r=_sp.run(PSQL,input=q,capture_output=True,text=True)
    for line in r.stdout.strip().split('\n'):
        f=line.split('\x1f')
        if len(f)>=4:
            for t,cnt in zip(_TIER_BAND_SQL, f[1:4]):
                RICH[(f[0],t)]=int(cnt or 0)>=100
def overlap_ok(cand_key,style,chosen,role=None,tier=None):
    """Разнообразие v2: «лицо ≤1» между стилями (обеспеченные стили и богатые роли) +
    запрет повторных СВЯЗОК крупных пар между любыми сетами. Декор лимитами не душим
    (урок 2026-08-05: жёсткая сумма оставляла сеты без люстры и подушек)."""
    if not STYLE_MODE: return True
    _load_rich()
    cur={emb_key(it['mid'],it['eid']) for it in chosen.values()}
    if cand_key in cur: return True
    cur_major={emb_key(it['mid'],it['eid']) for r,it in chosen.items() if r in MAJOR_ROLES}
    is_face=role in FACE_ROLES
    is_major=role in MAJOR_ROLES
    rich=RICH.get((role or '',tier or ''),False) if role else False
    for st,keys,mkeys in BUILT:
        if cand_key not in keys: continue
        if is_major and cand_key in mkeys and (cur_major & mkeys):
            return False                     # повторная связка крупной пары — одинаковость
        if st!=style and is_face and rich and style in ASSURED_STYLES and cand_key in mkeys \
           and len(cur_major & mkeys)>=1:
            return False                     # «лицо» уже делит >1 предмета с другим стилем
    return True
# --- Ш1 set-quality-fixes: санитайзер габаритов -------------------------------------------
# В фидах оси путаются (кашпо «80x40x50 см» приехало как Ш=40/Г=80) и встречается мусор
# (настольная лампа с глубиной 130 см). Если размеры есть в НАЗВАНИИ — они истина.
_DIM_IN_NAME=re.compile(r'(\d{2,3})\s*[xх*]\s*(\d{2,3})\s*[xх*]\s*(\d{2,3})\s*см', re.I)
# правдоподобие по ролям: (макс. отношение Г/Ш, макс. Г см, макс. Ш см)
_DIM_SANE={'лампа':(1.6,60,40),'ваза':(1.6,45,35),'кашпо':(1.6,60,45),'торшер':(1.6,60,50),
           'подушка':(1.6,80,80),'плед':(2.5,260,260),
           # корпусная мебель: глубина > ширины и > 60 см = перепутанные оси фида
           # (стеллаж «60×128» вставал торцом и ломал правило «спинкой к стене», set84 08.08)
           'стеллаж':(1.0,60,300),'комод':(1.0,60,300),'витрина':(1.0,60,300),
           'шкаф':(1.0,80,350),'стенка':(1.0,60,400),'тв-тумба':(1.0,60,300)}
def sane_dims(role,it):
    """Чинит/бракует габариты. Возвращает False, если товар брать нельзя."""
    m=_DIM_IN_NAME.search(it.get('name') or '')
    if m:
        a,b,c=(float(x) for x in m.groups())      # порядок в названиях РФ: Ш×Г×В
        it['w'],it['d'],it['h']=a,b,c
    rule=_DIM_SANE.get(role)
    if not rule: return True
    ratio,dmax,wmax=rule
    w,d=it.get('w') or 0, it.get('d') or 0
    # декор без габаритов брать нельзя: так в сет попал «Абажур для настольной лампы»
    # (комплектующая, а не светильник) — размеров нет, значит и проверить нечем
    if not w or not d: return False
    # ТОППЕР/ЧЕХОЛ — НЕ ДИВАН (владелец 13.08, set115: «Топпер для дивана» прошёл в
    # роль «диван 2»): аксессуары дивана в посадочные роли не годятся
    if role.startswith('диван') and re.search(r'топпер|чехол|наматрасник', (it.get('name') or '').lower()):
        return False
    if w and d and d>w*ratio and d>w:             # оси перепутаны — меняем местами
        it['w'],it['d']=d,w; w,d=it['w'],it['d']
    if (d and d>dmax) or (w and w>wmax): return False
    return True

# --- room-size-fit Ф2: жёсткий размер-гейт по ширине роли в метраже (size-bands.json) ---
SIZEB=json.load(open(os.path.join(HERE,'size-bands.json')))['bands']
def size_gate(band_name,role,w):
    rng=SIZEB.get(band_name,{}).get(role)
    if not rng or rng==[0,0] or not w: return True   # нет правила/размера — не гейтим
    return rng[0]<=w<=rng[1]
PSQL=["docker","exec","-i","remlab-devdb","psql","-U","remlab","-d","remlab","-q","-v","ON_ERROR_STOP=1","-t","-A","-F","\x1f"]
def rows(q):
    r=subprocess.run(PSQL,input=q,capture_output=True,text=True)
    if r.returncode!=0: print(r.stderr[:400]); sys.exit(1)
    return [l.split('\x1f') for l in r.stdout.strip().split('\n') if l]

STOP=re.compile(r'\b(беж\w*|сер\w*|син\w*|зел[её]н\w*|коричн\w*|ч[её]рн\w*|бел\w*|графит\w*|латте|мокко|изумруд\w*|горчичн\w*|пудр\w*|роз\w*|голуб\w*|фиолет\w*|бордо\w*|венге|дуб\s?\w*|орех\w*|ясень|сонома|капучино|шоколад\w*|молочн\w*|крем\w*|песочн\w*|терракот\w*|оливк\w*|мятн\w*|лаванд\w*|карбон|антрацит|жемчужн\w*|сливов\w*|вельвет\w*|велюр\w*|шенилл\w*|рогожк\w*|экокож\w*|микровелюр\w*|правый|левый|угол|бархат\w*|тёмн\w*|темн\w*|светл\w*|глосс|люкс|найс|плюш\w*)\b', re.I)
def model_key(name):
    n=STOP.sub(' ', name.lower()); n=re.sub(r'[^а-яa-z0-9 ]',' ',n)
    return ' '.join(re.sub(r'\s+',' ',n).strip().split()[:6])

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

# ---------- Ф4: CLIP-похожесть (fastembed, кэш) ----------
EMB_PATH=os.path.join(HERE,'embeddings.npz')
_emb={}; _model=[None]
if os.path.exists(EMB_PATH):
    z=np.load(EMB_PATH)
    _emb={k:z[k] for k in z.files}
def emb_key(mid,eid): return f"{mid}-{re.sub(r'[^A-Za-z0-9]','_',eid)[:40]}"
def embed_batch(items):
    todo=[(emb_key(it['mid'],it['eid']),thumb_path(it['mid'],it['eid'])) for it in items]
    todo=[(k,p) for k,p in todo if k not in _emb and os.path.exists(p)]
    if not todo: return
    if _model[0] is None:
        from fastembed import ImageEmbedding
        # кэш на ДИСК: дефолт /tmp — tmpfs 788M, модель не помещается (quota exceeded)
        _model[0]=ImageEmbedding('Qdrant/clip-ViT-B-32-vision',cache_dir=os.path.expanduser('~/.cache/fastembed'))
    vecs=list(_model[0].embed([p for _,p in todo],batch_size=16))
    for (k,_),v in zip(todo,vecs):
        v=np.asarray(v,dtype=np.float32); v/=(np.linalg.norm(v)+1e-8)
        _emb[k]=v.astype(np.float16)
def cos(a_key,b_key):
    a=_emb.get(a_key); b=_emb.get(b_key)
    if a is None or b is None: return None
    return float(np.dot(a.astype(np.float32),b.astype(np.float32)))

# ---------- каталог ----------
import footprint as _fp   # одно правило «размер известен» для сборки/лечения/экспорта/сцены (Р1)
_no_fp={}
ROLES=['диван','кресло','пуф','столик','тв-тумба','комод','стеллаж','витрина','стенка',
 'стол обеденный','стул','камин','кашпо','торшер','ковёр','лампа','люстра','ваза','статуэтка',
 'плед','подушка','растение','зеркало','полка','часы','шторы','бра']
print("Загружаю каталог...",flush=True)
# Роль — из КАТЕГОРИИ ФИДА (`products.cat_role`, см. category_map.py). Регекс по названию
# заводил в комплект карнизы вместо штор и садовые вазоны вместо кашпо (владелец, 2026-08-06).
raw=rows("""select p.cat_role, p.shop_mid, p.external_id, p.name, p.w_cm, p.d_cm, p.len_cm, p.dia_cm, p.h_cm,
 p.price_rub, p.shop, p.image_url,
 coalesce(p.direct_url, replace(replace(replace(substring(p.url from 'goto=([^&]+)'),'%3A',':'),'%2F','/'),'%3F','?')),
 coalesce(p.params->>'Материал','')||' '||coalesce(p.params->>'Назначение','')||' '||coalesce(p.params->>'Тип','')
 from products p
 where p.cat_role is not null and p.price_rub is not null and p.image_url is not null and p.in_stock
 order by p.price_rub, p.shop_mid, p.external_id""")
assert len(raw)>1000, f"каталог-запрос вернул {len(raw)} строк — SQL сломан, СТОП (не собирать пустые сеты)"

# Freshness SLA (T0 truth-first): магазины с ПРОТУХШИМ/битым фидом (feed_guard) не участвуют
# в сборке НОВЫХ сетов — цены/наличие недельной давности хуже дыры. Heal существующих сетов
# это не трогает (sets_incremental работает по своим правилам).
try:
    _fresh=json.load(open(os.path.join(HERE,'feed-freshness.json')))
    _stale_mids={int(m) for rec in _fresh.values()
                 if rec.get('state') in ('stale','broken') for m in rec.get('mids',[])}
    # Q5 (Codex 16.08, fail-closed для НОВЫХ pod-комплектов): у broken/stale-фида и «карантин
    # отложен» (mids_quarantine_pending, решение владельца) — SKU в pod не берём вовсе: комплект
    # либо из живого фида, либо честный gap. Общий пул (остальные роли) карантин не трогает.
    _pod_banned_mids={int(m) for rec in _fresh.values()
                      if rec.get('state') in ('stale','broken')
                      for m in list(rec.get('mids',[]))+list(rec.get('mids_quarantine_pending',[]))}
except Exception:
    _stale_mids=set(); _pod_banned_mids=set()
if _stale_mids:
    _before=len(raw)
    raw=[r for r in raw if int(r[1]) not in _stale_mids]
    print(f'freshness: исключены протухшие фиды mid={sorted(_stale_mids)} '
          f'(−{_before-len(raw)} офферов из пула сборки)')


# СИСТЕМНЫЙ фильтр пригодности для жилой гостиной (правило владельца: решения — на масштаб,
# не «для 1 ситуации»): недопустимые материалы/назначения по классам ролей, из params фида
UNFIT_ANY=re.compile(r'автомобильн|для ванн|банн|садов|уличн|для рассады|теплиц|туристич|детск сад',re.I)
UNFIT_BY_CLASS={
 ('ковёр','плед','подушка'): re.compile(r'каучук|эва|пвх|резин|силикон|грязезащит|противоскольз',re.I),
 ('кашпо','ваза'):           re.compile(r'для рассады|торфян|вазон|flower|чаша|горшечн|подвесн|ампельн|цеп|балконн',re.I),
 ('стул','кресло'):          re.compile(r'компьютерн|офисн|геймерск|игров|руководител|оператор|барн',re.I),
}
def unfit(role,name,mat,h=None,dia=None):
    txt=(name or '')+' '+(mat or '')
    if UNFIT_ANY.search(txt): return True
    for roles,rx in UNFIT_BY_CLASS.items():
        if role in roles and rx.search(txt): return True
    if role=='кашпо' and (h or dia) and (h or 0)<30 and (dia or 0)<30:
        return True  # напольное кашпо ≥30 см высоты или диаметра; мелочь = подвесное/настольное
    if role=='стул' and (h or 0)>110:
        return True  # спинка обеденного стула ≤110 см; выше — офисное/компьютерное кресло
    return False
cat={}
for r in raw:
    role=r[0]
    if role not in ROLES: continue
    if (int(r[1]),r[2]) in BLACK: continue
    if unfit(role,r[3],r[13] if len(r)>13 else '', float(r[8]) if r[8] else None, float(r[7]) if r[7] else None): continue
    k=(r[10],model_key(r[3]))
    pool=cat.setdefault(role,{})
    if k in pool: continue
    # РАЗМЕР НЕ ПРИДУМЫВАЕМ (владелец 03.09, план stock-and-dims-honesty Р1): глубина — только каталожная
    # `d_cm` (для tvoydom это переименованная «Длина», см. dim_resolver), диаметр — только `dia_cm`.
    # Раньше `len_cm` подставлялся вместо глубины, дивану без глубины считалась площадь как при 100 см,
    # торшеру/кашпо/камину — 0,16 м². Напольный предмет без footprint в пул НЕ попадает (см. ниже).
    w=float(r[4]) if r[4] else None; d=float(r[5]) if r[5] else None
    dia=float(r[7]) if r[7] else None; h=float(r[8]) if r[8] else None
    fp=_fp.footprint_m2({'w':w,'d':d,'dia':dia})
    if fp is None and _fp.is_floor(role):
        _no_fp[role]=_no_fp.get(role,0)+1
        continue
    pool[k]=dict(mid=int(r[1]),eid=r[2],name=r[3],w=w,d=d,dia=dia,h=h,fp=fp,
                 price=int(r[9]),shop=r[10],img=r[11],url=r[12],**tag(r[3]))
cat={role:list(p.values()) for role,p in cat.items()}
if _no_fp:
    print('[pool] напольные без размера (в расстановку не берём, витрина покажет «размеры не указаны магазином»): '
          + ', '.join(f'{r} {n}' for r,n in sorted(_no_fp.items(), key=lambda kv:-kv[1])), flush=True)
# Q6a свода №13: ПЛАНИРОВОЧНЫЙ СЛОТ «банкетка» — не роль каталога (cat_role не меняется), а SKU с
# capability wall_seat_capable (`capabilities.py --export` → capabilities-index.json: банкетки/кушетки из
# ролей пуф/диван). В сет такой SKU кладётся НЕ голым алиасом: с source_role/planning_role/caps_used/
# cap_rules_version (контракт Q6b edge_nook; Codex 17.08). Слот пуст, пока паспорт (Q6b/c) его не требует.
try:
    _capidx=json.load(open(os.path.join(HERE,'capabilities-index.json'),encoding='utf-8')).get('roles',{})
    _by_key={(it['mid'],it['eid']):it for role in ('пуф','диван') for it in cat.get(role,[])}
    _bench=[]
    for rec in _capidx.get('банкетка',[]):
        it=_by_key.get((rec['mid'],rec['eid']))
        if it is None: continue
        _bench.append(dict(it,source_role=rec['source_role'],planning_role='банкетка',
                           caps_used=rec.get('caps_used') or {},cap_rules_version=rec.get('cap_rules_version')))
    if _bench: cat['банкетка']=_bench
except Exception as _e:
    print(f'capabilities-index не прочитан ({_e}) — слот «банкетка» пуст')
print({k:len(v) for k,v in sorted(cat.items())},flush=True)
import bisect
def tier_band(role,tier):
    ps=sorted(x['price'] for x in cat.get(role,[]))
    if not ps: return (0,10**9)
    def pc(p): return ps[max(0,min(len(ps)-1,int(p*len(ps))))]
    return {'эконом':(pc(.05),pc(.45)),'комфорт':(pc(.35),pc(.80)),'премиум':(pc(.70),pc(.97))}[tier]

# ---------- Ф1+Ф2+Ф3+Ф4+Ф5: скоринг ----------
_ZR_PATH=os.path.join(HERE,'..','..','services','planner-solver','rules','zones.json')
try:
    _SLOT_ENV=json.load(open(_ZR_PATH)).get('template_slot_envelopes',{})
except Exception:
    _SLOT_ENV={}


def slot_ideal(role,m2,qty=1):
    """Идеальная ширина слота под каталог (решение владельца 11.08): подгоняем
    ИДЕАЛ под плотность фидов, не нарушая правил дизайна. Конфиг — zones.json
    `template_slot_envelopes` (тот же источник, что у шаблонов и проверки покрытия
    tools/scout/template_coverage.py). None — правило для роли не задано."""
    cfg=(_SLOT_ENV.get('slots') or {}).get(role)
    if not cfg: return None
    if 'ideal' in cfg: return float(cfg['ideal'])
    if 'by_seats' in cfg:                      # обеденный стол: 61 см кромки на едока
        seats='6' if m2>=40 else ('4' if m2>=22 else '2')
        return float(cfg['by_seats'][seats])
    if 'by_area_m2' in cfg:
        # ОБОБЩЁННЫЙ парсер ключей (13.08: фиксированный список ключей молча ронял
        # слот дивана '<=16'/'<=20' в ветку 230 — диван 230 проходил в комнату 15 м²)
        ba=cfg['by_area_m2']
        _les=sorted(((float(k[2:]),k) for k in ba if k.startswith('<=')))
        for lim,k in _les:
            if m2<=lim: return float(ba[k])
        _gts=sorted(((float(k[1:]),k) for k in ba if k.startswith('>')),reverse=True)
        for lim,k in _gts:
            if m2>lim: return float(ba[k])
    return None


def pick2(role,m2,share,tier,pair,ctx,soft=False,qty=1,color_goal=None,topn=3,pre_filter=None,no_envelope=False,no_prop=False):
    """ctx: dict(style, wood, metal, fabrics, temp, sofa_key, sofa_w, sofa_h, used_shops).
    Возвращает список топ-N кандидатов с why."""
    lo,hi=share; plo,phi=tier_band(role,tier)
    # H0 (корень «в больших комнатах меньше мебели», 08.08): доля роли — от площади ЗОНЫ
    # (кап 30 м² = потолок одной зоны по канону), не всей комнаты: 57 м² требовали стол
    # 1.7–5.8 м² и кресло 2.6–7 м² — таких SKU нет, роли отсеивались «0 кандидатов».
    # Рост метража даёт БОЛЬШЕ предметов/зон, а не мебель-гигантов (2modern/minimalistliving).
    zone_m2=min(m2, 30.0)
    tgt_lo,tgt_hi=zone_m2*lo/100/qty, zone_m2*hi/100/qty
    def _collect(gate):
        cs=[]
        for it in cat.get(role,[]):
            if it['fp'] is None:
                # напольным без footprint здесь уже не бывает (отсечены при загрузке пула, Р1);
                # T5 truth-first: шторы — не напольная роль, footprint им не положен вовсе
                # (WINDOW-слой онтологии). Требования: полотно до пола (h≥250) и ткань
                # ≥250 см (комплект «2 шт» = 2×w) — покрыть окно 120-180 + сборка.
                # Раньше отсутствие fp выкидывало ВСЕ шторы → дыра 126/126 (аудит рефери §14).
                if role=='шторы' and it['h'] and it['w']:
                    cloth=it['w']*(2 if re.search(r'2\s*шт',it['name'],re.I) else 1)
                    if it['h']>=250 and cloth>=250: it=dict(it,fp=0.0)
                    else: continue
                else: continue
            if not sane_dims(role,it): continue        # мусорные/перепутанные габариты — мимо
            if pre_filter is not None and not pre_filter(it): continue   # Q5: доп. ворота слота (pod)
            if gate and not size_gate(ctx.get('band',''),role,it['w']): continue  # legacy-ветка (не зовётся)
            if role!='шторы' and not (tgt_lo*0.75<=it['fp']<=tgt_hi*1.25): continue  # шторы: fp=0, целевая доля не применима
            # КОНВЕРТ СЛОТА — ЖЁСТКИЙ ФИЛЬТР ДЛЯ ВСЕХ СЛОТОВ (ADR template-integrity,
            # 12.08). Допуск −20/+10 применяется ЗДЕСЬ, при подборе товара в сет, и
            # больше нигде: солверу менять габарит SKU запрещено. Мягкого бонуса в
            # скоринге не хватало — в 15 м² попадал ковёр 290x200 (39% пола).
            # ФОТО ОБЯЗАТЕЛЬНО (владелец 26.08): товар без живого изображения в сет не берём —
            # в витрине это пустая карточка. Живость проверяется кэшем img_alive (раз в 14 дней).
            if not it.get('img'):
                _SLOT_MISS.setdefault(role,0); _SLOT_MISS[role]+=1
                continue
            try:
                from img_alive import alive as _ia
                if not _ia(it.get('img')):
                    _SLOT_MISS.setdefault(role,0); _SLOT_MISS[role]+=1
                    continue
            except Exception:
                pass
            # ПРИГОДНОСТЬ ФОТО — здесь, а не только при ночном лечении. Раньше первичная сборка
            # шла мимо ворот `_slot_ok`, и любое новое правило («коллажи в сеты не пускать»)
            # срабатывало задним числом: товар сперва вставал в сет, потом его выносило лечение.
            # Владелец 28.08: «на этапе выбора сетов проверку добавь».
            try:
                from slot_contract import mesh_ok as _mesh_ok, photo_ok as _photo_ok
                if not _photo_ok(f"{it['mid']}:{it['eid']}", context='new'):
                    _SLOT_MISS.setdefault(role,0); _SLOT_MISS[role]+=1
                    continue
                # Готовность представления (Codex P0-4): без этой проверки MESH_GATE_PHASE=hard_new
                # ничего не делал в ПЕРВИЧНОЙ сборке — гейт жил только в лечении.
                if not _mesh_ok(f"{it['mid']}:{it['eid']}"):
                    _SLOT_MISS.setdefault(role,0); _SLOT_MISS[role]+=1
                    continue
            except Exception:
                pass
            # АБСОЛЮТНЫЙ минимум главного дивана (26.08, Codex): детская/подростковая мягкая
            # мебель просачивается в общую категорию по имени без слова «детский» (диван «Умка»
            # 110 см в комнате 15 м²). Ловим размером — zones.json → slots.диван.abs_min_cm
            if role in ('диван','диван 2'):
                _abs=float(((_SLOT_ENV.get('slots') or {}).get('диван') or {}).get('abs_min_cm') or 0)
                if _abs and (it.get('w') or 0) < _abs:
                    _SLOT_MISS.setdefault(role,0); _SLOT_MISS[role]+=1
                    continue
            _id=None if no_envelope else slot_ideal(role,m2)   # Q5: pod-слоты (столик 2) — вне конверта главного слота
            if _id:
                _tol=_SLOT_ENV.get('tolerance',[0.80,1.10])
                _len=(max(it.get('w') or 0, it.get('d') or 0) if role=='ковёр'
                      else (it.get('w') or 0))
                if _len and not (_id*_tol[0]<=_len<=_id*_tol[1]):
                    _SLOT_MISS.setdefault(role,0); _SLOT_MISS[role]+=1
                    continue
            if not (plo<=it['price']<=phi) and not soft: continue
            # ЖЁСТКИЕ ОГРАНИЧЕНИЯ ДО ЭСТЕТИКИ (sets-feasibility-first, 2026-08-05).
            # 0) карточка должна быть годной: обогащение К2 отбраковывает мусорные размеры и
            #    карточки, где текст сам себе противоречит. Товара без обогащения это не касается.
            if not EB.quality_ok(it['mid'], it['eid']):
                continue
            # 1) товар должен подходить роли ПО ФУНКЦИИ: банкетка — не пуф, кресло-мешок — не пуф.
            #    Подтип из обогащения точнее регекса по названию; нет обогащения — старая эвристика.
            _sub_e = EB.subtype_ok(role, it['mid'], it['eid'])
            if _sub_e is False:
                continue
            fit_ok, _sub = fits_role(role, it)
            if not fit_ok and _sub_e is not True:
                continue
            # 2) пропорции относительно уже выбранных предметов: вне допустимых рамок — выбываем,
            #    сколько бы баллов ни давали цвет и стиль.
            _pctx = {'chosen': ctx.get('chosen_ref') or {}, 'wall': ctx.get('wall_len_cm'),
                     'corner_sofa': ctx.get('corner_sofa', False)}
            prop_ok, _bonus, _notes = (True, 0.0, []) if no_prop else prop_check(role, it, _pctx, _sub)
            if not prop_ok:
                continue
            if not overlap_ok(emb_key(it['mid'],it['eid']),ctx.get('style_name'),ctx.get('chosen_ref',{}),role=role,tier=tier): continue
            cs.append(it)
        return cs
    # W3 (аудит 08.08): размерная вилка band'а — ПРИОРИТЕТ, не жёсткий отсев SKU:
    # in-band сортируются первыми (и получат бонус в скоре), out-of-band живут со штрафом —
    # жёсткое выбывание оставлено только функции/пропорциям/качеству карточки (выше).
    cands=_collect(False); relaxed=False
    if not cands: return []
    _inb=lambda it: size_gate(ctx.get('band',''),role,it['w'])
    cands=sorted(cands,key=lambda it: 0 if _inb(it) else 1)[:70]
    with cf.ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda it: get_thumb(it['img'],it['mid'],it['eid']), cands))
    embed_batch(cands)
    scored=[]
    for it in cands:
        p=thumb_path(it['mid'],it['eid'])
        d1,d2=dominant2(p) if os.path.exists(p) else (None,None)
        cls1,cls2=classify(d1),classify(d2)
        why=[]
        s=palette_score(cls1,cls2,pair,ctx['temp'],d1); why.append(f"палитра{s:+.1f}")
        _ideal=slot_ideal(role,m2,qty)
        if _ideal:
            _tol=_SLOT_ENV.get('tolerance',[0.80,1.10])
            _w=max(it['w'] or 0, it['d'] or 0) if role=='ковёр' else (it['w'] or 0)
            if _w and _ideal*_tol[0]<=_w<=_ideal*_tol[1]:
                s+=1.2; why.append("в конверте слота+1.2")
        # M-A2 (свод №5): ВИЗУАЛЬНАЯ МАССА в тесных комнатах — при дефиците площади
        # предпочесть лёгкие предметы (данные обогащения: visual_mass/ножки/подлокотники)
        if m2<=18 and role in ('диван','кресло'):
            _enr=EB.get(it['mid'],it['eid']) or {}
            _vm=_enr.get('mass'); _legs=(_enr.get('specific') or {}).get('legs') or (_enr.get('photo') or {}).get('legs')
            if _vm=='лёгкая': s+=1.2; why.append("масса лёгкая+1.2")
            elif _vm=='тяжёлая': s-=1.0; why.append("масса тяжёлая-1.0")
            if str(_legs) in ('тонкий_металл','конические_деревянные','прямые_деревянные','точёные'): s+=0.6; why.append("на ножках+0.6")
        # M-A1 (свод №5): эффективность посадки — при равных местах меньший футпринт лучше
        if role=='диван' and (it.get('w') or 0):
            _seats_est=max(2,round((it['w'] or 0)/62))     # ~62 см на место (KB)
            _eff=_seats_est/max(it.get('fp') or 1.5, 0.5)
            s+=min(1.0,_eff*0.35); why.append(f"эфф.посадки+{min(1.0,_eff*0.35):.1f}")
        # M-A3 (свод №5, Livingetc): при вероятном конфликте траекторий круглый/овальный
        # столик предпочтительнее прямоугольного (нет углов в проходе)
        if m2<=18 and role=='столик' and (( (EB.get(it['mid'],it['eid']) or {}).get('specific') or {}).get('body')):
            s+=0.5; why.append("столик-хранение+0.5")   # A4 (свод №5): мультифункция прежде нового предмета
        if m2<=18 and role=='столик' and re.search(r'кругл|овал', (it.get('name') or '').lower()):
            s+=0.8; why.append("округлый+0.8")
        # S5 (small-свод §16): вертикальный бонус хранения — высокий узкий лучше
        # низкого широкого при равном объёме (вертикаль экономит стену)
        if role in ('стеллаж','витрина') and (it.get('h') or 0)>=180 and (it.get('w') or 99)<=90:
            s+=1.0; why.append("вертикаль+1.0")
        if color_goal:  # напр. вторая подушка обязана быть акцентной
            if cls1==color_goal or cls2==color_goal: s+=2.5; why.append("цель-цвет+2.5")
            else: s-=2.0
        # Ф1: стиль/дерево/металл
        st=it.get('style')
        if st and ctx['style']:
            if st==ctx['style']: s+=2.0; why.append(f"стиль {st}+2")
            elif style_ok(st,ctx['style']): s+=0.8; why.append(f"стиль совм.+0.8")
            else: s-=3.0; why.append(f"стиль {st} конфликт-3")
        wd=it.get('wood')
        if wd and ctx['wood']:
            if wd==ctx['wood']: s+=1.5; why.append(f"дерево {wd}+1.5")
            else: s-=2.5; why.append(f"дерево {wd}≠{ctx['wood']}-2.5")
        mt=it.get('metal')
        if mt and ctx['metal']:
            if mt==ctx['metal']: s+=1.2; why.append(f"металл {mt}+1.2")
            else: s-=2.0; why.append(f"металл {mt}≠{ctx['metal']}-2")
        fb=it.get('fabric')
        if fb and fb in ctx['fabrics']: s+=1.5; why.append(f"фактура {fb} повтор+1.5")
        # Ф2 v3: стиль-фит — ПЕРВЫМ идёт обогащение (attrs, ADR-0071): полное покрытие пула,
        # признаки с фото, честный «нейтральный». Старый style-scores.json — текстовый (16%
        # совпадения с фото), заморожен (style_score.py убран из крона 06.08) — только фолбэк.
        # Прежний обратный порядок опирался на замер 05.08, сделанный ДО vision-прогона.
        if ctx.get('style_name'):
            sf=EB.style_scores(it['mid'],it['eid']) or SS.get(emb_key(it['mid'],it['eid']))
            if sf:
                wgt=ROLE_W.get(role,0.4)
                if sf.get('universal'): s+=0.3; why.append("нейтрал+0.3")
                else:
                    f_=sf[ctx['style_name']]
                    s+=(f_-5)*0.9*wgt; why.append(f"стиль-фит {f_}·w{wgt}")
                    if f_<3.5 and wgt>=0.5: s-=3.0  # явный чужак на крупной роли
        # Ф3: пропорции — теперь ТОЛЬКО бонус за попадание в предпочтительный диапазон;
        # всё, что вне допустимого, уже отсеяно фильтром выше и сюда не доходит
        _pctx={'chosen': ctx.get('chosen_ref') or {}, 'wall': ctx.get('wall_len_cm'),
               'corner_sofa': ctx.get('corner_sofa', False)}
        _ok,_pb,_pn = prop_check(role,it,_pctx, subtype(role,it))
        if _pb: s+=_pb; why.append('пропорции+%.1f'%_pb)
        # W3: размер вне вилки метража — штраф вместо выбывания (band-вилка = приор)
        if not size_gate(ctx.get('band',''),role,it['w']):
            s-=1.5; why.append('размер-вне-вилки-1.5')
        if role=='торшер' and it['h']:
            s+= 1.0 if it['h']>=140 else -1.0
        # Ф4: визуальная похожесть на диван-якорь
        if ctx.get('sofa_key') and role!='диван':
            c=cos(emb_key(it['mid'],it['eid']),ctx['sofa_key'])
            if c is not None:
                s+=max(0.0,(c-0.5))*6; why.append(f"похожесть {c:.2f}")
        if it['shop'] in ctx['used_shops']: s+=0.7
        mid_fp=(tgt_lo+tgt_hi)/2
        s+=max(0,2-abs(it['fp']-mid_fp)/max(mid_fp,.01)*2)
        scored.append((s,dict(it,cls=cls1,cls2=cls2,rgb=list(d1) if d1 else None,
                              why="; ".join(why))))
    scored.sort(key=lambda x:(-x[0],x[1]['price']))
    return [dict(it,score=round(s,2),**({'size_relaxed':True} if relaxed else {})) for s,it in scored[:topn]]

TIERS=['эконом','комфорт','премиум']
QTY={'стул':4,'кресло':1}
STYLE_OF={}
if STYLE_MODE:  # псевдо-бэнды (метраж × стиль); по умолчанию band 14-16, --bands all → все 7 (room-size-fit Ф3)
    src=COMP['bands'] if ('--bands' in sys.argv and sys.argv[sys.argv.index('--bands')+1]=='all') else COMP['bands'][:1]
    runs=[(dict(b),st) for b in src for st in SNAMES6]
    COMP['bands']=[b for b,_ in runs]
    STYLE_OF={i:st for i,(_,st) in enumerate(runs)}
# ТЕСТОВЫЙ РЕЖИМ (владелец 07.08, «чтоб быстрее пока тестим»): SETS_ONLY="3,17,…" — пересборка
# только этих номеров, остальные КОПИРУЮТСЯ из прежнего sets3.json и честно участвуют в реестре
# разнообразия. По умолчанию (без env) — все сеты, это боевой режим.
from testmode import only as _tm_only
_ONLY=_tm_only()
_PREV=None
if _ONLY and STYLE_MODE and os.path.exists(os.path.join(HERE,'sets3.json')):
    _PREV=json.load(open(os.path.join(HERE,'sets3.json')))
    print(f'тестовый режим: пересобираю только {sorted(_ONLY)}, остальные {len(_PREV)-len(_ONLY)} — из прежнего файла')
# --- Z4 (MASTER-zones-first): состав из ШАБЛОНОВ ПОСАДОЧНЫХ ГРУПП (rules/zones.json) ---
# Группа выбирается по ПОЛЕЗНОЙ площади (usable = комната − swing двери − радиаторы − входной
# резерв; честный расчёт планнером, фолбэк 0.72·m2) и ротируется между сетами band'а —
# «не максимизировать посадку» (документ владельца) + разные лица групп между стилями.
_ZONES=json.load(open(os.path.join(HERE,'..','..','services','planner-solver','rules','zones.json')))
_TPL=json.load(open(os.path.join(HERE,'..','..','services','planner-solver','rules','templates.json')))
_TPL_ROLES=_TPL.get('floor_roles_claimable') or {}
# напольные роли, которые вообще участвуют в расстановке (декор на поверхностях,
# текстиль и свет в смете есть, но их ставит не схема)
_FLOOR_ROLES_ALL={'диван','диван 2','кресло','кресло 2','кресло 3','кресло 4','столик',
                  'приставной','ковёр','пуф','пуф 2','торшер','торшер 2','тв-тумба','стенка',
                  'стеллаж','стеллаж 2','витрина','комод','комод 2','шкаф','камин','кашпо',
                  'кашпо 2','стол обеденный','стул','стул 2','стул 3','стул 4','стул 5','стул 6'}
_ZGROUPS={g['id']:g for g in _ZONES['seating_groups']}
_ZBANDS=_ZONES['inventory_prior']['bands_usable_m2']
def _usable_m2(m2):
    try:
        sys.path.insert(0,os.path.join(HERE,'..','..','services','planner-solver'))
        from planner.models import Opening as _O, Radiator as _R, Room as _Rm
        from planner.zones import usable_m2 as _um
        W=int((m2*10000/1.15)**0.5//5*5); D=int(m2*10000/W//5*5)
        room=_Rm(width_cm=W,depth_cm=D,band='17-20',
                 openings=[_O(kind='door',wall='south',offset_cm=40,width_cm=90,swing_cm=92),
                           _O(kind='window',wall='east',offset_cm=int(D*0.3),width_cm=140,sill_cm=80)],
                 radiators=[_R(wall='east',offset_cm=int(D*0.3),width_cm=140,depth_cm=15)])
        return _um(room)
    except Exception as e:
        print(f'  Z4: планнер недоступен ({e}) — usable ≈ 0.72·m2')
        return m2*0.72
def _zone_group(m2,seq,kreslo_max=None):
    um=_usable_m2(m2)
    zb=next(b for b in _ZBANDS if um<=b['max'])
    def _ok(gid):
        g=_ZGROUPS[gid]
        req=g['roles']['required']
        # группа обязана быть ВЫПОЛНИМОЙ: kreslo_max=1 band'а несовместим с «кресло 2»
        if kreslo_max==1 and 'кресло 2' in req: return False
        need={r.split(' ')[0] for r in req}
        return all(cat.get(r) for r in need)
    avail=[gid for gid in zb['groups'] if _ok(gid)] or ['sofa_armchair']
    # D5b (вердикт владельца 50+): дефицит не молчит — если самая вместительная группа band'а
    # отпала из-за отсутствия роли в каталоге, логируем причину (иначе «почему один диван?»
    # невозможно диагностировать по сету)
    lost=[gid for gid in zb['groups'] if gid not in avail]
    if lost and _ZGROUPS[zb['groups'][0]]['seats']>_ZGROUPS[avail[0]]['seats']:
        _miss={r.split(' ')[0] for gid in lost for r in _ZGROUPS[gid]['roles']['required']
               if not cat.get(r.split(' ')[0])}
        print(f"  D5: группы {lost} недоступны (нет ролей {sorted(_miss)}) — band {zb.get('max')} м² собирается меньшей группой")
    return _ZGROUPS[avail[seq%len(avail)]],zb,um
sets=[]
for bi,band in enumerate(COMP['bands']):
    m2=sum(band['m2'])/2
    style_name=STYLE_OF.get(bi) if STYLE_MODE else None
    for ti,tier in enumerate(TIERS):
        _set_no=len(sets)+1
        if _ONLY is not None and _PREV and _set_no<=len(_PREV) and _set_no not in _ONLY:
            _p=_PREV[_set_no-1]
            sets.append(_p)
            if STYLE_MODE:
                BUILT.append((_p.get('style'),
                              {emb_key(it['mid'],it['eid']) for it in _p['items'].values()},
                              {emb_key(it['mid'],it['eid']) for r,it in _p['items'].items() if r in MAJOR_ROLES}))
            continue
        pair=STYLE_PAIR[style_name] if style_name else PAIRS[(bi+ti)%len(PAIRS)]
        ctx=dict(style=style_name,wood=None,metal=None,fabrics=set(),temp='mid',
                 sofa_key=None,sofa_w=None,sofa_h=None,used_shops=set(),style_name=style_name,
                 band=band['band'])
        # Z4: посадочная группа этого сета (ротация по индексу band+tier)
        zgroup,zband,z_usable=_zone_group(m2,bi+ti,band.get('kreslo_max'))
        _zreq={}; _zopt=set()
        for _r in zgroup['roles']['required']:
            _b=_r.split(' ')[0]; _zreq[_b]=_zreq.get(_b,0)+1
        for _r in zgroup['roles'].get('optional',[]):
            _zopt.add(_r.split(' ')[0])
        print(f"  Z4: группа {zgroup['id']} (мест {zgroup['seats']}, usable {z_usable:.1f} м²)")
        _extras_left=int(zband.get('extras_max',3))
        _EXTRA_ROLES={'пуф','торшер','кашпо'}
        chosen={}; alts={}; floor_fp=0; wall_len=0.0
        # свободный периметр комнаты этого метража (минус дверь+окно ≈230 см) — под кап
        # «суммарная ширина пристенной мебели ≤ доли периметра» (решение владельца 2026-08-03)
        _W=int((m2*10000/1.15)**0.5//5*5); _D=int(m2*10000/_W//5*5)
        free_perimeter=2*(_W+_D)-230
        WALL_ROLES=('стенка','шкаф','комод','витрина','стеллаж','тв-тумба','камин')
        WALL_SHARE=float((OCC or {}).get('wall_items_max_perimeter_share') or
                 json.load(open(os.path.join(HERE,'occupancy.json')))['layout_rules']['wall_items_max_perimeter_share'])
        ctx['chosen_ref']=chosen  # живая ссылка — для правила разнообразия и для пропорций
        ctx['wall_len_cm']=float(_W)  # длина стены этого метража — для правила «диван ≤ 2/3 стены»
        order=['диван','кресло','стол обеденный','стул','стенка','витрина','стеллаж','комод',
               'тв-тумба','столик','пуф','камин','торшер','кашпо']
        # взаимоисключающие роли по бэнду (кресло/пуф в малой площади) — из файла правил
        _EXCL_ORDERED=[list(g) for g in (json.load(open(os.path.join(HERE,'occupancy.json')))
               .get('placement_tiers',{}).get('exclusive_by_band',{}).get(band['band'],[]))]
        _EXCL=[set(g) for g in (json.load(open(os.path.join(HERE,'occupancy.json')))
               .get('placement_tiers',{}).get('exclusive_by_band',{}).get(band['band'],[]))]
        # Z4: группа — связная система; роли, ТРЕБУЕМЫЕ группой, обходят взаимоисключение
        # (сет 17: exclusive «пуф vs кресло» в 14-16 убивал кресла заявленной sofa_2armchairs)
        _EXCL_ORDERED=[g for g in _EXCL_ORDERED if not (set(g) & set(_zreq))]
        _EXCL=[g for g in _EXCL if not (g & set(_zreq))]
        # предпочтительная роль из взаимоисключающей пары идёт РАНЬШЕ (первая в списке правил)
        for _g in _EXCL_ORDERED:
            if len(_g) > 1 and _g[0] in order and _g[1] in order:
                order = [r for r in order if r != _g[0]]
                order.insert(order.index(_g[1]), _g[0])
        for role in order:
            if role not in band['floor']: continue
            if any(role in g and (g & set(chosen)) for g in _EXCL):
                continue     # роль-конкурент уже в сете (напр. кресло при выбранном пуфе)
            # Правило владельца 08.08: в стенке ВСЕГДА есть место под ТВ по центру —
            # при выбранной стенке тв-тумба не нужна (стенка = носитель ТВ; солвер и
            # валидатор это знают: occupancy.layout_rules.tv_bearer_roles)
            # ЛЕСТНИЦА НОСИТЕЛЕЙ (владелец 13.08: «шаблон со стенкой не лезет — автоматом
            # выбирать с тумбой, для того и есть шаблоны разные»). Сет = банк кандидатов:
            # кладём ОБОИХ, стенка приоритетна, тумба — запасной носитель. Мьютекс
            # «ставится только один» переехал в расстановку (place_media).
            if role=='тв-тумба' and chosen.get('стенка'):
                print('  стенка приоритетна; тв-тумба добирается ЗАПАСНЫМ носителем (банк)')
            # Z4: обеденная группа — ТОЛЬКО при свободном регионе (док владельца «dining у окна
            # requires_free_region»): после посадочной группы должно оставаться ≥6 м² usable —
            # иначе стол+стулья геометрически не встают (провалы band 21-25 на приёмке 08.08)
            if role=='стол обеденный':
                # Свод №7: регион — по числу мест (2 места ~3 м², не 6): фикс-порог
                # глушил столовую во всех 15-20 м² (0/72). Числа+пруф —
                # zones.json → dining_region_m2
                _drz=(json.load(open(_ZR_PATH))
                      .get('dining_region_m2',{}).get('by_seats',{'2':3.0,'4':6.0,'6':8.0}))
                _seats='6' if m2>=40 else ('4' if m2>=22 else '2')
                _need=float(_drz.get(_seats,6.0))
                if (z_usable-zgroup['footprint_m2'])<_need:
                    print(f"  Z4: usable {z_usable:.1f} − группа {zgroup['footprint_m2']} < {_need} м² ({_seats} мест) — обеденной нет региона")
                    continue
            # Z4: посадочные роли диктует ГРУППА — кресло/пуф вне её состава не берём;
            # спутники (пуф/торшер/кашпо) режет anchor-принцип (extras_max band'а)
            if role in ('кресло','пуф') and role not in _zreq and role not in _zopt:
                print(f"  Z4: «{role}» вне группы {zgroup['id']} — пропуск")
                continue
            if role in _EXTRA_ROLES:
                if _extras_left<=0:
                    print(f"  Z4: extras_max исчерпан — «{role}» не берём")
                    continue
            if role=='кресло':
                q=_zreq.get('кресло',1) if 'кресло' in _zreq else 1
                if band.get('kreslo_max')==1: q=min(q,1)
                # канон sectional (08.08): у Г-дивана chaise уже даёт посадку — пара кресел
                # избыточна и геометрически не встаёт (зеркало попадает в плечо); одно кресло
                if ctx.get('corner_sofa'): q=min(q,1)
            else:
                q=QTY.get(role,1)
            top=pick2(role,m2,band['floor'][role],tier,pair,ctx,qty=q) or \
                pick2(role,m2,band['floor'][role],tier,pair,ctx,soft=True,qty=q)
            if not top and role in ('столик','ковёр'):
                # 17.08: ЯДРО ЗОНЫ без замены недопустимо (премиум-сеты 85/103/118 остались без столика:
                # крупный диван 300+ → пропорция 55–75% и конверт слота убивали ВСЕХ кандидатов; солвер
                # без столика — 15+ мин и TIMEOUT). Последний рубеж: без пропорции к дивану, soft-тир.
                top=pick2(role,m2,band['floor'][role],tier,pair,ctx,soft=True,qty=q,no_prop=True)
                if top: print(f"  ядро зоны: «{role}» взят без пропорции к дивану ({top[0]['name'][:30]})")
            if not top:
                print(f"  ОТКАЗ: «{role}» — 0 кандидатов даже soft (тир/стиль/размер/пропорции)")
                continue
            # Z4: длина столика 55–75%% ширины дивана — принудительна ПРИ ПОДБОРЕ
            # (в валидации soft — правка владельца 07.08)
            if role=='столик' and ctx.get('sofa_w'):
                _lo,_hi=0.55*ctx['sofa_w'],0.75*ctx['sofa_w']
                _fit=[t for t in top if (t.get('w') or t.get('dia')) and _lo<=(t.get('w') or t.get('dia'))<=_hi]
                if _fit: top=_fit
                else: print(f"  Z4: нет столика {_lo:.0f}–{_hi:.0f} см (55–75%% дивана) — берём ближайший")
            it=top[0]
            add=(it['fp'] or 0.16)*q
            cap_hi=(OCC['floor_cap_pct'].get(band['band'],[None,COMP['global_floor_cap'][2]])[1]
                    if OCC else COMP['global_floor_cap'][2])  # динамический кап: мал. комнаты до 50%, больш. меньше
            if floor_fp+add>m2*cap_hi/100:
                # 17.08 (TIMEOUT 8 XL-сцен: премиум-сеты 85/103/118 остались БЕЗ главного столика — кап пола
                # выкинул top[0], а «клей» зоны без замены; солвер без столика мучается 15+ мин):
                # столик/ковёр — ЯДРО зоны (_CORE_ZONE): при отказе по капу берём МЕНЬШИЙ из кандидатов
                if role in ('столик','ковёр'):
                    _fit=[t for t in top if floor_fp+(t['fp'] or 0.16)*q<=m2*cap_hi/100]
                    if not _fit:
                        print(f"  кап пола: «{role}» не помещается даже меньшим — ядро зоны без {role}!")
                        continue
                    it=min(_fit,key=lambda t:(t['fp'] or 0.16)); add=(it['fp'] or 0.16)*q
                    print(f"  кап пола: «{role}» — взят меньший ({it['name'][:30]}, {it['fp']:.2f} м²) вместо {top[0]['name'][:30]}")
                else:
                    continue
            # кап периметра: три средних пристенных предмета съедали 40% стен, и раскладка
            # переставала собираться (замер провалов 59-61, 76, 99, 108, 115, 117)
            if role in WALL_ROLES:
                if wall_len+(it['w'] or 100)*q > free_perimeter*WALL_SHARE: continue
                wall_len+=(it['w'] or 100)*q
            chosen[role]=dict(it,qty=q); alts[role]=[{k:a[k] for k in ('mid','eid','name','price','score')} for a in top[1:]]
            if role=='диван': _sofa_top=[dict(a) for a in top[:12]]   # полные карточки — для лестницы диванов
            if role in _EXTRA_ROLES: _extras_left-=1
            ctx['used_shops'].add(it['shop']); floor_fp+=add
            # A2 (исследование рефери 08.08): приставной = subtype узкого столика (роли-SKU в
            # каталоге нет); ставим, когда его требует/допускает посадочная группа — поверхность
            # у кресел (H&G: every seat needs a surface; одна обслуживает соседние места)
            if role=='кресло' and ('приставной' in _zreq or 'приставной' in _zopt) \
                    and 'приставной' not in chosen:
                _side=pick2('столик',m2,(0.02,0.6),tier,pair,ctx,soft=True) or []
                _mid0=(chosen.get('столик') or {}).get('mid')
                _side=[t for t in _side if (t.get('w') or t.get('dia') or 99)<=55
                       and t.get('mid')!=_mid0]
                if _side and floor_fp+(_side[0]['fp'] or 0.09)<=m2*cap_hi/100:
                    chosen['приставной']=dict(_side[0],qty=1)
                    floor_fp+=(_side[0]['fp'] or 0.09)
                else:
                    print("  A2: узкого столика (≤55 см) под приставной нет — группа без него")
            # якорь и капсула сета — от первых выбранных
            if role=='диван':
                ctx['sofa_key']=emb_key(it['mid'],it['eid']); ctx['sofa_w']=it['w']; ctx['sofa_h']=it['h']
                ctx['corner_sofa']=bool(re.search(r'углов', (it.get('name') or '').lower()))
                ctx['temp']=temperature(tuple(it['rgb']) if it['rgb'] else None)
                if it.get('fabric'): ctx['fabrics'].add(it['fabric'])
            for kf in ('style','wood','metal'):
                if it.get(kf) and not ctx[kf]: ctx[kf]=it[kf]
            if it.get('fabric'): ctx['fabrics'].add(it['fabric'])
        # Z4: «диван 2» — легальная роль СОСТАВА ГРУППЫ (sofa_facing_sofa/loveseat, с 12–15 м²
        # usable), а не заплатка недобора площади (старое правило «только 41+» удалено)
        # W1 kb-rules-merge (владелец 10.08): «два РАЗНЫХ дивана выглядят странно» — пара
        # только (а) та же модель, (б) та же коллекция (магазин + корень имени; сюда же
        # «угловой + прямой одной модели»), (в) тот же магазин + тот же цвет-класс и не шире
        # первого. Иначе — демоция к книжной композиции «диван + 2 ОДИНАКОВЫХ кресла»
        # (qty=2 одной SKU; экземпляры «кресло 2» делает ядро).
        if _zreq.get('диван',0)>=2 and 'диван' in chosen:
            top=pick2('диван',m2,band['floor']['диван'],tier,pair,ctx,soft=True) or []
            first=chosen['диван']
            _TYPE_WORDS={'диван','угловой','еврокнижка','прямой','модульный','кровать',
                         'диван-кровать','мини','xl','хл'}
            def _model_token(nm):
                for w in (nm or '').lower().replace('-',' ').split():
                    if w not in _TYPE_WORDS: return w
                return (nm or '').lower()
            it2=why=None
            for t in top:
                if t['mid']==first['mid']: it2,why=t,'same_model'; break
            if not it2:
                for t in top:
                    if t['eid']!=first['eid'] and t['shop']==first['shop'] \
                            and _model_token(t['name'])==_model_token(first['name']):
                        it2,why=t,'same_collection'; break
            if not it2:
                for t in top:
                    if t['eid']==first['eid'] or t['shop']!=first['shop']: continue
                    if t.get('cls')!=first.get('cls'): continue
                    if (t.get('w') or 999)>(first.get('w') or 999): continue
                    it2,why=t,'palette_match'; break
            if it2 and floor_fp+it2['fp']<=m2*0.40:
                chosen['диван 2']=dict(it2,qty=1); floor_fp+=it2['fp']
                print(f"  Z4/W1: «диван 2» по парности ({why}): {it2['name'][:40]}")
            elif ('кресло' in chosen and not band.get('kreslo_max')
                    and not ctx.get('corner_sofa')
                    and chosen['кресло'].get('qty',1)<2):
                floor_fp+=chosen['кресло']['fp']; chosen['кресло']['qty']=2
                print("  W1: пары дивану нет — демоция к «диван + 2 одинаковых кресла»")
            else:
                print("  W1: пары дивану нет (парность) — группа без «диван 2»")
        # добор при пустоте — только квотой кресла, если группа его предусматривает
        cap_lo=(OCC['floor_cap_pct'].get(band['band'],[COMP['global_floor_cap'][0]])[0]
                if OCC else COMP['global_floor_cap'][0])
        if floor_fp<m2*cap_lo/100:
            if ('кресло' in chosen and chosen['кресло']['qty']<_zreq.get('кресло',1)
                    and not band.get('kreslo_max')):
                chosen['кресло']['qty']=_zreq['кресло']; floor_fp+=chosen['кресло']['fp']
        # R3 [[layout-rules-v2]] — состав по функциональным зонам (вердикты владельца 2026-08-07):
        # 1) стол ⇔ стулья: столовая группа целиком или никак — стол-«сирота» и стулья без стола
        #    рождали нелогичные раскладки (сет 59); priors: у стола p50 = 3 стула вплотную
        if ('стол обеденный' in chosen) != ('стул' in chosen):
            _orph='стол обеденный' if 'стол обеденный' in chosen else 'стул'
            _fp_o=chosen[_orph].get('fp') or 0
            print(f"  R3: «{_orph}» без пары (стол⇔стулья) — из состава вон")
            floor_fp-=_fp_o*chosen[_orph].get('qty',1); chosen.pop(_orph); alts.pop(_orph,None)
        if 'стул' in chosen and chosen['стул'].get('qty',1)<3 and (m2>=26):
            chosen['стул']['qty']=3   # priors p50: три стула вплотную к столу
        # 2) норматив хранения: p50 5 / p90 15 см ширины на м² (данные 18 804 сцен) — перебор
        #    выкидываем от наименее важного (витрина → стеллаж → комод; стенка — носитель ТВ, держим)
        _stw=lambda r: (chosen[r].get('w') or chosen[r].get('d') or 0)*chosen[r].get('qty',1)
        _storage=[r for r in ('витрина','стеллаж','комод','стенка') if r in chosen]
        _total=sum(_stw(r) for r in _storage)
        while _storage and _total > 15*m2:
            _r=next((r for r in ('витрина','стеллаж','комод') if r in _storage), None)
            if not _r: break
            print(f"  R3: хранения {_total:.0f} см при потолке {15*m2:.0f} (15 см/м²) — «{_r}» вон")
            _total-=_stw(_r); floor_fp-=(chosen[_r].get('fp') or 0)*chosen[_r].get('qty',1)
            chosen.pop(_r); alts.pop(_r,None); _storage.remove(_r)
        # ковёр — ПРИВЯЗКА К ДИВАНУ (решение владельца по своду р.2): ширина ≈ диван + 25–35 см
        # с каждой стороны (схема «передние ножки»); фолбэк на % пола, если дивана/размеров нет
        if cat.get('ковёр'):
            sofa_w=(chosen.get('диван') or {}).get('w')
            # ПОТОЛОК ПО ПЛОЩАДИ КОМНАТЫ (владелец 12.08): привязка к дивану даёт
            # ковёр 290 в комнате 15 м² (39% пола) — он не находил места и оставался
            # в банке. Верхняя граница — конверт слота (zones.json) +10%.
            # КАНОН РАЗМЕРА (перепроверено 12.08): ковёр достаёт до передних ножек
            # посадочных (диван + ~30 см с каждой стороны), а у стен остаётся полоса
            # пола 45-60 см. Потолок — по комнате, не по «доле пола».
            # ПОТОЛОК — ИЗ СЛОТА ШАБЛОНА, без вычислений в коде (замечание владельца
            # 12.08: «почему ковёр вообще считался, если есть чёткие шаблоны?»).
            # Число и его обоснование — services/planner-solver/rules/zones.json →
            # template_slot_envelopes.slots.ковёр; здесь только фильтр каталога.
            _rug_cap=(slot_ideal('ковёр',m2) or 999)*1.10
            best=None;bs=1e9; _best_any=None; _bs_any=1e9
            for it in cat['ковёр']:
                if not it['fp'] or re.search(r'ассортимент|мехов|ванн|придверн|подложк',it['name'].lower()): continue
                if not overlap_ok(emb_key(it['mid'],it['eid']),style_name,chosen,role='ковёр',tier=tier): continue
                rw=max(it.get('w') or 0, it.get('d') or 0) or None  # длинная сторона ковра
                _too_big = bool(_rug_cap and rw and rw>_rug_cap)
                _msr=((OCC or {}).get('rug_rules',{}) or {}).get('main_seating_rug_min',{}) \
                    or (OCC or {}).get('dynamic',{}).get('rug_rules',{}).get('main_seating_rug_min',{})
                _rshort=min(it.get('w') or 0, it.get('d') or 0)
                _rlong=max(it.get('w') or 0, it.get('d') or 0)
                if _rshort and _rshort < float(_msr.get('short_min_cm', 140)):
                    continue        # короткая сторона не держит зону (аудит 21.08)
                if _rlong==_rshort and _rlong <= float(_msr.get('round_max_as_zone_cm', 200)):
                    continue        # круглый коврик — не зонный ковёр (форма не решается)
                if sofa_w and rw:
                    _ov=(OCC or {}).get('rug_rules',{}).get('verified_r2',{}).get('front_legs_scheme_side_overhang_each_cm',[25,35])
                    tgt=min(sofa_w+2*sum(_ov)/2, _rug_cap or 1e9)  # диван + выступ, но в габарит комнаты
                    score=abs(rw-tgt)
                else:
                    kv=band.get('kover_pct') or (30,50)
                    score=abs(it['fp']-(kv[0]+kv[1])/2/100*m2)*100
                if score<_bs_any: _bs_any=score; _best_any=it     # запасной: без потолка
                if _too_big: continue                              # крупнее нормы площади
                if score<bs: bs=score; best=it
            # ЛУЧШЕ НЕ ДОСТРОИТЬ, ЧЕМ ДОСТРОИТЬ НЕВЕРНО (правило владельца 2026-08-05). Ковёр,
            # который не дотягивает до допустимого соотношения с диваном, в гостиной читается
            # половиком у дивана. В каталоге сейчас всего 14 ковров, крупнейший 100x150 — для
            # дивана 230 нужен от 265. Не кладём вовсе и помечаем дыру состава.
            # Две схемы ковра. Основная — «передние ножки»: ковёр заходит под диван и держит всю
            # зону. Если такого нет, допустима схема «только под столиком»: ковёр выступает за
            # столик со всех сторон (владелец, 2026-08-05). Если не годится ни одна — ковра нет.
            _scheme=None
            if best and sofa_w:
                _long=max(best.get('w') or 0, best.get('d') or 0)
                # I3 (канон 08.08, Lulu&Georgia/E.Henderson): ковёр от РАБОЧЕЙ ширины дивана
                # (у Г — минус плечо) + 15 см с каждой стороны; полная Г-длина требовала
                # несуществующих гигантов («нужен от 507» при рабочей 246+30=276)
                _work_w=sofa_w-(95 if ctx.get('corner_sofa') else 0)
                if _long and _long >= _work_w + 30:
                    _scheme='front_legs'
                else:
                    _tbl=chosen.get('столик')
                    _tl=max((_tbl or {}).get('w') or 0, (_tbl or {}).get('d') or 0) if _tbl else 0
                    _rlo,_rhi=PROP_RULES['rug_len_vs_table']
                    # под столик берём НАИБОЛЬШИЙ подходящий ковёр, а не ближайший к дивану
                    _cands=[]
                    for it2 in cat['ковёр']:
                        if not it2['fp'] or re.search(r'ассортимент|мехов|ванн|придверн|подложк',
                                                      it2['name'].lower()): continue
                        # лимит повторов действует и здесь: ветка «ковёр под столик» его обходила,
                        # и ровно из-за неё 40 пар комплектов повторяли друг друга сверх нормы
                        # (4 общих товара при лимите 3, 2026-08-05)
                        if not overlap_ok(emb_key(it2['mid'],it2['eid']),style_name,chosen,role='ковёр',tier=tier): continue
                        l2=max(it2.get('w') or 0, it2.get('d') or 0)
                        if _tl and _rlo<=l2/_tl<=_rhi: _cands.append((l2,it2))
                    # АУДИТ ВЛАДЕЛЬЦА 21.08 + Codex: схема table_only НЕ исполняется солвером
                    # (rug_scheme не доезжает, паспорта seating-формы нет) — по доктрине
                    # ADR-0113 исполняемое без паспорта запрещено. 78 планов стелили
                    # 180×120 «под столик» как обычный зонный ковёр. До появления паспорта
                    # и реализации: либо front_legs, либо честная дыра состава.
                    print(f"  дыра каталога: ковра нет под диван (нужен от "
                          f"{int(_work_w+30)} см — от РАБОЧЕЙ ширины) — сет без ковра "
                          f"(table_only отключена: нет паспорта/исполнителя)",flush=True)
                    best=None
            # фолбэк «ближайший неправильный» (_best_any) УДАЛЁН (Codex 21.08): именно он
            # клал накидку 80×50 и прикроватные форматы в разговорную зону
            if best: chosen['ковёр']=dict(best,qty=1,rug_scheme=_scheme)
        # люстра: диаметр по метражу + металл капсулы
        _f=(OCC or {}).get('chandelier_size',{}).get('diameter_cm_formula','')
        if '8.2' in _f:  # формула свода: (L+W)м × 8.2, ±20%
            import math as _m
            _lw=2*_m.sqrt(m2)  # приближение L+W для ~квадратной комнаты
            dmid=_lw*8.2; dlo,dhi=dmid*0.8,dmid*1.2
        else:
            dlo,dhi=(45,70) if m2<=20 else ((60,90) if m2<=30 else (60,100))
        lu=[it for it in cat.get('люстра',[]) if it['dia'] and dlo<=it['dia']<=dhi] or cat.get('люстра',[])
        lu=[it for it in lu if overlap_ok(emb_key(it['mid'],it['eid']),style_name,chosen,role='люстра',tier=tier)]  # строго: лимит важнее люстры
        if lu:
            plo,phi=tier_band('люстра',tier)
            lu2=[it for it in lu if plo<=it['price']<=phi] or lu
            lu3=[it for it in lu2 if not it.get('metal') or not ctx['metal'] or it['metal']==ctx['metal']] or lu2
            chosen['люстра']=dict(lu3[len(lu3)//2],qty=1)
        # E1 (вердикт владельца set55): media-состав ОБЯЗАН иметь носитель ТВ — нет ни
        # стенки, ни тумбы → добираем тумбу в мягком режиме (любой тир, пометка дефицита)
        if 'стенка' not in chosen and 'тв-тумба' not in chosen:
            _tvf = pick2('тв-тумба', m2, band['floor'].get('тв-тумба', (0.03, 0.8)),
                         tier, pair, ctx, soft=True)
            if _tvf:
                chosen['тв-тумба'] = dict(_tvf[0], qty=1, deficit_fallback=True)
                print('  E1: носитель ТВ добран soft-режимом (дефицит тира)')
            else:
                print('  E1: ДЕФИЦИТ — носителя ТВ нет даже soft (media-сет без ТВ!)')
        # A4 (исследование рефери 08.08): картина над диваном — focal-альтернатива ТВ; числа
        # из occupancy (wall_art_vs_sofa_width_pct 60–70, центр 145–160). Категории картин
        # включены в category-roles (роль появится в cat после следующей загрузки каталога).
        _sw=ctx.get('sofa_w') or 0
        _art=[it for it in cat.get('картина',[]) if it.get('w') and _sw
              and 0.5*_sw<=it['w']<=0.7*_sw]
        _art=[it for it in _art if overlap_ok(emb_key(it['mid'],it['eid']),style_name,chosen,
                                              role='картина',tier=tier)]
        if _art:
            chosen['картина']=dict(_art[len(_art)//2],qty=1)
        # Ф3: подушки — ДВЕ РАЗНЫЕ (акцент №1 и акцент №2/нейтраль); плед/ваза/лампа/растение
        p1=pick2('подушка',m2,(0.1,3),tier,pair,ctx,soft=True,color_goal='accent_'+pair[0])
        if p1: chosen['подушка']=dict(p1[0],qty=1)  # СРАЗУ в сет: иначе п2 не видит п1 в лимите разнообразия
        p2=pick2('подушка',m2,(0.1,3),tier,pair,ctx,soft=True,color_goal='accent_'+pair[1])
        if p2:
            it2=next((t for t in p2 if t['eid']!=(p1[0]['eid'] if p1 else '')),None)
            if it2: chosen['подушка 2']=dict(it2,qty=1)
        # cushions_count (свод р.2): широкий диван ≥254 см → 3-я подушка (нейтральная)
        if ((chosen.get('диван') or {}).get('w') or 0)>=254:
            p3=pick2('подушка',m2,(0.1,3),tier,pair,ctx,soft=True)
            it3=next((t for t in (p3 or []) if t['eid'] not in {x['eid'] for x in (chosen.get('подушка'),chosen.get('подушка 2')) if x}),None)
            if it3: chosen['подушка 3']=dict(it3,qty=1)
        # Шторы — часть комплекта гостиной (решение владельца 2026-08-06). В occupancy они и так
        # описаны как «100-160% ширины оконной стены по ткани», просто раньше не подбирались.
        for role in ('плед','ваза','лампа','шторы'):  # растение убрано: декор-зелень рисует нейронка (2026-08-02)
            if role=='лампа' and not (chosen.get('комод') or chosen.get('тв-тумба') or chosen.get('стенка')): continue
            top=pick2(role,m2,(0.1,3),tier,pair,ctx,soft=True)
            if top: chosen[role]=dict(top[0],qty=1); alts[role]=[{k:a[k] for k in ('mid','eid','name','price','score')} for a in top[1:]]
        # ПРАВИЛО ВЛАДЕЛЬЦА 11.08 «украшают ПОВЕРХНОСТИ, а не бока» (майнинг 9013
        # гостиных ProcTHOR: тв-тумба несёт 2.8 предмета, комод 2.0, стеллаж 1.0;
        # напольного декора всего 0.7–1.0 на комнату). Значит декор масштабируется
        # по ЧИСЛУ ПОВЕРХНОСТЕЙ в сете, а не по площади: вторая ваза при двух и
        # более носителях. Напольное (кашпо) остаётся одним — так в данных.
        _SURFACES=('комод','тв-тумба','стенка','стеллаж','витрина')
        _nsurf=sum(1 for r in _SURFACES if chosen.get(r))
        if _nsurf>=2 and chosen.get('ваза'):
            v2=pick2('ваза',m2,(0.1,3),tier,pair,ctx,soft=True)
            it2=next((t for t in (v2 or []) if t['eid']!=chosen['ваза']['eid']),None)
            if it2: chosen['ваза 2']=dict(it2,qty=1)
        # ОБОГАЩЕНИЕ ДО КОРИДОРА ЗАПОЛНЕНИЯ (решение владельца 11.08; пруфы —
        # zones.json fill_policy.target_pct: коридор 30–45% пола — диагностика/цель добора
        # состава банка (пристенное за половину); порядок зон — zone_priority.
        # Замер 11.08: комнаты выходили на 15–25% — пустые. Пока прогноз ниже нижней
        # границы, добираем СЛЕДУЮЩИЕ ПО ПРИОРИТЕТУ роли (хранение → посадка →
        # столовая → декор): солвер сам обогатить не может — мебели просто нет в сете.
        _WALLH={'стенка','тв-тумба','комод','стеллаж','витрина','шкаф','камин'}
        def _fill_now():
            a=0.0
            for r,it in chosen.items():
                if r.split(' ')[0] in ('ковёр','люстра','бра','плед','подушка','ваза',
                                       'лампа','шторы','картина','статуэтка','растение'):
                    continue
                w=(it.get('w') or 0)/100.0; d=(it.get('d') or it.get('dia') or 0)/100.0
                if not (w and d): continue
                a+=w*d*int(it.get('qty') or 1)*(0.5 if r.split(' ')[0] in _WALLH else 1.0)
            return a/max(m2,1)*100
        # ЁМКОСТЬ ШАБЛОНОВ (правило владельца 11.08 «шаблон целиком или другой
        # шаблон»): комплект не должен содержать больше, чем способен принять
        # шаблон, который влезет в эту площадь. Иначе лишнее становится ИЗБЫТКОМ
        # (экзамен: 425 лишних стульев — сеты давали 6, а вставала столовая на 4).
        # Ёмкости — из библиотеки шаблонов: столовая 2/4/6 по площади зоны.
        _seats_cap = 2 if m2 < 22 else (4 if m2 < 45 else 6)
        for _i in range(_seats_cap + 1, 7):
            chosen.pop(f'стул {_i}', None)
        if chosen.get('стул') and _seats_cap >= 2:
            chosen['стул']=dict(chosen['стул'], qty=min(int(chosen['стул'].get('qty') or 1),
                                                        _seats_cap))
        # порядок добора = приоритет зон (zones.json zone_priority, ADR-0094). В просторных
        # комнатах (40+ м²) канон разрешает ВТОРУЮ посадочную группу — там второй
        # диван и пара кресел дают основную площадь, иначе комната остаётся пустой
        # (замер 11.08: большие сеты держались на 20% при цели 30%).
        # добор — только тем, что примет какой-нибудь шаблон библиотеки:
        # стулья добираем СТРОГО до ёмкости столовой, кресла 3/4 — только в
        # просторных (тихая зона/U-композиция), пуф — компаньон посадки
        # Q5 свода №13: кресла 3/4 УБРАНЫ из _ENRICH (там они добирались как два независимых
        # SKU и только при недоборе fill) — пара второго pod создаётся АТОМАРНО ниже (один SKU,
        # pair_key), с порога zones.json seating_pods.second_pod_min_m2 (25), не 40
        _ENRICH=([('диван 2',1),('стеллаж',1),
                  ('стеллаж 2',1),('витрина',1),('комод 2',1),('пуф',1),
                  ('приставной',1),('стол обеденный',1),('стул',_seats_cap)]
                 if m2>=40 else
                 [('стеллаж',1),('витрина',1),('комод 2',1),('пуф',1),
                  ('приставной',1),('стол обеденный',1),('стул',_seats_cap)])
        _fill0=_fill_now()
        # ЗАЩИТА ЯДРА ЗОНЫ (гейт 11.08): обогащение НЕ добирает второстепенное, пока
        # в сете нет ядра посадочной зоны — ковра и журнального столика. Экзамен
        # показал: добор комода 2/витрины/кресел 3-4 вытеснял ковёр (26 сцен) и
        # столик (17) — вещи, которые и делают зону зоной.
        # ковёр исключён из ядра (аудит 21.08): без валидного SKU он — честная дыра
        # состава (inventory_gap), а не повод замораживать обогащение; клей зоны — столик
        _CORE_ZONE=('столик',)
        if not all(chosen.get(_c) for _c in _CORE_ZONE):
            _ENRICH=[]
        for _r,_q in _ENRICH:
            if _fill_now()>=30: break
            _base_r=_r.split(' ')[0]
            if chosen.get(_r): continue
            # A5 (свод №5, малые): концентрация хранения — в ≤18 м² ВТОРАЯ единица
            # хранения не добирается (три узких по 80 см = анти-паттерн «россыпь»);
            # коридор заполнения добивают следующие роли списка (пуф/приставной/столовая)
            if m2<=18 and _base_r in ('витрина','стеллаж','комод') and any(
                    r.split(' ')[0] in ('витрина','стеллаж','комод') for r in chosen):
                print(f"  A5: «{_r}» не добираем — хранение в малой уже есть (концентрация)")
                continue
            _top=pick2(_base_r,m2,(0.05,6),tier,pair,ctx,soft=True,qty=_q)
            if not _top: continue
            _cand=next((t for t in _top if t['eid'] not in {x.get('eid') for x in chosen.values()}),None)
            if not _cand: continue
            chosen[_r]=dict(_cand,qty=_q)
            if _fill_now()>45:            # перебор — откатываем последний добор
                chosen.pop(_r); break
        if os.environ.get('COMPOSE_DEBUG'):
            print(f'  обогащение: {_fill0:.0f}% → {_fill_now():.0f}% (цель 30–45%)',flush=True)
        for role,it in chosen.items():
            if 'cls' not in it or it.get('rgb') is None:
                p=get_thumb(it['img'],it['mid'],it['eid'])
                d1,_=dominant2(p) if p else (None,None)
                it['cls']=classify(d1); it['rgb']=list(d1) if d1 else None
        # --- валидатор состава по чек-листу гостиной (владелец 2026-08-02) ---
        CORE={'диван','столик','тв-тумба','ковёр','люстра','плед','подушка','шторы'}
        need=set(CORE)
        if chosen.get('стенка'): need.discard('тв-тумба')  # тумба — запасной, не обязательный
        if m2>=16: need|={'кресло','ваза','кашпо'}
        # взаимоисключающие роли: если конкурент уже в сете — «дырку» не добираем
        # (иначе валидатор состава возвращал кресло, выброшенное правилом «в малой площади — пуф»)
        for _g in _EXCL:
            if _g & set(chosen): need-= (_g - set(chosen))
        if not (chosen.get('торшер') or chosen.get('лампа')): need.add('торшер')  # локальный свет обязателен
        if m2>=16 and not any(chosen.get(r) for r in ('комод','стеллаж','витрина','стенка','тв-тумба')):
            need.add('комод')  # хранение
        gaps=sorted(r for r in need if r not in chosen and not (r=='подушка' and 'подушка' in chosen))
        # добор обязательных, которых нет из-за band-долей: мягкий pick без доли площади
        for r in list(gaps):
            top=pick2(r,m2,(0.05,6),tier,pair,ctx,soft=True)
            if top:
                chosen[r]=dict(top[0],qty=QTY.get(r,1) if r!='подушка' else 1)
                gaps.remove(r)
        if gaps: print(f"  ДЫРКИ состава (нет товара в каталоге): {', '.join(gaps)}",flush=True)
        # A5 (свод №5, малые): КОНЦЕНТРАЦИЯ хранения — в ≤18 м² один крупный блок
        # лучше двух мелких по разным стенам (свод: «один 180 лучше 100+80»).
        # Стоит ПОСЛЕ обогащения и gap-fill — раньше хранение ещё не добрано
        # (первая вставка стояла до них и не срабатывала ни разу). Мелочь убираем,
        # только если остающийся блок реально крупный (>=120 см); носитель ТВ
        # (стенка/тв-тумба) — медиа-зона, концентрация его не касается
        if m2<=18:
            _units=[r for r in chosen if r.split(' ')[0] in ('витрина','стеллаж','комод')]
            if len(_units)>=2:
                _units.sort(key=lambda r:(chosen[r].get('w') or 0)*(chosen[r].get('h') or 200))
                if (chosen[_units[-1]].get('w') or 0)>=120:
                    for _r in _units[:-1]:
                        print(f"  A5: концентрация — «{_r}» вон (остаётся блок {chosen[_units[-1]].get('w'):.0f} см)")
                        floor_fp-=(chosen[_r].get('fp') or 0)*chosen[_r].get('qty',1)
                        chosen.pop(_r); alts.pop(_r,None)
        # СЕТ СОБИРАЕТСЯ ПОД ШАБЛОНЫ (правило владельца 12.08: «шаблона на два стула
        # нет — как они попали в сет?»). Напольная роль, которую ни одна схема не может
        # поставить, — мусор в банке: она никогда не встанет и путает смету.
        _claim=set()
        for _z,_rs in (_TPL_ROLES or {}).items():
            if not _z.startswith('_'): _claim |= set(_rs)
        for _r in [r for r in chosen if r in _FLOOR_ROLES_ALL and r not in _claim]:
            print(f'  ШАБЛОНА НЕТ: «{_r}» — ни одна схема его не ставит, из состава вон')
            floor_fp-=(chosen[_r].get('fp') or 0)*chosen[_r].get('qty',1)
            chosen.pop(_r); alts.pop(_r,None)
        # ФИНАЛЬНАЯ СВЕРКА ПАР (12.08): проверка стол⇔стулья стоит РАНЬШЕ обрезки по
        # площади, и стол мог уйти позже — 27 из 126 сетов уезжали со стульями без
        # стола (мёртвый груз: стул сам по себе зоны не образует).
        if not any(r == 'стол обеденный' for r in chosen) and any(r.startswith('стул') for r in chosen):
            for _r in [r for r in chosen if r.startswith('стул')]:
                floor_fp -= (chosen[_r].get('fp') or 0)*chosen[_r].get('qty',1)
                chosen.pop(_r); alts.pop(_r, None)
            print('  R3-финал: стулья без обеденного стола — из состава вон')
        # ЛЕСТНИЦА ДИВАНОВ (владелец 13.08, планы без медиа: «угловой не влезает —
        # надо было прямой шаблон»): главный диван угловой и запасного прямого нет →
        # кладём ПРЯМОЙ диван в банк («диван 2»). В изрезанных комнатах (эркер/пилоны)
        # расстановка сама спустится на прямой; в обычных он честно останется в банке.
        _main=chosen.get('диван')
        import re as _re
        def _is_corner(d): return bool(_re.search(r'углов|модульн', (d.get('name') or '').lower()))
        if _main and _is_corner(_main) and 'диван 2' not in chosen:
            _cands=[t for t in (locals().get('_sofa_top') or []) if not _is_corner(t)
                    and not _re.search(r'топпер|чехол', (t.get('name') or '').lower())
                    and 140<=(t.get('w') or 0)<=220]
            if _cands:
                _bk=_cands[0]
                chosen['диван 2']=dict(_bk,qty=1)  # футпринт НЕ добавляем: запасной, ставится вместо
                print(f"  ЛЕСТНИЦА ДИВАНОВ: запасной прямой в банк: {_bk['name'][:40]}")
        # К5: явный отчёт незакрытых слотов (роль в слоте есть, товара в конверте не нашлось)
        # слот-отчёт: «стул» без стола — шум (столовой не будет, R3-финал уберёт);
        # причину смотреть по слоту «стол обеденный», а не по стульям
        if 'стол обеденный' not in chosen: _SLOT_MISS.pop('стул',None)
        for _r in list(_SLOT_MISS):
            if _r not in chosen and slot_ideal(_r,m2):
                print(f'  СЛОТ НЕ ЗАКРЫТ: «{_r}» — {_SLOT_MISS[_r]} кандидатов вне конверта, в конверте 0')
        _SLOT_MISS.clear()
        total=sum(it['price']*it['qty'] for it in chosen.values())
        fill=round(floor_fp/m2*100,1)
        sfit_agg=None
        if style_name:  # взвешенный стиль-фит сета: визуальный вес = роль × площадь (просьба владельца)
            num=den=0.0
            for r,it in chosen.items():
                c=EB.style_scores(it['mid'],it['eid']) or SS.get(emb_key(it['mid'],it['eid']))
                if not c: continue
                w=ROLE_W.get(r,ROLE_W.get(r.replace(' 2',''),0.3))*max(it.get('fp') or 0.16,0.05)
                num+=(5.5 if c.get('universal') else c[style_name])*w; den+=w
            sfit_agg=round(num/max(den,1e-6),1)
        if STYLE_MODE:  # реестр для правила разнообразия следующих сетов
            BUILT.append((style_name,{emb_key(it['mid'],it['eid']) for it in chosen.values()},{emb_key(it['mid'],it['eid']) for r,it in chosen.items() if r in MAJOR_ROLES}))
        # C-6 свода №11 (политика Q-A советника + Кодекс §6, dry-run 3/4):
        # ALTERNATIVE-ONLY кресло в банке с диваном от 17 м² — соседняя ступень
        # лестницы (sofa_armchair) достижима солвером. Строго в КОНЦЕ сборки:
        # вне fill/extras/wall-капов, без side-effects на ротации SKU (used_shops
        # не трогаем; BUILT/style_fit/total сняты ВЫШЕ — дифф только добавка кресла).
        # P4 свода №12 (владелец №174: «в 35 м² тот же малый шаблон; был вариант с двумя
        # креслами — почему не здесь»; Кодекс §2 п.4: богатая посадка с 40 м², а large-режим
        # солвера — с 25 м² (room_map.room_mode)). Банк large ОБЯЗАН давать ≥2 seating-
        # альтернативы: пара кресел (sofa_2armchairs) — alt-only, в конце сборки, вне капов.
        _POD=(json.load(open(_ZR_PATH)).get('seating_pods') or {})
        _LARGE_M2 = int(_POD.get('second_pod_min_m2', 25))   # данные (Q5): единый порог с солвером
        if m2>=_LARGE_M2 and 'диван' in chosen and 'кресло' in chosen and 'кресло 2' not in chosen \
                and int(chosen['кресло'].get('qty') or 1) < 2:   # qty=2 уже даёт пару (кресло 2 = экземпляр первого)
            # Q5 (Codex): «кресло 2» = ВТОРОЙ ЭКЗЕМПЛЯР основного кресла (пара одного SKU), а не
            # альтернативный SKU другого магазина (mid = shop_mid!) — прежний фильтр mid!= был ошибкой
            _a2=[dict(chosen['кресло'])]
            if _a2:
                chosen['кресло 2']=dict(_a2[0],qty=1,alt=True,pair_key=f"{_a2[0].get('mid')}:{_a2[0].get('eid')}",pair_provenance='exact_sku')
                print(f"  P4/Q5: кресло 2 = экземпляр основного ({_a2[0]['name'][:40]})")
            else:
                gaps.append('coverage_gap: кресло 2 (alt, large) — нет SKU')
        # Q5 свода №13: ВТОРОЙ POD — АТОМАРНЫЙ КОМПЛЕКТ «кресло 3 + кресло 4 (один SKU, qty=2,
        # компактные) + столик 2 (малая поверхность)», с second_pod_min_m2 (25). Codex (каталожная
        # сессия 16.08): без поверхности пару НЕ создавать (мёртвый груз `passed_not_placed`,
        # владелец №181 «пара визави без стола — зачем»); камин — альтернативная раскладка комплекта,
        # не замена поверхности. Столик 2 — отдельный слот вне конверта главного столика (120–135):
        # круглый dia 35–70 | прямоугольный обе стороны ≤70, h 40–65 предпочтительно, цена в тире,
        # (mid,eid) ≠ главного столика. Компактность кресел: preferred w≤90/d≤95, hard w≤100/d≤105,
        # без реклайнеров/кресел-кроватей. Вне капов (alt), после основного состава; цена/футпринт
        # комплекта — отдельными полями pod_delta_price/pod_floor_fp (в total их нет).
        _POD_CFG=_POD.get('pod_kit') or {}
        if m2>=_LARGE_M2 and 'диван' in chosen and 'кресло 3' not in chosen and 'кресло 4' not in chosen:
            _pref=tuple(_POD_CFG.get('armchair_preferred_wd_cm',[90,95])); _hard=tuple(_POD_CFG.get('armchair_hard_wd_cm',[100,105]))
            _bad=re.compile(_POD_CFG.get('armchair_exclude_regex',r'реклайнер|recliner|кресло-кроват|раскладн|качалк|мешок|подвесн'),re.I)
            def _arm_ok(lim):
                return lambda it: (it.get('w') or 999)<=lim[0] and (it.get('d') or 999)<=lim[1] and not _bad.search(it.get('name') or '') \
                    and int(it.get('mid') or 0) not in _pod_banned_mids
            _sh3=band['floor'].get('кресло')
            _c3=None
            if _sh3:
                for _lim in (_pref,_hard):
                    _c3=(pick2('кресло',m2,_sh3,tier,pair,ctx,qty=2,pre_filter=_arm_ok(_lim)) or
                         pick2('кресло',m2,_sh3,tier,pair,ctx,soft=True,qty=2,pre_filter=_arm_ok(_lim)))
                    if _c3: break
            _base_key=f"{chosen['кресло'].get('mid')}:{chosen['кресло'].get('eid')}" if 'кресло' in chosen else None
            _c3=[t for t in (_c3 or []) if f"{t.get('mid')}:{t.get('eid')}"!=_base_key] or (_c3 or [])
            _main_t=chosen.get('столик') or {}
            _main_key=f"{_main_t.get('mid')}:{_main_t.get('eid')}"
            _sd=tuple(_POD_CFG.get('surface_dia_cm',[35,70])); _smax=float(_POD_CFG.get('surface_side_max_cm',70))
            _sh_rng=tuple(_POD_CFG.get('surface_h_cm',[40,65]))
            def _surf_ok(strict_h):
                def _f(it):
                    if f"{it.get('mid')}:{it.get('eid')}"==_main_key: return False
                    if int(it.get('mid') or 0) in _pod_banned_mids: return False   # fail-closed: сломанный фид
                    dia=it.get('dia'); w=it.get('w') or 0; d=it.get('d') or 0
                    if dia: size_ok=_sd[0]<=dia<=_sd[1]
                    else: size_ok=(0<w<=_smax) and (0<d<=_smax)
                    if not size_ok: return False
                    h=it.get('h')
                    if strict_h and not (h and _sh_rng[0]<=h<=_sh_rng[1]): return False
                    return True
                return _f
            _surf=None
            if _c3:
                for _st in (True,False):
                    # вне конверта главного слота и вне пропорции к дивану (55–75% ширины — это про
                    # журнальный столик главной группы, не про малую поверхность pod)
                    _surf=pick2('столик',m2,tuple(_POD_CFG.get('surface_share_pct',[0.5,3.0])),tier,pair,ctx,qty=1,pre_filter=_surf_ok(_st),no_envelope=True,no_prop=True)
                    if _surf: break
            if _c3 and _surf:
                _k=f"{_c3[0].get('mid')}:{_c3[0].get('eid')}"
                _sk=f"{_surf[0].get('mid')}:{_surf[0].get('eid')}"
                _pk=f"{_k}|{_sk}"
                chosen['кресло 3']=dict(_c3[0],qty=1,alt=True,pair_key=_k,pair_provenance='exact_sku',pod='secondary_quiet',pod_key=_pk)
                chosen['кресло 4']=dict(_c3[0],qty=1,alt=True,pair_key=_k,pair_provenance='exact_sku',pod='secondary_quiet',pod_key=_pk)
                chosen['столик 2']=dict(_surf[0],qty=1,alt=True,surface_key=_sk,pod='secondary_quiet',pod_key=_pk)
                _pod_price=2*(_c3[0].get('price') or 0)+(_surf[0].get('price') or 0)
                _pod_fp=round(2*(_c3[0].get('fp') or 0)+(_surf[0].get('fp') or 0),2)
                print(f"  Q5: второй pod — комплект кресло 3/4 ({_c3[0]['name'][:32]}) + столик 2 ({_surf[0]['name'][:28]}), +{_pod_price} ₽, {_pod_fp} м²")
            else:
                _pod_price=0; _pod_fp=0.0
                gaps.append('coverage_gap: quiet_pod — нет ' + ('компактной пары кресел' if not _c3 else 'малой поверхности (столик 2)'))
        else:
            _pod_price=0; _pod_fp=0.0
        # Q6c свода №13: АЛЬТЕРНАТИВНЫЙ КОМПЛЕКТ СТОЛОВОЙ «уголок» (edge_nook) — банкетка к стене
        # вместо стула с дальней стороны. Кладём только там, где остров тесен (≤ nook_max_m2), при
        # наличии стола и ≥2 стульев; банкетка — из capability-индекса (dining_seat_capable +
        # guaranteed_seats ≥2, Q6a), совместимая со столом (0.5–1.2 ширины). Взаимоисключающих
        # bundle'ов на сет — не больше одного (`dining_bundle`); alt-роль вне капов, как pod.
        _NOOK_MAX_M2=float((_POD.get('nook_bundle_max_m2') or 25))
        if m2<=_NOOK_MAX_M2 and 'стол обеденный' in chosen and 'стул' in chosen \
                and 'банкетка' not in chosen and not chosen.get('dining_bundle'):
            _tw=float(chosen['стол обеденный'].get('w') or 0)
            _bench=[b for b in cat.get('банкетка',[])
                    if (b.get('caps_used') or {}).get('dining_seat_capable')
                    and ((b.get('caps_used') or {}).get('guaranteed_seats') or 0)>=2
                    and _tw and 0.5*float(b.get('w') or 0)<=_tw<=1.2*float(b.get('w') or 0)
                    and int(b.get('mid') or 0) not in _pod_banned_mids]
            if _bench:
                # порядок: стиль сета → цветовая совместимость с капсулой → близость к столу
                # (иначе во всех сетах одна и та же розовая банкетка — разнообразие галереи)
                _bench.sort(key=lambda b: (0 if b.get('style')==ctx.get('style') else (1 if style_ok(b.get('style'),ctx.get('style')) else 2),
                                           0 if (b.get('wood') or ctx.get('wood'))==ctx.get('wood') else 1,
                                           abs(float(b.get('w') or 0)-_tw)))
                _bb=_bench[0]
                chosen['банкетка']=dict(_bb,qty=1,alt=True,dining_bundle='edge_nook',
                                        bundle_provenance='Q6c: alt-состав столовой (уголок) — солвер выбирает уголок только когда остров/круг недостижимы')
                print(f"  Q6c: уголок — банкетка {_bb['name'][:34]} ({_bb.get('w')}×{_bb.get('d')}, мест {(_bb.get('caps_used') or {}).get('guaranteed_seats')}) к столу {_tw:.0f} см")
            else:
                gaps.append('coverage_gap: банкетка (уголок) — нет SKU с посадкой ≥2 и высотой 43–48')
        if m2>=17 and 'диван' in chosen and 'кресло' not in chosen:
            _sh=band['floor'].get('кресло')
            if _sh:
                _atop=pick2('кресло',m2,_sh,tier,pair,ctx,qty=1) or                       pick2('кресло',m2,_sh,tier,pair,ctx,soft=True,qty=1)
                if _atop:
                    chosen['кресло']=dict(_atop[0],qty=1,alt=True)
                    print(f"  C-6: alt-кресло в банк ({_atop[0]['name'][:40]})")
                else:
                    gaps.append('coverage_gap: кресло (alt) — нет SKU в стиле/тире')
            else:
                gaps.append('coverage_gap: кресло (alt) — нет floor-доли band')
        sets.append(dict(band=band['band'],m2=m2,tier=tier,pair=list(pair),gaps=gaps,
                         group=zgroup['id'],usable_m2=round(z_usable,1),
                         pod_delta_price=_pod_price,pod_floor_fp=_pod_fp,
                         style=style_name,style_fit=sfit_agg,
                         capsule=dict(style=ctx['style'],wood=ctx['wood'],metal=ctx['metal'],
                                      temp=ctx['temp'],fabrics=sorted(ctx['fabrics'])),
                         fill_pct=fill,total=total,
                         items={r:{k:v for k,v in it.items() if k!='img'} | {'img':it['img']} for r,it in chosen.items()},
                         alternates=alts))
        print(f"{style_name+' ' if style_name else ''}{band['band']} м² {tier}: {len(chosen)} пр., "
              f"капсула {ctx['style']}/{ctx['wood']}/{ctx['metal']}/{ctx['temp']}, пол {fill}%"
              +(f", стиль-фит {sfit_agg}" if sfit_agg else "")+f", {total:,} ₽".replace(',',' '),flush=True)
OUT_SETS='sets3.json' if STYLE_MODE else 'sets2.json'
# Стабильный set_id: сцены и отчёты живут на НОМЕРАХ сетов, и любая перестановка массива молча
# переадресует их на соседние комплекты. id детерминирован по полям замысла (площадь/ярус/стиль/
# капсула), поэтому пересборка с нуля выдаёт те же id — а замена товара в слоте их не меняет.
try:
    from set_identity import ensure_ids as _ensure_ids
    _ensure_ids(sets)
except Exception as _e:   # noqa: BLE001 — идентичность не должна ронять сборку сетов
    print(f'set_id не проставлен: {type(_e).__name__}: {_e}',flush=True)
# АТОМАРНАЯ запись (инцидент 08.08: падение посреди json.dump оставило файл на 18/126 сетов):
# пишем во временный и переименовываем — rename на одной ФС атомарен
_tmp=os.path.join(HERE,OUT_SETS+'.tmp')
json.dump(sets,open(_tmp,'w'),ensure_ascii=False,indent=1)
os.replace(_tmp,os.path.join(HERE,OUT_SETS))
np.savez_compressed(EMB_PATH,**_emb)
print(f"OK: {OUT_SETS} ({len(_emb)} embeddings в кэше)",flush=True)

# ---------- HTML-превью v2 ----------
def esc(s): return s.replace('&','&amp;').replace('<','&lt;')
H=[f'<!doctype html><meta charset="utf-8"><title>Сеты {"v3 — по стилям" if STYLE_MODE else "v2 — как дизайнер"}</title><style>',
'body{font-family:system-ui;margin:20px;background:#faf7f2;color:#222}',
'.set{background:#fff;border:1px solid #ddd;border-radius:12px;padding:16px;margin:18px 0}',
'.items{display:flex;flex-wrap:wrap;gap:10px}',
'.it{width:150px;border:1px solid #eee;border-radius:8px;padding:6px;font-size:11px;background:#fff}',
'.it img{width:100%;height:96px;object-fit:contain;background:#fff}',
'h2{margin:4px 0} .meta{color:#666;font-size:13px} a{color:#b06a4a}',
'.role{font-weight:600;color:#888;text-transform:uppercase;font-size:10px}',
'.why{color:#7a9;font-size:10px}</style>']
for i,s in enumerate(sets,1):
    c=s['capsule']
    st_badge=f' · <b style="color:#7a5">СТИЛЬ: {s["style"].upper()} (фит {s.get("style_fit","—")}/10)</b>' if s.get('style') else ''
    H.append(f'<div class=set><h2>Сет {i} ({"v3" if STYLE_MODE else "v2"}): {s["band"]} м² — {s["tier"].capitalize()}{" — "+s["style"] if s.get("style") else ""}</h2>')
    H.append(f'<div class=meta>капсула: стиль {c["style"] or "—"} · дерево {c["wood"] or "—"} · металл {c["metal"] or "—"} · гамма {c["temp"]} · акценты {"+".join(s["pair"])} · пол {s["fill_pct"]}% · ≈ {s["total"]:,} ₽{st_badge}</div><div class=items>'.replace(',',' '))
    for role,it in s['items'].items():
        img=it['img'] if not it['img'].startswith('//') else 'https:'+it['img']
        dims=f"{it['w'] or ''}×{it['d'] or it['dia'] or ''}"
        q=f" ×{it['qty']}" if it['qty']>1 else ''
        H.append(f'<div class=it><div class=role>{role}{q}</div><img loading=lazy src="{esc(img)}">'
                 f'<div>{esc(it["name"][:70])}</div><div>{dims} см · <b>{it["price"]:,} ₽</b></div>'.replace(',',' ')
                 +f'<div><a href="{esc(it["url"])}" target=_blank>открыть</a> · {it["shop"]}</div>'
                 +f'<div class=why>{esc(it.get("why","")[:120])}</div></div>')
    H.append('</div></div>')
PV='sets3-preview.html' if STYLE_MODE else 'sets2-preview.html'
open(os.path.join(HERE,PV),'w').write('\n'.join(H))
print(f"OK: {PV}",flush=True)
