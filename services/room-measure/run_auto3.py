import cv2, numpy as np, json, os
import cv_refine as CVR
from geometry_solver import Solver
from transformers import AutoConfig
D=os.path.dirname(os.path.abspath(__file__)); RUN="/tmp/room-measure/run-9"; os.makedirs(RUN,exist_ok=True)
PERSON_H=190; CEILING=263
img=cv2.imread(f"{D}/room1.jpg"); H,W=img.shape[:2]
a4,_=CVR.refine_a4(img); a4c=(int(a4[:,0].mean()),int(a4[:,1].mean()))
FOV=round(float(min(np.arange(58,68,0.3),key=lambda f:abs(Solver(img,a4,f).C[2]-0.82*PERSON_H))),1)
sol=Solver(img,a4,FOV); Ki,R,C=sol.Ki,sol.R,sol.C; t=(-R@C).reshape(3); fx=float(sol.K[0,0]); camh=float(C[2])
raw=np.load(f"{D}/depth_raw.npy"); seg=np.load(f"{D}/seg.npy")
depth=raw*100*(float((R@sol.floor(*a4c)+t)[2])/(float(raw[a4c[1],a4c[0]])*100))
def wpx(us,vs):
    Z=depth[vs,us];rays=Ki@np.vstack([us,vs,np.ones_like(us)]).astype(float);return (R.T@(rays*Z/rays[2]-t[:,None])).T
cfg=AutoConfig.from_pretrained("nvidia/segformer-b2-finetuned-ade-512-512")
nid={v.lower():int(k) for k,v in cfg.id2label.items()}; gid=lambda *ns:next((v for n in ns for k,v in nid.items() if n in k),None)

