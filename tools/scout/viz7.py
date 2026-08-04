#!/usr/bin/env python3
"""gpt-image-2: ВСЕ предметы сета (до 16 рефов) + опц. 2-й проход-доводка.
python3 viz7.py <сет> [pass2:кадр.jpg]"""
import json, os, sys, re, io, base64, urllib.request, uuid
from PIL import Image
HERE=os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE,'viz3.py')).read().split("HERE=")[0])
KEY=None
for line in open('/home/pakar/igor/v0-health-card/backend/.env'):
    m=re.match(r'OPENAI_API_KEY=(.+)',line.strip())
    if m: KEY=m.group(1).strip().strip('"')
sets=json.load(open(os.path.join(HERE,'sets.json')))
n=int(sys.argv[1]) if len(sys.argv)>1 else 1
s=sets[n-1]
ROLE_EN={'диван':'sofa','кресло':'armchair','пуф':'pouf','столик':'coffee table','тв-тумба':'TV stand',
 'торшер':'floor lamp','ковёр':'rug','люстра':'chandelier','кашпо':'plant pot','лампа':'table lamp',
 'плед':'throw blanket','подушка':'decorative cushion','ваза':'vase','растение':'hanging potted plant'}
SHAPE_HINT={'столик':'leaf-shaped (holly-leaf outline) top, three legs'}
SKIP=lambda role,it: role=='ковёр' and re.search(r'pyramid|придверн|коврик',it['name'],re.I)
items=[]
for role,it in s['items'].items():
    base=role.replace(' 2','')
    if base not in ROLE_EN or SKIP(base,it): continue
    items.append((base,it))
items=items[:16]
files=[]; descs=[]
for i,(role,it) in enumerate(items,1):
    u=it['img']
    if u.startswith('//'): u='https:'+u
    req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
    im=Image.open(io.BytesIO(urllib.request.urlopen(req,timeout=25).read())).convert('RGB')
    im.thumbnail((640,640)); im=clean_bg(im)
    buf=io.BytesIO(); im.save(buf,'JPEG',quality=88)
    files.append((f"item{i}.jpg",buf.getvalue()))
    col=name_color(it['name']); hint=SHAPE_HINT.get(role,'')
    d=f"image {i}: the {ROLE_EN[role]}"
    extra=', '.join(x for x in (col and 'true color: '+col, hint) if x)
    if extra: d+=f" ({extra})"
    q=it.get('qty',1)
    if q>1: d+=f" — place {q} of them"
    descs.append(d)
m2=s['m2']
prompt=(f"Create a photorealistic photo of a cozy {m2:.0f} sq m living room (3.8x4.0 m, one window with daylight, "
 "laminate floor, warm light walls) furnished with EXACTLY the products from the attached reference images "
 "(one of each unless stated): "+"; ".join(descs)+". Also add a simple plain light-grey low-pile rug in the "
 "center (no reference for it). Layout: sofa against the long wall with the throw blanket draped on it and the "
 "cushions on it; armchair beside the sofa; the leaf-shaped coffee table with the vase on it, centered on the rug; "
 "TV stand with a TV opposite the sofa, table lamp on it; floor lamp in the corner; chandelier on the ceiling; "
 "pouf near the table; plant pot by the window; the hanging plant suspended near the window. PRESERVE each "
 "product's exact silhouette, texture and color from its reference. Wide-angle corner view, natural daylight. "
 "No people, no text, no watermarks, no logos.")
B=uuid.uuid4().hex; body=io.BytesIO()
def part(name,val,fname=None,ctype=None):
    body.write(f"--{B}\r\n".encode())
    if fname:
        body.write(f'Content-Disposition: form-data; name="{name}"; filename="{fname}"\r\nContent-Type: {ctype}\r\n\r\n'.encode())
        body.write(val); body.write(b"\r\n")
    else:
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())
part("model","gpt-image-2"); part("prompt",prompt); part("size","1536x1024"); part("quality","medium"); part("n","1")
for fn,data in files: part("image[]",data,fn,"image/jpeg")
body.write(f"--{B}--\r\n".encode())
req=urllib.request.Request("https://api.openai.com/v1/images/edits",data=body.getvalue(),
    headers={"Authorization":f"Bearer {KEY}","Content-Type":f"multipart/form-data; boundary={B}"})
try:
    with urllib.request.urlopen(req,timeout=600) as r: out=json.loads(r.read())
    img=base64.b64decode(out['data'][0]['b64_json'])
    p=os.path.join(HERE,f"set{n}-full.jpg")
    open(p,'wb').write(img); print("saved",p,"| рефов:",len(files),"| usage:",out.get('usage',{}).get('total_tokens'))
except urllib.error.HTTPError as e:
    print("HTTP",e.code,e.read()[:400])
