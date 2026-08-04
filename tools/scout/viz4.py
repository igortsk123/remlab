#!/usr/bin/env python3
"""Seedream v4 edit (fal, $0.03): до 10 фото-референсов. python3 viz4.py <сет> [вариантов=2]"""
import json, os, sys, re, io, base64, urllib.request
from PIL import Image
HERE=os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE,'viz3.py')).read().split("HERE=")[0])  # clean_bg, NAME_COLORS, name_color
KEY=None
for line in open('/home/pakar/mltest/.env'):
    m=re.match(r'FAL_KEY=(.+)',line.strip())
    if m: KEY=m.group(1).strip().strip('"')
sets=json.load(open(os.path.join(HERE,'sets.json')))
n=int(sys.argv[1]) if len(sys.argv)>1 else 1
variants=int(sys.argv[2]) if len(sys.argv)>2 else 2
s=sets[n-1]
ROLE_EN={'диван':'sofa','кресло':'armchair','пуф':'pouf','столик':'coffee table','тв-тумба':'TV stand',
 'торшер':'floor lamp','ковёр':'rug','люстра':'chandelier','кашпо':'plant pot with plant','лампа':'table lamp',
 'комод':'chest of drawers','стеллаж':'shelving unit','стенка':'wall unit','стол обеденный':'dining table',
 'стул':'dining chair','витрина':'display cabinet','плед':'throw blanket','подушка':'cushion'}
PRIORITY=['диван','кресло','столик','тв-тумба','ковёр','торшер','люстра','пуф','кашпо','лампа']
items=[(r,it) for r in PRIORITY for rr,it in s['items'].items() if rr==r][:10]
urls=[]; descs=[]
for i,(role,it) in enumerate(items,1):
    u=it['img']
    if u.startswith('//'): u='https:'+u
    req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
    im=Image.open(io.BytesIO(urllib.request.urlopen(req,timeout=25).read())).convert('RGB')
    im.thumbnail((640,640)); im=clean_bg(im)
    buf=io.BytesIO(); im.save(buf,'JPEG',quality=88)
    urls.append('data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode())
    col=name_color(it['name'])
    descs.append(f"image {i}: the {ROLE_EN.get(role,role)}"+(f" ({col})" if col else ""))
m2=s['m2']
prompt=(f"Create a photorealistic photo of a cozy {m2:.0f} sq m living room (3.8 x 4.0 m, ceiling 2.7 m, "
 "one window with daylight, laminate floor, warm light walls) furnished with EXACTLY the products from the "
 "reference images, exactly one of each, no duplicates: "+"; ".join(descs)+". "
 "Placement: sofa (image 1) against the long wall; armchair (image 2) beside it angled toward it; coffee table "
 "(image 3) centered on the rug (image 5); TV stand (image 4) with a TV opposite the sofa; floor lamp (image 6) "
 "in the corner; chandelier (image 7) on the ceiling; pouf (image 8) near the table; plant pot (image 9) by the window; "
 "table lamp (image 10) on the TV stand. PRESERVE each product's exact silhouette, proportions, texture and color "
 "as in its reference. Interior magazine photography, wide-angle corner view. No people, no text, no watermarks, no logos.")
J=json
for i in range(1,variants+1):
    body={"prompt":prompt,"image_urls":urls,"image_size":{"width":1280,"height":960},"seed":900+n*10+i,
          "num_images":1,"enable_safety_checker":False}
    try:
        req=urllib.request.Request("https://fal.run/fal-ai/bytedance/seedream/v4/edit",
            data=J.dumps(body).encode(),headers={"Authorization":f"Key {KEY}","Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=300) as r: out=J.loads(r.read())
        u=out['images'][0]['url']
        p=os.path.join(HERE,f"set{n}-sd-v{i}.jpg")
        urllib.request.urlretrieve(u,p); print("saved",p,flush=True)
    except urllib.error.HTTPError as e:
        print("HTTP",e.code,e.read()[:300]); sys.exit(1)
