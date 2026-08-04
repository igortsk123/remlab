"""План пола сверху (top-down) — НАДЁЖНЫЙ результат на floor-геометрии (A4+solvePnP), без depth-хрупкости.
Габариты видимой комнаты + footprint мебели (ширина по полу + глубина из каталога) + свободная зона.
Это то, что нужно продукту «влезет/освежить». Высоты/окна — отдельный слой (run_f3)."""
import cv2, numpy as np, os, json, sys, base64, urllib.request, torch, torch.nn.functional as F
from PIL import Image, ImageDraw, ImageFont
import cv_refine as CVR
from geometry_solver import Solver
from taxonomy import canon, kind
from object_catalog import CATALOG
from openai_translate import translate
import fit_check as FC
D=os.path.dirname(os.path.abspath(__file__)); CACHE=f"{D}/cache"
ROOM=sys.argv[1] if len(sys.argv)>1 else "room2"; FOV=62.0
FKEY=os.environ.get("FAL_KEY")
RUN=f"/tmp/room-measure/plan-{ROOM}"; os.makedirs(RUN,exist_ok=True)
img=cv2.imread(f"{D}/{ROOM}.jpg"); H,W=img.shape[:2]
a4,_=CVR.refine_a4(img); sol=Solver(img,a4,FOV)

# --- пол: SegFormer ADE20K (кэш) ---
scache=f"{CACHE}/{ROOM}_seg.npy"
if os.path.exists(scache): seg=np.load(scache)
else:
    from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation
    sc="nvidia/segformer-b2-finetuned-ade-512-512"
    sp=AutoImageProcessor.from_pretrained(sc); sm=AutoModelForSemanticSegmentation.from_pretrained(sc).eval()
    with torch.no_grad(): lg=sm(**sp(images=Image.open(f"{D}/{ROOM}.jpg").convert("RGB"),return_tensors="pt")).logits
    seg=F.interpolate(lg,(H,W),mode="bilinear",align_corners=False).argmax(1)[0].numpy().astype(np.int16); np.save(scache,seg)
FL=3; WALL=0; WIN=8  # ADE20K floor/wall/windowpane
np.random.seed(0)

# --- зоны мебели (по детекции) — выкинуть из поиска линии стена-пол (светлый матрас = ложный «пол») ---
_keep=json.load(open(f"{CACHE}/{ROOM}_gdino_raw.json"))
furn_boxes=[]
for lab,sc_,x1,y1,x2,y2 in _keep:
    cn=canon(lab)
    if cn and kind(cn) in ("support","floor") and (x2-x1)*(y2-y1)>4000: furn_boxes.append((x1,y1,x2,y2))
def in_furn(x,y):
    return any(bx1-6<=x<=bx2+6 and by1-6<=y<=by2+6 for bx1,by1,bx2,by2 in furn_boxes)

# --- точки линии стена-пол (метрич., на плоскости пола), без зон мебели ---
contact=[]
for x in range(0,W,4):
    col=seg[:,x]; fys=np.where(col==FL)[0]
    if len(fys)<8: continue
    ytop=int(fys.min())
    if in_furn(x,ytop): continue                       # верхний «пол» на мебели (матрас) — не стена-пол
    above=col[max(0,ytop-22):ytop]
    if len(above)==0 or np.mean(np.isin(above,[WALL,WIN]))<0.4: continue  # над полом стена/окно, не мебель
    P=sol.floor(x,ytop)[:2]
    if abs(P[0])<700 and 0<P[1]<800: contact.append([x,P[0],P[1]])   # imgx, X, Y(метрич.)
contact=np.array(contact,float)

# --- секвенциальный RANSAC на прямые стен (по метрич. X,Y; carry imgx для упорядочивания) ---
def seq_ransac(C,thr=6.0,min_inl=12,max_lines=8,iters=400):
    lines=[]; rem=C.copy()
    while len(rem)>=min_inl and len(lines)<max_lines:
        P=rem[:,1:]; best=None;bc=0
        for _ in range(iters):
            i,j=np.random.randint(0,len(rem),2); a,b=P[i],P[j]; d=b-a; L=np.linalg.norm(d)
            if L<25: continue
            d/=L; nrm=np.array([-d[1],d[0]]); dist=np.abs((P-a)@nrm); c=int((dist<thr).sum())
            if c>bc: bc=c; best=dist<thr
        if bc<min_inl: break
        inl=rem[best]; Pi=inl[:,1:]; ctr=Pi.mean(0); _,_,Vt=np.linalg.svd(Pi-ctr); d=Vt[0]
        t=(Pi-ctr)@d
        lines.append({"c":ctr,"d":d,"a":ctr+d*t.min(),"b":ctr+d*t.max(),"imgx":float(inl[:,0].mean()),"n":bc})
        rem=rem[~best]
    return lines
