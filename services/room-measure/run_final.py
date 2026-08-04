import cv2, numpy as np, json, os, torch
import cv_refine as CVR
from geometry_solver import Solver
from torchvision.models.detection import maskrcnn_resnet50_fpn, MaskRCNN_ResNet50_FPN_Weights
from torchvision.transforms.functional import to_tensor
D=os.path.dirname(os.path.abspath(__file__)); RUN="/tmp/room-measure/run-11"; os.makedirs(RUN,exist_ok=True)
PERSON_H=190; CEILING=263; MATTRESS_W=100
img=cv2.imread(f"{D}/room1.jpg"); H,W=img.shape[:2]
G=json.load(open(f"{D}/02_vision_gpt55.json"))
a4,_=CVR.refine_a4(img); a4c=(int(a4[:,0].mean()),int(a4[:,1].mean()))
FOV=round(float(min(np.arange(58,68,0.3),key=lambda f:abs(Solver(img,a4,f).C[2]-0.82*PERSON_H))),1)
sol=Solver(img,a4,FOV); Ki,R,C=sol.Ki,sol.R,sol.C; t=(-R@C).reshape(3); fx=float(sol.K[0,0])
raw=np.load(f"{D}/depth_raw.npy"); seg=np.load(f"{D}/seg.npy")
depth=raw*100*(float((R@sol.floor(*a4c)+t)[2])/(float(raw[a4c[1],a4c[0]])*100))
def wpx(us,vs):
    Z=depth[vs,us];rays=Ki@np.vstack([us,vs,np.ones_like(us)]).astype(float);return (R.T@(rays*Z/rays[2]-t[:,None])).T

