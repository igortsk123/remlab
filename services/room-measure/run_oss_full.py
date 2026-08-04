import cv2, numpy as np, json
import cv_refine as CVR
from geometry_solver import Solver
from ultralytics import YOLO
D=os.path.dirname(os.path.abspath(__file__)); RUN="/tmp/room-measure/run-5"
import os; os.makedirs(RUN,exist_ok=True)
img=cv2.imread(f"{D}/room1.jpg"); H,W=img.shape[:2]
CEIL=263

# --- A4 + поза (OpenCV) ---
a4,_=CVR.refine_a4(img); sol=Solver(img,a4,62.0,ceiling_cm=CEIL)
def fl(x,y): return sol.floor(x,y)
a4c=(int(a4[:,0].mean()),int(a4[:,1].mean()))

# --- сегментация (реюз seg.npy) ---
seg=np.load(f"{D}/seg.npy")
floor=(seg==3); win=(seg==8)

# --- линия пол-стена по столбцам ---
line=[]
for x in range(0,W,6):
    col=np.where(floor[:,x])[0]
    if len(col)==0: continue
    yt=col.min(); above=seg[max(yt-6,0),x]
    line.append((x,int(yt), above not in (0,8,5)))   # occluded если над полом не стена/окно/потолок
clean=[(x,y) for x,y,o in line if not o]
# видимый габарит комнаты по всем floor-точкам
fpts=np.array([fl(x,y)[:2] for x,y,_ in line])
room_w=round(float(fpts[:,0].max()-fpts[:,0].min())); room_d=round(float(fpts[:,1].max()-fpts[:,1].min()))
# самая дальняя точка пола (низ эркера) и глубина A4->эркер
deep=min(line,key=lambda p:p[1]); bay_pt=(deep[0],deep[1])
a4_to_bay=round(float(np.linalg.norm(fl(*a4c)-fl(*bay_pt))))
# длина чистых (видимых) сегментов стен
wall_len=sum(float(np.linalg.norm(fl(*clean[i])-fl(*clean[i+1]))) for i in range(len(clean)-1) if abs(clean[i+1][0]-clean[i][0])<=12)

# --- окна: разбить маску эркера по провалу плотности (перегородка) ---
wins=[]; allpts=[(x,y) for x,y,_ in line]
ys0,xs0=np.where(win)
boxes=[]
if len(xs0):
    x0,x1=int(xs0.min()),int(xs0.max()); colc=win[:,x0:x1+1].sum(0)
    lo=int(0.32*(x1-x0)); hi=int(0.68*(x1-x0))
    split=x0+lo+int(np.argmin(colc[lo:hi]))          # столбец-перегородка
    for xa,xb in [(x0,split),(split,x1)]:
        sub=win[:,xa:xb+1]; yy,xx=np.where(sub)
        if len(xx)<800: continue
        boxes.append((xa+int(xx.min()),int(yy.min()),int(xx.max()-xx.min()),int(yy.max()-yy.min())))
for x,y,w,h in boxes:
    cx=x+w//2; near=sorted(allpts,key=lambda p:abs(p[0]-cx))[:8]
    A=fl(*min(near,key=lambda p:p[0])); B=fl(*max(near,key=lambda p:p[0]))
    P=[sol.on_facet(u,v,A,B) for u,v in [(x,y),(x+w,y),(x+w,y+h),(x,y+h)]]
    wc=(np.linalg.norm(P[1][:2]-P[0][:2])+np.linalg.norm(P[2][:2]-P[3][:2]))/2
    hc=(abs(P[0][2]-P[3][2])+abs(P[1][2]-P[2][2]))/2
    wins.append({"box":[int(x),int(y),int(w),int(h)],"w_cm":round(wc),"h_cm":round(hc)})

# --- мебель YOLO + footprint (ширина по низу бокса, проекция на пол) ---
m=YOLO(f"{D}/yolov8s-world.pt"); cls=["chair","dining table","couch","potted plant","radiator"]; m.set_classes(cls)
yb=m.predict(f"{D}/room1.jpg",conf=0.25,iou=0.5,verbose=False)[0]
furn=[]
for b in yb.boxes:
    x1,y1,x2,y2=[int(v) for v in b.xyxy[0].tolist()]; nm=cls[int(b.cls)]
    fw=round(float(np.linalg.norm(fl(x1,y2)-fl(x2,y2))))   # ширина основания по полу
    furn.append({"name":nm,"box":[x1,y1,x2,y2],"footprint_w_cm":fw})

result={"stack":"SegFormer+YOLO-World+OpenCV (open-source, CPU, $0)","camera_height_cm":round(sol.cam_h,1),
        "ceiling_cm":CEIL,"room_visible_wxd_cm":[room_w,room_d],"visible_wall_len_cm":round(wall_len),
        "a4_to_bay_depth_cm":a4_to_bay,"windows":wins,"furniture":furn}
json.dump(result,open(f"{RUN}/measurements.json","w"),ensure_ascii=False,indent=2)

# --- рендер ---
fin=img.copy(); cv2.polylines(fin,[a4.astype(int).reshape(-1,1,2)],True,(255,60,0),2)
def lab(t,p,c,s=0.6):
    x,y=int(p[0]),int(p[1]);(tw,th),_=cv2.getTextSize(t,cv2.FONT_HERSHEY_SIMPLEX,s,2)
    cv2.rectangle(fin,(x-2,y-th-5),(x+tw+2,y+3),(255,255,255),-1);cv2.putText(fin,t,(x,y),cv2.FONT_HERSHEY_SIMPLEX,s,c,2)
for i in range(len(line)-1):
    x0,y0,o0=line[i]; x1,y1,o1=line[i+1]
    if abs(x1-x0)>12: continue
    cv2.line(fin,(x0,y0),(x1,y1),(0,150,220) if(o0 or o1)else(0,200,0),3)
cv2.line(fin,a4c,bay_pt,(0,0,220),2); lab(f"A4->эркер {a4_to_bay}см",((a4c[0]+bay_pt[0])//2-60,(a4c[1]+bay_pt[1])//2),(0,0,220),0.55)
for wd in wins:
    x,y,w,h=wd["box"]; cv2.rectangle(fin,(x,y),(x+w,y+h),(255,200,0),2); lab(f"{wd['w_cm']}x{wd['h_cm']}",(x,max(y-6,20)),(255,150,0),0.6)
for f in furn:
    x1,y1,x2,y2=f["box"]; cv2.rectangle(fin,(x1,y1),(x2,y2),(0,140,255),2); lab(f"{f['name']} {f['footprint_w_cm']}см",(x1,max(y1-6,14)),(0,140,255),0.5)
cv2.rectangle(fin,(0,0),(W,90),(30,30,30),-1)
cv2.putText(fin,f"REMLAB OSS ($0): комната ~{room_w}x{room_d}см(видимо) | потолок {CEIL} | A4->эркер {a4_to_bay}",(10,34),cv2.FONT_HERSHEY_SIMPLEX,0.5,(255,255,255),1)
cv2.putText(fin,"зел=стык пол-стена, оранж=перекрыто, голуб=окна(ШxВ), синие рамки=мебель(ширина)",(10,66),cv2.FONT_HERSHEY_SIMPLEX,0.46,(0,200,255),1)
cv2.imwrite(f"{RUN}/oss_full.jpg",fin,[cv2.IMWRITE_JPEG_QUALITY,88])
print(json.dumps(result,ensure_ascii=False,indent=2))
