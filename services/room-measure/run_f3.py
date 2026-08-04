"""Ф3 — само-проверяющий замер (рефактор: без ручных переводов).
DINO даёт сырой англ. ярлык → taxonomy.canon() класс → kind + таблица размеров (англ. ключи);
русскую подпись даёт авто-словарь OpenAI по каноническому слову (кэш растёт). Ф1+Ф2+Ф3 в одном."""
import cv2, numpy as np, os, json, sys, torch, torch.nn.functional as F
from PIL import Image, ImageDraw, ImageFont
import cv_refine as CVR
from geometry_solver import Solver
from sizes_prior import validate_dim, resolve_class
from object_catalog import CATALOG
from taxonomy import canon, kind, DETECT_VOCAB
from openai_translate import translate
D=os.path.dirname(os.path.abspath(__file__)); CACHE=f"{D}/cache"
ROOM=sys.argv[1] if len(sys.argv)>1 else "room2"          # какая комната
FOV_BY_ROOM={"room1":62.0,"room2":62.0}; FOV=FOV_BY_ROOM.get(ROOM,62.0)  # один прайор — не тюним под фото
RUN=f"/tmp/room-measure/run16-{ROOM}"; os.makedirs(RUN,exist_ok=True)
img=cv2.imread(f"{D}/{ROOM}.jpg"); H,W=img.shape[:2]
a4,_=CVR.refine_a4(img); a4c=(int(a4[:,0].mean()),int(a4[:,1].mean()))
sol=Solver(img,a4,FOV); Ki,R,C=sol.Ki,sol.R,sol.C; t=(-R@C).reshape(3)
# --- depth (Depth Anything V2 metric) + якорь A4; кэш ---
dcache=f"{CACHE}/{ROOM}_depth.npy"
if os.path.exists(dcache):
    depth=np.load(dcache)
else:
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    nm="depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf"
    pr=AutoImageProcessor.from_pretrained(nm); md=AutoModelForDepthEstimation.from_pretrained(nm).eval()
    with torch.no_grad(): dd=md(**pr(images=Image.open(f"{D}/{ROOM}.jpg").convert("RGB"),return_tensors="pt")).predicted_depth
    raw=F.interpolate(dd[None],(H,W),mode="bicubic",align_corners=False)[0,0].numpy()
    Xc=R@sol.floor(*a4c)+t; depth=raw*100*(float(Xc[2])/(float(raw[a4c[1],a4c[0]])*100)); np.save(dcache,depth)

# --- детекция: СЫРЫЕ англ. ярлыки (кэш) ---
graw=f"{CACHE}/{ROOM}_gdino_raw.json"
if os.path.exists(graw):
    keep=json.load(open(graw))
else:
    from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
    mid="IDEA-Research/grounding-dino-tiny"
    prc=AutoProcessor.from_pretrained(mid); mdl=AutoModelForZeroShotObjectDetection.from_pretrained(mid).eval()
    im=Image.open(f"{D}/{ROOM}.jpg").convert("RGB"); inp=prc(images=im,text=DETECT_VOCAB,return_tensors="pt")
    with torch.no_grad(): out=mdl(**inp)
    res=prc.post_process_grounded_object_detection(out,inp["input_ids"],threshold=0.30,text_threshold=0.25,target_sizes=[im.size[::-1]])[0]
    dts=[]
    for box,score,lab in zip(res["boxes"],res["scores"],res["labels"]):
        x1,y1,x2,y2=[int(v) for v in box.tolist()]
        if (x2-x1)*(y2-y1)<400: continue
        dts.append([lab,float(score),x1,y1,x2,y2])   # lab = СЫРОЙ англ.
    dts.sort(key=lambda d:-d[1]); keep=[]
    def iou(a,b):
        ix=max(0,min(a[4],b[4])-max(a[2],b[2]));iy=max(0,min(a[5],b[5])-max(a[3],b[3]));inter=ix*iy
        aa=(a[4]-a[2])*(a[5]-a[3]);bb=(b[4]-b[2])*(b[5]-b[3]);return inter/max(1,aa+bb-inter)
    for d in dts:
        if all(iou(d,k)<0.5 for k in keep): keep.append(d)
    json.dump(keep,open(graw,"w"),ensure_ascii=False)

