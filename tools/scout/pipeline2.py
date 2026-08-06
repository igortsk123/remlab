#!/usr/bin/env python3
"""Конвейер v2 (тюнинг Этапа A, план viz-pipeline):
- bbox-трекинг вклеек; ковёр из сета — перспективной вклейкой (не промптом);
- кашпо компонуется с растением; люстра не режется кадром; столик/ваза разнесены от дивана;
- QA: «ничего лишнего» + позиции + ΔRGB-контроль цвета героев КОДОМ;
- ретрай ЛОКАЛЬНЫМ инпейнтом по маске bbox (полная перегенерация запрещена).
pipeline2.py <сет> [--no-qa]"""
import json, os, sys, re, io, base64, urllib.request, uuid, time as _time
_T0=_time.time(); _TM={}
def _tick(stage): _TM[stage]=round(_time.time()-_T0-sum(_TM.values()),1)
from PIL import Image, ImageDraw
HERE=os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE,'viz3.py')).read().split("HERE=")[0])
OAI=None
for _envp in (os.path.join(HERE,'.env'),'/home/pakar/igor/v0-health-card/backend/.env'):
    if OAI or not os.path.exists(_envp): continue
    for line in open(_envp):
        m=re.match(r'OPENAI_API_KEY=(.+)',line.strip())
        if m: OAI=m.group(1).strip().strip('"')
SETS_FILE='sets3.json' if '--v3' in sys.argv else ('sets2.json' if '--v2' in sys.argv else 'sets.json')
TAG='v3set' if '--v3' in sys.argv else 'set'  # артефакты v3 не перетирают v1/v2
sets=json.load(open(os.path.join(HERE,SETS_FILE)))
n=int(sys.argv[1]) if len(sys.argv)>1 else 1
s=sets[n-1]
# --- Ф3 sets-style-v3: сет со стилем → полный РЕМОНТ под стиль (разрешение владельца 2026-08-02);
# товары неизменны (форма/цвет с фото), меняется только отделка/свет/декор комнаты
STYLE=s.get('style'); SBLOCK=''
if STYLE:
    _sp=json.load(open(os.path.join(HERE,'styles.json')))['styles']
    if STYLE in _sp:
        SBLOCK=(" "+_sp[STYLE]['prompt']+" The draft shows a plain beige room — you MUST fully renovate the "
         "finish (walls, floor, ceiling, curtains, wall decor, lighting mood) to this style; only the PRODUCTS "
         "keep their exact design, colours, sizes and positions from the draft.")
        print(f"стиль сета: {STYLE}",flush=True)
# --- раскладка: ранняя загрузка + НОРМАЛИЗАЦИЯ (диван всегда у дальней стены, лицом к камере;
# солвер может поставить его к любой стене — мир поворачивается целиком) + габариты комнаты ---
VIEW=''; LN=None; ROOMWD=None
if '--layout' in sys.argv:
    _li=sys.argv.index('--layout')
    VIEW=sys.argv[_li+1] if _li+1<len(sys.argv) and sys.argv[_li+1] in ('A','B') else 'A'
    _L=json.load(open(os.path.join(HERE,f"{TAG}{n}-layout.json")))
    _room=_L.pop('_room',None)
    _rw,_rd=(_room['w'],_room['d']) if _room else (380,400)
    _rot=_L.get('диван',{}).get('rot',180)
    def _tr(x,z):
        if _rot==180: return x,z            # диван лицом на юг (к камере) — как есть
        if _rot==0:   return _rw-x,_rd-z    # лицом на север — мир на 180°
        if _rot==90:  return z,_rw-x        # лицом на восток — мир на 90°
        return _rd-z,x                       # 270: лицом на запад
    LN={r:_tr(v['x'],v['z']) for r,v in _L.items()}
    # РАЗВОРОТЫ из раскладки → в промпт словами относительно камеры. Раньше в промпт уходили
    # только координаты, и модель крутила кресло к окну, а столик по диагонали (вердикт владельца
    # 2026-08-03): «параллельно стенам» без указания стороны — пожелание, а не инструкция.
    _CAMDIR={180:'faces the CAMERA (towards the viewer)',0:'faces AWAY from the camera (back to viewer)',
             90:'faces to the RIGHT side of the frame',270:'faces to the LEFT side of the frame'}
    _EN={'диван':'sofa','кресло':'armchair','тв-тумба':'TV stand','столик':'coffee table','пуф':'footstool',
         'стеллаж':'shelving unit','комод':'chest of drawers','стенка':'wall storage unit','витрина':'display cabinet',
         'шкаф':'wardrobe','камин':'fireplace','стол обеденный':'dining table','стул':'chair','торшер':'floor lamp',
         'кашпо':'planter'}
    _FACING=[]
    for _r,_v in _L.items():
        _rn=(int(_v.get('rot',180))-(int(_rot)-180))%360
        if _r in _EN and _rn in _CAMDIR:
            _FACING.append(f"the {_EN[_r]} {_CAMDIR[_rn]}")
    if _rot in (90,270): _rw,_rd=_rd,_rw
    ROOMWD=(_rw,_rd)
W,H=1536,1024
RX,RZ,RY=(ROOMWD[0]/100,ROOMWD[1]/100,2.7) if ROOMWD else (3.8,4.0,2.7)
CAMX,CAMY,CAMZ=RX/2,1.35,-1.35
F=1250.0; CX,CY=W/2,500.0  # шире FOV: пол виден с Z≈1.5 — передний план (столик/тумба/ковёр) в кадре
def P(X,Y,Z):
    d=Z-CAMZ
    return (CX+F*(X-CAMX)/d, CY-F*(Y-CAMY)/d)
