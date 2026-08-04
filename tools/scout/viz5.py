#!/usr/bin/env python3
"""OpenAI gpt-image-1(-mini) images/edits: до 16 референсов. python3 viz5.py <сет> [model]"""
import json, os, sys, re, io, base64, urllib.request, uuid
from PIL import Image
HERE=os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE,'viz3.py')).read().split("HERE=")[0])
KEY=None
for line in open('/home/pakar/igor/v0-health-card/backend/.env'):
    m=re.match(r'OPENAI_API_KEY=(.+)',line.strip())
    if m: KEY=m.group(1).strip().strip('"')
assert KEY,'нет ключа'
sets=json.load(open(os.path.join(HERE,'sets.json')))
n=int(sys.argv[1]) if len(sys.argv)>1 else 1
model=sys.argv[2] if len(sys.argv)>2 else 'gpt-image-1-mini'
s=sets[n-1]
ROLE_EN={'диван':'sofa','кресло':'armchair','пуф':'pouf','столик':'coffee table','тв-тумба':'TV stand',
 'торшер':'floor lamp','ковёр':'rug','люстра':'chandelier','кашпо':'plant pot with plant','лампа':'table lamp'}
PRIORITY=['диван','кресло','столик','тв-тумба','ковёр','торшер','люстра','пуф','кашпо','лампа']
items=[(r,it) for r in PRIORITY for rr,it in s['items'].items() if rr==r][:10]
files=[]; descs=[]
for i,(role,it) in enumerate(items,1):
    u=it['img']
    if u.startswith('//'): u='https:'+u
    req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
    im=Image.open(io.BytesIO(urllib.request.urlopen(req,timeout=25).read())).convert('RGB')
    im.thumbnail((640,640)); im=clean_bg(im)
    buf=io.BytesIO(); im.save(buf,'JPEG',quality=88)
    files.append((f"item{i}.jpg",buf.getvalue()))
    col=name_color(it['name'])
    descs.append(f"image {i}: the {ROLE_EN.get(role,role)}"+(f" ({col})" if col else ""))
m2=s['m2']
prompt=(f"Create a photorealistic photo of a cozy {m2:.0f} sq m living room (3.8x4.0 m, one window with daylight, "
 "laminate floor, warm light walls) furnished with EXACTLY the products from the attached reference images, "
 "exactly one of each, no duplicates: "+"; ".join(descs)+". Sofa against the long wall, armchair beside it, "
 "coffee table centered on the rug, TV stand with TV opposite the sofa, floor lamp in the corner, chandelier on "
 "the ceiling, pouf near the table, plant pot by the window, table lamp on the TV stand. PRESERVE each product's "
 "exact silhouette, texture and color. Wide-angle corner view. No people, no text, no watermarks.")
B=uuid.uuid4().hex
body=io.BytesIO()
def part(name,val,fname=None,ctype=None):
    body.write(f"--{B}\r\n".encode())
    if fname:
        body.write(f'Content-Disposition: form-data; name="{name}"; filename="{fname}"\r\nContent-Type: {ctype}\r\n\r\n'.encode())
        body.write(val); body.write(b"\r\n")
    else:
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())
part("model",model); part("prompt",prompt); part("size","1536x1024"); part("quality","medium"); part("n","1")
for fn,data in files: part("image[]",data,fn,"image/jpeg")
body.write(f"--{B}--\r\n".encode())
req=urllib.request.Request("https://api.openai.com/v1/images/edits",data=body.getvalue(),
    headers={"Authorization":f"Bearer {KEY}","Content-Type":f"multipart/form-data; boundary={B}"})
try:
    with urllib.request.urlopen(req,timeout=600) as r: out=json.loads(r.read())
    img=base64.b64decode(out['data'][0]['b64_json'])
    p=os.path.join(HERE,f"set{n}-oai.jpg")
    open(p,'wb').write(img); print("saved",p,"usage:",out.get('usage'))
except urllib.error.HTTPError as e:
    print("HTTP",e.code,e.read()[:500])
