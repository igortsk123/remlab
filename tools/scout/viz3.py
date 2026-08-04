#!/usr/bin/env python3
"""Визуалка сета: fal.ai FLUX.2 [pro] edit — до 8 ОТДЕЛЬНЫХ фото-референсов, $0.03/кадр.
По гайду BFL: нумерованные референсы + точные цвета + preservation.
Запуск: python3 viz3.py <номер сета> [вариантов=2]"""
import json, os, sys, re, io, base64, urllib.request
from PIL import Image
def clean_bg(im):
    """Заменить фон (кластеры по рамке: белый/брендовый паттерн/лого) на белый."""
    w,h=im.size; px=im.load()
    bw=max(2,int(min(w,h)*0.08))
    from collections import Counter
    border=[px[x,y] for y in range(h) for x in range(w) if x<bw or x>=w-bw or y<bw or y>=h-bw]
    q=Image.new('RGB',(len(border),1)); q.putdata(border)
    bc=Counter(q.quantize(4).convert('RGB').getdata())
    bg=[c for c,n_ in bc.items() if n_>=len(border)*0.12]
    out=im.copy(); po=out.load()
    for y in range(h):
        for x in range(w):
            c=px[x,y]
            if any(abs(c[0]-b[0])+abs(c[1]-b[1])+abs(c[2]-b[2])<110 for b in bg) or (c[0]>235 and c[1]>235 and c[2]>235):
                po[x,y]=(255,255,255)
    return out
NAME_COLORS=[('шоколад','chocolate brown'),('светло-беж','light beige'),('беж','beige'),
 ('платина','platinum grey'),('светло-сер','light grey'),('серо','grey'),('сер','grey'),
 ('графит','graphite'),('антрацит','anthracite'),('бел','white'),('чёрн','black'),('черн','black'),
 ('орех','walnut wood'),('венге','wenge'),('дуб','oak'),('ясень','ash'),('коричн','brown'),
 ('изумруд','emerald'),('зелён','green'),('зелен','green'),('оливк','olive'),('горчичн','mustard'),
 ('терракот','terracotta'),('син','navy'),('голуб','light blue'),('бирюз','teal'),('роз','pink'),
 ('лаванд','lavender'),('бордо','burgundy'),('медн','copper'),('молочн','milky white'),('крем','cream')]
def name_color(name):
    nl=name.lower()
    for ru,en in NAME_COLORS:
        if ru in nl: return en
    return ''

HERE=os.path.dirname(os.path.abspath(__file__))
KEY=None
for line in open('/home/pakar/mltest/.env'):
    m=re.match(r'FAL_KEY=(.+)',line.strip())
    if m: KEY=m.group(1).strip().strip('"')
sets=json.load(open(os.path.join(HERE,'sets.json')))
n=int(sys.argv[1]) if len(sys.argv)>1 else 1
variants=int(sys.argv[2]) if len(sys.argv)>2 else 2
s=sets[n-1]
ROLE_EN={'диван':'sofa','кресло':'armchair','пуф':'pouf','столик':'coffee table','тв-тумба':'TV stand',
 'торшер':'floor lamp','ковёр':'rug','люстра':'chandelier','кашпо':'plant pot','комод':'chest of drawers',
 'стеллаж':'shelving unit','стенка':'wall unit','стол обеденный':'dining table','стул':'dining chair','витрина':'display cabinet'}
PRIORITY=['диван','кресло','столик','тв-тумба','ковёр','торшер','люстра','пуф']
items=[(r,it) for r in PRIORITY for rr,it in s['items'].items() if rr==r][:6]
urls=[]; descs=[]
for i,(role,it) in enumerate(items,1):
    url=it['img']
    if url.startswith('//'): url='https:'+url
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    im=Image.open(io.BytesIO(urllib.request.urlopen(req,timeout=25).read())).convert('RGB')
    im.thumbnail((512,512)); im=clean_bg(im)
    buf=io.BytesIO(); im.save(buf,'JPEG',quality=88)
    urls.append('data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode())
    col=name_color(it['name'])
    d=f"image {i} is the {ROLE_EN.get(role,role)}"
    if col: d+=f" (true color: {col})"
    descs.append(d)
m2=s['m2']
prompt=(f"Create a photorealistic interior photo of a cozy {m2:.0f} sq m living room "
 "(3.8 x 4.0 m, ceiling 2.7 m, one window with daylight, laminate floor, warm light walls). "
 f"Furnish it with EXACTLY the products from the reference images, exactly one of each, no duplicates: "
 +"; ".join(descs)+". "
 "Placement: the sofa (image 1) against the long wall; the single armchair (image 2) beside the sofa, angled toward it; "
 "the coffee table (image 3) in the center on the rug (image 5); the TV stand (image 4) with a TV against the wall opposite the sofa; "
 "the floor lamp (image 6) in the corner near the sofa; additionally a simple small white classic chandelier on the ceiling "
 "and a small light-grey pouf near the coffee table. "
 "PRESERVE each product's exact silhouette, proportions, upholstery texture and exact color as in its reference image — "
 "do not restyle, do not recolor, do not add furniture that is not referenced (a TV on the stand is allowed). "
 "Interior magazine photography, wide-angle corner view, natural daylight. No people, no text, no watermarks, no logos.")
J=json
for i in range(1,variants+1):
    body={"prompt":prompt,"image_urls":urls,"image_size":{"width":1024,"height":768},"seed":700+n*10+i}
    try:
        req=urllib.request.Request("https://fal.run/fal-ai/flux-2-pro/edit",data=J.dumps(body).encode(),
            headers={"Authorization":f"Key {KEY}","Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=240) as r: out=J.loads(r.read())
        url=out['images'][0]['url']
        p=os.path.join(HERE,f"set{n}-f2-v{i}.jpg")
        urllib.request.urlretrieve(url,p); print("saved",p,flush=True)
    except urllib.error.HTTPError as e:
        print("HTTP",e.code,e.read()[:400]); sys.exit(1)
