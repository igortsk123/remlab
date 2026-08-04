import cv2, numpy as np, json, os, torch, base64, urllib.request, torch.nn.functional as F
import cv_refine as CVR
from geometry_solver import Solver
from transformers import AutoImageProcessor, AutoModelForDepthEstimation, AutoConfig, AutoModelForSemanticSegmentation
from torchvision.models.detection import maskrcnn_resnet50_fpn, MaskRCNN_ResNet50_FPN_Weights
from torchvision.transforms.functional import to_tensor
from PIL import Image
D=os.path.dirname(os.path.abspath(__file__)); RUN="/tmp/room-measure/run-13"; os.makedirs(RUN,exist_ok=True)
KEY=os.environ["FAL_KEY"]; FOV=62.0   # iPhone SE3 прайор (фотограф неизвестен -> без калибровки по росту)
img=cv2.imread(f"{D}/room2.jpg"); H,W=img.shape[:2]

# --- A4 + поза ---
a4,a4c_ok=CVR.refine_a4(img)
if a4 is None: print("A4 НЕ найден!"); raise SystemExit
a4c=(int(a4[:,0].mean()),int(a4[:,1].mean()))
sol=Solver(img,a4,FOV); Ki,R,C=sol.Ki,sol.R,sol.C; t=(-R@C).reshape(3); fx=float(sol.K[0,0])
print(f"A4 найден, углы={a4.astype(int).tolist()}, камера высота={round(float(C[2]),1)}см")

# --- depth (Depth Anything V2 metric) + якорь A4 ---
nm="depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf"
pr=AutoImageProcessor.from_pretrained(nm); md=AutoModelForDepthEstimation.from_pretrained(nm).eval()
with torch.no_grad(): dd=md(**pr(images=Image.open(f"{D}/room2.jpg").convert("RGB"),return_tensors="pt")).predicted_depth
raw=F.interpolate(dd[None],(H,W),mode="bicubic",align_corners=False)[0,0].numpy()
Xc=R@sol.floor(*a4c)+t; depth=raw*100*(float(Xc[2])/(float(raw[a4c[1],a4c[0]])*100))
def wpx(us,vs): Z=depth[vs,us];r=Ki@np.vstack([us,vs,np.ones_like(us)]).astype(float);return (R.T@(r*Z/r[2]-t[:,None])).T

# --- SegFormer ADE20K ---
sc="nvidia/segformer-b2-finetuned-ade-512-512"
sp=AutoImageProcessor.from_pretrained(sc); sm_=AutoModelForSemanticSegmentation.from_pretrained(sc).eval()
with torch.no_grad(): lg=sm_(**sp(images=Image.open(f"{D}/room2.jpg").convert("RGB"),return_tensors="pt")).logits
seg=F.interpolate(lg,(H,W),mode="bilinear",align_corners=False).argmax(1)[0].numpy()
cfg=AutoConfig.from_pretrained(sc); nid={v.lower():int(k) for k,v in cfg.id2label.items()}
gid=lambda *ns:next((v for n in ns for k,v in nid.items() if n in k),None)
FL,WL,CE,WN,DR=gid("floor"),gid("wall"),gid("ceiling"),gid("windowpane"),gid("door")
print("ADE ids: floor",FL,"wall",WL,"ceiling",CE,"window",WN,"door",DR)