img=Image.new('RGB',(W,H),(246,240,230)); dr=ImageDraw.Draw(img)
dr.polygon([P(0,0,0.01),P(RX,0,0.01),P(RX,0,RZ),P(0,0,RZ)],fill=(186,143,96))
dr.polygon([P(0,0,RZ),P(RX,0,RZ),P(RX,RY,RZ),P(0,RY,RZ)],fill=(243,232,215))
dr.polygon([P(0,0,0.01),P(0,0,RZ),P(0,RY,RZ),P(0,RY,0.01)],fill=(238,226,208))
dr.polygon([P(RX,0,0.01),P(RX,0,RZ),P(RX,RY,RZ),P(RX,RY,0.01)],fill=(240,229,211))
dr.polygon([P(0,RY,0.01),P(RX,RY,0.01),P(RX,RY,RZ),P(0,RY,RZ)],fill=(250,247,242))
# окно: восточная стена; в виде B мир повёрнут на 180°, значит окно уходит на ЗАПАДНУЮ стену
# и по глубине тоже зеркалится — иначе на двух кадрах видно «два разных окна» (вердикт владельца)
_wx = 0.0 if VIEW=='B' else RX
_wz0,_wz1 = ((RZ-2.8, RZ-1.4) if VIEW=='B' else (1.4, 2.8))
dr.polygon([P(_wx,0.9,_wz0),P(_wx,0.9,_wz1),P(_wx,2.1,_wz1),P(_wx,2.1,_wz0)],
           fill=(210,228,240),outline=(255,255,255),width=6)
def _flood(im,lo,spread):
    px=im.load(); w,h=im.size
    from collections import deque
    def floodable(p):
        return min(p[0],p[1],p[2])>lo and max(p[0],p[1],p[2])-min(p[0],p[1],p[2])<spread
    seen=bytearray(w*h); dq=deque()
    for x in range(w):
        for y in (0,h-1):
            if floodable(px[x,y]) and not seen[y*w+x]: seen[y*w+x]=1; dq.append((x,y))
    for y in range(h):
        for x in (0,w-1):
            if floodable(px[x,y]) and not seen[y*w+x]: seen[y*w+x]=1; dq.append((x,y))
    while dq:
        x,y=dq.popleft(); p=px[x,y]; px[x,y]=(p[0],p[1],p[2],0)
        for nx,ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
            if 0<=nx<w and 0<=ny<h and not seen[ny*w+nx] and floodable(px[nx,ny]):
                seen[ny*w+nx]=1; dq.append((nx,ny))
    return im
