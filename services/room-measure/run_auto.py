"""Полностью АВТОМАТИЧЕСКИЙ замер: вход только (фото, модель телефона, рост, потолок).
Ноль ручного выбора пикселей — всё алгоритмами (A4-детект, solvePnP, depth, сегментация, 3D)."""
import cv2, numpy as np, json, os
import cv_refine as CVR
from geometry_solver import Solver
from transformers import AutoConfig
D=os.path.dirname(os.path.abspath(__file__)); RUN="/tmp/room-measure/run-7"; os.makedirs(RUN,exist_ok=True)

# ---------- ВХОД (единственное, что задаётся) ----------
PHOTO=f"{D}/room1.jpg"; PHONE="iPhone SE 3"; PERSON_H=190; CEILING=263

# ---------- FOV из модели телефона (алгоритм, не руками) ----------
PHONE_FOCAL_EQ={"iphone se 3":28.0,"iphone se 2":28.0,"iphone 15 pro":24.0,"iphone 15":26.0}  # 35мм-экв
def portrait_vfov(model):
    f=PHONE_FOCAL_EQ.get(model.lower(),26.0); diag=2*np.degrees(np.arctan(43.27/(2*f)))
    hd=np.tan(np.radians(diag/2)); return round(2*np.degrees(np.arctan(hd*4/5)),1)  # длинная ось (портрет-вертикаль)
FOV=portrait_vfov(PHONE)

img=cv2.imread(PHOTO); H,W=img.shape[:2]
# ---------- A4 автодетект + поза (OpenCV) ----------
a4,a4c_conf=CVR.refine_a4(img); sol=Solver(img,a4,FOV,ceiling_cm=CEILING)
Ki,R,C=sol.Ki,sol.R,sol.C; t=(-R@C).reshape(3)
a4c=(int(a4[:,0].mean()),int(a4[:,1].mean()))

# ---------- depth (кэш, посчитан Depth-Anything-V2-metric алгоритмом) + якорь A4 ----------
depth=np.load(f"{D}/depth_cm.npy")            # уже откалибр. по A4 в этом же пайплайне
seg=np.load(f"{D}/seg.npy")                    # SegFormer ADE20K
def wpx(us,vs):
    Z=depth[vs,us]; rays=Ki@np.vstack([us,vs,np.ones_like(us)]).astype(float)
    return (R.T@(rays*Z/rays[2]-t[:,None])).T

# ---------- габариты комнаты + потолок (по стенам+потолку, сквозь мебель) ----------
ys,xs=np.where((seg==0)|(seg==5)); s=slice(0,len(xs),max(1,len(xs)//4000))
P=wpx(xs[s],ys[s]); P=P[(P[:,2]>-50)&(P[:,2]<330)]
room_w=round(float(np.percentile(P[:,0],97)-np.percentile(P[:,0],3)))
room_d=round(float(np.percentile(P[:,1],97)-np.percentile(P[:,1],3)))
cy,cx=np.where(seg==5); ceil=round(float(np.median(wpx(cx[::max(1,len(cx)//300)],cy[::max(1,len(cy)//300)])[:,2]))) if len(cy) else CEILING

# ---------- объекты: маска -> связные компоненты -> 3D-протяжённость (Ш×Г×В) ----------
cfg=AutoConfig.from_pretrained("nvidia/segformer-b2-finetuned-ade-512-512")
nid={v.lower():int(k) for k,v in cfg.id2label.items()}
def gid(*ns):
    for n in ns:
        for k,v in nid.items():
            if n in k: return v
CLS=[("стул",gid("chair")),("стол",gid("table")),("матрас",gid("bed")),("окно",gid("windowpane")),("растение",gid("plant"))]
objs=[]
for lbl,cid in CLS:
    if cid is None: continue
    m=cv2.morphologyEx((seg==cid).astype(np.uint8),cv2.MORPH_OPEN,np.ones((5,5),np.uint8))
    n,lab,st,_=cv2.connectedComponentsWithStats(m)
    for i in range(1,n):
        if st[i,cv2.CC_STAT_AREA]<3000: continue
        yy,xx=np.where(lab==i); ss=slice(0,len(xx),max(1,len(xx)//2500))
        Q=wpx(xx[ss],yy[ss]); Q=Q[(Q[:,2]>-30)&(Q[:,2]<330)]
        if len(Q)<40: continue
        w=round(float(np.percentile(Q[:,0],95)-np.percentile(Q[:,0],5)))
        h=round(float(np.percentile(Q[:,2],95)-max(0,np.percentile(Q[:,2],5))))
        bx,by,bw,bh=st[i,0],st[i,1],st[i,2],st[i,3]
        objs.append({"label":lbl,"w_cm":w,"h_cm":h,"box":[int(bx),int(by),int(bw),int(bh)]})

res={"auto":True,"inputs":{"phone":PHONE,"person_h":PERSON_H,"ceiling":CEILING},"fov_deg":FOV,
     "room_wxd_cm":[room_w,room_d],"ceiling_cm":ceil,"objects":objs}
json.dump(res,open(f"{RUN}/measurements.json","w"),ensure_ascii=False,indent=2)

# ---------- рендер ----------
fin=img.copy(); cv2.polylines(fin,[a4.astype(int).reshape(-1,1,2)],True,(255,60,0),2)
def L(t,p,c,s=0.55):
    x,y=int(p[0]),int(p[1]);(tw,th),_=cv2.getTextSize(t,cv2.FONT_HERSHEY_SIMPLEX,s,2)
    cv2.rectangle(fin,(x-2,y-th-5),(x+tw+2,y+3),(255,255,255),-1);cv2.putText(fin,t,(x,y),cv2.FONT_HERSHEY_SIMPLEX,s,c,2)
for o in objs:
    x,y,w,h=o["box"]; col=(255,150,0) if o["label"]=="окно" else (0,140,255)
    cv2.rectangle(fin,(x,y),(x+w,y+h),col,2); L(f"{o['label']} {o['w_cm']}x{o['h_cm']}",(x,max(y-6,16)),col,0.5)
cv2.rectangle(fin,(0,0),(W,90),(30,30,30),-1)
cv2.putText(fin,f"REMLAB АВТО (0 ручного): комната ~{room_w}x{room_d}см, потолок {ceil}см, FOV {FOV}(из модели)",(10,34),cv2.FONT_HERSHEY_SIMPLEX,0.48,(255,255,255),1)
cv2.putText(fin,"всё алгоритмами: A4-детект+solvePnP, Depth-Anything, SegFormer, 3D-обмер объектов",(10,66),cv2.FONT_HERSHEY_SIMPLEX,0.44,(0,200,255),1)
cv2.imwrite(f"{RUN}/final.jpg",fin,[cv2.IMWRITE_JPEG_QUALITY,88])
print("FOV из модели:",FOV,"| комната",room_w,"x",room_d,"| потолок",ceil)
for o in objs: print(f"  {o['label']:9} {o['w_cm']}x{o['h_cm']} см")
