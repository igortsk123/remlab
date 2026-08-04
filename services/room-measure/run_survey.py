import cv2, numpy as np, json, os, torch, base64, urllib.request
import cv_refine as CVR
from geometry_solver import Solver
from torchvision.models.detection import maskrcnn_resnet50_fpn, MaskRCNN_ResNet50_FPN_Weights
from torchvision.transforms.functional import to_tensor
D=os.path.dirname(os.path.abspath(__file__)); RUN="/tmp/room-measure/run-12"; os.makedirs(RUN,exist_ok=True)
KEY=os.environ["FAL_KEY"]; PERSON_H=190; CEILING=263; MATTRESS_W=100
img=cv2.imread(f"{D}/room1.jpg"); H,W=img.shape[:2]
G=json.load(open(f"{D}/02_vision_gpt55.json"))
a4,_=CVR.refine_a4(img); a4c=(int(a4[:,0].mean()),int(a4[:,1].mean()))
FOV=round(float(min(np.arange(58,68,0.3),key=lambda f:abs(Solver(img,a4,f).C[2]-0.82*PERSON_H))),1)
sol=Solver(img,a4,FOV); Ki,R,C=sol.Ki,sol.R,sol.C; t=(-R@C).reshape(3); fx=float(sol.K[0,0]); K=sol.K
raw=np.load(f"{D}/depth_raw.npy"); seg=np.load(f"{D}/seg.npy")
depth=raw*100*(float((R@sol.floor(*a4c)+t)[2])/(float(raw[a4c[1],a4c[0]])*100))
def wpx(us,vs): Z=depth[vs,us];r=Ki@np.vstack([us,vs,np.ones_like(us)]).astype(float);return (R.T@(r*Z/r[2]-t[:,None])).T
def topx(Xw): Xc=R@np.array([Xw[0],Xw[1],0.0])+t;p=K@Xc;return (int(p[0]/p[2]),int(p[1]/p[2]))