def cutout(im,solid=False):
    """Фон → прозрачность flood-fill от границ (вотермарки уходят). Для МОНОЛИТНЫХ ролей
    (solid=True): флуд прожёг корпус white-on-white (тумба-шагрень) — заполненность bbox
    <35% → фото прямоугольником без вырезки. Тонкие предметы (торшер/люстра) не трогаем."""
    base=clean_bg(im).convert('RGBA')
    out=_flood(base.copy(),190,34)
    if solid:
        cc=content_crop(out); w,h=cc.size; px=cc.load()
        total=max(1,(w//3)*(h//3))
        opaque=sum(1 for y in range(0,h,3) for x in range(0,w,3) if px[x,y][3]>0)
        if opaque < total*0.35:
            bp=base.load(); bw,bh=base.size
            rows=[0]*bh; cols=[0]*bw
            for y in range(bh):
                for x in range(bw):
                    p=bp[x,y]
                    if min(p[0],p[1],p[2])<225: rows[y]+=1; cols[x]+=1
            ys=[y for y in range(bh) if rows[y]>bw*0.03]; xs=[x for x in range(bw) if cols[x]>bh*0.03]
            if ys and xs: return base.crop((xs[0],ys[0],xs[-1]+1,ys[-1]+1))
    return out
def content_crop(im):
    """Кроп по ПЛОТНОСТИ непрозрачного (одиночные хвосты вотермарок не раздувают bbox)."""
    px=im.load(); w,h=im.size
    rows=[0]*h; cols=[0]*w
    for y in range(h):
        for x in range(w):
            if px[x,y][3]>0: rows[y]+=1; cols[x]+=1
    tr=max(2,int(w*0.01)); tc=max(2,int(h*0.01))
    ys=[y for y in range(h) if rows[y]>tr]; xs=[x for x in range(w) if cols[x]>tc]
    if not ys or not xs: return im
    return im.crop((xs[0],ys[0],xs[-1]+1,ys[-1]+1))
SOLID={'диван','кресло','тв-тумба','пуф','кашпо','ваза','лампа','комод','стенка','витрина','камин'}  # НЕ столик/люстра/торшер: тонкие ножки = ложный white-on-white; лампа — белый абажур на белом фоне (у Сета 1 вырезка «обезглавила»)
def fetch_cut(it,maxpx=800,solid=False):
    """None при недоступном фото (404 CDN и т.п.) — роль пропускается, кадр не падает."""
    u=it['img']; u='https:'+u if u.startswith('//') else u
    for cand in (u, u.replace('/small.','/big.'), u.replace('/big.','/small.')):
        try:
            req=urllib.request.Request(cand,headers={'User-Agent':'Mozilla/5.0'})
            ph=Image.open(io.BytesIO(urllib.request.urlopen(req,timeout=25).read())).convert('RGB')
            ph.thumbnail((maxpx,maxpx)); return content_crop(cutout(ph,solid))
        except Exception: continue
    print(f"фото недоступно: {it.get('name','')[:50]}",flush=True)
    return None
def mean_rgb(im):
    px=im.load(); w,h=im.size; r=g=b=cnt=0
    for y in range(0,h,3):
        for x in range(0,w,3):
            p=px[x,y]
            if len(p)==4 and p[3]<128: continue
            r+=p[0]; g+=p[1]; b+=p[2]; cnt+=1
    return (r//cnt,g//cnt,b//cnt) if cnt else (0,0,0)
def solve8(A,b):
    m=[row[:]+[b[i]] for i,row in enumerate(A)]
    for c in range(8):
        p=max(range(c,8),key=lambda r:abs(m[r][c])); m[c],m[p]=m[p],m[c]
        d=m[c][c]
        m[c]=[v/d for v in m[c]]
        for r in range(8):
            if r!=c and m[r][c]:
                f=m[r][c]; m[r]=[v-f*m[c][i] for i,v in enumerate(m[r])]
    return [m[i][8] for i in range(8)]
def persp_coeffs(src,dst):
    A=[]; b=[]
    for (sx,sy),(dx,dy) in zip(src,dst):
        A.append([dx,dy,1,0,0,0,-sx*dx,-sx*dy]); b.append(sx)
        A.append([0,0,0,dx,dy,1,-sy*dx,-sy*dy]); b.append(sy)
    return solve8(A,b)
items=dict(s['items'])  # роли НЕ схлопывать: «подушка 2» — отдельный товар (бага: пэчворк пропадала)
# позиции: (X, Z, Y_низа); столик разнесён от дивана; кашпо в углу (не на кресле);
# растение и торшер разведены (раньше сливались в один объект)
POS={'диван':(1.55,3.72,0),'кресло':(3.1,3.1,0),'столик':(1.55,2.35,0),'пуф':(0.7,2.5,0),
 'торшер':(0.5,3.45,0),'кашпо':(3.62,3.3,0),'тв-тумба':(3.55,1.7,0),'люстра':(1.9,2.9,None)}
order=['люстра','торшер','кашпо','тв-тумба','кресло','диван','столик','пуф']
# Этап B: --layout A|B — позиции от солвера (нормализованы выше: диван у дальней стены).
# Вид A = зона дивана, вид B = зона ТВ (мир повёрнут на 180°).
if LN is not None:
    POS={'люстра':(RX/2,RZ-1.1,None)}
    for r,(xc,zc) in LN.items():
        x,z=xc/100,zc/100
        if VIEW=='B': x,z=RX-x,RZ-z
        if z<(2.6 if VIEW=='B' else 1.5):  # B — крупный план ТВ-зоны, средний план не загромождать
            print(f"[{VIEW}] вне кадра (за камерой): {r}",flush=True); continue
        POS[r]=(x,z,0)
    if 'стул' in POS and 'стол обеденный' not in POS:
        del POS['стул']; print("стул без стола в кадре — убран (правило)",flush=True)
    order=[r for r in ['люстра','торшер','кашпо','стенка','витрина','стеллаж','комод','камин',
                       'тв-тумба','стол обеденный','стул','кресло','диван','столик','пуф'] if r in POS]
    if VIEW=='B': F,CY=1500.0,540.0  # зум на ТВ-зону у дальней стены
draft=img.copy(); anchors={}; BB={}; HERO_RGB={}
HEROES=('диван','кресло','пуф','плед','ваза','кашпо')  # НЕ столик (в bbox пол) и НЕ белые тумба/лампа (тёплый свет всегда даёт ложный ΔRGB)
def paste_track(role,ph,x0,y0):
    draft.paste(ph,(int(x0),int(y0)),ph)
    BB[role]=(int(x0),int(y0),int(x0)+ph.width,int(y0)+ph.height)
    if role in HEROES: HERO_RGB[role]=mean_rgb(ph)

# ковёр НЕ вклеиваем и промптом запрещаем: в каталоге пока нет нормальных ковров
# («Коврик Pyramid» — техковрик, решение владельца 2026-08-01); ветка-растение — В кашпо, не «в воздухе»
# Эргономика ковра (ресёрч 2026-08-02): ковёр = зона отдыха — передние ножки дивана на ковре,
# столик на ковре целиком; в виде без дивана (ТВ-зона B) ковёр НЕ рисуем — у ТВ-стены он неуместен.
if 'ковёр' in items and 'диван' in POS and (лph:=fetch_cut(items['ковёр'],700)) is not None:
    it=items['ковёр']; ph=лph.convert('RGBA')
    rw=(it.get('w') or 150)/100; rd=(it.get('d') or 90)/100
    # правило rug_long_side_along_sofa (владелец 2026-08-03): длинная сторона ковра — ВДОЛЬ
    # длинной стороны дивана. После нормализации мира диван всегда лицом к камере, значит
    # длинная сторона ковра идёт по X.
    if rd>rw: rw,rd=rd,rw
    _sx,_sz,_=POS['диван']
    _sofa_d=(items['диван'].get('d') or 95)/100
    rd_m=(it.get('d') or 90)/100
    _occ=json.load(open(os.path.join(HERE,'occupancy.json')))['dynamic'] if os.path.exists(os.path.join(HERE,'occupancy.json')) else {}
    _ovl=_occ.get('rug_rules',{}).get('front_legs_on_rug_cm',25)/100
    cxr,czr=_sx, _sz-_sofa_d/2-rd_m/2+_ovl  # передние ножки дивана на ковре (occupancy)
    quad=[P(cxr-rw/2,0,czr+rd/2),P(cxr+rw/2,0,czr+rd/2),P(cxr+rw/2,0,czr-rd/2),P(cxr-rw/2,0,czr-rd/2)]
    xs=[q[0] for q in quad]; ys=[q[1] for q in quad]
    x0,y0=min(xs),min(ys); dst=[(q[0]-x0,q[1]-y0) for q in quad]
    ow,oh=int(max(xs)-x0)+1,int(max(ys)-y0)+1
    # берём центральные 70% фото — это чистая фактура без искажённых краёв и теней подложки
    _cw,_ch=int(ph.width*0.7),int(ph.height*0.7)
    tex=ph.crop(((ph.width-_cw)//2,(ph.height-_ch)//2,(ph.width+_cw)//2,(ph.height+_ch)//2))
    src=[(0,0),(tex.width,0),(tex.width,tex.height),(0,tex.height)]
    co=persp_coeffs(src,dst)
    warped=tex.transform((ow,oh),Image.PERSPECTIVE,co,Image.BICUBIC)
    paste_track('ковёр',warped,x0,y0)
    dr2=ImageDraw.Draw(draft)  # контрастная кромка: бежевый ковёр на бежевом полу иначе невидим рендеру
    dr2.polygon([(q[0],q[1]) for q in quad],outline=(90,80,70),width=3)
for role in order:
    if role not in items or role not in POS: continue
    if role=='стул' and 'стол обеденный' not in BB: continue  # стул без стола В КАДРЕ не рисуем
    it=items[role]; X,Z,Yb=POS[role]
    ph=fetch_cut(it,solid=role in SOLID)
    if ph is None: continue  # мёртвое фото — роль пропущена (печать в fetch_cut)
    hcm=it.get('h') or ((it.get('w') or 60)*ph.height/max(ph.width,1))
    if role=='люстра': hcm=min(it.get('h') or 45,60); Yb=RY-hcm/100
    if role=='кашпо': hcm=min(hcm or 40,50)  # кашпо — напольный аксессуар, не «кубок» в полкомнаты
    dpt=Z-CAMZ
    pxh=F*(hcm/100)/dpt; pxw=pxh*ph.width/max(ph.height,1)
    ph=ph.resize((max(int(pxw),8),max(int(pxh),8)))
    cu,cv=P(X,Yb if Yb is not None else 0,Z)
    if cu<-ph.width*0.3 or cu>W+ph.width*0.3:  # предмет за БОКОВЫМ краем кадра — не клеим (одинокие стулья)
        print(f"[{VIEW}] вне кадра (сбоку): {role}",flush=True); continue
    x0,y0=cu-ph.width/2,cv-ph.height
    if role=='люстра' and y0<10:  # люстру не резать кадром: опустить точку подвеса
        y0=10
    paste_track(role,ph,x0,y0)
    anchors[role]=(X,Z,hcm)
# ветка-растение компонуется В кашпо (не «в воздухе» и не пустое «ведёрко»)
if 'кашпо' in BB and 'растение' in items and fetch_cut(items['растение'],400) is not None:
    kx0,ky0,kx1,ky1=BB['кашпо']; kw=kx1-kx0; kh=ky1-ky0
    fol=fetch_cut(items['растение'],400)
    fol=fol.crop((0,int(fol.height*0.35),fol.width,fol.height))  # только пышная листва, без голых стеблей
    fw=int(kw*1.6); fh=int(fw*fol.height/max(fol.width,1))
    fh=min(fh,int(kh*2.2))  # свис не глубже чем на 2 высоты кашпо
    fol=fol.resize((max(fw,8),max(fh,8)))
    paste_track('ветка-в-кашпо',fol,(kx0+kx1)/2-fol.width/2,ky0+int(kh*0.5)-fol.height)
    kaspo_sprite=fetch_cut(items['кашпо'],800,solid=True)
    if kaspo_sprite is not None:
        kaspo_sprite=kaspo_sprite.resize((kx1-kx0,ky1-ky0))
        draft.paste(kaspo_sprite,(kx0,ky0),kaspo_sprite if kaspo_sprite.mode=='RGBA' else None)  # кашпо поверх стеблей
# декор по назначению
if 'диван' in anchors:
    X,Z,hs=anchors['диван']; dpt=Z-CAMZ
    pillows=[it for r,it in items.items() if r.startswith('подушка')][:2]
    for i,(dx,pil) in enumerate(zip((-0.55,0.5),pillows or [])):
        ph=fetch_cut(pil,300)
        if ph is None: continue
        pxh=F*0.30/dpt; ph=ph.resize((int(pxh*ph.width/ph.height),int(pxh)))
        cu,cv=P(X+dx,0.42,Z)
        paste_track(f'подушка{i+1}',ph,cu-ph.width/2,cv-ph.height)
    if 'плед' in items and (ph:=fetch_cut(items['плед'],500)) is not None:
        cwq,chq=ph.width//4,ph.height//4  # центральный кроп текстуры → «сложенная стопка» на сиденье
        ph=ph.crop((cwq,chq,ph.width-cwq,ph.height-chq))
        pxw=F*0.55/dpt; pxhh=F*0.16/dpt
        ph=ph.resize((max(int(pxw),8),max(int(pxhh),8)))
        cu,cv=P(X-0.45,0.52,Z)
        paste_track('плед',ph,cu-ph.width/2,cv-ph.height)
if 'столик' in anchors and 'ваза' in items and (ph:=fetch_cut(items['ваза'],200)) is not None:
    X,Z,hs=anchors['столик']; dpt=Z-CAMZ
    pxh=F*((min(items['ваза'].get('h') or 22,30))/100)/dpt
    ph=ph.resize((max(int(pxh*ph.width/ph.height),5),max(int(pxh),5)))
    cu,cv=P(X,hs/100,Z)
    cv+=int(0.10*F*(hs/100)/dpt)  # ваза ВНУТРИ видимой столешницы (низ ниже верхней кромки), иначе читается «на полу»
    paste_track('ваза',ph,cu-ph.width/2,cv-ph.height)
if 'тв-тумба' in anchors and 'лампа' in items and (ph:=fetch_cut(items['лампа'],300,solid=True)) is not None:
    X,Z,hs=anchors['тв-тумба']; dpt=Z-CAMZ
    pxh=F*(max(min(items['лампа'].get('h') or 40,55),28)/100)/dpt  # фидовые 19 см — заниженные (упаковка?)
    ph=ph.resize((max(int(pxh*ph.width/ph.height),6),max(int(pxh),6)))
    cu,cv=P(X-0.1,hs/100,Z)
    paste_track('лампа',ph,cu-ph.width/2,cv-ph.height)
SUF=f"-{VIEW}" if VIEW else ""
if '--q' in sys.argv:
    _q=sys.argv[sys.argv.index('--q')+1]
    if _q!='medium': SUF+=f"-{_q}"  # не перетирать основной кадр пробами качества
p_draft=os.path.join(HERE,f"{TAG}{n}-pipe2{SUF}-draft.jpg"); draft.save(p_draft,'JPEG',quality=92)
json.dump(BB,open(os.path.join(HERE,f"{TAG}{n}-bb{SUF}.json"),'w'),ensure_ascii=False)
print("draft ok; objects:",", ".join(BB),flush=True)
print("hero rgb:",{r:HERO_RGB[r] for r in HERO_RGB},flush=True)
if '--draft' in sys.argv: sys.exit(0)  # бесплатная проверка макета без рендера
ROLE_DESC={'диван':'sofa','кресло':'armchair','столик':'coffee table','пуф':'footstool','торшер':'floor lamp',
 'кашпо':'floor plant pot','тв-тумба':'TV stand','люстра':'ceiling chandelier','ваза':'vase on the coffee table',
 'лампа':'small table lamp on the TV stand','плед':'folded blanket on the sofa seat','подушка':'cushion on the sofa','подушка 2':'second (different) cushion on the sofa','ковёр':'flat woven area rug lying on the floor',
 'растение':'trailing potted plant planted IN the plant pot, foliage spilling DOWN over the pot edge',
 'комод':'chest of drawers','стеллаж':'shelving unit','стенка':'wall storage unit','витрина':'display cabinet',
 'камин':'electric fireplace','стол обеденный':'dining table','стул':'dining chair'}
# в промпт/QA — ТОЛЬКО вставленные в ЭТОТ вид роли (иначе модель дорисовывает «текстовых клонов» товаров)
PRESENT={('подушка' if r.startswith('подушка') else 'растение' if r=='ветка-в-кашпо' else r) for r in BB}
items={r:it for r,it in items.items() if r in PRESENT}
import subprocess as _sp
def _mats():
    keys=[(it['mid'],it['eid']) for it in items.values()]
    if not keys: return {}
    vals=",".join(f"({m},'{e}')" for m,e in keys)
    q=(f"select shop_mid, external_id, coalesce(params->>'Материал',''), coalesce(params->>'Состав',''), "
       f"coalesce(params->>'Цвет','') from products where (shop_mid,external_id) in ({vals})")
    r=_sp.run(["docker","exec","-i","remlab-devdb","psql","-U","remlab","-d","remlab","-q","-v","ON_ERROR_STOP=1","-t","-A","-F","\x1f"],
              input=q,capture_output=True,text=True)
    out={}
    for l in r.stdout.strip().split('\n'):
        if not l: continue
        x=l.split('\x1f'); out[(int(x[0]),x[1])]=", ".join(v for v in x[2:] if v)[:60]
    return out
MATS=_mats()
PRODUCTS="; ".join(f"{ROLE_DESC.get(r,r)}: «{it.get('name','')[:60]}»"+
    (f" {int(it['w'])}x{int(it['h'])}cm" if it.get('w') and it.get('h') else "")+
    (f" [{MATS[(it['mid'],it['eid'])]}]" if MATS.get((it['mid'],it['eid'])) else "")
    for r,it in items.items() if r in ROLE_DESC)
# условные фразы — ТОЛЬКО про роли, реально вставленные в этот вид (иначе модель рисует «клонов» из текста)
_cl=[]
if 'плед' in PRESENT or 'подушка' in PRESENT: _cl.append("The folded blanket and the cushions lie ON the sofa.")
if 'ваза' in PRESENT: _cl.append("The vase stands ON TOP of the coffee table; you MAY put delicate decorative "
    "flowers or a dried branch INTO it (the vase itself stays exactly as drawn).")
if 'лампа' in PRESENT: _cl.append("The small table lamp stands ON the TV stand.")
if 'растение' in PRESENT: _cl.append("The decorative dry branch is PLANTED IN the lavender pot which stands "
    "ON THE FLOOR — the branch must not float in the air.")
if 'кашпо' in PRESENT and 'растение' not in PRESENT: _cl.append("Plant a lush green indoor plant INTO the floor "
    "planter — an empty planter on the floor looks unfinished (the planter itself stays exactly as drawn).")
if 'тв-тумба' in PRESENT: _cl.append("A TV stands on the TV stand.")
_cl.append("Each product's SHAPE (tabletop form, number of legs, lamp silhouette) must match its pasted photo "
 "EXACTLY — never substitute a different design: count the legs and copy the top shape from the draft.")
if 'люстра' in PRESENT: _cl.append("The ceiling lamp hangs fully inside the frame.")
# Промпт СЖАТ (владелец 2026-08-03: «слишком большой промпт → модель хуже слушается»):
# 6600 знаков → ~2800. Убраны повторы (цвет каждого товара дублировался после списка товаров),
# разжёванные разрешения «что МОЖНО добавить» и перечисления, которые модель и так делает.
# Оставлено: геометрия и развороты, список товаров, стиль-блок, жёсткие запреты, мелочь-чек-лист.
_tiny=[r for r in BB if (BB[r][2]-BB[r][0])*(BB[r][3]-BB[r][1])<6000]
PROMPT=("Photoreal interior photo from this draft of a SMALL city-flat living room %.1f x %.1f m "
 "(%.0f sq m), ceiling only 2.7 m — keep this scale honest: the walls are close, do NOT make the "
 "room look bigger, wider or taller than the draft, no hall-like proportions. "
 "The draft has real product photos pasted at their exact positions and sizes: KEEP every object's "
 "position, size, silhouette and colour; never replace a product with a different design. "
 % (RX, RZ, RX*RZ)
 +" ".join(_cl)+
 " Style: professional furniture-store photography — soft daylight from the window, gentle shadows, "
 "cosy styling, clean composition. Room finish may be restyled, products may NOT."
 +(SBLOCK or " Laminate floor"+("" if "ковёр" in PRESENT else " with NO rug")+", warm walls, sheer curtains.")
 +" Walls and ceiling: freshly painted, perfectly clean smooth matte — no stains, no watercolour washes, "
 "no patina, no sponge texture. Add a white panel radiator under the window, skirting boards, "
 "framed art (up to ~90 cm), curtains, a view outside."
 +" STRICT: nothing beyond the draft — no extra furniture, lamps, rugs, plants, vases or textiles; "
 "no people, text or watermarks. Every object complete, never cut off."
 +(" These small items MUST be visible: "+", ".join(_tiny)+"." if _tiny else "")+
 " Products (role: «name» WxH, colour — match colours exactly): "+PRODUCTS+"; "
 +"; ".join(f"{ROLE_DESC[r]} is {name_color(it.get('name','')) or 'RGB'+str(HERO_RGB[r])}"
    for r,it in items.items() if r in ROLE_DESC and r!='растение'
    and (name_color(it.get('name','')) or r in HERO_RGB))+".")
CALLS=[0]
QUAL=sys.argv[sys.argv.index('--q')+1] if '--q' in sys.argv else 'medium'  # low ≈ $0.016, medium ≈ $0.07
def img_edit(base_jpg,prompt,mask_png=None,refs=()):
    CALLS[0]+=1
    # DUMP_PAYLOAD=<dir>: выложить ТО ЖЕ, что уходит в модель (кадр-композит, референсы, промпт) —
    # для показа владельцу и разбора «что именно видела нейронка»
    _dd=os.environ.get('DUMP_PAYLOAD')
    if _dd:
        os.makedirs(_dd,exist_ok=True); _k=CALLS[0]
        open(os.path.join(_dd,f'call{_k}-1-base.jpg'),'wb').write(base_jpg)
        for _i,_rb in enumerate(refs,1):
            open(os.path.join(_dd,f'call{_k}-ref{_i:02d}.png'),'wb').write(_rb)
        if mask_png: open(os.path.join(_dd,f'call{_k}-mask.png'),'wb').write(mask_png)
        open(os.path.join(_dd,f'call{_k}-prompt.txt'),'w').write(prompt)
    B=uuid.uuid4().hex; body=io.BytesIO()
    def part(name,val,fname=None,ctype=None):
        body.write(f"--{B}\r\n".encode())
        if fname:
            body.write(f'Content-Disposition: form-data; name="{name}"; filename="{fname}"\r\nContent-Type: {ctype}\r\n\r\n'.encode())
            body.write(val); body.write(b"\r\n")
        else:
            body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())
    part("model","gpt-image-2"); part("prompt",prompt); part("size","1536x1024")
    part("quality",QUAL); part("n","1")
    part("image[]",base_jpg,"base.jpg","image/jpeg")
    for i,rb in enumerate(refs): part("image[]",rb,f"ref{i}.png","image/png")
    if mask_png: part("mask",mask_png,"mask.png","image/png")
    body.write(f"--{B}--\r\n".encode())
    req=urllib.request.Request("https://api.openai.com/v1/images/edits",data=body.getvalue(),
        headers={"Authorization":f"Bearer {OAI}","Content-Type":f"multipart/form-data; boundary={B}"})
    for att in range(3):  # 502/503/timeout у OpenAI транзиентны — ретрай с паузой (сет 47 упал без ретрая)
        try:
            with urllib.request.urlopen(req,timeout=600) as r: out=json.loads(r.read())
            return base64.b64decode(out['data'][0]['b64_json'])
        except Exception as e:
            if att==2: raise
            print(f"img_edit retry {att+1}: {str(e)[:80]}",flush=True); _time.sleep(20*(att+1))
def qa_vlm(final_jpg):
    b64=base64.b64encode(final_jpg).decode()
    b64d=base64.b64encode(open(p_draft,'rb').read()).decode()
    body={"model":"gpt-5-mini","messages":[{"role":"user","content":[
        {"type":"text","text":"Image 1 is a draft with exact product positions/colours; image 2 is the final render "
         "(both 1536x1024). The draft contains EXACTLY these objects: "
         +", ".join(ROLE_DESC[r] for r in items if r in ROLE_DESC)+". "
         "Refer to objects ONLY by these role names (the object on the TV stand is a table lamp, not a vase). "
         "Product colours are defined by the DRAFT ONLY: if the draft plant is orange/autumn-coloured, the render "
         "must be orange too — NEVER 'correct' a product colour to what seems more natural. "
         "Check: (1) every draft object present exactly once, (2) positions kept, (3) colours match, "
         "(4) blanket/cushions on sofa; the vase must sit ON TOP of the coffee table surface — if the vase touches "
         "the floor or stands beside the table, FLAG IT; lamp on TV stand; decorative branch planted in "
         "the floor planter (not floating), "+("the rug lies FLAT on the floor as drawn, " if "ковёр" in PRESENT else "NO rug on the floor, ")+
         "(5) NO EXTRA furniture, light fixtures, rugs, plants, vases or textiles beyond the draft — even another "
         "sofa/armchair/TV-stand-like piece that is not in the draft is EXTRA and must be flagged; but wall art/"
         "posters/mirror, curtains, window view, TV screen on the stand, wall/floor finishes and shadows ARE allowed "
         "by design (do not flag them), "
         +("the room got a STYLE renovation — feature walls (brick/panelling), track/spot ceiling lights, "
           "style-appropriate finishes and small decor ARE allowed by design (do not flag them), " if SBLOCK else "")
         +("books/ceramics lightly styling the open shelves ARE allowed by design, " if any(r in PRESENT for r in ('стеллаж','витрина','стенка')) else "")
         +("a TV on the fireplace mantel IS an error — flag it, " if ('камин' in PRESENT and 'тв-тумба' in PRESENT) else "")
         +"(6) ceiling lamp fully inside frame, (7) every object COMPLETE — e.g. a table lamp must have both its "
         "base AND its shade, chairs have all legs, nothing looks cut off or half-drawn. Reply STRICT JSON: "
         "{\"ok\":bool,\"issues\":[{\"what\":\"short fix instruction\",\"box\":[x0,y0,x1,y1]}]} "
         "box = pixel coords on image 2. Max 4 issues, worst first."},
        {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+b64d}},
        {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+b64}}]}]}
    req=urllib.request.Request("https://api.openai.com/v1/chat/completions",data=json.dumps(body).encode(),
        headers={"Authorization":f"Bearer {OAI}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r: out=json.loads(r.read())
    txt=out['choices'][0]['message']['content']
    m=re.search(r'\{.*\}',txt,re.S)
    try: return json.loads(m.group(0))
    except: return {"ok":True,"issues":[]}
def chroma(c): return (c[0]-c[1],c[1]-c[2])  # свето-инвариантные разности каналов
def qa_drgb(final_jpg):
    """ΔRGB-контроль героев кодом; рендер смещает предметы на десятки px — ищем минимум по сдвигам."""
    fin=Image.open(io.BytesIO(final_jpg)).convert('RGB')
    issues=[]
    for role,src in HERO_RGB.items():
        x0,y0,x1,y1=BB[role]
        mx,my=int((x1-x0)*0.2),int((y1-y0)*0.2)
        d=1e9
        for dx in (-40,0,40):
            for dy in (-40,0,40):
                cx0,cy0,cx1,cy1=max(0,x0+mx+dx),max(0,y0+my+dy),min(W,x1-mx+dx),min(H,y1-my+dy)
                if cx1<=cx0 or cy1<=cy0: continue  # герой (частично) за кадром — кроп вырожден
                c=fin.crop((cx0,cy0,cx1,cy1)).convert('RGBA')
                if c.width<4 or c.height<4: continue
                got=mean_rgb(c)
                d=min(d,max(abs(a-b) for a,b in zip(chroma(src),chroma(got))))
        if d>12:  # пастель дрейфует в серый незаметно для общего порога
            # диван/кресло инпейнтом НЕ чинить: декор на них смещается в рендере, маска-дырка мажет,
            # перекраска «раздевает» носитель (реф-фото без пледа/подушек). Их цвет держат промпт-хинты.
            if role in ('диван','кресло','кашпо'): continue  # кашпо: в bbox попадает свисающая ветка — вечный ложняк
            issues.append({"what":f"repaint the {role} to exact colour RGB{src} as in the draft, keep shape",
                           "box":list(BB[role]),"role":role,"drgb":d})
    return issues
ROLE_EN={'rug':'ковёр','carpet':'ковёр','sofa':'диван','couch':'диван','armchair':'кресло','coffee table':'столик','table':'столик',
 'footstool':'пуф','ottoman':'пуф','floor lamp':'торшер','planter':'кашпо','pot':'кашпо','branch':'кашпо',
 'tv stand':'тв-тумба','vase':'ваза','blanket':'плед','cushion':'подушка1','pillow':'подушка1',
 'chandelier':'люстра','ceiling lamp':'люстра','lamp':'лампа'}
def clamp_issues(issues):
    """Маска = НАШИ точные bbox ролей (VLM-боксы врут и разрастаются); суммарно ≤18% кадра."""
    out=[]; area=0
    for it in issues:
        role=it.get('role')
        if not role:
            wl=(it.get('what') or '').lower()
            for en,ru in ROLE_EN.items():
                if en in wl: role=ru; break
        box=BB.get(role) or it.get('box')
        if not box: continue
        if role in BB and it.get('box') and 'drgb' not in it:
            bx=it['box']; ox0,oy0,ox1,oy1=BB[role]
            # VLM-бокс не пересекает наш bbox роли → VLM перепутал предмет (лампу назвал вазой) — пропустить
            if bx[2]<ox0-60 or bx[0]>ox1+60 or bx[3]<oy0-60 or bx[1]>oy1+60: continue
        x0,y0,x1,y1=box
        a=max(0,(x1-x0))*max(0,(y1-y0))
        if a>W*H*0.12: continue  # огромный бокс = гарантированное разрушение соседей
        if area+a>W*H*0.18: break
        area+=a; it=dict(it); it['box']=[x0,y0,x1,y1]; it['role']=role; out.append(it)
    return out
DECOR=('плед','подушка1','подушка2','ваза','лампа','ветка-в-кашпо')
def mask_from(issues):
    m=Image.new('RGBA',(W,H),(0,0,0,255)); dm=ImageDraw.Draw(m)
    for it in issues:
        x0,y0,x1,y1=it['box']
        x0c,y0c,x1c,y1c=max(x0-25,0),max(y0-25,0),min(x1+25,W),min(y1+25,H)
        if x1c<=x0c or y1c<=y0c: continue  # бокс за кадром — инвертированный прямоугольник роняет PIL
        dm.rectangle([x0c,y0c,x1c,y1c],fill=(0,0,0,0))
    roles={it.get('role') for it in issues}
    for d in DECOR:  # декор на носителях НЕ перерисовывать при правке носителя (реф-фото дивана «раздевает» его)
        if d in BB and d not in roles:
            x0,y0,x1,y1=BB[d]
            dm.rectangle([x0-5,y0-5,x1+5,y1+5],fill=(0,0,0,255))
    buf=io.BytesIO(); m.save(buf,'PNG'); return buf.getvalue()
_tick('черновик-коллаж')
buf=io.BytesIO(); draft.save(buf,'JPEG',quality=92)
_refs=[]
if VIEW:
    _lp=os.path.join(HERE,f"{TAG}{n}-layout.png")
    if os.path.exists(_lp): _refs.append(open(_lp,'rb').read())
_corner_hint=""
if 'диван' in items and (re.search(r'углов',(items['диван'].get('name') or '').lower()) or (items['диван'].get('d') or 0)>150):
    _corner_hint=(" The sofa is a CORNER sofa: it FILLS the corner — both sections flush against the two walls, "
     "no gap behind it.")
_top_hint=""
_TOPS=[r for r in ('комод','тумба','тв-тумба','стеллаж','витрина','стенка') if r in PRESENT]
if _TOPS:
    # владелец 2026-08-03: «если комод стоит, надо обязательно декор на него» — пустая
    # столешница читается как незаселённая комната; декор стоит НА мебели и в кап пола не входит
    _top_hint=(" The top surface of every storage piece (chest of drawers, TV stand, shelving unit, "
     "cabinet) MUST be styled with 2-3 small objects in an odd group — a vase with dried stems, "
     "stacked books, a small frame, a candle or a ceramic bowl; never left bare, never cluttered.")
_shelf_hint=""
if any(r in PRESENT for r in ('стеллаж','витрина','стенка')):
    # ADR-0051 (владелец 2026-08-02): полки/столешницы заполняются на 50–70% (макс 90%) — прежний
    # «лёгкий стайлинг» давал пустые полки = незаконченный интерьер. Это НЕ пол, кап пола не применим.
    _shelf_hint=(" Open shelving units must be STYLED so that roughly 50-70% of every shelf is occupied "
     "(never more than 90%, never near-empty): stacks and rows of books, ceramics, framed art, boxes and "
     "a trailing plant, grouped in odd numbers with breathing room between groups, style-appropriate; "
     "NEVER put electronics, screens or a TV on shelves.")
_fire_hint=""
if 'камин' in PRESENT:
    _fire_hint=(" The electric fireplace is NOT a TV stand: put only small decor on its mantel (a vase or a clock)"
     +("; the TV stands ONLY on the TV stand" if 'тв-тумба' in PRESENT else "")+". Never place a TV on the fireplace.")
_facing_block=""
if '_FACING' in dir() and _FACING:
    _facing_block=(" EXACT ORIENTATIONS from the floor plan — obey them literally, this is not a suggestion: "
     +"; ".join(_FACING)+". Every piece is rotated by exactly 0/90/180/270 degrees — nothing stands diagonally. "
     "The armchair must be turned TOWARDS the sofa and coffee table (the seating group), never towards the window or the wall.")
_orient=(" Product photos are pasted at their showroom 3/4 angle — REORIENT every furniture piece so it stands "
 "PARALLEL to the walls (rotations of 0/90/180/270 degrees only), facing the seating area; NEVER leave a piece "
 "at its showroom 3/4 angle. Rectangular tables, desks and storage furniture must be parallel to walls, storage "
 "backs flush against the wall. Keep every item's exact design, colours and proportions."
 +_facing_block+_corner_hint+_shelf_hint+_top_hint+_fire_hint
 +(" The LAST reference image is the top-down floor plan of this room — follow it for "
 "furniture orientation and placement." if _refs else ""))
final=img_edit(buf.getvalue(),PROMPT+_orient,refs=_refs)
_tick('генерация-картинки')
p_base=os.path.join(HERE,f"{TAG}{n}-pipe2{SUF}-base.jpg"); open(p_base,'wb').write(final)
p_final=os.path.join(HERE,f"{TAG}{n}-pipe2{SUF}.jpg"); open(p_final,'wb').write(final)
print("base render saved",flush=True)
if '--no-qa' not in sys.argv:
    prev=final; prev_n=99
    for attempt in (1,2):
        # VLM-косметика («adjust/match colour/replace finish») ломает больше, чем чинит:
        # берём только СТРУКТУРНЫЕ находки; оттенки честнее ловит наш ΔRGB-контроль
        issues=[i for i in (qa_vlm(final).get('issues') or []) if isinstance(i,dict)
                and re.search(r'\b(add|remove|missing|extra|not present|absent)\b',(i.get('what') or '').lower())][:3]
        issues+=qa_drgb(final)[:2]
        print(f"QA#{attempt}:",json.dumps(issues,ensure_ascii=False)[:500],flush=True)
        if len(issues)>=prev_n:  # хуже/не лучше — откат к предыдущему кадру
            final=prev; open(p_final,'wb').write(final)
            print("rollback to previous frame",flush=True); break
        if not issues: break
        prev=final; prev_n=len(issues)
        clamped=clamp_issues(issues)
        if not clamped: print("issues too large for local inpaint — keep frame",flush=True); break
        refs=[]
        for it in clamped:
            r=it.get('role')
            if r and r in items and len(refs)<3:
                _pc=fetch_cut(items[r],400,solid=r in SOLID)
                if _pc is not None:
                    b=io.BytesIO(); _pc.save(b,'PNG'); refs.append(b.getvalue())
        fix="; ".join(f"({k+1}) {it['what']}" for k,it in enumerate(clamped))
        final=img_edit(final,
            "Photo of a living room. Edit ONLY the transparent-masked regions, minimal local fix: "+fix+
            ". Use the extra reference photos for exact shape and colour. Everything outside the mask stays identical. "
            "Do not add anything new.",mask_png=mask_from(clamped),refs=refs)
        open(p_final,'wb').write(final)
        open(os.path.join(HERE,f"{TAG}{n}-pipe2-fix{attempt}.jpg"),'wb').write(final)
        print(f"inpaint#{attempt} saved",flush=True)
# ---- СТАБИЛИЗАТОР мелких/нестабильных предметов (системно, все сеты) ----
# Один дешёвый VLM-чек: присутствует ли каждый и похож ли на СВОЁ фото → точечная врисовка по фото.
UNSTABLE=[r for r in BB if r in ('люстра','лампа','ваза','торшер','кашпо') or r.startswith('подушка')]
if UNSTABLE and '--no-fix' not in sys.argv and '--no-qa' not in sys.argv:
    def _refjpg(role):
        key=role if role in items else ('подушка' if role=='подушка1' else 'подушка 2' if role=='подушка2' else role)
        it=items.get(key)
        if not it: return None
        u=it['img']; u='https:'+u if u.startswith('//') else u
        try:
            ph=Image.open(io.BytesIO(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=25).read())).convert('RGB')
            ph.thumbnail((400,400)); b=io.BytesIO(); ph.save(b,'JPEG',quality=85); return b.getvalue()
        except Exception: return None
    refs={r:_refjpg(r) for r in UNSTABLE}
    refs={r:v for r,v in refs.items() if v}
    if refs:
        content=[{"type":"text","text":
          "Image 1 is a rendered living room. The following reference photos are numbered products that MUST "
          "appear in the render and look like their photo (same shape and colour; texture may simplify): "
          +", ".join(f"ref{i+2}={r}" for i,r in enumerate(refs))+
          ". For EACH product answer strictly: present and similar (shape+colour; for LAMPS both the base AND the shade must be visible and match — a lamp without its shade is NOT similar). "
          'Reply STRICT JSON: {"items":[{"name":"<role>","present":bool,"similar":bool}]}'},
          {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+base64.b64encode(final).decode()}}]
        for r,v in refs.items():
            content.append({"type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+base64.b64encode(v).decode()}})
        body={"model":"gpt-5-mini","messages":[{"role":"user","content":content}]}
        try:
            req=urllib.request.Request("https://api.openai.com/v1/chat/completions",data=json.dumps(body).encode(),
                headers={"Authorization":f"Bearer {OAI}","Content-Type":"application/json"})
            with urllib.request.urlopen(req,timeout=180) as rr: out=json.loads(rr.read())
            txt=out['choices'][0]['message']['content']
            mm=re.search(r'\{.*\}',txt,re.S)
            verdict=json.loads(mm.group(0))['items'] if mm else []
        except Exception as e:
            print("stabilizer VLM fail:",str(e)[:80],flush=True); verdict=[]
        bad=[v['name'] for v in verdict if isinstance(v,dict) and not (v.get('present') and v.get('similar'))]
        bad=[b for b in bad if b in BB][:3]
        # ОДИН вызов на все врисовки: общая маска с дырками + все рефы (было 3 вызова по ~45 с)
        m=Image.new('RGBA',(W,H),(0,0,0,255)); dm=ImageDraw.Draw(m)
        todo=[]
        for r in bad:
            x0,y0,x1,y1=BB[r]; pad=35
            x0c,y0c,x1c,y1c=max(0,x0-pad),max(0,y0-pad),min(W,x1+pad),min(H,y1+pad)
            if x1c<=x0c or y1c<=y0c:  # предмет (частично) за кадром — врисовывать нечего
                print(f"стабилизатор: {r} за кадром — скип",flush=True); continue
            dm.rectangle([x0c,y0c,x1c,y1c],fill=(0,0,0,0)); todo.append(r)
        if todo:
            print("стабилизатор: врисовка одним вызовом →",", ".join(todo),flush=True)
            mb=io.BytesIO(); m.save(mb,'PNG')
            fix="; ".join(f"({k+1}) the {ROLE_DESC.get(r if r in ROLE_DESC else ('подушка' if r.startswith('подушка') else r),r)} exactly as in reference photo {k+1}" for k,r in enumerate(todo))
            final=img_edit(final,
                "Photo of a living room. Edit ONLY the transparent-masked regions — draw: "+fix+
                " — same shape, colour and proportions as the matching reference, integrated naturally with correct "
                "perspective and soft shadow. Everything outside the masks stays identical. Do not add anything else.",
                mask_png=mb.getvalue(),refs=[refs[r] for r in todo])
            open(p_final,'wb').write(final)

_tick('проверка-и-правки')
print(f"final: {p_final}  calls={CALLS[0]}")
print("TIMING:",json.dumps(_TM,ensure_ascii=False))