walls=seq_ransac(contact) if len(contact)>24 else []
walls.sort(key=lambda w:w["imgx"])                      # слева→направо по кадру (естественный порядок стен)
def isect(w1,w2):
    A=np.array([w1["d"],-w2["d"]]).T
    if abs(np.linalg.det(A))<1e-6: return None
    t=np.linalg.solve(A,w2["c"]-w1["c"]); return w1["c"]+t[0]*w1["d"]
outline=[]
if walls:
    bx0,bx1=contact[:,1].min()-70,contact[:,1].max()+70   # рамка контактов — обрезаем улетающие пересечения
    by0,by1=contact[:,2].min()-70,contact[:,2].max()+70
    w0=walls[0]; outline.append(w0["a"] if w0["a"][0]<w0["b"][0] else w0["b"])
    for i in range(len(walls)-1):
        p=isect(walls[i],walls[i+1])
        if p is not None and bx0<p[0]<bx1 and by0<p[1]<by1:
            outline.append(p)                              # валидный угол = пересечение соседних стен
        else:
            outline.append(walls[i]["b"]); outline.append(walls[i+1]["a"])  # стык встык (не улетаем)
    wl=walls[-1]; outline.append(wl["b"] if wl["b"][0]>wl["a"][0] else wl["a"])
outline=np.array(outline,float) if outline else np.empty((0,2))

