"""Ф4 — «вот так впишется»: стереть старый объект (LaMa) + вставить товар в ВЫЧИСЛЕННОМ масштабе (3D-габарит).
run_viz.py <room> <что_заменить>  → берёт top-1 подошедший товар из Ф3, чистит место, ставит его в масштабе.
Принцип: масштаб/позиция = наш детерминированный движок (истина); картинка = убеждалка."""
import cv2, numpy as np, os, sys, json, base64, urllib.request
from PIL import Image, ImageDraw, ImageFont
import cv_refine as CVR
from geometry_solver import Solver
import product_match as PM
D=os.path.dirname(os.path.abspath(__file__)); ROOM=sys.argv[1]; TARGET=sys.argv[2]
RUN=f"/tmp/room-measure/plan-{ROOM}"; FKEY=os.environ["FAL_KEY"]
data=json.load(open(f"{RUN}/plan.json")); catalog=json.load(open(f"{D}/demo_catalog.json"))
tgt=next((f for f in data["foot"] if TARGET.lower() in f["ru"].lower()),None)
if tgt is None: print("нет объекта",TARGET); raise SystemExit
top,_=PM.match(tgt["w"],tgt["d"],tgt["ru"],catalog,1)
if not top: print("нет подходящего товара под зону"); raise SystemExit
prod=top[0]
img=cv2.imread(f"{D}/{ROOM}.jpg"); H,W=img.shape[:2]
a4,_=CVR.refine_a4(img); sol=Solver(img,a4,62.0); tvec=(-sol.R@sol.C)
def proj3(X,Y,Z):
    cam=sol.R@np.array([X,Y,Z],float)+tvec
    if cam[2]<=1e-6: return None
    q=sol.K@cam; return (float(q[0]/q[2]),float(q[1]/q[2]))
def durl(bgr):
    ok,b=cv2.imencode(".png",bgr); return "data:image/png;base64,"+base64.b64encode(b).decode()

# --- маска старого объекта (SAM) → LaMa стереть ---
bx=tgt["box"]; DURL="data:image/jpeg;base64,"+base64.b64encode(cv2.imencode(".jpg",img)[1]).decode()
def sam(cx,cy):
    body=json.dumps({"image_url":DURL,"prompts":[{"x":int(cx),"y":int(cy),"label":1}]}).encode()
    r=json.loads(urllib.request.urlopen(urllib.request.Request("https://fal.run/fal-ai/sam2/image",data=body,headers={"Content-Type":"application/json","Authorization":f"Key {FKEY}"}),timeout=90).read())
    png=urllib.request.urlopen(r["image"]["url"],timeout=60).read()
    return cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_GRAYSCALE)>127
m=sam((bx[0]+bx[2])//2,(bx[1]+3*bx[3])//4)
mask=(cv2.dilate(m.astype(np.uint8),np.ones((15,15),np.uint8))*255)
maskbgr=cv2.cvtColor(mask,cv2.COLOR_GRAY2BGR)
lbody=json.dumps({"image_url":DURL,"mask_image_url":durl(maskbgr)}).encode()
lr=json.loads(urllib.request.urlopen(urllib.request.Request("https://fal.run/fal-ai/lama",data=lbody,headers={"Content-Type":"application/json","Authorization":f"Key {FKEY}"}),timeout=120).read())
clean=cv2.imdecode(np.frombuffer(urllib.request.urlopen(lr["images"][0]["url"] if "images" in lr else lr["image"]["url"],timeout=60).read(),np.uint8),cv2.IMREAD_COLOR)
if clean is None or clean.shape[:2]!=(H,W): clean=cv2.resize(clean,(W,H)) if clean is not None else img.copy()

# --- товар: 3D-габарит в зоне старого, проекция на кадр (масштаб точный) ---
tp=np.array(tgt["poly"]); ctr=tp.mean(0)
e1=tp[1]-tp[0]; e1=e1/(np.linalg.norm(e1)+1e-9); e2=np.array([-e1[1],e1[0]])
pw,pd,ph=prod["w"],prod["d"],prod["h"]
if not (pw<=tgt["w"] and pd<=tgt["d"]) and (pd<=tgt["w"] and pw<=tgt["d"]): pw,pd=pd,pw
base=[ctr+e1*(pw/2)+e2*(pd/2),ctr-e1*(pw/2)+e2*(pd/2),ctr-e1*(pw/2)-e2*(pd/2),ctr+e1*(pw/2)-e2*(pd/2)]
b2=[proj3(p[0],p[1],0) for p in base]; t2=[proj3(p[0],p[1],ph) for p in base]

# --- рендер: очищенное фото + товар в масштабе (полупрозрачный габарит + каркас) ---
out=Image.fromarray(cv2.cvtColor(clean,cv2.COLOR_BGR2RGB)).convert("RGBA"); ov=Image.new("RGBA",out.size,(0,0,0,0)); dr=ImageDraw.Draw(ov)
def F(s,b=False): return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if b else ''}.ttf",s)
if all(b2) and all(t2):
    faces=[[b2[0],b2[1],b2[2],b2[3]],[b2[0],b2[1],t2[1],t2[0]],[b2[3],b2[2],t2[2],t2[3]],[t2[0],t2[1],t2[2],t2[3]]]
    for f in faces: dr.polygon([tuple(map(int,p)) for p in f],fill=(60,150,230,70))
    for a,b in [(0,1),(1,2),(2,3),(3,0)]:
        dr.line([tuple(map(int,b2[a])),tuple(map(int,b2[b]))],fill=(20,90,200,255),width=3)
        dr.line([tuple(map(int,t2[a])),tuple(map(int,t2[b]))],fill=(20,90,200,255),width=3)
        dr.line([tuple(map(int,b2[a])),tuple(map(int,t2[a]))],fill=(20,90,200,255),width=3)
    lx,ly=int(min(p[0] for p in t2)),int(min(p[1] for p in t2))-30
    tx=f"{prod['name']} · {prod['w']}×{prod['d']}×{prod['h']} · {prod['price']:,}₽".replace(","," ")
    dr.rectangle([lx,ly,lx+ 9*len(tx),ly+24],fill=(255,255,255,235)); dr.text((lx+4,ly+3),tx,font=F(15,1),fill=(20,90,200,255))
res=Image.alpha_composite(out,ov).convert("RGB")

# --- склейка: было | стало ---
before=Image.fromarray(cv2.cvtColor(img,cv2.COLOR_BGR2RGB)); bd=ImageDraw.Draw(before)
bd.rectangle([bx[0],bx[1],bx[2],bx[3]],outline=(180,60,60),width=4); bd.rectangle([bx[0],bx[1]-24,bx[0]+150,bx[1]],fill=(180,60,60)); bd.text((bx[0]+4,bx[1]-22),"было",font=F(15,1),fill=(255,255,255))
rd=ImageDraw.Draw(res); rd.rectangle([0,0,260,26],fill=(20,90,200)); rd.text((6,4),f"стало: {prod['name']}",font=F(15,1),fill=(255,255,255))
comb=Image.new("RGB",(W*2+20,H),(245,245,247)); comb.paste(before,(0,0)); comb.paste(res,(W+20,0))
comb.save(f"{RUN}/viz.jpg",quality=90)
print(f"стёрли {tgt['ru']} → вписали {prod['name']} {prod['w']}×{prod['d']}×{prod['h']} {prod['price']}₽")
print("saved",f"{RUN}/viz.jpg")
