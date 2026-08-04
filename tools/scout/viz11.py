#!/usr/bin/env python3
"""Честная проекция: комната-бокс рисуется кодом (pinhole-камера), предметы масштабируются
по глубине из реальных размеров. Затем чистовой gpt-image-2. viz11.py <сет>"""
import json, os, sys, re, io, base64, urllib.request, uuid
from PIL import Image, ImageDraw
HERE=os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE,'viz3.py')).read().split("HERE=")[0])
OAI=None
for line in open('/home/pakar/igor/v0-health-card/backend/.env'):
    m=re.match(r'OPENAI_API_KEY=(.+)',line.strip())
    if m: OAI=m.group(1).strip().strip('"')
sets=json.load(open(os.path.join(HERE,'sets.json')))
n=int(sys.argv[1]) if len(sys.argv)>1 else 1
s=sets[n-1]
W,H=1536,1024
# --- камера: комната X 0..3.8 (ширина), Z 0..4.0 (глубина от камеры), Y 0..2.7 ---
RX,RZ,RY=3.8,4.0,2.7
CAMX,CAMY,CAMZ=1.55,1.35,-1.35
F=1750.0; CX,CY=W/2,512
def P(X,Y,Z):
    d=Z-CAMZ
    return (CX+F*(X-CAMX)/d, CY-F*(Y-CAMY)/d)
img=Image.new('RGB',(W,H),(246,240,230)); d=ImageDraw.Draw(img)
# пол, стены, потолок
floor=[P(0,0,0.01),P(RX,0,0.01),P(RX,0,RZ),P(0,0,RZ)]
d.polygon(floor,fill=(186,143,96))
d.polygon([P(0,0,RZ),P(RX,0,RZ),P(RX,RY,RZ),P(0,RY,RZ)],fill=(243,232,215))   # задняя
d.polygon([P(0,0,0.01),P(0,0,RZ),P(0,RY,RZ),P(0,RY,0.01)],fill=(238,226,208)) # левая
d.polygon([P(RX,0,0.01),P(RX,0,RZ),P(RX,RY,RZ),P(RX,RY,0.01)],fill=(240,229,211)) # правая
d.polygon([P(0,RY,0.01),P(RX,RY,0.01),P(RX,RY,RZ),P(0,RY,RZ)],fill=(250,247,242)) # потолок
# окно на правой стене (Z 1.4..2.8, Y 0.9..2.1)
d.polygon([P(RX,0.9,1.4),P(RX,0.9,2.8),P(RX,2.1,2.8),P(RX,2.1,1.4)],fill=(210,228,240),outline=(255,255,255),width=6)
# плинтус линии
for z in (RZ,):
    d.line([P(0,0,z),P(RX,0,z)],fill=(210,195,175),width=3)
def cutout(im):
    im=clean_bg(im).convert('RGBA')
    px=im.load(); w,h=im.size
    for y in range(h):
        for x in range(w):
            r,g,b,a=px[x,y]
            if r>245 and g>245 and b>245: px[x,y]=(r,g,b,0)
    return im
# --- раскладка (X центра, Z центра, Y низа) ---
items={r.replace(' 2',''):it for r,it in s['items'].items()}
POS={'диван':(1.55,3.72,0),'кресло':(3.05,3.25,0),'столик':(1.55,2.55,0),'пуф':(0.75,2.15,0),
 'торшер':(0.42,3.35,0),'кашпо':(3.35,3.75,0),'тв-тумба':(3.55,1.35,0),'люстра':(1.8,2.12,None),
 'лампа':None,'ваза':None}
order=sorted([r for r in POS if r in items and POS[r]], key=lambda r:-POS[r][1])
draft=img.copy()
tumba_top=None
for role in order:
    it=items[role]
    X,Z,Yb=POS[role]
    u=it['img']; u='https:'+u if u.startswith('//') else u
    req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
    ph=Image.open(io.BytesIO(urllib.request.urlopen(req,timeout=25).read())).convert('RGB')
    ph.thumbnail((800,800)); ph=cutout(ph)
    hcm=it.get('h') or ((it.get('w') or 60)*ph.height/ph.width)
    wcm=it.get('w') or hcm*ph.width/ph.height
    if role=='люстра':
        hcm=it.get('h') or 45; Yb=RY-hcm/100
    dpt=Z-CAMZ
    pxh=F*(hcm/100)/dpt; pxw=pxh*ph.width/ph.height
    # ширина честнее по w: если фронтальное фото — берём по высоте, ширина из пропорций фото
    ph=ph.resize((max(int(pxw),8),max(int(pxh),8)))
    cu,cv=P(X,Yb,Z)
    draft.paste(ph,(int(cu-ph.width/2),int(cv-ph.height)),ph)
    if role=='тв-тумба': tumba_top=(X,(it.get('h') or 50)/100,Z)
if tumba_top and 'лампа' in items:
    it=items['лампа']; X,Ytop,Z=tumba_top
    u=it['img']; u='https:'+u if u.startswith('//') else u
    ph=Image.open(io.BytesIO(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=25).read())).convert('RGB')
    ph.thumbnail((400,400)); ph=cutout(ph)
    hcm=min(it.get('h') or 40,60); dpt=Z-CAMZ
    pxh=F*(hcm/100)/dpt
    ph=ph.resize((max(int(pxh*ph.width/ph.height),6),max(int(pxh),6)))
    cu,cv=P(X,Ytop,Z)
    draft.paste(ph,(int(cu-ph.width/2),int(cv-ph.height)),ph)
p_draft=os.path.join(HERE,f"set{n}-draft2.jpg"); draft.save(p_draft,'JPEG',quality=92)
print("draft2 saved",flush=True)
prompt=("This is a geometric draft of a living room 3.8 x 4.0 m: flat-coloured box room with real product photos "
 "pasted at CORRECT positions and CORRECT sizes for their depth. Render as ONE photorealistic interior photo. "
 "KEEP every object's position, size, silhouette and colour EXACTLY as in the draft; rotate objects only as needed "
 "to sit naturally on the floor in correct perspective (the TV stand stands along the right wall). Make the room "
 "real: laminate floor, warm light walls, white ceiling, daylight from the window on the right, curtains allowed; "
 "add a TV on the TV stand, a plain light-grey rug under the coffee table, natural contact shadows. "
 "Do not add other furniture. No people, no text, no watermarks.")
B=uuid.uuid4().hex; body=io.BytesIO()
def part(name,val,fname=None,ctype=None):
    body.write(f"--{B}\r\n".encode())
    if fname:
        body.write(f'Content-Disposition: form-data; name="{name}"; filename="{fname}"\r\nContent-Type: {ctype}\r\n\r\n'.encode())
        body.write(val); body.write(b"\r\n")
    else:
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())
buf=io.BytesIO(); draft.save(buf,'JPEG',quality=92)
part("model","gpt-image-2"); part("prompt",prompt); part("size","1536x1024"); part("quality","medium"); part("n","1")
part("image[]",buf.getvalue(),"draft.jpg","image/jpeg")
body.write(f"--{B}--\r\n".encode())
req=urllib.request.Request("https://api.openai.com/v1/images/edits",data=body.getvalue(),
    headers={"Authorization":f"Bearer {OAI}","Content-Type":f"multipart/form-data; boundary={B}"})
try:
    with urllib.request.urlopen(req,timeout=600) as r: out=json.loads(r.read())
    open(os.path.join(HERE,f"set{n}-final2.jpg"),'wb').write(base64.b64decode(out['data'][0]['b64_json']))
    print("final2 saved")
except urllib.error.HTTPError as e:
    print("HTTP",e.code,e.read()[:300])
