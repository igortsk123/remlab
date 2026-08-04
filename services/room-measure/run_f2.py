"""Ф2 — иерархия «что на чём стоит» (containment).
Опоры (стол/кровать/матрас/диван/полка) vs предметы (монитор/чашка/коробка…).
Для каждого предмета: стоит на опоре или на полу → высота меряется ОТ поверхности опоры."""
import cv2, numpy as np, torch, os, json, torch.nn.functional as F
from PIL import Image, ImageDraw, ImageFont
import cv_refine as CVR
from geometry_solver import Solver
D=os.path.dirname(os.path.abspath(__file__)); CACHE=f"{D}/cache"; os.makedirs(CACHE,exist_ok=True)
RUN="/tmp/room-measure/run-15"; os.makedirs(RUN,exist_ok=True)
FOV=62.0
img=cv2.imread(f"{D}/room2.jpg"); H,W=img.shape[:2]

# --- A4 + поза ---
a4,_=CVR.refine_a4(img); a4c=(int(a4[:,0].mean()),int(a4[:,1].mean()))
sol=Solver(img,a4,FOV); Ki,R,C=sol.Ki,sol.R,sol.C; t=(-R@C).reshape(3)

# --- depth (кэш) ---
dcache=f"{CACHE}/room2_depth.npy"
if os.path.exists(dcache):
    depth=np.load(dcache)
else:
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    nm="depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf"
    pr=AutoImageProcessor.from_pretrained(nm); md=AutoModelForDepthEstimation.from_pretrained(nm).eval()
    with torch.no_grad(): dd=md(**pr(images=Image.open(f"{D}/room2.jpg").convert("RGB"),return_tensors="pt")).predicted_depth
    raw=F.interpolate(dd[None],(H,W),mode="bicubic",align_corners=False)[0,0].numpy()
    Xc=R@sol.floor(*a4c)+t; depth=raw*100*(float(Xc[2])/(float(raw[a4c[1],a4c[0]])*100))
    np.save(dcache,depth)

def Zof(x1,y1,x2,y2,plo=5,phi=95):
    """3D-Z (высота над полом, см) точек внутри бокса по depth."""
    xs,ys=np.meshgrid(np.arange(x1,x2,3),np.arange(y1,y2,3)); xs=xs.ravel();ys=ys.ravel()
    Zc=depth[ys,xs]; r=Ki@np.vstack([xs,ys,np.ones_like(xs)]).astype(float)
    P=(R.T@(r*Zc/r[2]-t[:,None])).T; z=P[:,2]; z=z[(z>-20)&(z<300)]
    if len(z)<10: return None,None
    return np.percentile(z,plo), np.percentile(z,phi)

# --- Grounding DINO (кэш) ---
gcache=f"{CACHE}/room2_gdino.json"
VMAP=[("office chair","кресло"),("chair","стул"),("desk","стол"),("table","стол"),("sofa","диван"),
      ("couch","диван"),("bed","кровать"),("mattress","матрас"),("wardrobe","шкаф"),("shelf","полка"),
      ("computer monitor","монитор"),("television","телевизор"),("laptop","ноутбук"),("keyboard","клавиатура"),
      ("humidifier","увлажнитель"),("air purifier","очиститель"),("fan","вентилятор"),("heater","обогреватель"),
      ("radiator","радиатор"),("floor lamp","торшер"),("lamp","лампа"),("potted plant","растение"),
      ("box","коробка"),("books","книги"),("bottle","бутылка"),("cup","чашка"),("speaker","колонка"),
      ("router","роутер"),("mirror","зеркало"),("picture frame","картина"),("curtain","штора"),
      ("window","окно"),("door","дверь"),("rug","ковёр"),("pillow","подушка"),("bag","сумка"),("clothes","одежда")]
def clean_label(raw):
    w=set(raw.replace("#","").split()); best=None;bs=-1
    for ph,ru in VMAP:
        pw=set(ph.split()); ov=len(w&pw)/max(1,len(pw))
        if ov>bs: bs=ov; best=ru
    return best or raw
