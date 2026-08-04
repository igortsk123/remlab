#!/usr/bin/env python3
"""gpt-image-2 по плейбуку схожести: сватчи цвета, кропы деталей, preserve-блок. viz8.py <сет>"""
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
 'плед':'throw blanket','подушка':'decorative cushion','ваза':'vase','растение':'hanging plant'}
def dom_rgb(im):
    im2=im.copy(); im2.thumbnail((120,120))
    w,h=im2.size; px=[im2.getpixel((x,y)) for y in range(int(h*.25),int(h*.75)) for x in range(int(w*.25),int(w*.75))]
    px=[c for c in px if not (c[0]>235 and c[1]>235 and c[2]>235)]
    if not px: return (128,128,128)
    q=Image.new('RGB',(len(px),1)); q.putdata(px); q=q.quantize(4).convert('RGB')
    cc={}
    for c in q.getdata(): cc[c]=cc.get(c,0)+1
    return max(cc,key=cc.get)
SKIP=lambda role,it: role=='ковёр' and re.search(r'pyramid|придверн|коврик',it['name'],re.I)
HERO={'диван','кресло','столик'}
items=[(r.replace(' 2',''),it) for r,it in s['items'].items() if r.replace(' 2','') in ROLE_EN and not SKIP(r.replace(' 2',''),it)]
files=[]; descs=[]; inv=[]
idx=0
imgs={}
for role,it in items:
    u=it['img']
    if u.startswith('//'): u='https:'+u
    req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
    im=Image.open(io.BytesIO(urllib.request.urlopen(req,timeout=25).read())).convert('RGB')
    im.thumbnail((640,640)); im=clean_bg(im); imgs[role]=im
    idx+=1
    buf=io.BytesIO(); im.save(buf,'JPEG',quality=88)
    files.append((f"i{idx}.jpg",buf.getvalue()))
    descs.append(f"image {idx}: the {ROLE_EN[role]}")
    if role in HERO:  # сватч точного цвета отдельным референсом
        rgb=dom_rgb(im)
        sw=Image.new('RGB',(256,256),rgb)
        idx+=1
        b2=io.BytesIO(); sw.save(b2,'JPEG',quality=90)
        files.append((f"i{idx}.jpg",b2.getvalue()))
        descs.append(f"image {idx}: flat colour swatch = the EXACT colour of the {ROLE_EN[role]}")
        inv.append(f"{ROLE_EN[role]}: exact colour of its swatch; exact silhouette and leg shape from its photo")
# кроп столешницы крупно (деталь формы)
if 'столик' in imgs:
    im=imgs['столик']; w,h=im.size
    crop=im.crop((0,0,w,int(h*0.55))).resize((640,int(640*0.55*h/w/h*w)) if False else (640,352))
    idx+=1
    b3=io.BytesIO(); crop.save(b3,'JPEG',quality=90)
    files.append((f"i{idx}.jpg",b3.getvalue()))
    descs.append(f"image {idx}: close-up of the coffee table TOP — note the pointed leaf shape with a notch")
    inv.append("coffee table: leaf-shaped top with pointed tip exactly as the close-up")
m2=s['m2']
prompt=("Use the referenced product photos as EXACT products. "
 f"Scene: cozy {m2:.0f} sq m living room, 3.8x4.0 m, one window, daylight, laminate floor, warm light walls, "
 "plain light-grey low-pile rug in the center (no reference). "
 +"; ".join(descs)+". "
 "Layout: sofa against the long wall, throw blanket and cushions on it; armchair beside it; leaf coffee table with "
 "the vase on the rug; TV stand with TV opposite, table lamp on it; floor lamp in corner; chandelier on ceiling; "
 "pouf near table; plant pot by window; hanging plant on a WALL bracket beside the window at 1.9 m height, clearly "
 "below the ceiling. PRESERVE EXACTLY (do not redesign, simplify or restyle): "+"; ".join(inv)+"; every other "
 "product keeps its photo's silhouette and colour. Wide-angle corner view. No people, text, watermarks, logos.")
B=uuid.uuid4().hex; body=io.BytesIO()
def part(name,val,fname=None,ctype=None):
    body.write(f"--{B}\r\n".encode())
    if fname:
        body.write(f'Content-Disposition: form-data; name="{name}"; filename="{fname}"\r\nContent-Type: {ctype}\r\n\r\n'.encode())
        body.write(val); body.write(b"\r\n")
    else:
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())
part("model","gpt-image-2"); part("prompt",prompt); part("size","1536x1024"); part("quality","medium"); part("n","1")
for fn,data in files[:16]: part("image[]",data,fn,"image/jpeg")
body.write(f"--{B}--\r\n".encode())
req=urllib.request.Request("https://api.openai.com/v1/images/edits",data=body.getvalue(),
    headers={"Authorization":f"Bearer {KEY}","Content-Type":f"multipart/form-data; boundary={B}"})
try:
    with urllib.request.urlopen(req,timeout=600) as r: out=json.loads(r.read())
    open(os.path.join(HERE,f"set{n}-v8.jpg"),'wb').write(base64.b64decode(out['data'][0]['b64_json']))
    print("saved",f"set{n}-v8.jpg","рефов:",min(len(files),16))
except urllib.error.HTTPError as e:
    print("HTTP",e.code,e.read()[:300])