def Zof(x1,y1,x2,y2,plo=5,phi=95):
    xs,ys=np.meshgrid(np.arange(x1,x2,3),np.arange(y1,y2,3)); xs=xs.ravel();ys=ys.ravel()
    Zc=depth[ys,xs]; r=Ki@np.vstack([xs,ys,np.ones_like(xs)]).astype(float)
    P=(R.T@(r*Zc/r[2]-t[:,None])).T; z=P[:,2]; z=z[(z>-20)&(z<300)]
    if len(z)<10: return None,None
    return np.percentile(z,plo), np.percentile(z,phi)
def floor_w(x1,y1,x2,y2):
    A=sol.floor(x1,y2)[:2]; B=sol.floor(x2,y2)[:2]; return float(np.linalg.norm(A-B))
def region_xyz(x1,y1,x2,y2,step=3):
    x1=max(0,x1);y1=max(0,y1);x2=min(W,x2);y2=min(H,y2)
    if x2-x1<step or y2-y1<step: return None
    xs,ys=np.meshgrid(np.arange(x1,x2,step),np.arange(y1,y2,step)); xs=xs.ravel();ys=ys.ravel()
    Zc=depth[ys,xs]; r=Ki@np.vstack([xs,ys,np.ones_like(xs)]).astype(float)
    return (R.T@(r*Zc/r[2]-t[:,None])).T
