#!/usr/bin/env python3
"""Nano Banana 2 (gemini-3.1-flash-image, НАШ ключ): 10 объектных референсов. python3 viz6.py <сет> [вар=1]"""
import json, os, sys, re, io, base64, urllib.request
from PIL import Image
HERE=os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE,'viz3.py')).read().split("HERE=")[0])
KEY=None
for line in open('/home/pakar/mltest/.env'):
    m=re.match(r'FAL_KEY=(.+)',line.strip())
    if m: KEY=m.group(1).strip().strip('"')
assert KEY
sets=json.load(open(os.path.join(HERE,'sets.json')))
n=int(sys.argv[1]) if len(sys.argv)>1 else 1
variants=int(sys.argv[2]) if len(sys.argv)>2 else 1
s=sets[n-1]
ROLE_EN={'диван':'sofa','кресло':'armchair','пуф':'pouf','столик':'coffee table','тв-тумба':'TV stand',
 'торшер':'floor lamp','ковёр':'rug','люстра':'chandelier','кашпо':'plant pot with plant','лампа':'table lamp'}
PRIORITY=['диван','кресло','столик','тв-тумба','ковёр','торшер','люстра','пуф','кашпо','лампа']
items=[(r,it) for r in PRIORITY for rr,it in s['items'].items() if rr==r][:10]
parts=[]; descs=[]
for i,(role,it) in enumerate(items,1):
    u=it['img']
    if u.startswith('//'): u='https:'+u
    req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
    im=Image.open(io.BytesIO(urllib.request.urlopen(req,timeout=25).read())).convert('RGB')
    im.thumbnail((768,768)); im=clean_bg(im)
    buf=io.BytesIO(); im.save(buf,'JPEG',quality=88)
    parts.append('data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode())
    col=name_color(it['name'])
    descs.append(f"reference {i}: the {ROLE_EN.get(role,role)}"+(f" (true color: {col})" if col else ""))
m2=s['m2']
prompt=(f"Using the attached product reference photos, create a photorealistic interior photograph of a cozy "
 f"{m2:.0f} sq m living room (3.8 x 4.0 m, ceiling 2.7 m, one window with daylight, laminate floor, warm light "
 "walls) furnished with EXACTLY these products, exactly one of each, no duplicates: "+"; ".join(descs)+". "
 "Placement: sofa (ref 1) against the long wall; armchair (ref 2) beside it, angled toward it; coffee table (ref 3) "
 "centered on the rug (ref 5); TV stand (ref 4) with a TV opposite the sofa; floor lamp (ref 6) in the corner; "
 "chandelier (ref 7) on the ceiling; pouf (ref 8) near the table; plant pot (ref 9) by the window; table lamp "
 "(ref 10) on the TV stand. PRESERVE each product's exact silhouette, proportions, upholstery texture and exact "
 "color as in its reference photo — do not restyle or recolor. Interior magazine photography, wide-angle corner "
 "view, natural daylight, 4:3. No people, no text, no watermarks, no logos.")
for i in range(1,variants+1):
    body={"prompt":prompt,"image_urls":parts,"num_images":1,"output_format":"jpeg",
          "aspect_ratio":"4:3","seed":1100+n*10+i}
    req=urllib.request.Request("https://fal.run/fal-ai/nano-banana-2/edit",
        data=json.dumps(body).encode(),
        headers={"Authorization":f"Key {KEY}","Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=400) as r: out=json.loads(r.read())
        u=out['images'][0]['url']
        p=os.path.join(HERE,f"set{n}-nb2-v{i}.jpg")
        urllib.request.urlretrieve(u,p); print("saved",p,flush=True)
    except urllib.error.HTTPError as e:
        print("HTTP",e.code,e.read()[:400]); sys.exit(1)
