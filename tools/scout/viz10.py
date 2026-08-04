#!/usr/bin/env python3
"""Трёхэтапный пайплайн: пустая комната → детерминированная вклейка товаров → чистовой рендер.
viz10.py <сет> [skip-base]"""
import json, os, sys, re, io, base64, urllib.request, uuid
from PIL import Image
HERE=os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE,'viz3.py')).read().split("HERE=")[0])
FAL=None; OAI=None
for line in open('/home/pakar/mltest/.env'):
    m=re.match(r'FAL_KEY=(.+)',line.strip())
    if m: FAL=m.group(1).strip().strip('"')
for line in open('/home/pakar/igor/v0-health-card/backend/.env'):
    m=re.match(r'OPENAI_API_KEY=(.+)',line.strip())
    if m: OAI=m.group(1).strip().strip('"')
sets=json.load(open(os.path.join(HERE,'sets.json')))
n=int(sys.argv[1]) if len(sys.argv)>1 else 1
s=sets[n-1]
W,H=1536,1024
BASE=os.path.join(HERE,'room-base.jpg')
# --- этап 1: пустая комната (один раз, фиксированный сид) ---
if not os.path.exists(BASE):
    body={"prompt":"Photorealistic EMPTY living room, completely unfurnished, 3.8 x 4.0 meters, ceiling 2.7 m, "
     "one window with daylight on the right wall, laminate floor, warm light walls, white ceiling, "
     "wide-angle corner view from a corner showing the long left wall and the window wall on the right, "
     "interior photography. No furniture at all, no people, no text.",
     "image_size":{"width":W,"height":H},"num_inference_steps":4,"seed":42}
    req=urllib.request.Request("https://fal.run/fal-ai/flux/schnell",data=json.dumps(body).encode(),
        headers={"Authorization":f"Key {FAL}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r: out=json.loads(r.read())
    urllib.request.urlretrieve(out['images'][0]['url'],BASE)
    print("base room saved",flush=True)
room=Image.open(BASE).convert('RGB').resize((W,H))
# --- этап 2: вклейка. Зоны нашего ракурса: (cx, y_floor - НИЗ предмета, px_per_cm на этой глубине) ---
ZONES={'диван':(0.32,0.80,2.6),'кресло':(0.62,0.74,2.2),'столик':(0.45,0.88,2.4),
 'тв-тумба':(0.86,0.83,2.5),'пуф':(0.24,0.93,2.6),'торшер':(0.53,0.70,2.0),
 'кашпо':(0.72,0.72,1.9),'люстра':(0.45,0.26,1.6),'лампа':(0.86,0.70,2.0)}
ORDER=['люстра','торшер','кашпо','тв-тумба','кресло','диван','лампа','столик','пуф']
def cutout(im):
    """clean_bg + альфа: белое → прозрачное."""
    im=clean_bg(im).convert('RGBA')
    px=im.load(); w,h=im.size
    for y in range(h):
        for x in range(w):
            r,g,b,a=px[x,y]
            if r>245 and g>245 and b>245: px[x,y]=(r,g,b,0)
    return im
items={r.replace(' 2',''):it for r,it in s['items'].items()}
draft=room.copy()
for role in ORDER:
    if role not in items or role not in ZONES: continue
    it=items[role]
    u=it['img']; u='https:'+u if u.startswith('//') else u
    req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
    im=Image.open(io.BytesIO(urllib.request.urlopen(req,timeout=25).read())).convert('RGB')
    im.thumbnail((800,800)); im=cutout(im)
    cx,yb,ppc=ZONES[role]
    wcm=it.get('w') or (it.get('dia') or 60)
    hcm=it.get('h') or wcm*0.8
    tw=int(wcm*ppc); th=int(im.height*tw/im.width)
    if it.get('h'): th=int(hcm*ppc); tw=int(im.width*th/im.height)
    im=im.resize((max(tw,10),max(th,10)))
    x=int(cx*W-im.width/2); y=int(yb*H-im.height)
    draft.paste(im,(x,y),im)
draft_p=os.path.join(HERE,f"set{n}-draft.jpg"); draft.save(draft_p,'JPEG',quality=90)
print("draft saved",draft_p,flush=True)
# --- этап 3: чистовой рендер gpt-image-2 ---
prompt=("This is a rough collage draft of a living room: real product photos pasted onto an empty room. "
 "Render it as ONE photorealistic interior photograph. KEEP every object's POSITION, SIZE, SILHOUETTE and "
 "COLOUR exactly as in the draft — do not move, resize, restyle or recolor anything, do not add furniture. "
 "Fix only: perspective of each object to match the camera, natural contact shadows, lighting consistency "
 "with the window daylight, seam blending. Add a TV on the TV stand and a plain light-grey rug under the "
 "coffee table. No people, no text, no watermarks.")
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
    open(os.path.join(HERE,f"set{n}-final.jpg"),'wb').write(base64.b64decode(out['data'][0]['b64_json']))
    print("final saved",f"set{n}-final.jpg")
except urllib.error.HTTPError as e:
    print("HTTP",e.code,e.read()[:300])
