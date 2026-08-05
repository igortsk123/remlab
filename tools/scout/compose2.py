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
BUILT=[]  # [(style, {keys})] — уже собранные сеты этого прогона
def overlap_ok(cand_key,style,chosen):
    if not STYLE_MODE: return True
    cur={emb_key(it['mid'],it['eid']) for it in chosen.values()}
    for st,keys in BUILT:
        lim=5 if st==style else 3
        ov=len(cur&keys)+(1 if (cand_key in keys and cand_key not in cur) else 0)
        if ov>lim: return False
    return True
# --- Ш1 set-quality-fixes: санитайзер габаритов -------------------------------------------
# В фидах оси путаются (кашпо «80x40x50 см» приехало как Ш=40/Г=80) и встречается мусор
# (настольная лампа с глубиной 130 см). Если размеры есть в НАЗВАНИИ — они истина.
_DIM_IN_NAME=re.compile(r'(\d{2,3})\s*[xх*]\s*(\d{2,3})\s*[xх*]\s*(\d{2,3})\s*см', re.I)
# правдоподобие по ролям: (макс. отношение Г/Ш, макс. Г см, макс. Ш см)
_DIM_SANE={'лампа':(1.6,60,40),'ваза':(1.6,45,35),'кашпо':(1.6,60,45),'торшер':(1.6,60,50),
           'подушка':(1.6,80,80),'плед':(2.5,260,260)}
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
ROLES=['диван','кресло','пуф','столик','тв-тумба','комод','стеллаж','витрина','стенка',
 'стол обеденный','стул','камин','кашпо','торшер','ковёр','лампа','люстра','ваза','статуэтка',
 'плед','подушка','растение','зеркало','полка','часы','шторы','бра']
print("Загружаю каталог...",flush=True)
raw=rows("""select l.role, l.shop_mid, l.external_id, l.name, l.w_cm, l.d_cm, l.len_cm, l.dia_cm, l.h_cm,
 l.price_rub, l.shop, l.image_url,
 coalesce(p.direct_url, replace(replace(replace(substring(l.url from 'goto=([^&]+)'),'%3A',':'),'%2F','/'),'%3F','?')),
 coalesce(p.params->>'Материал','')||' '||coalesce(p.params->>'Назначение','')||' '||coalesce(p.params->>'Тип','')
 from lr_roles l join products p using (shop_mid, external_id)
 where l.role is not null and l.price_rub is not null and l.image_url is not null and p.in_stock
 order by l.price_rub, l.shop_mid, l.external_id""")
assert len(raw)>1000, f"каталог-запрос вернул {len(raw)} строк — SQL сломан, СТОП (не собирать пустые сеты)"


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
    w=float(r[4]) if r[4] else None; d=float(r[5]) if r[5] else (float(r[6]) if r[6] else None)
    dia=float(r[7]) if r[7] else None; h=float(r[8]) if r[8] else None
    fp=None
    if w and d: fp=w*d/10000
    elif dia: fp=math.pi*(dia/200)**2
    elif w and role=='диван': fp=w*1.0/100
    pool[k]=dict(mid=int(r[1]),eid=r[2],name=r[3],w=w,d=d,dia=dia,h=h,fp=fp,
                 price=int(r[9]),shop=r[10],img=r[11],url=r[12],**tag(r[3]))
cat={role:list(p.values()) for role,p in cat.items()}
print({k:len(v) for k,v in sorted(cat.items())},flush=True)
import bisect
def tier_band(role,tier):
    ps=sorted(x['price'] for x in cat.get(role,[]))
    if not ps: return (0,10**9)
    def pc(p): return ps[max(0,min(len(ps)-1,int(p*len(ps))))]
    return {'эконом':(pc(.05),pc(.45)),'комфорт':(pc(.35),pc(.80)),'премиум':(pc(.70),pc(.97))}[tier]