# ---------- комната/потолок/эркер (как в run_plan: SegFormer stuff + gpt-5.5 контур) ----------
ys,xs=np.where((seg==0)|(seg==5)); s=slice(0,len(xs),max(1,len(xs)//4000))
P=wpx(xs[s],ys[s]); P=P[(P[:,2]>-50)&(P[:,2]<330)]
room_w=round(float(np.percentile(P[:,0],97)-np.percentile(P[:,0],3))); room_d=round(float(np.percentile(P[:,1],97)-np.percentile(P[:,1],3)))
cy,cx=np.where(seg==5); ceil=round(float(np.median(wpx(cx[::max(1,len(cx)//300)],cy[::max(1,len(cy)//300)])[:,2])))
order=["floor_wall_edge_left","floor_wall_edge_back_bay","floor_wall_edge_right"]
lines={l["label"]:l["coordinates"] for l in G["key_lines"] if l["label"] in order}
bay_px=lines["floor_wall_edge_back_bay"]; bayW=np.array([sol.floor(x,y)[:2] for x,y in bay_px])
op0,op1=bayW[0],bayW[-1]; bay_open=round(float(np.linalg.norm(op1-op0)))
bvh=[]
for l in G["key_lines"]:
    if "bay_opening" in l["label"] and "vertical" in l["label"]:
        ps=sorted(l["coordinates"],key=lambda p:p[1]);top,bot=ps[0],ps[-1]
        Xb=sol.floor(*bot);dr=sol.ray(*top);sf=((Xb[0]-C[0])/dr[0]+(Xb[1]-C[1])/dr[1])/2;bvh.append(C[2]+sf*dr[2])
bay_h=round(float(np.median(bvh))) if bvh else None
win=(seg==8);ys0,xs0=np.where(win);bx0,bx1,by0,by1=int(xs0.min()),int(xs0.max()),int(ys0.min()),int(ys0.max())
bayw=(seg==0).copy();bayw[:by0]=False;bayw[by1+80:]=False;bayw[:,:bx0-20]=False;bayw[:,bx1+20:]=False
yy,xx=np.where(bayw);s2=slice(0,len(xx),max(1,len(xx)//2000));Y_bay=float(np.median(wpx(xx[s2],yy[s2])[:,1]))
# глубина эркера = протрузия задней стены эркера за плоскость боковой стены комнаты
rwm=(seg==0).copy();rwm[:, :760]=False;yr,xr=np.where(rwm);s4=slice(0,len(xr),max(1,len(xr)//2000))
Y_main=float(np.median(wpx(xr[s4],yr[s4])[:,1])); bay_depth=round(Y_bay-Y_main)
glaz_w=round((bx1-bx0)*Y_bay/fx);glaz_h=round((by1-by0)*Y_bay/fx)
# ===== ДОБАВЛЕННЫЕ РАЗМЕРЫ (были не учтены) =====
allc=[]
for lb in order:
    for p in lines.get(lb,[]):
        if not allc or (abs(p[0]-allc[-1][0])+abs(p[1]-allc[-1][1]))>3: allc.append([int(p[0]),int(p[1])])
CW=np.array([sol.floor(x,y)[:2] for x,y in allc])
seglens=[round(float(np.linalg.norm(CW[i+1]-CW[i]))) for i in range(len(CW)-1)]
perim=round(sum(seglens))
wall_area=round(perim*ceil/10000,1)               # м² видимых стен (брутто)
floor_area=round(room_w*room_d/10000,1)           # м² пол/потолок (bbox-оценка видимой зоны)
def onwall(u,v): d=sol.ray(u,v); tp=(Y_bay-C[1])/d[1]; return float((C+tp*d)[2])
sill=round(onwall(int((bx0+bx1)/2),by1))          # высота подоконника (пол->низ окна)
wtop=round(onwall(int((bx0+bx1)/2),by0))          # верх остекления над полом
win_to_ceil=round(ceil-wtop)                      # окно->потолок (лоб/простенок)

# ---------- МЕБЕЛЬ: Mask R-CNN инстансы + наш обмер ----------
w=MaskRCNN_ResNet50_FPN_Weights.DEFAULT; names=w.meta["categories"]; model=maskrcnn_resnet50_fpn(weights=w).eval()
with torch.no_grad(): det=model([to_tensor(cv2.cvtColor(img,cv2.COLOR_BGR2RGB))])[0]
PR={"chair":(35,70,80,120,"vert"),"dining table":(30,160,45,95,"surf"),"bed":(70,220,10,60,"ext"),"couch":(70,260,15,90,"ext")}
def measure(mask,mode):
    yy,xx=np.where(mask); ss=slice(0,len(xx),max(1,len(xx)//4000)); uu,vv=xx[ss],yy[ss]; dv=depth[vv,uu]
    hist,e=np.histogram(dv,40);pk=e[np.argmax(hist)];k=(dv>pk-45)&(dv<pk+55)
    if k.sum()<50: return None
    Q=wpx(uu[k],vv[k]);Q=Q[(Q[:,2]>-20)&(Q[:,2]<200)]
    if len(Q)<50: return None
    xy=Q[:,:2]-Q[:,:2].mean(0);_,_,Vt=np.linalg.svd(xy,full_matrices=False);pr=xy@Vt.T
    wd=abs(np.percentile(pr[:,0],95)-np.percentile(pr[:,0],5));dp=abs(np.percentile(pr[:,1],95)-np.percentile(pr[:,1],5))
    if mode=="vert":
        ay,ax=np.where(mask);ty=ay.min();tx=int(np.median(ax[ay<=ty+4]));by=ay.max();bxx=int(np.median(ax[ay>=by-4]))
        Xb=sol.floor(bxx,by);dr=sol.ray(tx,ty);sf=((Xb[0]-C[0])/dr[0]+(Xb[1]-C[1])/dr[1])/2;h=float(C[2]+sf*dr[2])
    elif mode=="surf": h=float(np.median(Q[:,2]))
    else: h=np.percentile(Q[:,2],95)-max(0,np.percentile(Q[:,2],5))
    seat=None
    if mode=="vert":
        zc=Q[(Q[:,2]>30)&(Q[:,2]<62),2];seat=round(float(np.median(zc))) if len(zc)>15 else None
    return {"w":round(min(wd,dp)),"d":round(max(wd,dp)),"h":round(h),"seat":seat}
furn=[]
for b,l,sc,m in zip(det["boxes"],det["labels"],det["scores"],det["masks"]):
    nm=names[l]
    if sc<0.5 or nm not in PR: continue
    wmin,wmax,hmin,hmax,mode=PR[nm]; mask=(m[0].numpy()>0.5)
    r=measure(mask,mode)
    if not r: continue
    x1,y1,x2,y2=[int(v) for v in b.tolist()]
    edge = x1<=3 or y1<=3 or x2>=W-3 or y2>=H-3
    label={"chair":"стул","dining table":"стол","bed":"матрас","couch":"матрас"}[nm]
    if not edge and not (wmin<=r["w"]<=wmax and hmin<=r["h"]<=hmax): continue
    furn.append({"label":label,**r,"box":[x1,y1,x2,y2],"conf":round(float(sc),2),"partial":edge})

res={"fov":FOV,"cam_h":round(float(C[2]),1),"room_wxd":[room_w,room_d],"ceiling":ceil,"ceiling_input":CEILING,
     "perimeter_visible_cm":perim,"wall_segments_cm":seglens,"wall_area_m2":wall_area,"floor_ceiling_area_m2":floor_area,
     "bay_hxwxd":[bay_h,bay_open,bay_depth],"glazing_wxh":[glaz_w,glaz_h],
     "windowsill_h_cm":sill,"window_top_h_cm":wtop,"window_to_ceiling_cm":win_to_ceil,
     "furniture":[{k:f[k] for k in("label","w","d","h","seat","conf","partial")} for f in furn]}
json.dump(res,open(f"{RUN}/measurements.json","w"),ensure_ascii=False,indent=2)

# ---------- рендер ----------
fin=img.copy();cv2.polylines(fin,[a4.astype(int).reshape(-1,1,2)],True,(255,60,0),2)
def L(tx,p,c,s=0.5):
    x,y=int(p[0]),int(p[1]);(tw,th),_=cv2.getTextSize(tx,cv2.FONT_HERSHEY_SIMPLEX,s,2)
    cv2.rectangle(fin,(x-2,y-th-4),(x+tw+2,y+3),(255,255,255),-1);cv2.putText(fin,tx,(x,y),cv2.FONT_HERSHEY_SIMPLEX,s,c,1)
# ===== ПОЛНЫЙ КАРКАС КОМНАТЫ (пол + потолок + вертикальные рёбра) =====
# 1) низ: контур пол↔стена + длина каждой стены
for i in range(len(allc)-1):
    cv2.line(fin,tuple(allc[i]),tuple(allc[i+1]),(0,200,0),3)
    if seglens[i]>25: L(str(seglens[i]),((allc[i][0]+allc[i+1][0])//2-10,(allc[i][1]+allc[i+1][1])//2-4),(0,130,0),0.55)
# 2) верх: линия стена↔потолок (gpt-5.5 точки)
for l in G["key_lines"]:
    if l["label"].startswith("wall_ceiling_edge"):
        p=np.array(l["coordinates"],int); cv2.polylines(fin,[p.reshape(-1,1,2)],False,(255,90,0),3)
# 3) вертикальные углы комнаты пол→потолок (рёбра стен) + высота
for l in G["key_lines"]:
    nm=l["label"]
    if ("bay_opening" in nm and "vertical" in nm) or nm=="right_wall_inside_corner_vertical" or nm.startswith("vertical_wall_edge"):
        p=np.array(l["coordinates"],int); cv2.line(fin,tuple(p[0]),tuple(p[-1]),(0,215,255),3)
L(f"выс.стен {ceil}",(int(W*0.62),int(H*0.30)),(0,150,180),0.6)
cv2.rectangle(fin,(bx0,by0),(bx1,by1),(255,150,0),2);L(f"остекл. {glaz_w}x{glaz_h}",(bx0,by0-6),(255,120,0))
# линия подоконника (горизонт) + окно->потолок
cv2.line(fin,(bx0,by1),(bx1,by1),(255,120,0),2);L(f"подоконник {sill}",(bx0,by1+18),(255,120,0),0.55)
cv2.line(fin,(bx0,by0),(bx1,by0),(180,80,0),2);L(f"окно->потолок {win_to_ceil}",(int((bx0+bx1)/2)-70,by0-8),(180,80,0),0.55)
# сводная панель площадей/периметра (крупно, справа-снизу)
py=H-120
for i,tx in enumerate([f"Периметр: {perim} см",f"Стены: ~{wall_area} м2",f"Пол/потолок: ~{floor_area} м2",f"Потолок: {ceil} см"]):
    L(tx,(W-260,py+i*26),(20,20,20),0.62)
cols={"стул":(0,140,255),"стол":(0,170,0),"матрас":(200,0,200)}
for f in furn:
    x1,y1,x2,y2=f["box"];c=cols[f["label"]];cv2.rectangle(fin,(x1,y1),(x2,y2),c,2)
    if f["label"]=="стул": txt=f"стул {f['w']}x{f['d']} сид{f['seat']} h{f['h']}"
    elif f["label"]=="стол": txt=f"стол {f['w']}x{f['d']} h{f['h']}"
    else: txt=f"матрас {MATTRESS_W if f['partial'] else f['w']}{'*' if f['partial'] else ''} h{f['h']}"
    L(txt,(x1,max(y1-6,14)),c)
cv2.rectangle(fin,(0,0),(W,92),(30,30,30),-1)
cv2.putText(fin,f"REMLAB 1-фото: комната ~{room_w}x{room_d}, потолок {ceil}, ЭРКЕР В{bay_h}xШ{bay_open}xГ{bay_depth}",(10,34),cv2.FONT_HERSHEY_SIMPLEX,0.45,(255,255,255),1)
cv2.putText(fin,f"периметр {perim} | стены ~{wall_area}м2 | пол ~{floor_area}м2 | подоконник {sill} | мебель=Mask R-CNN",(10,66),cv2.FONT_HERSHEY_SIMPLEX,0.42,(0,200,255),1)
cv2.imwrite(f"{RUN}/final.jpg",fin,[cv2.IMWRITE_JPEG_QUALITY,88])
print(json.dumps(res,ensure_ascii=False,indent=2))
