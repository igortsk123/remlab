#!/usr/bin/env python3
"""Визуалка сета: fal.ai FLUX schnell ($0.003/img). Текстовая опись сцены из sets.json.
Запуск: python3 viz.py <номер сета 1..21> [вариантов=3]"""
import json, os, sys, urllib.request, re

HERE=os.path.dirname(os.path.abspath(__file__))
KEY=None
for line in open('/home/pakar/mltest/.env'):
    m=re.match(r'FAL_KEY=(.+)',line.strip())
    if m: KEY=m.group(1).strip().strip('"')
assert KEY, 'FAL_KEY не найден'
sets=json.load(open(os.path.join(HERE,'sets.json')))
n=int(sys.argv[1]) if len(sys.argv)>1 else 1
variants=int(sys.argv[2]) if len(sys.argv)>2 else 3
s=sets[n-1]

CLS_EN={'neutral_light':'light neutral (off-white/cream)','neutral_grey':'grey','neutral_dark':'dark charcoal',
 'wood_light':'light wood','wood_dark':'dark walnut wood','unknown':'neutral',
 'accent_terra':'terracotta','accent_yellow':'mustard yellow','accent_green':'sage green',
 'accent_cyan':'teal','accent_blue':'deep blue','accent_violet':'violet','accent_pink':'dusty pink','accent_red':'brick red'}
# цвет из НАЗВАНИЯ товара — надёжнее миниатюры (для мебели)
NAME_COLORS=[('шоколад','chocolate brown'),('светло-беж','light beige'),('беж','beige'),
 ('светло-сер','light grey'),('серо','grey'),('сер','grey'),('графит','graphite grey'),
 ('антрацит','anthracite'),('бел','white'),('чёрн','black'),('черн','black'),
 ('орех','walnut wood'),('венге','dark wenge wood'),('дуб сонома','sonoma oak'),('дуб','oak wood'),
 ('ясень','ash wood'),('латте','latte beige'),('капучино','cappuccino beige'),('мокко','mocha brown'),
 ('коричн','brown'),('изумруд','emerald green'),('зелён','green'),('зелен','green'),('оливк','olive'),
 ('горчичн','mustard'),('терракот','terracotta'),('син','navy blue'),('голуб','light blue'),
 ('бирюз','teal'),('роз','dusty pink'),('пудр','powder pink'),('фиолет','violet'),('лаванд','lavender'),
 ('бордо','burgundy'),('красн','red'),('жёлт','yellow'),('желт','yellow'),('медн','copper'),
 ('золот','gold'),('молочн','milky white'),('крем','cream'),('песочн','sand beige')]
SOFT={'диван','кресло','пуф','стул','подушка','плед'}
def color_of(role,it):
    nl=it['name'].lower()
    for ru,en in NAME_COLORS:
        if ru in nl: return en
    en=CLS_EN.get(it.get('cls','unknown'),'neutral')
    base=role.replace(' 2','')
    if base in SOFT and 'wood' in en:  # ткань, не дерево
        return 'chocolate brown fabric' if 'dark' in en else 'warm beige fabric'
    return en
ROLE_EN={'диван':'sofa','кресло':'armchair','пуф':'pouf','столик':'coffee table','тв-тумба':'TV stand',
 'комод':'chest of drawers','стеллаж':'shelving unit','витрина':'display cabinet','стенка':'wall unit',
 'стол обеденный':'dining table','стул':'dining chair','камин':'electric fireplace','кашпо':'floor plant in pot',
 'торшер':'floor lamp','ковёр':'area rug','лампа':'table lamp','люстра':'ceiling chandelier','ваза':'vase',
 'статуэтка':'figurine','плед':'throw blanket on the sofa','подушка':'decorative cushions on the sofa',
 'растение':'hanging/large potted plant','зеркало':'wall mirror','полка':'wall shelf'}
parts=[]
for role,it in s['items'].items():
    r=ROLE_EN.get(role.replace(' 2',''),role)
    col=color_of(role,it)
    if role=='диван' and 'fabric' not in col and 'wood' not in col: col+=' fabric'
    dims=''
    if it.get('w') and (it.get('d') or it.get('dia')):
        dims=f" ({int(it['w'])}x{int(it.get('d') or it.get('dia'))} cm)"
    q=it.get('qty',1)
    qword={1:'exactly one',2:'exactly two',4:'exactly four'}.get(q,f'{q}')
    parts.append(f"{qword} {col} {r}{dims}")
m2=s['m2']
prompt=("Photorealistic interior photo of a cozy Russian apartment living room, "
 f"{m2:.0f} square meters (about 3.8 x 4.0 m), 2.7 m ceiling, one window with daylight, laminate floor, warm light walls. "
 "Furnished with: "+", ".join(parts)+". "
 "Sofa against the long wall, TV stand opposite the sofa, rug in the center under the coffee table, "
 "floor lamp beside the sofa, realistic proportions matching the given dimensions, wide-angle corner view, "
 "interior magazine photography, natural daylight. No text, no captions, no numbers, no people.")
print("PROMPT:",prompt[:400],"...\n",flush=True)
import json as J
for i in range(1,variants+1):
    req=urllib.request.Request("https://fal.run/fal-ai/flux/schnell",
        data=J.dumps({"prompt":prompt,"image_size":{"width":1344,"height":1008},"num_inference_steps":4,
                      "seed":1000+n*10+i}).encode(),
        headers={"Authorization":f"Key {KEY}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r:
        out=J.loads(r.read())
    url=out['images'][0]['url']
    p=os.path.join(HERE,f"set{n}-v{i}.jpg")
    urllib.request.urlretrieve(url,p)
    print("saved",p,flush=True)