def facet_from_depth(box):
    """плоскость стены вокруг объекта (по depth стены слева/справа/сверху) → floor-линия A,B (Z=0)."""
    x1,y1,x2,y2=box; m=max(20,(x2-x1)//4)
    regs=[(x1-m,y1,x1-2,y2),(x2+2,y1,x2+m,y2),(x1,y1-m,x2,y1-2)]  # стена по бокам и сверху (не пол снизу)
    pts=[]
    for r in regs:
        P=region_xyz(*r)
        if P is not None: pts.append(P)
    if not pts: return None
    P=np.vstack(pts); P=P[(P[:,2]>10)&(P[:,2]<300)]         # только стена (над полом)
    if len(P)<30: return None
    XY=P[:,:2]; c=XY.mean(0); _,_,Vt=np.linalg.svd(XY-c,full_matrices=False); u=Vt[0]  # вдоль стены
    A=np.array([c[0]-140*u[0],c[1]-140*u[1],0.]); B=np.array([c[0]+140*u[0],c[1]+140*u[1],0.])
    return A,B
def measure_wall(box,A,B):
    """проекция 4 углов рамки на плоскость стены (через floor-линию A,B) → Ш,В,подоконник."""
    x1,y1,x2,y2=box; corners=[(x1,y1),(x2,y1),(x2,y2),(x1,y2)]  # TL,TR,BR,BL
    Pp=[sol.on_facet(u,v,A,B) for u,v in corners]
    w=(np.linalg.norm(Pp[1][:2]-Pp[0][:2])+np.linalg.norm(Pp[2][:2]-Pp[3][:2]))/2
    h=(abs(Pp[0][2]-Pp[3][2])+abs(Pp[1][2]-Pp[2][2]))/2
    sill=min(Pp[2][2],Pp[3][2])
    return round(float(w)),round(float(h)),round(float(sill))
FX=float(sol.K[0,0])
def h_geom(box):
    """высота напольного объекта БЕЗ depth: основание на полу (solvePnP) + луч на верх → z.
    Надёжнее depth для вертикали; даёт правильный ОТНОСИТЕЛЬНЫЙ порядок высот."""
    x1,y1,x2,y2=box; bx=(x1+x2)//2
    Bf=sol.floor(bx,y2)                          # (X,Y,0) — точка основания на полу
    tvec=(-sol.R@sol.C); a=sol.R@np.array([Bf[0],Bf[1],0.])+tvec  # cam-координаты основания
    r2=sol.R[:,2]; fy=float(sol.K[1,1]); cy=float(sol.K[1,2])
    k=(y1-cy)/fy                                  # верхний пиксель по вертикали
    den=(r2[1]-k*r2[2])
    if abs(den)<1e-6: return None
    z=(k*a[2]-a[1])/den
    return round(float(z)) if 0<z<330 else None
# оценка потолка (кросс-чек): верх кадра, точки с Z>200
_Ptop=region_xyz(0,0,W,H//3); _z=_Ptop[:,2]; _z=_z[(_z>200)&(_z<340)]
CEIL=round(float(np.percentile(_z,80))) if len(_z)>50 else None
def measure_wall_fronto(box):
    """способ 2: фронтальная стена на медианной глубине (px*Z/fx). Для не-угловых стен."""
    x1,y1,x2,y2=box; Zc=float(np.median(depth[y1:y2,x1:x2]))
    w=(x2-x1)*Zc/FX; h=(y2-y1)*Zc/FX
    Pb=region_xyz(x1,max(0,y2-5),x2,y2); sill=float(np.percentile(Pb[:,2],20)) if Pb is not None and len(Pb) else 0
    return round(w),round(h),round(sill)
def wall_ok(cls,w,h,sill):
    """сверка со справочником + потолок-кросс-чек. True если правдоподобно (не «косяк»)."""
    for dim,val in (("w",w),("h",h)):
        st,_,_=validate_dim(cls,dim,val)
        if st in ("flag_low","flag_high"): return False
    top=(sill or 0)+h
    if CEIL and top>CEIL+20: return False           # верх окна/двери выше потолка = косяк
    return True
def measure_wall_best(o):
    """≤3 способа: (1) плоскость из depth, (2) фронтальная, (3) прайор каталога.
    Если два способа сильно расходятся → метка disagree (окно не будет зелёным)."""
    box=o["box"]; cls=o["cls"]
    m1=None; fa=facet_from_depth(box)
    if fa is not None: m1=measure_wall(box,*fa)
    m2=measure_wall_fronto(box)
    # расхождение способов по ширине → неуверенность
    if m1 and m2 and max(m1[0],m2[0])>0 and abs(m1[0]-m2[0])/max(m1[0],m2[0])>0.28:
        o["wall_disagree"]=[m1[0],m2[0]]
    # выбор: первый правдоподобный (каталог+потолок)
    if m1 and wall_ok(cls,*m1): return (*m1,"плоскость(1)")
    if wall_ok(cls,*m2): return (*m2,"фронталь(2)")
    e=CATALOG.get(cls,{}); pw=e.get("w",{}).get("avg"); ph=e.get("h",{}).get("avg")
    if ph is not None: return (pw,ph,(m1 or m2)[2],"прайор(3,проверить)")
    b=m1 or m2 or (None,None,None)
    return (b[0],b[1],b[2],"замер(проверить)")

# --- классы + русские подписи (авто-словарь по каноническому слову) ---
objs=[]
for lab,sc,x1,y1,x2,y2 in keep:
    cn=canon(lab)
    if cn is None: continue
    zlo,zhi=Zof(x1,y1,x2,y2)
    objs.append({"raw":lab,"cn":cn,"sc":sc,"box":[x1,y1,x2,y2],"kind":kind(cn),"zlo":zlo,"zhi":zhi})
def iou(a,b):
    ix=max(0,min(a[2],b[2])-max(a[0],b[0]));iy=max(0,min(a[3],b[3])-max(a[1],b[1]));inter=ix*iy
    return inter/max(1,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter)
LARGE={"support","floor","wall"}
def dedup_large(thr):   # схлопнуть ТОЛЬКО одинаковые классы с сильным перекрытием (одно и то же дважды).
    big=sorted([o for o in objs if o["kind"] in LARGE],key=lambda o:-o["sc"]);kept=[]
    for o in big:
        if any(o["cn"]==k["cn"] and iou(o["box"],k["box"])>thr for k in kept): o["_dup"]=True
        else: kept.append(o)
    return [o for o in objs if not o.get("_dup")]
objs=dedup_large(0.6)
# --- подпись = ЧЕСТНЫЙ перевод сырого ярлыка DINO (ошибки поправит человек) ---
RU=translate(sorted({o["raw"] for o in objs}))
for o in objs: o["ru"]=RU.get(o["raw"],o["raw"])
# --- класс каталога: прямой или ближайший синоним через GPT ---
for o in objs: o["cls"]=resolve_class(o["cn"])

# --- Ф2: опоры + привязка предметов ---
for o in objs:
    if o["kind"]=="support": _,o["top_z"]=Zof(*o["box"],plo=5,phi=80)
def contain(it,sp):
    ax1,ay1,ax2,ay2=it["box"]; bx1,by1,bx2,by2=sp["box"]
    ix=max(0,min(ax2,bx2)-max(ax1,bx1)); iy=max(0,min(ay2,by2)-max(ay1,by1)); return ix*iy/max(1,(ax2-ax1)*(ay2-ay1))
def xov(it,sp):
    ax1,_,ax2,_=it["box"]; bx1,_,bx2,_=sp["box"]; return max(0,min(ax2,bx2)-max(ax1,bx1))/max(1,ax2-ax1)
for o in objs:
    if o["kind"]=="wall": o["base_z"]=None; continue
    if o["kind"]!="item": o["base_z"]=0.0; continue
    best=None;bs=0.0;bi=None
    for j,sp in enumerate(objs):
        if sp["kind"]!="support" or sp.get("top_z") is None: continue
        c=contain(o,sp); xo=xov(o,sp); bok=o["zlo"] is not None and abs(o["zlo"]-sp["top_z"])<35
        s=c if c>0.6 else (xo if (bok and xo>0.3) else 0)
        if s>bs: bs=s;best=sp;bi=j
    if best and bs>0.3: o["base_z"]=best["top_z"]; o["on_idx"]=bi
    else: o["base_z"]=0.0

# --- измерение h,w ---
for o in objs:
    if o["kind"]=="support": o["h"]=round(o["top_z"]) if o.get("top_z") else None; o["w"]=round(floor_w(*o["box"]))
    elif o["kind"]=="floor":
        hg=h_geom(o["box"]); hd=round(o["zhi"]) if o["zhi"] is not None else None
        o["h_geo"]=hg; o["h_depth"]=hd
        o["h"]=hg if hg is not None else hd     # геометрия надёжнее depth для вертикали
        o["w"]=round(floor_w(*o["box"]))
    elif o["kind"]=="item": o["h"]=max(0,round(o["zhi"]-o["base_z"])) if (o["zhi"] is not None and o["base_z"] is not None) else None; o["w"]=None
    else:  # wall — ≤3 способа с само-выбором по каталогу+потолку
        wv,hv,sill,meth=measure_wall_best(o); o["w"]=wv; o["h"]=hv; o["sill"]=sill; o["method"]=meth

# --- КОНСЕНСУС одинаковых объектов: два стула/радиатора равны → медиана, выброс подтянуть ---
from collections import defaultdict
grp=defaultdict(list)
for o in objs:
    if o["kind"] in ("floor","support") and o.get("cls"): grp[o["cls"]].append(o)
for cls,gs in grp.items():
    if len(gs)<2: continue
    for dim in ("h","w"):
        vals=[g[dim] for g in gs if g.get(dim) is not None]
        if len(vals)<2: continue
        med=float(np.median(vals))
        for g in gs:
            if g.get(dim) is not None and med>0 and abs(g[dim]-med)/med>0.22:
                g.setdefault("consensus",{})[dim]=[g[dim],round(med)]; g[dim]=round(med)
# --- САМО-ПРОВЕРКА по каталогу (ключ = класс каталога) ---
for o in objs:
    o["checks"]={}
    for dim in ("h","w"):
        if o.get(dim) is None: continue
        st,cf,corr=validate_dim(o["cls"],dim,o[dim]); o["checks"][dim]={"status":st,"conf":cf,"raw":o[dim],"val":corr}
        if st=="corrected": o[dim]=corr
    cfs=[c["conf"] for c in o["checks"].values()] or [0.3]
    o["conf"]=round(float(np.mean(cfs)),2)
    o["flagged"]=any(c["status"].startswith("flag") for c in o["checks"].values())
    o["corrected"]=any(c["status"]=="corrected" for c in o["checks"].values())
    if o.get("wall_disagree"):   # способы стены разошлись → не зелёное, «проверить»
        o["conf"]=round(min(o["conf"],0.5),2); o["corrected"]=True
    # достоверность выше, если геометрия и depth сошлись (высота)
    if o.get("h_geo") is not None and o.get("h_depth") is not None and o["h_depth"]>0:
        o["methods_agree"]=abs(o["h_geo"]-o["h_depth"])/o["h_depth"]<0.2

# --- ЭТАЛОНЫ: уверенные объекты (совпал с каталогом + способы сошлись) → линейка для проверки соседей ---
def depth_med(b):
    z=depth[b[1]:b[3],b[0]:b[2]]; return float(np.median(z)) if z.size else None
for o in objs:
    o["anchor"]=bool(o["conf"]>=0.85 and not o["flagged"] and o["kind"] in ("floor","support")
                     and o.get("h") is not None and o.get("methods_agree",False))
# (кросс-проверка разных объектов по пиксельному соотношению убрана — ненадёжна при неточных рамках.
#  Надёжный относительный сигнал уже даёт h_geom: общая калибровка пола делает высоты взаимно согласованными.)

# --- рендер (только крупные; мелочь → счётчик) ---
pim=Image.fromarray(cv2.cvtColor(img,cv2.COLOR_BGR2RGB)); dr=ImageDraw.Draw(pim)
FT=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",14)
FTb=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",15)
def col(o):
    if o["flagged"]: return (230,40,40)
    if o["corrected"]: return (220,170,0)
    if o["conf"]>=0.85: return (0,180,60)
    return (0,140,230)
clutter=[0]*len(objs); floor_clutter=0
for o in objs:
    if o["kind"]=="item":
        if o.get("on_idx") is not None: clutter[o["on_idx"]]+=1
        else: floor_clutter+=1
for i,o in enumerate(objs): o["_i"]=i
shown=[o for o in objs if o["kind"] in {"support","floor","wall"}]
placed=[]
def place_label(x,tw,th,ypref):
    for dy in range(0,600,th+5):
        for yy in ((ypref+dy),(ypref-dy)):
            if yy<78: continue
            r=(x,yy,x+tw+6,yy+th+6)
            if all(not(r[0]<p[2] and p[0]<r[2] and r[1]<p[3] and p[1]<r[3]) for p in placed):
                placed.append(r); return yy
    placed.append((x,ypref,x+tw+6,ypref+th+6)); return ypref
for o in sorted(shown,key=lambda o:0 if o["kind"]=="support" else 1):
    x1,y1,x2,y2=o["box"]; c=col(o); dr.rectangle([x1,y1,x2,y2],outline=c,width=3 if o["kind"]=="support" else 2)
    parts=[o["ru"]]
    if o.get("w"): parts.append(f"Ш{o['w']}")
    if o.get("h") is not None: parts.append(f"В{o['h']}")
    if o["kind"]=="wall":
        if o.get("sill") is not None and o["cn"]=="window": parts.append(f"подок{o['sill']}")
        parts.append("[стена]")
    n=clutter[o["_i"]]
    if o["kind"]=="support" and n: parts.append(f"+предм:{n}")
    if o.get("wall_disagree"): parts.append("(способы расх.)")
    if o.get("anchor"): parts.append("⚓")
    lab=" ".join(parts)+f" ·{int(o['conf']*100)}%"
    tb=dr.textbbox((0,0),lab,font=FT); tw,th=tb[2]-tb[0],tb[3]-tb[1]
    tx=min(x1,W-tw-8); ty=place_label(tx,tw,th,max(y1-th-6,80))
    dr.rectangle([tx,ty,tx+tw+6,ty+th+6],fill=(255,255,255)); dr.text((tx+3,ty+2),lab,font=FT,fill=c)
    dr.line([tx+3,ty+th+6,(x1+x2)//2,y1],fill=c,width=1)  # выноска к объекту
nfl=sum(o["flagged"] for o in shown); ncr=sum(o["corrected"] for o in shown)
dr.rectangle([0,0,W,74],fill=(24,24,24))
dr.text((10,6),f"REMLAB {ROOM} · Ф3 само-проверка · только крупные объекты",font=FTb,fill=(255,255,255))
dr.text((10,28),"зел=измерено+правдоподобно  жёлт=поправлено по типовому  красн=не сходится (проверить)  син=нет прайора",font=FT,fill=(180,220,255))
dr.text((10,50),f"крупных {len(shown)} · поправлено {ncr} · проверить {nfl} · мелочь не рисуем (шум)",font=FT,fill=(255,210,120))
cv2.imwrite(f"{RUN}/f3.jpg",cv2.cvtColor(np.array(pim),cv2.COLOR_RGB2BGR),[cv2.IMWRITE_JPEG_QUALITY,90])

na=sum(1 for o in objs if o.get("anchor")); nref=sum(1 for o in objs if o.get("ref_note")); nwd=sum(1 for o in objs if o.get("wall_disagree"))
print(f"=== КАСКАД: эталонов(⚓)={na} · подтянуто по эталону={nref} · окна с расхождением способов={nwd} ===")
for o in objs:
    tag="FLAG" if o["flagged"] else ("CORR" if o["corrected"] else "ok")
    ch=" ".join(f"{d}:{c['status']}" for d,c in o["checks"].items()) or "—"
    print(f"[{tag:4s}] raw='{o['raw']}' -> {o['cn']:9s}/{o['ru']:11s} {o['kind']:7s} Ш{o.get('w','-')} В{o.get('h','-')} c{o['conf']} {ch}")
print("saved",f"{RUN}/f3.jpg")