# площадь пола (видимого) — по спроецированным пикселям пола
fy,fx=np.where(seg==FL); s=slice(0,len(fx),max(1,len(fx)//5000))
FP=np.array([sol.floor(x,y)[:2] for x,y in zip(fx[s],fy[s])])
FP=FP[(np.abs(FP[:,0])<700)&(FP[:,1]>-40)&(FP[:,1]<800)]
hull=cv2.convexHull(FP.astype(np.float32)).reshape(-1,2)
floor_area=round(abs(cv2.contourArea(hull.astype(np.float32)))/10000,1)
room_w=round(float(np.ptp(outline[:,0]))) if len(outline)>2 else round(float(np.ptp(FP[:,0])))
room_d=round(float(outline[:,1].max())) if len(outline)>2 else round(float(np.ptp(FP[:,1])))
# защита: RANSAC-контур вырожден (мало стен / габариты / площадь не сходится с полом) → фолбэк на оболочку
def poly_area_m2(pts):
    if len(pts)<3: return 0.0
    x=pts[:,0];y=pts[:,1]; return abs(np.dot(x,np.roll(y,1))-np.dot(y,np.roll(x,1)))/2/10000
oa=poly_area_m2(outline)
contour_ok = len(walls)>=3 and 120<room_w<400 and 120<room_d<430 and 0.6*floor_area<oa<1.8*floor_area
contour_src="RANSAC-стены" if contour_ok else "оболочка"   # фолбэк-оболочку соберём ПОСЛЕ footprint (с мебелью внутри)

# --- footprint: круглые/овальные → эллипс (SAM-маска + back-проекция на плоскость z=h), прочее → прямоуг ---
def floor_at_z(u,v,z):                                # луч камеры ∩ горизонт. плоскость z=h → метрич. (X,Y)
    d=sol.ray(u,v)
    if abs(d[2])<1e-9: return None
    t=(z-sol.C[2])/d[2]; P=sol.C+t*d; return P[:2]
ok_,buf_=cv2.imencode(".jpg",img); DURL="data:image/jpeg;base64,"+base64.b64encode(buf_).decode()
mcache=f"{CACHE}/{ROOM}_masks.npz"; MASKS=dict(np.load(mcache)) if os.path.exists(mcache) else {}
def sam(cx,cy):
    k=f"{cx}_{cy}"
    if k in MASKS: return MASKS[k]
    if not FKEY: return None
    try:
        body=json.dumps({"image_url":DURL,"prompts":[{"x":int(cx),"y":int(cy),"label":1}]}).encode()
        r=json.loads(urllib.request.urlopen(urllib.request.Request("https://fal.run/fal-ai/sam2/image",data=body,headers={"Content-Type":"application/json","Authorization":f"Key {FKEY}"}),timeout=90).read())
        png=urllib.request.urlopen(r["image"]["url"],timeout=60).read()
        m=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_GRAYSCALE)>127; MASKS[k]=m; return m
    except Exception as e: print("sam fail",e); return None
def try_ellipse(m,hcm):                               # маска круглая/овальная? → метрич. эллипс (диаметры)
    if m is None: return None
    ys,xs=np.where(m)
    if len(xs)<300: return None
    Hm=m.shape[0]; rmin=np.full(Hm,1e9); rmax=np.full(Hm,-1e9)
    np.minimum.at(rmin,ys,xs); np.maximum.at(rmax,ys,xs)
    rw=rmax-rmin; maxw=rw.max()
    if maxw<20: return None
    band=np.where(rw>0.6*maxw)[0]                     # широкая верхняя полоса = столешница (без ножки/пьедестала)
    bm=np.zeros_like(m); bm[band,:]=m[band,:]
    cs,_=cv2.findContours(bm.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    if not cs: return None
    c=max(cs,key=cv2.contourArea)
    if len(c)<8 or cv2.contourArea(c)<1500: return None
    (ex,ey),(MA,ma),ang=cv2.fitEllipse(c)
    if MA<5 or ma<5: return None
    fill=cv2.contourArea(c)/max(np.pi*MA*ma/4,1)      # заполняет эллипс?
    approx=cv2.approxPolyDP(c,0.03*cv2.arcLength(c,True),True)
    if not (fill>0.82 and len(approx)>=5): return None  # не круг/овал (прямоуг = 4 угла / плохо заполняет)
    pp=cv2.ellipse2Poly((int(ex),int(ey)),(int(MA/2),int(ma/2)),int(ang),0,360,12)
    M=np.array([q for q in (floor_at_z(u,v,hcm) for u,v in pp) if q is not None],float)
    if len(M)<6: return None
    (mx,my),(D1,D2),a2=cv2.fitEllipse(M.astype(np.float32))
    if not (30<max(D1,D2)<400): return None
    pm=cv2.ellipse2Poly((int(round(mx)),int(round(my))),(int(D1/2),int(D2/2)),int(a2),0,360,12).astype(float)
    return {"poly":pm,"w":round(max(D1,D2)),"d":round(min(D1,D2)),"round":min(D1,D2)/max(D1,D2)>0.82}

keep=json.load(open(f"{CACHE}/{ROOM}_gdino_raw.json"))
RU=translate(sorted({k[0] for k in keep}))
hull_c=hull.astype(np.float32).reshape(-1,1,2)
EXCL={"wardrobe","door","window","mirror","picture","curtain","shelf"}
foot=[]; seen=[]
for lab,sc_,x1,y1,x2,y2 in keep:
    cn=canon(lab)
    if cn is None or kind(cn) not in ("support","floor") or cn in EXCL: continue
    if (x2-x1)*(y2-y1)<3000: continue
    if any(cn==bc and max(0,min(x2,b[2])-max(x1,b[0]))*max(0,min(y2,b[3])-max(y1,b[1]))>0.6*min((x2-x1)*(y2-y1),(b[2]-b[0])*(b[3]-b[1])) for b,bc in seen): continue  # дедуп только ОДИНАКОВЫХ классов
    A=sol.floor(x1,y2)[:2]; B=sol.floor(x2,y2)[:2]; mid=(A+B)/2
    if cv2.pointPolygonTest(hull_c,(float(mid[0]),float(mid[1])),True)<-70: continue
    seen.append(([x1,y1,x2,y2],cn))
    hcm=CATALOG.get(cn,{}).get("h",{}).get("avg",74)
    TABLE_CLS={"desk","table","dining_table","coffee_table"}
    ell=try_ellipse(sam((x1+x2)//2,int(y1+(y2-y1)*0.32)),hcm) if cn in TABLE_CLS else None  # точка по столешнице (выше центра)
    if ell:                                           # круглый/овальный → эллипс
        foot.append({"ru":RU.get(lab,lab),"w":ell["w"],"d":ell["d"],"poly":ell["poly"],"box":[x1,y1,x2,y2],"shape":"эллипс","round":ell["round"]})
    else:                                             # прямоугольный: ширина по полу + глубина каталога
        wcm=float(np.linalg.norm(A-B))
        if not (15<wcm<400): continue
        dcm=CATALOG.get(cn,{}).get("d",{}).get("avg") or round(CATALOG.get(cn,{}).get("w",{}).get("avg",60)*0.6)
        dirw=B-A; dirw=dirw/(np.linalg.norm(dirw)+1e-6); n=np.array([-dirw[1],dirw[0]])
        if n[1]<0: n=-n
        poly=np.array([A,B,B+n*dcm,A+n*dcm])
        foot.append({"ru":RU.get(lab,lab),"w":round(float(wcm)),"d":round(dcm),"poly":poly,"box":[x1,y1,x2,y2],"shape":"прямоуг"})
if FKEY: np.savez(mcache,**{k:v for k,v in MASKS.items()})

# полигон КОМНАТЫ = пол ∪ footprint мебели (мебель ВСЕГДА внутри — светлый матрас не обрезается)
room_pts=np.vstack([FP]+[f["poly"] for f in foot]) if foot else FP
room_poly=cv2.convexHull(room_pts.astype(np.float32)).reshape(-1,2)
if not contour_ok:                                    # RANSAC вырожден → оболочка комнаты (с мебелью внутри)
    outline=room_poly; room_w=round(float(np.ptp(room_poly[:,0]))); room_d=round(float(np.ptp(room_poly[:,1])))
# данные плана → json (для интерактивного fit-check)
json.dump({"room_poly":[[float(a),float(b)] for a,b in room_poly],
           "foot":[{"ru":f["ru"],"w":f["w"],"d":f["d"],"poly":[[float(a),float(b)] for a,b in f["poly"]],
                    "box":f["box"],"shape":f.get("shape","прямоуг")} for f in foot]},
          open(f"{RUN}/plan.json","w"),ensure_ascii=False)

# --- рендер плана сверху ---
allp=np.vstack([hull]+[f["poly"] for f in foot])
x0,x1_=allp[:,0].min()-20,allp[:,0].max()+20; y0,y1_=allp[:,1].min()-20,allp[:,1].max()+20
PW=960; sx=PW/(x1_-x0); PH=int((y1_-y0)*sx); off=72
def T(p): return (int((p[0]-x0)*sx), off+int(PH-(p[1]-y0)*sx))
cv=Image.new("RGB",(PW,PH+off),(245,245,247)); dr=ImageDraw.Draw(cv)
FTs=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",13)
FTb=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",16)
dr.polygon([T(p) for p in room_poly],fill=(226,233,239),outline=(180,190,205))   # полигон комнаты (мебель внутри)
if len(outline)>2:                       # ломаная стен (по линии стена-пол, ловит эркер)
    dr.line([T(p) for p in outline],fill=(90,105,125),width=4,joint="curve")
for gx in range(int(x0//100*100),int(x1_)+100,100): dr.line([T((gx,y0)),T((gx,y1_))],fill=(233,237,241))
for gy in range(int(y0//100*100),int(y1_)+100,100): dr.line([T((x0,gy)),T((x1_,gy))],fill=(233,237,241))
cxp,cyp=T(sol.C[:2]); dr.ellipse([cxp-6,cyp-6,cxp+6,cyp+6],fill=(60,60,60)); dr.text((cxp+8,cyp-6),"камера",font=FTs,fill=(90,90,90))
COLS=[(70,130,200),(210,120,60),(90,170,90),(170,90,180),(200,170,50),(80,170,180),(200,80,80)]
for i,f in enumerate(foot):
    c=COLS[i%len(COLS)]; dr.polygon([T(p) for p in f["poly"]],outline=c,width=3)
    tx,ty=T(np.mean(f["poly"],0))
    if f.get("shape")=="эллипс": lab=f"{f['ru']} Ø{f['w']}" if f.get("round") else f"{f['ru']} Ø{f['w']}×{f['d']}"
    else: lab=f"{f['ru']} {f['w']}×{f['d']}"
    tw=dr.textbbox((0,0),lab,font=FTs)[2]
    dr.rectangle([tx-tw//2-3,ty-9,tx+tw//2+3,ty+9],fill=(255,255,255)); dr.text((tx-tw//2,ty-8),lab,font=FTs,fill=c)
# --- Ф2 fit-check ДЕМО: влезет ли диван 200×90 (с проходом 55 см)? ---
DEMO_W,DEMO_D=200,90; rp=[tuple(map(float,p)) for p in room_poly]
occ=[{"poly":[tuple(map(float,q)) for q in f["poly"]],"ru":f["ru"]} for f in foot]
try:
    free=FC.free_space(rp,[o["poly"] for o in occ],0)
    gs=[free] if free.geom_type=="Polygon" else list(getattr(free,"geoms",[]))
    for g in gs:
        if not g.is_empty and len(g.exterior.coords)>2: dr.polygon([T(p) for p in np.array(g.exterior.coords)],outline=(120,175,120))
    fc=FC.place_or_remove(rp,occ,DEMO_W,DEMO_D,walkway=55)
    demo_txt=f"диван {DEMO_W}×{DEMO_D}: {fc['verdict']}"
    if fc["place"]:
        pl=fc["place"]; dr.polygon([T(p) for p in pl["poly"]],outline=(0,160,0),width=4)
        tX,tY=T((pl["x"],pl["y"])); dr.text((tX-38,tY-7),f"диван {DEMO_W}×{DEMO_D} ✓",font=FTs,fill=(0,130,0))
        if fc["remove"]: demo_txt+=f" · убрать: {fc['remove']}"
except Exception as e: demo_txt=f"fit-check err: {e}"
dr.rectangle([0,off+PH-28,PW,off+PH],fill=(18,52,18))
dr.text((10,off+PH-23),f"Ф2 FIT-CHECK · {demo_txt} · зелёная зона = свободно",font=FTb,fill=(190,255,190))
dr.rectangle([0,0,PW,off-2],fill=(28,28,30))
dr.text((10,8),f"REMLAB {ROOM} · ПЛАН ПОЛА (сверху) · видимая комната ~{room_w}×{room_d} см · пол {floor_area} м²",font=FTb,fill=(255,255,255))
dr.text((10,36),f"мебель {len(foot)} · footprint Ш:пол Г:каталог · контур: {contour_src} · голубая линия на фото = сверка контура",font=FTs,fill=(180,210,240))
# --- фото рядом (узнаваемо!) с ТЕМИ ЖЕ цветами → связь фото↔план ---
photo=Image.fromarray(cv2.cvtColor(img,cv2.COLOR_BGR2RGB)).copy(); pdr=ImageDraw.Draw(photo)
pdr.polygon([(int(p[0]),int(p[1])) for p in a4],outline=(255,60,0),width=3)   # A4 — используется в расчётах (масштаб/пол)
pdr.text((int(a4[:,0].mean())-8,int(a4[:,1].mean())-8),"A4",font=FTb,fill=(255,60,0))
tvec=(-sol.R@sol.C)
def proj(P):                                  # метрич. точка пола (X,Y,0) → пиксель (сверка контура)
    cam=sol.R@np.array([P[0],P[1],0.])+tvec
    if cam[2]<=1e-6: return None
    q=sol.K@cam; return (float(q[0]/q[2]),float(q[1]/q[2]))
if len(outline)>2:                            # НАЛОЖЕНИЕ контура стен на фото (проверка совпадения)
    pp=[proj(p) for p in outline]; pp=[q for q in pp if q]
    if len(pp)>1: pdr.line(pp,fill=(0,210,255),width=4,joint="curve")
for i,f in enumerate(foot):
    c=COLS[i%len(COLS)]; x1,y1,x2,y2=f["box"]
    pdr.rectangle([x1,y1,x2,y2],outline=c,width=4)
    lab=f"{f['ru']} {f['w']}×{f['d']}"; tw=pdr.textbbox((0,0),lab,font=FTs)[2]
    ty=max(y1-20,4); pdr.rectangle([x1,ty,x1+tw+6,ty+18],fill=(255,255,255)); pdr.text((x1+3,ty+2),lab,font=FTs,fill=c)
Hp=cv.height; wp=int(photo.width*Hp/photo.height); photo=photo.resize((wp,Hp))
comb=Image.new("RGB",(wp+cv.width,Hp),(245,245,247)); comb.paste(photo,(0,0)); comb.paste(cv,(wp,0))
comb.save(f"{RUN}/plan.jpg",quality=90)
print(f"комната ~{room_w}×{room_d} см · пол {floor_area} м² · мебель {len(foot)}:")
for f in foot: print(f"  {f['ru']:16s} {f['w']}×{f['d']} см  [{f.get('shape','?')}{' круг' if f.get('round') else ''}]")
print("saved",f"{RUN}/plan.jpg")