# ---------- Ф1+Ф2+Ф3+Ф4+Ф5: скоринг ----------
def pick2(role,m2,share,tier,pair,ctx,soft=False,qty=1,color_goal=None,topn=3):
    """ctx: dict(style, wood, metal, fabrics, temp, sofa_key, sofa_w, sofa_h, used_shops).
    Возвращает список топ-N кандидатов с why."""
    lo,hi=share; plo,phi=tier_band(role,tier)
    tgt_lo,tgt_hi=m2*lo/100/qty, m2*hi/100/qty
    def _collect(gate):
        cs=[]
        for it in cat.get(role,[]):
            if it['fp'] is None:
                if role in ('торшер','кашпо','камин') and it['h']: it=dict(it,fp=0.16)
                else: continue
            if not sane_dims(role,it): continue        # мусорные/перепутанные габариты — мимо
            if gate and not size_gate(ctx.get('band',''),role,it['w']): continue
            if not (tgt_lo*0.75<=it['fp']<=tgt_hi*1.25): continue
            if not (plo<=it['price']<=phi) and not soft: continue
            # ЖЁСТКИЕ ОГРАНИЧЕНИЯ ДО ЭСТЕТИКИ (sets-feasibility-first, 2026-08-05).
            # 1) товар должен подходить роли ПО ФУНКЦИИ: банкетка — не пуф, кресло-мешок — не пуф.
            fit_ok, _sub = fits_role(role, it)
            if not fit_ok:
                continue
            # 2) пропорции относительно уже выбранных предметов: вне допустимых рамок — выбываем,
            #    сколько бы баллов ни давали цвет и стиль.
            _pctx = {'chosen': ctx.get('chosen_ref') or {}, 'wall': ctx.get('wall_len_cm'),
                     'corner_sofa': ctx.get('corner_sofa', False)}
            prop_ok, _bonus, _notes = prop_check(role, it, _pctx, _sub)
            if not prop_ok:
                continue
            if not overlap_ok(emb_key(it['mid'],it['eid']),ctx.get('style_name'),ctx.get('chosen_ref',{})): continue
            cs.append(it)
        return cs
    # room-size-fit Ф2: сперва с жёстким размер-гейтом; пусто → фолбэк без гейта с пометкой
    cands=_collect(True); relaxed=False
    if not cands:
        cands=_collect(False); relaxed=bool(cands)
        if relaxed: print(f"  size_relaxed: {role} ({ctx.get('band','')}) — нет товара в размерном диапазоне",flush=True)
    if not cands: return []
    cands=cands[:70]
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
        # Ф2 v3: стиль-фит из style-scores (LLM+правила+CLIP) с ВИЗУАЛЬНЫМ весом роли
        if ctx.get('style_name'):
            sf=SS.get(emb_key(it['mid'],it['eid']))
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
sets=[]
for bi,band in enumerate(COMP['bands']):
    m2=sum(band['m2'])/2
    style_name=STYLE_OF.get(bi) if STYLE_MODE else None
    for ti,tier in enumerate(TIERS):
        pair=STYLE_PAIR[style_name] if style_name else PAIRS[(bi+ti)%len(PAIRS)]
        ctx=dict(style=style_name,wood=None,metal=None,fabrics=set(),temp='mid',
                 sofa_key=None,sofa_w=None,sofa_h=None,used_shops=set(),style_name=style_name,
                 band=band['band'])
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
        # предпочтительная роль из взаимоисключающей пары идёт РАНЬШЕ (первая в списке правил)
        for _g in _EXCL_ORDERED:
            if len(_g) > 1 and _g[0] in order and _g[1] in order:
                order = [r for r in order if r != _g[0]]
                order.insert(order.index(_g[1]), _g[0])
        for role in order:
            if role not in band['floor']: continue
            if any(role in g and (g & set(chosen)) for g in _EXCL):
                continue     # роль-конкурент уже в сете (напр. кресло при выбранном пуфе)
            q=1 if (role=='кресло' and band.get('kreslo_max')==1) else QTY.get(role,1)
            top=pick2(role,m2,band['floor'][role],tier,pair,ctx,qty=q) or \
                pick2(role,m2,band['floor'][role],tier,pair,ctx,soft=True,qty=q)
            if not top: continue
            it=top[0]
            add=(it['fp'] or 0.16)*q
            cap_hi=(OCC['floor_cap_pct'].get(band['band'],[None,COMP['global_floor_cap'][2]])[1]
                    if OCC else COMP['global_floor_cap'][2])  # динамический кап: мал. комнаты до 50%, больш. меньше
            if floor_fp+add>m2*cap_hi/100: continue
            # кап периметра: три средних пристенных предмета съедали 40% стен, и раскладка
            # переставала собираться (замер провалов 59-61, 76, 99, 108, 115, 117)
            if role in WALL_ROLES:
                if wall_len+(it['w'] or 100)*q > free_perimeter*WALL_SHARE: continue
                wall_len+=(it['w'] or 100)*q
            chosen[role]=dict(it,qty=q); alts[role]=[{k:a[k] for k in ('mid','eid','name','price','score')} for a in top[1:]]
            ctx['used_shops'].add(it['shop']); floor_fp+=add
            # якорь и капсула сета — от первых выбранных
            if role=='диван':
                ctx['sofa_key']=emb_key(it['mid'],it['eid']); ctx['sofa_w']=it['w']; ctx['sofa_h']=it['h']
                ctx['corner_sofa']=bool(re.search(r'углов', (it.get('name') or '').lower()))
                ctx['temp']=temperature(tuple(it['rgb']) if it['rgb'] else None)
                if it.get('fabric'): ctx['fabrics'].add(it['fabric'])
            for kf in ('style','wood','metal'):
                if it.get(kf) and not ctx[kf]: ctx[kf]=it[kf]
            if it.get('fabric'): ctx['fabrics'].add(it['fabric'])
        # добор при пустоте
        cap_lo=(OCC['floor_cap_pct'].get(band['band'],[COMP['global_floor_cap'][0]])[0]
                if OCC else COMP['global_floor_cap'][0])
        if floor_fp<m2*cap_lo/100:
            if m2>=41 and 'диван' in chosen:
                top=pick2('диван',m2,band['floor']['диван'],tier,pair,ctx,soft=True)
                it2=next((t for t in top if t['eid']!=chosen['диван']['eid']),None)
                if it2 and floor_fp+it2['fp']<=m2*0.40:
                    chosen['диван 2']=dict(it2,qty=1); floor_fp+=it2['fp']
            if floor_fp<m2*cap_lo/100 and 'кресло' in chosen and chosen['кресло']['qty']==1 and not band.get('kreslo_max'):
                chosen['кресло']['qty']=2; floor_fp+=chosen['кресло']['fp']
        # ковёр — ПРИВЯЗКА К ДИВАНУ (решение владельца по своду р.2): ширина ≈ диван + 25–35 см
        # с каждой стороны (схема «передние ножки»); фолбэк на % пола, если дивана/размеров нет
        if cat.get('ковёр'):
            sofa_w=(chosen.get('диван') or {}).get('w')
            best=None;bs=1e9
            for it in cat['ковёр']:
                if not it['fp'] or re.search(r'ассортимент|мехов|ванн|придверн|подложк',it['name'].lower()): continue
                if not overlap_ok(emb_key(it['mid'],it['eid']),style_name,chosen): continue
                rw=max(it.get('w') or 0, it.get('d') or 0) or None  # длинная сторона ковра
                if sofa_w and rw:
                    _ov=(OCC or {}).get('rug_rules',{}).get('verified_r2',{}).get('front_legs_scheme_side_overhang_each_cm',[25,35])
                    tgt=sofa_w+2*sum(_ov)/2  # диван + выступ с каждой стороны (occupancy)
                    score=abs(rw-tgt)
                else:
                    kv=band.get('kover_pct') or (30,50)
                    score=abs(it['fp']-(kv[0]+kv[1])/2/100*m2)*100
                if score<bs: bs=score; best=it
            # ЛУЧШЕ НЕ ДОСТРОИТЬ, ЧЕМ ДОСТРОИТЬ НЕВЕРНО (правило владельца 2026-08-05). Ковёр,
            # который не дотягивает до допустимого соотношения с диваном, в гостиной читается
            # половиком у дивана. В каталоге сейчас всего 14 ковров, крупнейший 100x150 — для
            # дивана 230 нужен от 265. Не кладём вовсе и помечаем дыру состава.
            if best and sofa_w:
                _long=max(best.get('w') or 0, best.get('d') or 0)
                _lo=PROP_RULES['rug_len_vs_sofa'][0]
                if _long and _long/sofa_w < _lo:
                    print(f"  дыра каталога: ковра от {int(sofa_w*_lo)} см нет "
                          f"(лучший {int(_long)} см) — сет без ковра",flush=True)
                    best=None
            if best: chosen['ковёр']=dict(best,qty=1)
        # люстра: диаметр по метражу + металл капсулы
        _f=(OCC or {}).get('chandelier_size',{}).get('diameter_cm_formula','')
        if '8.2' in _f:  # формула свода: (L+W)м × 8.2, ±20%
            import math as _m
            _lw=2*_m.sqrt(m2)  # приближение L+W для ~квадратной комнаты
            dmid=_lw*8.2; dlo,dhi=dmid*0.8,dmid*1.2
        else:
            dlo,dhi=(45,70) if m2<=20 else ((60,90) if m2<=30 else (60,100))
        lu=[it for it in cat.get('люстра',[]) if it['dia'] and dlo<=it['dia']<=dhi] or cat.get('люстра',[])
        lu=[it for it in lu if overlap_ok(emb_key(it['mid'],it['eid']),style_name,chosen)]  # строго: лимит важнее люстры
        if lu:
            plo,phi=tier_band('люстра',tier)
            lu2=[it for it in lu if plo<=it['price']<=phi] or lu
            lu3=[it for it in lu2 if not it.get('metal') or not ctx['metal'] or it['metal']==ctx['metal']] or lu2
            chosen['люстра']=dict(lu3[len(lu3)//2],qty=1)
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
        for role in ('плед','ваза','лампа'):  # растение убрано: декор-зелень рисует нейронка (решение владельца 2026-08-02)
            if role=='лампа' and not (chosen.get('комод') or chosen.get('тв-тумба')): continue
            top=pick2(role,m2,(0.1,3),tier,pair,ctx,soft=True)
            if top: chosen[role]=dict(top[0],qty=1); alts[role]=[{k:a[k] for k in ('mid','eid','name','price','score')} for a in top[1:]]
        for role,it in chosen.items():
            if 'cls' not in it or it.get('rgb') is None:
                p=get_thumb(it['img'],it['mid'],it['eid'])
                d1,_=dominant2(p) if p else (None,None)
                it['cls']=classify(d1); it['rgb']=list(d1) if d1 else None
        # --- валидатор состава по чек-листу гостиной (владелец 2026-08-02) ---
        CORE={'диван','столик','тв-тумба','ковёр','люстра','плед','подушка'}
        need=set(CORE)
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
        total=sum(it['price']*it['qty'] for it in chosen.values())
        fill=round(floor_fp/m2*100,1)
        sfit_agg=None
        if style_name:  # взвешенный стиль-фит сета: визуальный вес = роль × площадь (просьба владельца)
            num=den=0.0
            for r,it in chosen.items():
                c=SS.get(emb_key(it['mid'],it['eid']))
                if not c: continue
                w=ROLE_W.get(r,ROLE_W.get(r.replace(' 2',''),0.3))*max(it.get('fp') or 0.16,0.05)
                num+=(5.5 if c.get('universal') else c[style_name])*w; den+=w
            sfit_agg=round(num/max(den,1e-6),1)
        if STYLE_MODE:  # реестр для правила разнообразия следующих сетов
            BUILT.append((style_name,{emb_key(it['mid'],it['eid']) for it in chosen.values()}))
        sets.append(dict(band=band['band'],m2=m2,tier=tier,pair=list(pair),gaps=gaps,
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
json.dump(sets,open(os.path.join(HERE,OUT_SETS),'w'),ensure_ascii=False,indent=1)
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
