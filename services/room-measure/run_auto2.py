import cv2, numpy as np, json, os, torch, torch.nn.functional as F
import cv_refine as CVR
from geometry_solver import Solver
from transformers import AutoConfig, AutoImageProcessor, AutoModelForDepthEstimation
from PIL import Image
D=os.path.dirname(os.path.abspath(__file__)); RUN="/tmp/room-measure/run-8"; os.makedirs(RUN,exist_ok=True)
PHOTO=f"{D}/room1.jpg"; PHONE="iPhone SE 3"; PERSON_H=190; CEILING=263
img=cv2.imread(PHOTO); H,W=img.shape[:2]

# ---------- сырая глубина (кэш) ----------
if os.path.exists(f"{D}/depth_raw.npy"):
    raw=np.load(f"{D}/depth_raw.npy")
else:
    nm="depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf"
    pr=AutoImageProcessor.from_pretrained(nm); md=AutoModelForDepthEstimation.from_pretrained(nm).eval()
    with torch.no_grad(): dd=md(**pr(images=Image.open(PHOTO).convert("RGB"),return_tensors="pt")).predicted_depth
    raw=F.interpolate(dd[None],(H,W),mode="bicubic",align_corners=False)[0,0].numpy(); np.save(f"{D}/depth_raw.npy",raw)
seg=np.load(f"{D}/seg.npy")
a4,_=CVR.refine_a4(img); a4c=(int(a4[:,0].mean()),int(a4[:,1].mean()))

# ---------- АВТО-калибровка FOV по росту (камера ≈ 0.82*рост) ----------
target_h=0.82*PERSON_H
def cam_height(fov):
    s=Solver(img,a4,fov); return float(s.C[2]),s
best=min(np.arange(58,68,0.3), key=lambda f: abs(cam_height(f)[0]-target_h))
FOV=round(float(best),1); camh,sol=cam_height(FOV)
Ki,R,C=sol.Ki,sol.R,sol.C; t=(-R@C).reshape(3)

# ---------- якорь глубины по A4 (под выбранный FOV) ----------
Xc=R@sol.floor(*a4c)+t; true_d=float(Xc[2]); model_d=float(raw[a4c[1],a4c[0]])*100
depth=raw*100*(true_d/model_d)
def wpx(us,vs):
    Z=depth[vs,us]; rays=Ki@np.vstack([us,vs,np.ones_like(us)]).astype(float)
    return (R.T@(rays*Z/rays[2]-t[:,None])).T

# ---------- комната + потолок ----------
ys,xs=np.where((seg==0)|(seg==5)); s=slice(0,len(xs),max(1,len(xs)//4000))
P=wpx(xs[s],ys[s]); P=P[(P[:,2]>-50)&(P[:,2]<330)]
room_w=round(float(np.percentile(P[:,0],97)-np.percentile(P[:,0],3)))
room_d=round(float(np.percentile(P[:,1],97)-np.percentile(P[:,1],3)))
cy,cx=np.where(seg==5); ceil=round(float(np.median(wpx(cx[::max(1,len(cx)//300)],cy[::max(1,len(cy)//300)])[:,2]))) if len(cy) else CEILING

# ---------- объекты: маска -> компонента -> КЛАСТЕР по глубине -> 3D + ФИЛЬТР ----------
cfg=AutoConfig.from_pretrained("nvidia/segformer-b2-finetuned-ade-512-512")
nid={v.lower():int(k) for k,v in cfg.id2label.items()}
gid=lambda *ns:next((v for n in ns for k,v in nid.items() if n in k),None)
CLS=[("стул",gid("chair"),(35,120,40,110)),("стол",gid("table"),(50,160,60,120)),
     ("матрас",gid("bed"),(70,220,10,60)),("окно",gid("windowpane"),(40,300,40,240)),
     ("растение",gid("plant"),(20,120,25,180))]  # (w_min,w_max,h_min,h_max) фильтр
objs=[]
for lbl,cid,(wmin,wmax,hmin,hmax) in CLS:
    if cid is None: continue
    m=cv2.morphologyEx((seg==cid).astype(np.uint8),cv2.MORPH_OPEN,np.ones((5,5),np.uint8))
    n,lab,st,_=cv2.connectedComponentsWithStats(m)
    for i in range(1,n):
        if st[i,cv2.CC_STAT_AREA]<3500: continue
        yy,xx=np.where(lab==i); ss=slice(0,len(xx),max(1,len(xx)//3000))
        uu,vv=xx[ss],yy[ss]; dv=depth[vv,uu]
        front=np.percentile(dv,20); keep=dv<front*1.25+40      # кластер: ближняя поверхность объекта
        if keep.sum()<40: continue
        Q=wpx(uu[keep],vv[keep]); Q=Q[(Q[:,2]>-30)&(Q[:,2]<330)]
        if len(Q)<40: continue
        w=round(float(np.percentile(Q[:,0],95)-np.percentile(Q[:,0],5)))
        h=round(float(np.percentile(Q[:,2],95)-max(0,np.percentile(Q[:,2],5))))
        if not (wmin<=w<=wmax and hmin<=h<=hmax): continue   # ФИЛЬТР ложных
        objs.append({"label":lbl,"w_cm":w,"h_cm":h,"box":[int(st[i,0]),int(st[i,1]),int(st[i,2]),int(st[i,3])]})

res={"auto":True,"fov_auto_deg":FOV,"cam_height_cm":round(camh,1),"room_wxd_cm":[room_w,room_d],
     "ceiling_cm":ceil,"ceiling_input":CEILING,"objects":objs}
json.dump(res,open(f"{RUN}/measurements.json","w"),ensure_ascii=False,indent=2)
fin=img.copy(); cv2.polylines(fin,[a4.astype(int).reshape(-1,1,2)],True,(255,60,0),2)
def L(t,p,c,s=0.55):
    x,y=int(p[0]),int(p[1]);(tw,th),_=cv2.getTextSize(t,cv2.FONT_HERSHEY_SIMPLEX,s,2)
    cv2.rectangle(fin,(x-2,y-th-5),(x+tw+2,y+3),(255,255,255),-1);cv2.putText(fin,t,(x,y),cv2.FONT_HERSHEY_SIMPLEX,s,c,2)
for o in objs:
    x,y,w,h=o["box"]; col=(255,150,0) if o["label"]=="окно" else (0,140,255)
    cv2.rectangle(fin,(x,y),(x+w,y+h),col,2); L(f"{o['label']} {o['w_cm']}x{o['h_cm']}",(x,max(y-6,16)),col,0.5)
cv2.rectangle(fin,(0,0),(W,90),(30,30,30),-1)
cv2.putText(fin,f"REMLAB АВТО+калибр: комната ~{room_w}x{room_d}, потолок {ceil}(эталон {CEILING}), FOV авто {FOV}, камера {round(camh)}см",(10,34),cv2.FONT_HERSHEY_SIMPLEX,0.44,(255,255,255),1)
cv2.putText(fin,"FOV откалиброван по росту | кластер глубины + фильтр ложных | всё алгоритмами",(10,66),cv2.FONT_HERSHEY_SIMPLEX,0.44,(0,200,255),1)
cv2.imwrite(f"{RUN}/final.jpg",fin,[cv2.IMWRITE_JPEG_QUALITY,88])
print(f"FOV авто={FOV} камера={round(camh,1)}см | комната {room_w}x{room_d} | потолок {ceil} (эталон {CEILING})")
for o in objs: print(f"  {o['label']:9} {o['w_cm']}x{o['h_cm']}")
