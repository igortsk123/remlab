#!/usr/bin/env python3
"""Сверка: фото товара (слева) ↔ вырез из финального кадра по bbox вклейки (справа).
Выход: set<n>-cmp-A.jpg / -B.jpg (по 7 строк)."""
import json, os, sys, re, io, urllib.request
from PIL import Image, ImageDraw
HERE=os.path.dirname(os.path.abspath(__file__))
n=int(sys.argv[1]) if len(sys.argv)>1 else 1
s=json.load(open(os.path.join(HERE,'sets.json')))[n-1]
items={r.replace(' 2',''):it for r,it in s['items'].items()}
fin=Image.open(os.path.join(HERE,f"set{n}-pipe2.jpg")).convert('RGB')
W,H=fin.size
# bbox вклеек из прогона pipeline2 (пересобирать драфт не нужно — берём координаты POS-проекции)
# проще: перезапустить геометрию без сети нельзя (фото нужны для aspect) — читаем из сохранённого лога?
# Надёжно: сериализуем BB при прогоне. Если файла нет — грубые зоны по позициям.
bbf=os.path.join(HERE,f"set{n}-bb.json")
BB=json.load(open(bbf)) if os.path.exists(bbf) else None
ROWH=240; PAD=8
def fetch(it,maxpx=600):
    u=it['img']; u='https:'+u if u.startswith('//') else u
    req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
    ph=Image.open(io.BytesIO(urllib.request.urlopen(req,timeout=25).read())).convert('RGB')
    ph.thumbnail((maxpx,maxpx)); return ph
def fit(im,w,h,bg=(255,255,255)):
    im=im.copy(); im.thumbnail((w,h))
    out=Image.new('RGB',(w,h),bg); out.paste(im,((w-im.width)//2,(h-im.height)//2)); return out
roles=[r for r in BB if r in items or r.startswith('подушка') or r=='ветка-в-кашпо']
rows=[]
for role in roles:
    x0,y0,x1,y1=BB[role]
    px,py=int((x1-x0)*0.35)+30,int((y1-y0)*0.35)+30
    crop=fin.crop((max(0,x0-px),max(0,y0-py),min(W,x1+px),min(H,y1+py)))
    key='подушка' if role.startswith('подушка') else ('растение' if role=='ветка-в-кашпо' else role)
    if key not in items: continue
    rows.append((role,fetch(items[key]),crop))
def sheet(rows,path):
    Wp=1200
    out=Image.new('RGB',(Wp,len(rows)*(ROWH+PAD)+PAD),(240,240,240))
    dr=ImageDraw.Draw(out)
    y=PAD
    for role,ph,crop in rows:
        out.paste(fit(ph,560,ROWH),(PAD,y))
        out.paste(fit(crop,560,ROWH,(230,230,230)),(600,y))
        dr.text((580,y+4),role[:2],fill=(0,0,0))
        dr.text((PAD+4,y+4),role,fill=(200,30,30))
        y+=ROWH+PAD
    out.save(path,'JPEG',quality=88)
half=(len(rows)+1)//2
sheet(rows[:half],os.path.join(HERE,f"set{n}-cmp-A.jpg"))
sheet(rows[half:],os.path.join(HERE,f"set{n}-cmp-B.jpg"))
print("rows:",", ".join(r for r,_,_ in rows))
