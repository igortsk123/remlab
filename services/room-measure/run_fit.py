"""Интерактивный fit-check: заменить объект X на товар Ш×Г → вердикт «влезет / велик на N» + картинка.
Использование: run_fit.py <room> <что_заменить> <Ш> <Г> [имя_товара]
Пример: run_fit.py room1 стол 160 85 диван"""
import cv2, numpy as np, os, sys, json
from PIL import Image, ImageDraw, ImageFont
import cv_refine as CVR
from geometry_solver import Solver
import fit_check as FC
D=os.path.dirname(os.path.abspath(__file__))
ROOM=sys.argv[1]; TARGET=sys.argv[2]; PW_=float(sys.argv[3]); PD_=float(sys.argv[4])
PNAME=sys.argv[5] if len(sys.argv)>5 else "товар"
RUN=f"/tmp/room-measure/plan-{ROOM}"
data=json.load(open(f"{RUN}/plan.json"))
room=np.array(data["room_poly"],float); foot=data["foot"]
tgt=next((f for f in foot if TARGET.lower() in f["ru"].lower()),None)
if tgt is None: print("не нашёл объект:",TARGET,"| есть:",[f["ru"] for f in foot]); raise SystemExit
img=cv2.imread(f"{D}/{ROOM}.jpg"); H,W=img.shape[:2]
a4,_=CVR.refine_a4(img); sol=Solver(img,a4,62.0)

# --- вердикт замены в зону старого объекта ---
zone_w,zone_d=tgt["w"],tgt["d"]
v=FC.fit_in_zone(zone_w,zone_d,PW_,PD_)
# товар в зоне: ориентация под лучшую посадку, центр зоны
tp=np.array(tgt["poly"]); ctr=tp.mean(0)
e1=tp[1]-tp[0]; e1=e1/(np.linalg.norm(e1)+1e-9); e2=np.array([-e1[1],e1[0]])
pw,pd=PW_,PD_
if not (PW_<=zone_w and PD_<=zone_d) and (PD_<=zone_w and PW_<=zone_d): pw,pd=PD_,PW_
prod=np.array([ctr+e1*(pw/2)+e2*(pd/2),ctr-e1*(pw/2)+e2*(pd/2),ctr-e1*(pw/2)-e2*(pd/2),ctr+e1*(pw/2)-e2*(pd/2)])

# --- рендер плана сверху ---
allp=np.vstack([room,tp,prod]); x0,x1_=allp[:,0].min()-20,allp[:,0].max()+20; y0,y1_=allp[:,1].min()-20,allp[:,1].max()+20
PWpx=760; sx=PWpx/(x1_-x0); PH=int((y1_-y0)*sx); off=64
def T(p): return (int((p[0]-x0)*sx),off+int(PH-(p[1]-y0)*sx))
cv=Image.new("RGB",(PWpx,PH+off+30),(245,245,247)); dr=ImageDraw.Draw(cv)
FTs=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",13)
FTb=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",15)
dr.polygon([T(p) for p in room],fill=(228,234,240),outline=(180,190,205))
for f in foot:                                          # остальная мебель — серым
    if f is tgt: continue
    dr.polygon([T(p) for p in np.array(f["poly"])],outline=(150,160,175),width=2)
    tx,ty=T(np.mean(f["poly"],0)); dr.text((tx-16,ty-7),f["ru"],font=FTs,fill=(120,130,145))
dr.polygon([T(p) for p in tp],outline=(180,60,60),width=3)  # зона старого — красным контуром
tx,ty=T(ctr); dr.text((tx-40,ty-24),f"зона: {tgt['ru']} {zone_w}×{zone_d}",font=FTs,fill=(180,60,60))
col=(0,160,0) if v["fits"] else (230,120,0)                 # товар — зелёный/оранжевый
dr.polygon([T(p) for p in prod],outline=col,width=4)
dr.text((tx-30,ty+6),f"{PNAME} {PW_:.0f}×{PD_:.0f}",font=FTb,fill=col)
dr.rectangle([0,0,PWpx,off-2],fill=(28,28,30))
dr.text((10,8),f"REMLAB {ROOM} · FIT-CHECK: заменить «{tgt['ru']}» на {PNAME} {PW_:.0f}×{PD_:.0f}",font=FTb,fill=(255,255,255))
dr.text((10,34),f"зона старого {zone_w}×{zone_d} см · красный=зона, {'зелёный' if v['fits'] else 'оранжевый'}=товар",font=FTs,fill=(180,210,240))
bar=(20,70,20) if v["fits"] else (90,55,15)
dr.rectangle([0,off+PH,PWpx,off+PH+30],fill=bar)
dr.text((10,off+PH+6),f"ВЕРДИКТ: {PNAME} {PW_:.0f}×{PD_:.0f} — {v['note'].upper()}",font=FTb,fill=(200,255,200) if v["fits"] else (255,220,170))

# --- фото: подсветить зону старого объекта + вердикт ---
photo=Image.fromarray(cv2.cvtColor(img,cv2.COLOR_BGR2RGB)).copy(); pdr=ImageDraw.Draw(photo)
bx=tgt["box"]; pdr.rectangle(bx,outline=(180,60,60),width=5)
pdr.rectangle([bx[0],max(bx[1]-26,0),bx[0]+320,max(bx[1]-26,0)+24],fill=(255,255,255))
pdr.text((bx[0]+4,max(bx[1]-24,2)),f"заменяем: {tgt['ru']} {zone_w}×{zone_d}",font=FTb,fill=(180,60,60))
Hp=cv.height; wp=int(photo.width*Hp/photo.height); photo=photo.resize((wp,Hp))
comb=Image.new("RGB",(wp+cv.width,Hp),(245,245,247)); comb.paste(photo,(0,0)); comb.paste(cv,(wp,0))
out=f"{RUN}/fit.jpg"; comb.save(out,quality=90)
print(f"зона {tgt['ru']} {zone_w}×{zone_d} | {PNAME} {PW_:.0f}×{PD_:.0f} → {v['note']}")
print("saved",out)
