#!/usr/bin/env python3
"""Точечный инпейнт одной зоны поверх готового кадра. fixone.py <сет> <x0 y0 x1 y1> <промпт> [роль-реф ...]"""
import json, os, sys, re, io, base64, urllib.request, uuid
from PIL import Image, ImageDraw
HERE=os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE,'viz3.py')).read().split("HERE=")[0])
OAI=None
for line in open('/home/pakar/igor/v0-health-card/backend/.env'):
    m=re.match(r'OPENAI_API_KEY=(.+)',line.strip())
    if m: OAI=m.group(1).strip().strip('"')
n=int(sys.argv[1]); x0,y0,x1,y1=map(int,sys.argv[2:6]); fixp=sys.argv[6]; roles=sys.argv[7:]
s=json.load(open(os.path.join(HERE,'sets.json')))[n-1]
items={r.replace(' 2',''):it for r,it in s['items'].items()}
W,H=1536,1024
src=os.path.join(HERE,f"set{n}-pipe2-fix1.jpg")
base=open(src,'rb').read()
def fetch(it,maxpx=500):
    u=it['img']; u='https:'+u if u.startswith('//') else u
    req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
    ph=Image.open(io.BytesIO(urllib.request.urlopen(req,timeout=25).read())).convert('RGB')
    ph.thumbnail((maxpx,maxpx)); return ph
m=Image.new('RGBA',(W,H),(0,0,0,255)); ImageDraw.Draw(m).rectangle([x0,y0,x1,y1],fill=(0,0,0,0))
mb=io.BytesIO(); m.save(mb,'PNG')
B=uuid.uuid4().hex; body=io.BytesIO()
def part(name,val,fname=None,ctype=None):
    body.write(f"--{B}\r\n".encode())
    if fname:
        body.write(f'Content-Disposition: form-data; name="{name}"; filename="{fname}"\r\nContent-Type: {ctype}\r\n\r\n'.encode())
        body.write(val); body.write(b"\r\n")
    else:
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())
part("model","gpt-image-2"); part("prompt",fixp); part("size","1536x1024"); part("quality","medium"); part("n","1")
part("image[]",base,"base.jpg","image/jpeg")
for i,r in enumerate(roles):
    b=io.BytesIO(); fetch(items[r]).save(b,'PNG'); part("image[]",b.getvalue(),f"ref{i}.png","image/png")
part("mask",mb.getvalue(),"mask.png","image/png")
body.write(f"--{B}--\r\n".encode())
req=urllib.request.Request("https://api.openai.com/v1/images/edits",data=body.getvalue(),
    headers={"Authorization":f"Bearer {OAI}","Content-Type":f"multipart/form-data; boundary={B}"})
with urllib.request.urlopen(req,timeout=600) as r: out=json.loads(r.read())
img=base64.b64decode(out['data'][0]['b64_json'])
p=os.path.join(HERE,f"set{n}-pipe2.jpg"); open(p,'wb').write(img)
print("saved",p)
