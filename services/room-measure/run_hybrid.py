import cv2, numpy as np, json, os
import cv_refine as CVR
from geometry_solver import Solver
from ultralytics import YOLO
D=os.path.dirname(os.path.abspath(__file__)); RUN="/tmp/room-measure/run-6"; os.makedirs(RUN,exist_ok=True)
img=cv2.imread(f"{D}/room1.jpg"); H,W=img.shape[:2]
a4,_=CVR.refine_a4(img); sol=Solver(img,a4,62.0,ceiling_cm=263)
K,Ki,R,C=sol.K,sol.Ki,sol.R,sol.C; t=(-R@C).reshape(3); fx=float(K[0,0])
depth=np.load(f"{D}/depth_cm.npy"); seg=np.load(f"{D}/seg.npy")
def world(u,v):
    Z=depth[int(v),int(u)]; ray=Ki@np.array([float(u),float(v),1.]); Xc=ray*Z/ray[2]; return R.T@(Xc-t)
a4c=(int(a4[:,0].mean()),int(a4[:,1].mean()))

# --- габариты комнаты из стен+потолка (depth, сквозь мебель) ---
ys,xs=np.where((seg==0)|(seg==5)); P=[]
for i in range(0,len(xs),max(1,len(xs)//4000)):
    w=world(xs[i],ys[i])
    if -50<w[2]<330: P.append(w[:2])
P=np.array(P); room_w=round(float(P[:,0].max()-P[:,0].min())); room_d=round(float(P[:,1].max()-P[:,1].min()))
# --- потолок (depth) ---
cy,cx=np.where(seg==5); ceil=round(float(np.median([world(cx[i],cy[i])[2] for i in range(0,len(cx),max(1,len(cx)//300))]))) if len(cy) else 263
# --- окна (маска, разбить, размер через глубину: px*depth/f) ---
win=(seg==8); wins=[]
ys0,xs0=np.where(win)
if len(xs0):
    x0,x1=int(xs0.min()),int(xs0.max()); colc=win[:,x0:x1+1].sum(0)
    lo,hi=int(0.32*(x1-x0)),int(0.68*(x1-x0)); split=x0+lo+int(np.argmin(colc[lo:hi]))
    for xa,xb in [(x0,split),(split,x1)]:
        sub=win[:,xa:xb+1]; yy,xx=np.where(sub)
        if len(xx)<800: continue
        bx,bw,by,bh=xa+int(xx.min()),int(xx.max()-xx.min()),int(yy.min()),int(yy.max()-yy.min())
        d=float(np.median(depth[by:by+bh,bx:bx+bw]))
        wins.append({"box":[bx,by,bw,bh],"w":round(bw*d/fx),"h":round(bh*d/fx)})
# --- A4 -> эркер (к центроиду окон, а не случайной точке) ---
if len(xs0):
    wc=(int(xs0.mean()),int(ys0.mean()))
    a4_bay=round(float(np.linalg.norm(world(*a4c)[:2]-world(*wc)[:2])))  # горизонталь по полу, без высоты
else: a4_bay=None
# --- мебель: размер через глубину (px*depth/f) ---
m=YOLO(f"{D}/yolov8s-world.pt"); cls=["chair","dining table","couch","potted plant","radiator"]; m.set_classes(cls)
yb=m.predict(f"{D}/room1.jpg",conf=0.25,iou=0.5,verbose=False)[0]
furn=[]
for b in yb.boxes:
    x1,y1,x2,y2=[int(v) for v in b.xyxy[0].tolist()]; nm=cls[int(b.cls)]
    d=float(np.percentile(depth[y1:y2,x1:x2],30))
    furn.append({"name":nm,"box":[x1,y1,x2,y2],"w":round((x2-x1)*d/fx),"h":round((y2-y1)*d/fx)})

res={"tier":"free (hybrid: solvePnP+A4 масштаб/пол, metric-depth высоты/стены)","room_wxd_cm":[room_w,room_d],
     "ceiling_cm":ceil,"a4_to_bay_cm":a4_bay,"windows":[{k:w[k] for k in("w","h")} for w in wins],
     "furniture":[{"name":f["name"],"w_cm":f["w"],"h_cm":f["h"]} for f in furn]}
json.dump(res,open(f"{RUN}/measurements.json","w"),ensure_ascii=False,indent=2)

# --- рендер ---
fin=img.copy(); cv2.polylines(fin,[a4.astype(int).reshape(-1,1,2)],True,(255,60,0),2)
def lab(t,p,c,s=0.6):
    x,y=int(p[0]),int(p[1]);(tw,th),_=cv2.getTextSize(t,cv2.FONT_HERSHEY_SIMPLEX,s,2)
    cv2.rectangle(fin,(x-2,y-th-5),(x+tw+2,y+3),(255,255,255),-1);cv2.putText(fin,t,(x,y),cv2.FONT_HERSHEY_SIMPLEX,s,c,2)
for wd in wins:
    x,y,w,h=wd["box"]; cv2.rectangle(fin,(x,y),(x+w,y+h),(255,200,0),2); lab(f"~{wd['w']}x{wd['h']}см",(x,max(y-6,20)),(255,150,0),0.6)
for f in furn:
    x1,y1,x2,y2=f["box"]; cv2.rectangle(fin,(x1,y1),(x2,y2),(0,140,255),2); lab(f"~{f['name']} {f['w']}x{f['h']}",(x1,max(y1-6,14)),(0,140,255),0.48)
if a4_bay: cv2.line(fin,a4c,(int(xs0.mean()),int(ys0.mean())),(0,0,220),2); lab(f"A4->эркер {a4_bay}",(a4c[0]-70,a4c[1]-30),(0,0,220),0.55)
cv2.rectangle(fin,(0,0),(W,90),(30,30,30),-1)
cv2.putText(fin,f"REMLAB бесплатный (гибрид A4+metric-depth): комната ~{room_w}x{room_d}см, потолок {ceil}см",(10,34),cv2.FONT_HERSHEY_SIMPLEX,0.5,(255,255,255),1)
cv2.putText(fin,"размеры сквозь мебель (depth по стенам/потолку) + масштаб по A4 | голуб=окна, синие=мебель",(10,66),cv2.FONT_HERSHEY_SIMPLEX,0.44,(0,200,255),1)
cv2.imwrite(f"{RUN}/final.jpg",fin,[cv2.IMWRITE_JPEG_QUALITY,88])
print(json.dumps(res,ensure_ascii=False,indent=2))