if os.path.exists(gcache):
    keep=json.load(open(gcache))
else:
    from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
    mid="IDEA-Research/grounding-dino-tiny"
    prc=AutoProcessor.from_pretrained(mid); mdl=AutoModelForZeroShotObjectDetection.from_pretrained(mid).eval()
    VOCAB=". ".join(p for p,_ in VMAP)+"."
    im=Image.open(f"{D}/room2.jpg").convert("RGB"); inp=prc(images=im,text=VOCAB,return_tensors="pt")
    with torch.no_grad(): out=mdl(**inp)
    res=prc.post_process_grounded_object_detection(out,inp["input_ids"],threshold=0.30,text_threshold=0.25,target_sizes=[im.size[::-1]])[0]
    dts=[]
    for box,score,lab in zip(res["boxes"],res["scores"],res["labels"]):
        x1,y1,x2,y2=[int(v) for v in box.tolist()]
        if (x2-x1)*(y2-y1)<400: continue
        dts.append([clean_label(lab),float(score),x1,y1,x2,y2])
    dts.sort(key=lambda d:-d[1]); keep=[]
    def iou(a,b):
        ix=max(0,min(a[4],b[4])-max(a[2],b[2]));iy=max(0,min(a[5],b[5])-max(a[3],b[3]));inter=ix*iy
        aa=(a[4]-a[2])*(a[5]-a[3]);bb=(b[4]-b[2])*(b[5]-b[3]);return inter/max(1,aa+bb-inter)
    for d in dts:
        if all(iou(d,k)<0.5 for k in keep): keep.append(d)
    json.dump(keep,open(gcache,"w"),ensure_ascii=False)

# --- классификация опора / предмет / напольный ---
SUPPORT={"стол","кровать","матрас","диван","полка","шкаф"}
FLOOROBJ={"вентилятор","обогреватель","радиатор","стул","кресло","торшер","растение"}  # стоят на полу
WALLOBJ={"зеркало","картина","окно","штора","телевизор","дверь"}  # висят/стоят на стене
# всё остальное — «предмет» (может лежать на опоре): монитор,ноутбук,чашка,бутылка,коробка,клавиатура,увлажнитель...
def kind(lb): return "support" if lb in SUPPORT else ("wall" if lb in WALLOBJ else ("floor" if lb in FLOOROBJ else "item"))

