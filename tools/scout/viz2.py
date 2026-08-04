#!/usr/bin/env python3
"""Визуалка сета ПО ФОТО товаров: коллаж-референс → fal.ai FLUX Kontext (image-to-image).
Запуск: python3 viz2.py <номер сета> [вариантов=2]"""
import json, os, sys, re, io, base64, urllib.request

HERE=os.path.dirname(os.path.abspath(__file__))
from PIL import Image, ImageDraw
NAME_COLORS=[('шоколад','chocolate brown'),('светло-беж','light beige'),('беж','beige'),
 ('платина','platinum grey'),('светло-сер','light grey'),('серо','grey'),('сер','grey'),
 ('графит','graphite'),('антрацит','anthracite'),('бел','white'),('чёрн','black'),('черн','black'),
 ('орех','walnut wood'),('венге','wenge'),('дуб','oak'),('ясень','ash'),('латте','latte'),
 ('коричн','brown'),('изумруд','emerald'),('зелён','green'),('зелен','green'),('оливк','olive'),
 ('горчичн','mustard'),('терракот','terracotta'),('син','navy'),('голуб','light blue'),
 ('бирюз','teal'),('роз','pink'),('лаванд','lavender'),('бордо','burgundy'),('медн','copper'),
 ('молочн','milky white'),('крем','cream')]
ROLE_EN={'диван':'SOFA','кресло':'ARMCHAIR','пуф':'POUF','столик':'COFFEE TABLE','тв-тумба':'TV STAND',
 'комод':'CHEST','стеллаж':'SHELVING','витрина':'CABINET','стенка':'WALL UNIT','стол обеденный':'DINING TABLE',
 'стул':'CHAIR','камин':'FIREPLACE','кашпо':'PLANT POT','торшер':'FLOOR LAMP','ковёр':'RUG','лампа':'TABLE LAMP',
 'люстра':'CHANDELIER'}
def name_color(name):
    nl=name.lower()
    for ru,en in NAME_COLORS:
        if ru in nl: return en
    return ''
KEY=None
for line in open('/home/pakar/mltest/.env'):
    m=re.match(r'FAL_KEY=(.+)',line.strip())
    if m: KEY=m.group(1).strip().strip('"')
sets=json.load(open(os.path.join(HERE,'sets.json')))
n=int(sys.argv[1]) if len(sys.argv)>1 else 1
variants=int(sys.argv[2]) if len(sys.argv)>2 else 2
s=sets[n-1]
# ключевые предметы для референса (влезает ~9 в коллаж 3x3)
PRIORITY=['диван','кресло','столик','тв-тумба','пуф','ковёр','торшер','люстра','кашпо','стеллаж','комод','стенка','стол обеденный','стул']
items=[(r,it) for r in PRIORITY for rr,it in s['items'].items() if rr==r][:9]
def fetch(url):
    if url.startswith('//'): url='https:'+url
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    return Image.open(io.BytesIO(urllib.request.urlopen(req,timeout=25).read())).convert('RGB')
def clean_bg(im):
    """Заменить фон (кластеры по рамке: белый/брендовый паттерн/лого) на белый."""
    w,h=im.size; px=im.load()
    bw=max(2,int(min(w,h)*0.08))
    from collections import Counter
    border=[px[x,y] for y in range(h) for x in range(w) if x<bw or x>=w-bw or y<bw or y>=h-bw]
    q=Image.new('RGB',(len(border),1)); q.putdata(border)
    bc=Counter(q.quantize(4).convert('RGB').getdata())
    bg=[c for c,n in bc.items() if n>=len(border)*0.12]
    out=im.copy(); po=out.load()
    for y in range(h):
        for x in range(w):
            c=px[x,y]
            if any(abs(c[0]-b[0])+abs(c[1]-b[1])+abs(c[2]-b[2])<110 for b in bg) or (c[0]>235 and c[1]>235 and c[2]>235):
                po[x,y]=(255,255,255)
    return out
CELL=400; LBL=34
cols=3; rows=(len(items)+cols-1)//cols
sheet=Image.new('RGB',(cols*CELL,rows*(CELL+LBL)),(255,255,255))
drw=ImageDraw.Draw(sheet)
for i,(role,it) in enumerate(items):
    try:
        im=fetch(it['img']); im.thumbnail((CELL-14,CELL-14-LBL)); im=clean_bg(im)
        cx=(i%cols)*CELL; cy=(i//cols)*(CELL+LBL)
        sheet.paste(im,(cx+(CELL-im.width)//2, cy+(CELL-LBL-im.height)//2))
        col=name_color(it['name'])
        label=f"{ROLE_EN.get(role,role)}{' - '+col.upper() if col else ''} x1"
        drw.rectangle([cx,cy+CELL-LBL,cx+CELL,cy+CELL],fill=(20,20,20))
        drw.text((cx+10,cy+CELL-LBL+9),label,fill=(255,255,255))
    except Exception as e: print('skip',role,e)
ref=os.path.join(HERE,f'set{n}-ref.jpg'); sheet.save(ref,'JPEG',quality=88)
b64=base64.b64encode(open(ref,'rb').read()).decode()
data_url='data:image/jpeg;base64,'+b64
m2=s['m2']
itemlist=', '.join(f"exactly one {name_color(it['name'])+' ' if name_color(it['name']) else ''}{ROLE_EN.get(r,r).lower()}" for r,it in items)
prompt=(f"The reference sheet shows labeled furniture products. Create a photorealistic photo of a cozy "
 f"{m2:.0f} sq m living room (3.8 x 4.0 m, ceiling 2.7 m) furnished with EXACTLY the labeled items, "
 f"one of each, no duplicates: {itemlist}. "
 "Placement: sofa against the long wall, TV stand opposite, coffee table on the rug in the center, "
 "the single armchair beside the sofa, floor lamp in the corner, chandelier on the ceiling, plant pot near the window. "
 "STRICTLY keep each product's real shape, exact color and upholstery as shown in its reference photo; "
 "the labels state the true colors. One window with daylight, laminate floor, warm light walls, "
 "interior magazine photography, wide-angle corner view. No text, no labels, no numbers, no people, "
 "no collage grid in the output. ABSOLUTELY NO watermarks, NO logos, NO lettering anywhere in the image.")
J=json
for i in range(1,variants+1):
    body={"prompt":prompt,"image_url":data_url,"guidance_scale":3.5,"num_images":1,"seed":500+n*10+i,
          "output_format":"jpeg","aspect_ratio":"4:3"}
    ok=False
    for ep in ("fal-ai/flux-pro/kontext","fal-ai/flux-pro/kontext/max"):
        try:
            req=urllib.request.Request(f"https://fal.run/{ep}",data=J.dumps(body).encode(),
                headers={"Authorization":f"Key {KEY}","Content-Type":"application/json"})
            with urllib.request.urlopen(req,timeout=180) as r: out=J.loads(r.read())
            url=out['images'][0]['url']
            p=os.path.join(HERE,f"set{n}-ref-v{i}.jpg")
            urllib.request.urlretrieve(url,p); print("saved",p,"via",ep,flush=True); ok=True; break
        except Exception as e:
            print(ep,"failed:",str(e)[:200],flush=True)
    if not ok: sys.exit(1)