# --- комната + потолок (стены+потолок, сквозь мебель) ---
ys,xs=np.where((seg==WL)|(seg==CE));s=slice(0,len(xs),max(1,len(xs)//4000))
P=wpx(xs[s],ys[s]);P=P[(P[:,2]>-50)&(P[:,2]<350)]
room_w=round(float(np.percentile(P[:,0],97)-np.percentile(P[:,0],3)));room_d=round(float(np.percentile(P[:,1],97)-np.percentile(P[:,1],3)))
cy,cx=np.where(seg==CE);ceil=round(float(np.median(wpx(cx[::max(1,len(cx)//300)],cy[::max(1,len(cy)//300)])[:,2]))) if len(cy) else None
free=(seg==FL);fys,fxs=np.where(free)
FP=np.array([sol.floor(x,y)[:2] for x,y in zip(fxs[::max(1,len(fxs)//4000)],fys[::max(1,len(fys)//4000)])])
free_area=round(abs(cv2.contourArea(cv2.convexHull(FP.astype(np.float32))))/10000,1)

# --- окно + дверь (на плоскости стены) ---
def obj_wall(mask):
    ys,xs=np.where(mask)
    if len(xs)<400: return None
    bx0,bx1,by0,by1=xs.min(),xs.max(),ys.min(),ys.max()
    Yw=float(np.median(wpx(xs[::max(1,len(xs)//1500)],ys[::max(1,len(ys)//1500)])[:,1]))
    return round((bx1-bx0)*Yw/fx),round((by1-by0)*Yw/fx),[int(bx0),int(by0),int(bx1),int(by1)]
window=obj_wall(seg==WN) if WN is not None else None
# дверь: непрозрачная -> depth ок; берём по стене за ней (рама)
door=obj_wall(seg==DR) if DR is not None else None

# --- мебель Mask R-CNN + SAM2 ---
w=MaskRCNN_ResNet50_FPN_Weights.DEFAULT;names=w.meta["categories"];mm=maskrcnn_resnet50_fpn(weights=w).eval()
with torch.no_grad():det=mm([to_tensor(cv2.cvtColor(img,cv2.COLOR_BGR2RGB))])[0]
ok,buf=cv2.imencode(".jpg",img);durl="data:image/jpeg;base64,"+base64.b64encode(buf).decode()
def sam2(cx,cy):
    body=json.dumps({"image_url":durl,"prompts":[{"x":int(cx),"y":int(cy),"label":1}]}).encode()
    r=json.loads(urllib.request.urlopen(urllib.request.Request("https://fal.run/fal-ai/sam2/image",data=body,headers={"Content-Type":"application/json","Authorization":f"Key {KEY}"}),timeout=90).read())
    png=urllib.request.urlopen(r["image"]["url"],timeout=60).read()
    return cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_GRAYSCALE)>127
FURN={"chair":"стул","dining table":"стол","bed":"пуфик/матрас","couch":"диван","suitcase":"чемодан"}
furn=[]
for b,l,sc_ in zip(det["boxes"],det["labels"],det["scores"]):
    nmc=names[l]
    if sc_<0.5 or nmc not in FURN: continue
    x1,y1,x2,y2=[int(v) for v in b.tolist()]
    m=sam2((x1+x2)//2,(y1+y2)//2)
    if m.sum()<800: continue
    yy,xx=np.where(m);dv=depth[yy,xx];hist,e=np.histogram(dv,40);pk=e[np.argmax(hist)];k=(dv>pk-45)&(dv<pk+55)
    if k.sum()<50: continue
    Q=wpx(xx[k],yy[k]);Q=Q[(Q[:,2]>-20)&(Q[:,2]<200)]
    if len(Q)<50: continue
    xy=Q[:,:2]-Q[:,:2].mean(0);_,_,Vt=np.linalg.svd(xy,full_matrices=False);pr2=xy@Vt.T
    wd=abs(np.percentile(pr2[:,0],95)-np.percentile(pr2[:,0],5));dp=abs(np.percentile(pr2[:,1],95)-np.percentile(pr2[:,1],5))
    hh=np.percentile(Q[:,2],95)-max(0,np.percentile(Q[:,2],5))
    dup=any(max(0,min(x2,g["box"][2])-max(x1,g["box"][0]))*max(0,min(y2,g["box"][3])-max(y1,g["box"][1]))>0.5*min((x2-x1)*(y2-y1),(g["box"][2]-g["box"][0])*(g["box"][3]-g["box"][1])) for g in furn)
    if dup: continue
    furn.append({"label":FURN[nmc],"w":round(min(wd,dp)),"d":round(max(wd,dp)),"h":round(hh),"box":[x1,y1,x2,y2],"mask":m})

res={"a4":True,"cam_h":round(float(C[2]),1),"fov":FOV,"room_wxd":[room_w,room_d],"ceiling":ceil,"free_floor_m2":free_area,
     "window_wxh":window[:2] if window else None,"door_wxh":door[:2] if door else None,
     "furniture":[{k:f[k] for k in("label","w","d","h")} for f in furn]}
json.dump(res,open(f"{RUN}/measurements.json","w"),ensure_ascii=False,indent=2)

# --- рендер ---
fin=img.copy();cv2.polylines(fin,[a4.astype(int).reshape(-1,1,2)],True,(255,120,0),2)
def L(tx,p,c,s=0.5):
    x,y=int(p[0]),int(p[1]);(tw,th),_=cv2.getTextSize(tx,cv2.FONT_HERSHEY_SIMPLEX,s,2)
    cv2.rectangle(fin,(x-2,y-th-4),(x+tw+3,y+4),(255,255,255),-1);cv2.putText(fin,tx,(x,y),cv2.FONT_HERSHEY_SIMPLEX,s,c,2)
ov=fin.copy();ov[free]=(0,200,0);fin=cv2.addWeighted(ov,0.18,fin,0.82,0)
if window: x1,y1,x2,y2=window[2];cv2.rectangle(fin,(x1,y1),(x2,y2),(255,150,0),2);L(f"окно {window[0]}x{window[1]}",(x1,max(y1-6,16)),(200,90,0),0.5)
if door: x1,y1,x2,y2=door[2];cv2.rectangle(fin,(x1,y1),(x2,y2),(0,180,255),2);L(f"дверь {door[0]}x{door[1]}",(x1,max(y1-6,16)),(0,120,200),0.5)
cols=[(0,140,255),(0,170,0),(200,0,200),(255,90,0),(120,60,220)]
for i,f in enumerate(furn):
    c=cols[i%len(cols)];cnts,_=cv2.findContours(f["mask"].astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE);cv2.drawContours(fin,cnts,-1,c,2)
    L(f"{f['label']} {f['w']}x{f['d']} h{f['h']}",(f["box"][0],max(f["box"][1]-6,16)),c,0.46)
cv2.rectangle(fin,(0,0),(W,64),(28,28,28),-1)
cv2.putText(fin,f"REMLAB room2 (тест генерализации) | комната ~{room_w}x{room_d} | потолок {ceil} | свободно {free_area} м2",(12,28),cv2.FONT_HERSHEY_SIMPLEX,0.48,(255,255,255),1)
cv2.putText(fin,f"окно {window[:2] if window else '-'} | дверь {door[:2] if door else '-'} | FOV {FOV} (SE3 прайор, без калибр. роста)",(12,52),cv2.FONT_HERSHEY_SIMPLEX,0.44,(0,210,255),1)
cv2.imwrite(f"{RUN}/survey.jpg",fin,[cv2.IMWRITE_JPEG_QUALITY,90])
print(json.dumps(res,ensure_ascii=False,indent=2))