objs=[]
for lb,sc,x1,y1,x2,y2 in keep:
    zlo,zhi=Zof(x1,y1,x2,y2)
    objs.append({"lb":lb,"sc":sc,"box":[x1,y1,x2,y2],"kind":kind(lb),
                 "zlo":zlo,"zhi":zhi,"cx":(x1+x2)//2,"cy":(y1+y2)//2})

# опоры: верхняя поверхность = высокий процентиль Z
for o in objs:
    if o["kind"]=="support":
        _,ztop=Zof(*o["box"],plo=5,phi=80); o["top_z"]=ztop

def contain(it,sp):
    ax1,ay1,ax2,ay2=it["box"]; bx1,by1,bx2,by2=sp["box"]
    ix=max(0,min(ax2,bx2)-max(ax1,bx1)); iy=max(0,min(ay2,by2)-max(ay1,by1))
    return ix*iy/max(1,(ax2-ax1)*(ay2-ay1))
def xoverlap(it,sp):
    ax1,_,ax2,_=it["box"]; bx1,_,bx2,_=sp["box"]
    return max(0,min(ax2,bx2)-max(ax1,bx1))/max(1,ax2-ax1)

# --- решение: предмет на опоре / стене / полу ---
for o in objs:
    if o["kind"]=="wall":
        o["base"]="стена"; o["base_z"]=None; continue   # высоту меряем по плоскости стены (Ф-двери), не от пола
    if o["kind"]!="item":
        o["base"]="пол"; o["base_z"]=0.0; continue
    best=None; bscore=0.0
    for sp in objs:
        if sp["kind"]!="support" or sp.get("top_z") is None: continue
        c=contain(o,sp); xo=xoverlap(o,sp)
        base_ok = o["zlo"] is not None and abs(o["zlo"]-sp["top_z"])<35   # основание предмета ≈ верх опоры
        # засчитываем «на опоре» если: (бокс вложен) ИЛИ (основание совпало с верхом + горизонт. перекрытие)
        score = c if (c>0.6) else (xo if (base_ok and xo>0.3) else 0)
        if score>bscore: bscore=score; best=sp
    if best and bscore>0.3:
        o["base"]=f"на: {best['lb']}"; o["base_z"]=best["top_z"]; o["on"]=best["lb"]
    else:
        o["base"]="пол"; o["base_z"]=0.0
    if o["zhi"] is not None and o["base_z"] is not None:
        o["h"]=max(0,round(o["zhi"]-o["base_z"]))

# --- рендер ---
pim=Image.fromarray(cv2.cvtColor(img,cv2.COLOR_BGR2RGB)); dr=ImageDraw.Draw(pim)
FT=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",15)
FTb=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",15)
COL={"support":(255,140,0),"floor":(0,180,0),"wall":(220,200,0),"item_on":(190,0,200),"item_floor":(0,120,255)}
def draw(o):
    x1,y1,x2,y2=o["box"]
    if o["kind"]=="support": c=COL["support"];w=3
    elif o["kind"]=="floor": c=COL["floor"];w=2
    elif o["kind"]=="wall": c=COL["wall"];w=2
    else: c=COL["item_on"] if o.get("on") else COL["item_floor"];w=2
    dr.rectangle([x1,y1,x2,y2],outline=c,width=w)
    lab=o["lb"]
    if o["kind"]=="support" and o.get("top_z"): lab+=f" (верх {round(o['top_z'])}см)"
    elif o["kind"]=="wall": lab+=" [стена]"
    elif o["kind"]=="item":
        lab+=f" [{o['base']}]"
        if o.get("h") is not None: lab+=f" h{o['h']}"
    tb=dr.textbbox((0,0),lab,font=FT); tw,th=tb[2]-tb[0],tb[3]-tb[1]
    ty=max(y1-th-6,0); dr.rectangle([x1,ty,x1+tw+6,ty+th+6],fill=(255,255,255)); dr.text((x1+3,ty+2),lab,font=FT,fill=c)
for o in sorted(objs,key=lambda o:0 if o["kind"]=="support" else 1): draw(o)
dr.rectangle([0,0,W,52],fill=(28,28,28))
n_on=sum(1 for o in objs if o.get("on"))
dr.text((10,6),"REMLAB room2 | Ф2 иерархия «что на чём»",font=FTb,fill=(255,255,255))
dr.text((10,28),f"оранж=опора  зел=напольный  жёлт=стена  фиол=предмет НА опоре ({n_on})  син=предмет на полу",font=FT,fill=(180,220,255))
cv2.imwrite(f"{RUN}/f2.jpg",cv2.cvtColor(np.array(pim),cv2.COLOR_RGB2BGR),[cv2.IMWRITE_JPEG_QUALITY,90])

print("=== Ф2 иерархия ===")
for o in objs:
    if o["kind"]=="support": print(f"ОПОРА  {o['lb']:10s} верх={round(o['top_z']) if o.get('top_z') else '?'}см  box={o['box']}")
for o in objs:
    if o["kind"]=="item": print(f"предм  {o['lb']:12s} {o['base']:16s} h={o.get('h','?')}  z[{o['zlo'] and round(o['zlo'])}..{o['zhi'] and round(o['zhi'])}]")
for o in objs:
    if o["kind"]=="floor": print(f"пол    {o['lb']:10s} h={o.get('zhi') and round(o['zhi'])}  box={o['box']}")
print("saved",f"{RUN}/f2.jpg")
