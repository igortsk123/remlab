import cv2, numpy as np, torch, sys
from PIL import Image
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
D=os.path.dirname(os.path.abspath(__file__)); RUN="/tmp/room-measure/run-14"
import os; os.makedirs(RUN,exist_ok=True)
img=cv2.imread(f"{D}/room2.jpg"); H,W=img.shape[:2]
mid="IDEA-Research/grounding-dino-tiny"
pr=AutoProcessor.from_pretrained(mid); md=AutoModelForZeroShotObjectDetection.from_pretrained(mid).eval()
# open-vocab словарь: (англ. фраза, рус. имя) — каждая фраза уникальна по ключевому слову
VMAP=[("office chair","кресло"),("chair","стул"),("desk","стол"),("table","стол"),("sofa","диван"),
      ("couch","диван"),("bed","кровать"),("mattress","матрас"),("wardrobe","шкаф"),("shelf","полка"),
      ("computer monitor","монитор"),("television","телевизор"),("laptop","ноутбук"),("keyboard","клавиатура"),
      ("humidifier","увлажнитель"),("air purifier","очиститель"),("fan","вентилятор"),("heater","обогреватель"),
      ("radiator","радиатор"),("floor lamp","торшер"),("lamp","лампа"),("potted plant","растение"),
      ("box","коробка"),("books","книги"),("bottle","бутылка"),("cup","чашка"),("speaker","колонка"),
      ("router","роутер"),("mirror","зеркало"),("picture frame","картина"),("curtain","штора"),
      ("window","окно"),("door","дверь"),("rug","ковёр"),("pillow","подушка"),("bag","сумка"),("clothes","одежда")]
VOCAB=". ".join(p for p,_ in VMAP)+"."
def clean_label(raw):
    w=set(raw.replace("#","").split())
    best=None;bs=-1
    for ph,ru in VMAP:
        pw=set(ph.split()); ov=len(w&pw)/max(1,len(pw))
        if ov>bs: bs=ov; best=ru
    return best or raw
im=Image.open(f"{D}/room2.jpg").convert("RGB")
inp=pr(images=im,text=VOCAB,return_tensors="pt")
with torch.no_grad(): out=md(**inp)
res=pr.post_process_grounded_object_detection(out,inp["input_ids"],threshold=0.30,text_threshold=0.25,target_sizes=[im.size[::-1]])[0]
dets=[]
for box,score,lab in zip(res["boxes"],res["scores"],res["labels"]):
    x1,y1,x2,y2=[int(v) for v in box.tolist()]
    if (x2-x1)*(y2-y1) < 400: continue
    dets.append((lab,float(score),x1,y1,x2,y2))
# NMS простая по IoU 0.5, оставляем более уверенный
dets.sort(key=lambda d:-d[1]); keep=[]
def iou(a,b):
    ix=max(0,min(a[4],b[4])-max(a[2],b[2]));iy=max(0,min(a[5],b[5])-max(a[3],b[3]));inter=ix*iy
    aa=(a[4]-a[2])*(a[5]-a[3]);bb=(b[4]-b[2])*(b[5]-b[3]);return inter/max(1,aa+bb-inter)
for d in dets:
    if all(iou(d,k)<0.5 for k in keep): keep.append(d)
print(f"найдено объектов: {len(keep)}")
from PIL import ImageDraw, ImageFont
FT=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",16)
FTb=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",15)
pim=Image.fromarray(cv2.cvtColor(img,cv2.COLOR_BGR2RGB)); dr=ImageDraw.Draw(pim)
cols=[(255,140,0),(0,170,0),(200,0,200),(0,90,255),(120,60,220),(0,200,200),(200,160,0),(160,0,120)]
for i,(lab,sc,x1,y1,x2,y2) in enumerate(keep):
    c=cols[i%len(cols)]; ru=clean_label(lab)
    dr.rectangle([x1,y1,x2,y2],outline=c,width=2)
    tx=f"{ru} {sc:.2f}"; tb=dr.textbbox((0,0),tx,font=FT); tw,th=tb[2]-tb[0],tb[3]-tb[1]
    ty=max(y1-th-6,0); dr.rectangle([x1,ty,x1+tw+6,ty+th+6],fill=(255,255,255)); dr.text((x1+3,ty+2),tx,font=FT,fill=c)
    print(f"  {ru:14s} <- {lab:26s} {sc:.2f}  [{x1},{y1},{x2},{y2}]")
dr.rectangle([0,0,W,30],fill=(28,28,28))
dr.text((10,7),f"REMLAB room2 | Grounding DINO open-vocab | {len(keep)} объектов (вкл. незнакомые приборы)",font=FTb,fill=(255,255,255))
cv2.imwrite(f"{RUN}/gdino.jpg",cv2.cvtColor(np.array(pim),cv2.COLOR_RGB2BGR),[cv2.IMWRITE_JPEG_QUALITY,90])
print("saved",f"{RUN}/gdino.jpg")