# --- комната/потолок ---
ys,xs=np.where((seg==0)|(seg==5));s=slice(0,len(xs),max(1,len(xs)//4000))
P=wpx(xs[s],ys[s]);P=P[(P[:,2]>-50)&(P[:,2]<330)]
room_w=round(float(np.percentile(P[:,0],97)-np.percentile(P[:,0],3)));room_d=round(float(np.percentile(P[:,1],97)-np.percentile(P[:,1],3)))
cy,cx=np.where(seg==5);ceil=round(float(np.median(wpx(cx[::max(1,len(cx)//300)],cy[::max(1,len(cy)//300)])[:,2])))
# --- контур пола (gpt точки) + длины + периметр + площади ---
order=["floor_wall_edge_left","floor_wall_edge_back_bay","floor_wall_edge_right"]
lines={l["label"]:l["coordinates"] for l in G["key_lines"] if l["label"] in order}
allc=[]
for lb in order:
    for p in lines.get(lb,[]):
        if not allc or (abs(p[0]-allc[-1][0])+abs(p[1]-allc[-1][1]))>3: allc.append([int(p[0]),int(p[1])])
CW=np.array([sol.floor(x,y)[:2] for x,y in allc])
seglen=[round(float(np.linalg.norm(CW[i+1]-CW[i]))) for i in range(len(CW)-1)]
perim=round(sum(seglen)); wall_area=round(perim*ceil/10000,1); floor_area=round(room_w*room_d/10000,1)
# --- эркер В×Ш×Г ---
bay=lines["floor_wall_edge_back_bay"];bayW=np.array([sol.floor(x,y)[:2] for x,y in bay])
bay_open=round(float(np.linalg.norm(bayW[-1]-bayW[0])))
bvh=[]
for l in G["key_lines"]:
    if "bay_opening" in l["label"] and "vertical" in l["label"]:
        ps=sorted(l["coordinates"],key=lambda p:p[1]);Xb=sol.floor(*ps[-1]);dr=sol.ray(*ps[0]);sfc=((Xb[0]-C[0])/dr[0]+(Xb[1]-C[1])/dr[1])/2;bvh.append(C[2]+sfc*dr[2])
bay_h=round(float(np.median(bvh)))
win=(seg==8);ys0,xs0=np.where(win);bx0,bx1,by0,by1=int(xs0.min()),int(xs0.max()),int(ys0.min()),int(ys0.max())
bw=(seg==0).copy();bw[:by0]=False;bw[by1+80:]=False;bw[:,:bx0-20]=False;bw[:,bx1+20:]=False
yy,xx=np.where(bw);Y_bay=float(np.median(wpx(xx[::max(1,len(xx)//2000)],yy[::max(1,len(yy)//2000)])[:,1]))
rwm=(seg==0).copy();rwm[:, :760]=False;yr,xr=np.where(rwm);Y_main=float(np.median(wpx(xr[::max(1,len(xr)//2000)],yr[::max(1,len(yr)//2000)])[:,1]))
bay_depth=round(Y_bay-Y_main)
glaz_w=round((bx1-bx0)*Y_bay/fx);glaz_h=round((by1-by0)*Y_bay/fx)
def onwall(u,v): d=sol.ray(u,v);tp=(Y_bay-C[1])/d[1];return float((C+tp*d)[2])
sill=round(onwall((bx0+bx1)//2,by1));win2ceil=round(ceil-onwall((bx0+bx1)//2,by0))
# ОКНА эркера по отдельности: деление по перегородке рамы (~x=340, найдено Hough), размер на плоскости стены
wins=[]
for a,b in [(bx0,340),(340,bx1)]:
    sub=win[:,a:b+1];py,px=np.where(sub)
    if len(px)<400: continue
    px=px+a;wins.append({"box":[int(px.min()),int(py.min()),int(px.max()),int(py.max())],"w":round((px.max()-px.min())*Y_bay/fx),"h":round((py.max()-py.min())*Y_bay/fx)})
if len(wins)>=2:                       # домен-правило: окна группы = одна высота
    hm=int(np.median([w["h"] for w in wins]))
    for w in wins: w["h"]=hm
# глубина эркера в пикселях: от передней точки контура эркера к дальней (для выносной линии)
bay_front_px=allc[[i for i,p in enumerate(allc) if p in [bay[0]]][0]] if bay[0] in allc else allc[0]
depth_a=tuple(bay[0]); depth_b=tuple(min(bay,key=lambda p:p[1]))   # перед->зад (мин y = дальше)

# --- мебель: Mask R-CNN боксы -> SAM2 маски (fal) -> обмер ---
w=MaskRCNN_ResNet50_FPN_Weights.DEFAULT;names=w.meta["categories"];mm=maskrcnn_resnet50_fpn(weights=w).eval()
with torch.no_grad():det=mm([to_tensor(cv2.cvtColor(img,cv2.COLOR_BGR2RGB))])[0]
ok,buf=cv2.imencode(".jpg",img);durl="data:image/jpeg;base64,"+base64.b64encode(buf).decode()
def sam2(cx,cy):
    body=json.dumps({"image_url":durl,"prompts":[{"x":int(cx),"y":int(cy),"label":1}]}).encode()
    r=json.loads(urllib.request.urlopen(urllib.request.Request("https://fal.run/fal-ai/sam2/image",data=body,headers={"Content-Type":"application/json","Authorization":f"Key {KEY}"}),timeout=90).read())
    png=urllib.request.urlopen(r["image"]["url"],timeout=60).read()
    return cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_GRAYSCALE)>127
PR={"chair":("стул",(35,70,80,120),"vert"),"dining table":("стол",(30,160,45,95),"surf"),"bed":("матрас",(70,230,10,60),"ext")}
def measure(mask,mode):
    yy,xx=np.where(mask);ss=slice(0,len(xx),max(1,len(xx)//4000));uu,vv=xx[ss],yy[ss];dv=depth[vv,uu]
    hist,e=np.histogram(dv,40);pk=e[np.argmax(hist)];k=(dv>pk-45)&(dv<pk+55)
    if k.sum()<50:return None
    Q=wpx(uu[k],vv[k]);Q=Q[(Q[:,2]>-20)&(Q[:,2]<200)]
    if len(Q)<50:return None
    xy=Q[:,:2]-Q[:,:2].mean(0);_,_,Vt=np.linalg.svd(xy,full_matrices=False);pr=xy@Vt.T
    wd=abs(np.percentile(pr[:,0],95)-np.percentile(pr[:,0],5));dp=abs(np.percentile(pr[:,1],95)-np.percentile(pr[:,1],5))
    ay,ax=np.where(mask)
    if mode=="vert":
        ty=ay.min();tx=int(np.median(ax[ay<=ty+4]));by=ay.max();bxx=int(np.median(ax[ay>=by-4]))
        Xb=sol.floor(bxx,by);dr=sol.ray(tx,ty);sf=((Xb[0]-C[0])/dr[0]+(Xb[1]-C[1])/dr[1])/2;h=float(C[2]+sf*dr[2])
    elif mode=="surf": h=float(np.median(Q[:,2]))
    else: h=np.percentile(Q[:,2],95)-max(0,np.percentile(Q[:,2],5))
    seat=None
    if mode=="vert":
        zc=Q[(Q[:,2]>30)&(Q[:,2]<62),2];seat=round(float(np.median(zc))) if len(zc)>15 else None
    return {"w":round(min(wd,dp)),"d":round(max(wd,dp)),"h":round(h),"seat":seat,"box":[int(ax.min()),int(ay.min()),int(ax.max()),int(ay.max())]}
furn=[]
for b,l,sc in zip(det["boxes"],det["labels"],det["scores"]):
    nm=names[l]
    if sc<0.5 or nm not in PR: continue
    x1,y1,x2,y2=[int(v) for v in b.tolist()]
    label,(wmin,wmax,hmin,hmax),mode=PR[nm]
    if nm=="dining table": pcx,pcy=x1+int((x2-x1)*0.75),y1+int((y2-y1)*0.2)   # видимая столешница справа-сверху
    else: pcx,pcy=(x1+x2)//2,(y1+y2)//2
    sm=sam2(pcx,pcy)
    if sm.sum()<800: continue
    r=measure(sm,mode)
    if not r: continue
    if nm=="bed":   # матрас плоский -> footprint = проекция нижней кромки маски на пол (ИЗМЕРЯЕМ, не хардкод)
        fpm=np.array([sol.floor(x,int(np.where(sm[:,x])[0].max()))[:2] for x in range(0,W,6) if sm[:,x].any()])
        r["w"]=round(float(fpm[:,0].max()-fpm[:,0].min()));r["d"]=round(float(fpm[:,1].max()-fpm[:,1].min()))
    edge = x1<=3 or x2>=W-3 or y2>=H-3
    if not (18<=r["w"]<=270 and 8<=r["h"]<=135): continue   # только явный мусор
    # NMS: не дублировать один объект
    dup=False
    for g in furn:
        gx1,gy1,gx2,gy2=g["box"];ix=max(0,min(x2,gx2)-max(x1,gx1));iy=max(0,min(y2,gy2)-max(y1,gy1))
        if ix*iy>0.5*min((x2-x1)*(y2-y1),(gx2-gx1)*(gy2-gy1)): dup=True;break
    if dup: continue
    furn.append({"label":label,**r,"mask":sm,"partial":edge})

# стол перекрыт -> прайор (обеденный h73) + диаметр по боксу Mask R-CNN (честный флаг)
if not any(f["label"]=="стол" for f in furn):
    for b,l,sc in zip(det["boxes"],det["labels"],det["scores"]):
        if names[l]=="dining table" and sc>0.45:
            x1,y1,x2,y2=[int(v) for v in b.tolist()]
            dia=round(float(np.linalg.norm(sol.floor(x1,y2)-sol.floor(x2,y2))))
            furn.append({"label":"стол","w":dia,"d":dia,"h":73,"seat":None,"mask":None,"box":[x1,y1,x2,y2],"partial":True,"prior":True})
            break
# домен-правило: одинаковые стулья -> одна высота (медиана); footprint стула -> квадрат по меньшей стороне
ch=[f for f in furn if f["label"]=="стул"]
if len(ch)>=2:
    hm=int(np.median([c["h"] for c in ch]))
    for c in ch: c["h"]=hm
res={"room_wxd":[room_w,room_d],"ceiling":ceil,"perimeter_cm":perim,"wall_area_m2":wall_area,"floor_area_m2":floor_area,
     "wall_segments_cm":seglen,"bay_hxwxd":[bay_h,bay_open,bay_depth],"glazing_wxh":[glaz_w,glaz_h],
     "windowsill_cm":sill,"window_to_ceiling_cm":win2ceil,"windows_wxh":[[w["w"],w["h"]] for w in wins],
     "furniture":[{k:f[k] for k in("label","w","d","h","seat","partial")} for f in furn]}
json.dump(res,open(f"{RUN}/measurements.json","w"),ensure_ascii=False,indent=2)

# ================= РЕНДЕР (замерщицкий, чистый) =================
fin=img.copy()
def L(tx,p,c,s=0.5,bg=(255,255,255)):
    x,y=int(p[0]),int(p[1]);(tw,th),_=cv2.getTextSize(tx,cv2.FONT_HERSHEY_SIMPLEX,s,2)
    cv2.rectangle(fin,(x-3,y-th-5),(x+tw+3,y+4),bg,-1);cv2.putText(fin,tx,(x,y),cv2.FONT_HERSHEY_SIMPLEX,s,c,2)
cv2.polylines(fin,[a4.astype(int).reshape(-1,1,2)],True,(255,120,0),2)
# каркас: пол (зел) + потолок (оранж) + вертикали (жёлт)
for i in range(len(allc)-1):
    cv2.line(fin,tuple(allc[i]),tuple(allc[i+1]),(0,200,0),3)
    if seglen[i]>25: L(str(seglen[i]),((allc[i][0]+allc[i+1][0])//2-10,(allc[i][1]+allc[i+1][1])//2-4),(0,120,0),0.5)
for l in G["key_lines"]:
    nm=l["label"]
    if nm.startswith("wall_ceiling_edge"): cv2.polylines(fin,[np.array(l["coordinates"],int).reshape(-1,1,2)],False,(255,120,0),2)
    if ("bay_opening" in nm and "vertical" in nm) or nm=="right_wall_inside_corner_vertical":
        p=np.array(l["coordinates"],int);cv2.line(fin,tuple(p[0]),tuple(p[-1]),(0,215,255),2)
# окно: остекление + подоконник + окно->потолок
# окна эркера по отдельности + подоконник
for i,wd in enumerate(wins):
    x1,y1,x2,y2=wd["box"];cv2.rectangle(fin,(x1,y1),(x2,y2),(255,150,0),2);L(f"окно{i+1} {wd['w']}x{wd['h']}",(x1,max(y1-6,72)),(200,90,0),0.48)
cv2.line(fin,(bx0,by1),(bx1,by1),(255,120,0),1);L(f"подок. {sill}",(bx0,by1+16),(200,90,0),0.45)
# ВЫСОТА КОМНАТЫ — отдельная выноска (пурпур, чтобы не сливалась с зелёным полом), с засечками и подписью
vt=[l["coordinates"] for l in G["key_lines"] if l["label"]=="bay_opening_left_outer_vertical"]
if vt:
    ps=sorted(vt[0],key=lambda p:p[1]);tp=tuple(ps[0]);bp=tuple(ps[-1]);HC=(200,0,200)
    lx=max(tp[0],bp[0])+14
    cv2.arrowedLine(fin,(lx,bp[1]),(lx,tp[1]),HC,3,tipLength=0.02);cv2.arrowedLine(fin,(lx,tp[1]),(lx,bp[1]),HC,3,tipLength=0.02)
    cv2.line(fin,(lx-10,tp[1]),(lx+10,tp[1]),HC,2);cv2.line(fin,(lx-10,bp[1]),(lx+10,bp[1]),HC,2)   # засечки
    L(f"ВЫСОТА {ceil} см",(lx+8,(tp[1]+bp[1])//2),HC,0.6)
# ГЛУБИНА ЭРКЕРА — выноска перед->зад
cv2.arrowedLine(fin,depth_a,depth_b,(0,0,220),2,tipLength=0.06);L(f"глубина эркера {bay_depth}",((depth_a[0]+depth_b[0])//2-50,(depth_a[1]+depth_b[1])//2-6),(0,0,220),0.5)
# мебель (SAM2 контур + подпись)
cols={"стул":(0,140,255),"стол":(0,170,0),"матрас":(200,0,200)}
for f in furn:
    c=cols[f["label"]];x1,y1,x2,y2=f["box"]
    if f.get("mask") is not None:
        cnts,_=cv2.findContours(f["mask"].astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE);cv2.drawContours(fin,cnts,-1,c,2)
    else: cv2.rectangle(fin,(x1,y1),(x2,y2),c,2)
    if f["label"]=="стул": tx=f"стул {f['w']}x{f['d']} сид{f['seat']} h{f['h']}"
    elif f["label"]=="стол": tx=f"стол Ø{max(f['w'],f['d'])} h{f['h']}"+(" (перекрыт)" if f.get('prior') else "")
    else: tx=f"матрас ~{f['w']}x{f['d']} h{f['h']}"+(" (обрезан кадром)" if f['partial'] else "")
    L(tx,(x1,max(y1-6,16)),c,0.48)
# шапка + панель
cv2.rectangle(fin,(0,0),(W,64),(28,28,28),-1)
cv2.putText(fin,f"REMLAB обмер | комната ~{room_w}x{room_d} см | потолок {ceil} | ЭРКЕР В{bay_h}xШ{bay_open}xГ{bay_depth}",(12,28),cv2.FONT_HERSHEY_SIMPLEX,0.5,(255,255,255),1)
cv2.putText(fin,f"периметр {perim} | стены ~{wall_area} м2 | пол ~{floor_area} м2 | окно->потолок {win2ceil}",(12,52),cv2.FONT_HERSHEY_SIMPLEX,0.46,(0,210,255),1)
# панель ведомости справа-снизу
px,py=W-268,H-150;cv2.rectangle(fin,(px-10,py-26),(W-6,H-8),(255,255,255),-1);cv2.rectangle(fin,(px-10,py-26),(W-6,H-8),(80,80,80),1)
cv2.putText(fin,"ВЕДОМОСТЬ (см):",(px,py-6),cv2.FONT_HERSHEY_SIMPLEX,0.5,(20,20,20),1)
rows=[f"Комната ~{room_w}x{room_d}",f"Потолок {ceil}",f"Эркер В{bay_h} Ш{bay_open} Г{bay_depth}",f"Периметр {perim}",f"Стены ~{wall_area} м2 / Пол ~{floor_area} м2"]
for i,r in enumerate(rows): cv2.putText(fin,r,(px,py+18+i*22),cv2.FONT_HERSHEY_SIMPLEX,0.44,(30,30,30),1)
cv2.imwrite(f"{RUN}/survey.jpg",fin,[cv2.IMWRITE_JPEG_QUALITY,90])
print(json.dumps(res,ensure_ascii=False,indent=2))