# --- комната + потолок (по стенам+потолку, БЕЗ стекла) ---
ys,xs=np.where((seg==0)|(seg==5)); s=slice(0,len(xs),max(1,len(xs)//4000))
P=wpx(xs[s],ys[s]); P=P[(P[:,2]>-50)&(P[:,2]<330)]
room_w=round(float(np.percentile(P[:,0],97)-np.percentile(P[:,0],3))); room_d=round(float(np.percentile(P[:,1],97)-np.percentile(P[:,1],3)))
cy,cx=np.where(seg==5); ceil=round(float(np.median(wpx(cx[::max(1,len(cx)//300)],cy[::max(1,len(cy)//300)])[:,2]))) if len(cy) else CEILING

# --- эркер: задняя плоскость по СТЕНЕ + 3 окна на плоскости стены ---
win=(seg==8); wall=(seg==0); ys0,xs0=np.where(win)
bx0,bx1,by0,by1=int(xs0.min()),int(xs0.max()),int(ys0.min()),int(ys0.max())
bayw=wall.copy(); bayw[:by0,:]=False; bayw[by1+80:,:]=False; bayw[:,:bx0-20]=False; bayw[:,bx1+20:]=False
yy,xx=np.where(bayw); s2=slice(0,len(xx),max(1,len(xx)//2000)); Y_bay=float(np.median(wpx(xx[s2],yy[s2])[:,1]))
rw=wall.copy(); rw[:, :760]=False; yr,xr=np.where(rw); s3=slice(0,len(xr),max(1,len(xr)//2000)); Y_main=float(np.median(wpx(xr[s3],yr[s3])[:,1]))
bay_depth=round(Y_bay-Y_main)
# Оконная зона эркера ЦЕЛИКОМ (деление на створки неоднозначно -> в бэклог)
bw=round((bx1-bx0)*Y_bay/fx); bh=round((by1-by0)*Y_bay/fx)
windows=[{"box":[bx0,by0,bx1-bx0,by1-by0],"w":bw,"h":bh,"note":"зона остекления эркера целиком"}]

# --- мебель: ориент-бокс(PCA) + кластер глубины + фильтр; стул -> высота сиденья ---
def analyze(cid,seat=False,height="extent"):
    out=[]; m=cv2.morphologyEx((seg==cid).astype(np.uint8),cv2.MORPH_OPEN,np.ones((5,5),np.uint8))
    n,lab,st,_=cv2.connectedComponentsWithStats(m)
    for i in range(1,n):
        if st[i,cv2.CC_STAT_AREA]<4000: continue
        yy,xx=np.where(lab==i); ss=slice(0,len(xx),max(1,len(xx)//4000)); uu,vv=xx[ss],yy[ss]; dv=depth[vv,uu]
        hist,edges=np.histogram(dv,bins=40); peak=edges[np.argmax(hist)]; keep=(dv>peak-45)&(dv<peak+55)
        if keep.sum()<50: continue
        Q=wpx(uu[keep],vv[keep]); Q=Q[(Q[:,2]>-20)&(Q[:,2]<200)]
        if len(Q)<50: continue
        xy=Q[:,:2]-Q[:,:2].mean(0); _,_,Vt=np.linalg.svd(xy,full_matrices=False); pr=xy@Vt.T
        w=abs(np.percentile(pr[:,0],95)-np.percentile(pr[:,0],5)); d=abs(np.percentile(pr[:,1],95)-np.percentile(pr[:,1],5))
        if height=="vertical":   # стул/окно: верх маски через вертикаль над основанием (спинка тонкая)
            ally,allx=np.where(lab==i)
            topy=ally.min(); topx=int(np.median(allx[ally<=topy+4]))
            boty=ally.max(); botx=int(np.median(allx[ally>=boty-4]))
            Xb=sol.floor(botx,boty); dr=sol.ray(topx,topy)
            sfac=((Xb[0]-C[0])/dr[0]+(Xb[1]-C[1])/dr[1])/2; th=float(C[2]+sfac*dr[2])
        else:                    # плоский (матрас/стол): Z-протяжённость облака
            th=np.percentile(Q[:,2],95)-max(0,np.percentile(Q[:,2],5))
        o={"w":round(min(w,d)),"d":round(max(w,d)),"h":round(th),"box":[int(st[i,0]),int(st[i,1]),int(st[i,2]),int(st[i,3])]}
        if seat:
            zc=Q[(Q[:,2]>30)&(Q[:,2]<62),2]; o["seat"]=round(float(np.median(zc))) if len(zc)>15 else None
        out.append(o)
    return out
chairs=[c for c in analyze(gid("chair"),seat=True,height="vertical") if 35<=c["w"]<=70 and 60<=c["h"]<=110]
tables=[c for c in analyze(gid("table")) if 50<=c["w"]<=160]
beds=[c for c in analyze(gid("bed")) if 60<=c["w"]<=250]

res={"auto":True,"fov":FOV,"cam_h":round(camh,1),"room_wxd":[room_w,room_d],"ceiling":ceil,"ceiling_input":CEILING,
     "bay_depth_cm":bay_depth,"windows":[{k:w[k] for k in("w","h")} for w in windows],
     "chairs":[{"footprint":f"{c['w']}x{c['d']}","seat_h":c.get("seat"),"total_h":c["h"]} for c in chairs],
     "tables":[{"w":c["w"],"h":c["h"]} for c in tables],"mattress":[{"w":c["w"],"h":c["h"]} for c in beds]}
json.dump(res,open(f"{RUN}/measurements.json","w"),ensure_ascii=False,indent=2)

fin=img.copy(); cv2.polylines(fin,[a4.astype(int).reshape(-1,1,2)],True,(255,60,0),2)
def L(tx,p,c,s=0.5):
    x,y=int(p[0]),int(p[1]);(tw,th),_=cv2.getTextSize(tx,cv2.FONT_HERSHEY_SIMPLEX,s,2)
    cv2.rectangle(fin,(x-2,y-th-5),(x+tw+2,y+3),(255,255,255),-1);cv2.putText(fin,tx,(x,y),cv2.FONT_HERSHEY_SIMPLEX,s,c,2)
for wd in windows:
    x,y,w,h=wd["box"]; cv2.rectangle(fin,(x,y),(x+w,y+h),(255,150,0),2); L(f"остекление {wd['w']}x{wd['h']}",(x,max(y-6,16)),(255,120,0),0.5)
for c in chairs:
    x,y,w,h=c["box"]; cv2.rectangle(fin,(x,y),(x+w,y+h),(0,140,255),2); L(f"стул {c['w']}x{c['d']} сид.{c.get('seat')}",(x,max(y-6,16)),(0,140,255),0.45)
for c in tables:
    x,y,w,h=c["box"]; cv2.rectangle(fin,(x,y),(x+w,y+h),(0,200,0),2); L(f"стол Ø{c['w']} h{c['h']}",(x,max(y-6,16)),(0,160,0),0.45)
for c in beds:
    x,y,w,h=c["box"]; cv2.rectangle(fin,(x,y),(x+w,y+h),(200,0,200),2); L(f"матрас {c['w']}x{c['h']}",(x,max(y-6,16)),(180,0,180),0.45)
cv2.rectangle(fin,(0,0),(W,92),(30,30,30),-1)
cv2.putText(fin,f"REMLAB АВТО: комната ~{room_w}x{room_d}, потолок {ceil}(эт.{CEILING}), ЭРКЕР глубина ~{bay_depth}см",(10,34),cv2.FONT_HERSHEY_SIMPLEX,0.46,(255,255,255),1)
cv2.putText(fin,f"остекление эркера целиком (деление на створки - в бэклог) | стул: footprint+высота сиденья | FOV авто {FOV}",(10,66),cv2.FONT_HERSHEY_SIMPLEX,0.42,(0,200,255),1)
cv2.imwrite(f"{RUN}/final.jpg",fin,[cv2.IMWRITE_JPEG_QUALITY,88])
print(json.dumps(res,ensure_ascii=False,indent=2))
