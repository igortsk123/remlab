"""Ф3 демо: заменить объект → 3 РЕАЛЬНЫХ товара из каталога, которые ВЛЕЗУТ (с ценой/магазином/ссылкой).
run_match.py <room> <что_заменить>   напр.: run_match.py room1 матрас"""
import cv2, numpy as np, os, sys, json
from PIL import Image, ImageDraw, ImageFont
import product_match as PM
D=os.path.dirname(os.path.abspath(__file__)); ROOM=sys.argv[1]; TARGET=sys.argv[2]
RUN=f"/tmp/room-measure/plan-{ROOM}"
data=json.load(open(f"{RUN}/plan.json")); catalog=json.load(open(f"{D}/demo_catalog.json"))
tgt=next((f for f in data["foot"] if TARGET.lower() in f["ru"].lower()),None)
if tgt is None: print("нет объекта",TARGET,"| есть:",[f["ru"] for f in data["foot"]]); raise SystemExit
zone_w,zone_d=tgt["w"],tgt["d"]
top,cats=PM.match(zone_w,zone_d,tgt["ru"],catalog,3)
img=cv2.imread(f"{D}/{ROOM}.jpg")

def F(sz,b=False): return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if b else ''}.ttf",sz)
# --- фото слева: зона подсвечена ---
photo=Image.fromarray(cv2.cvtColor(img,cv2.COLOR_BGR2RGB)).copy(); pd=ImageDraw.Draw(photo)
bx=tgt["box"]; pd.rectangle(bx,outline=(180,60,60),width=5)
pd.rectangle([bx[0],max(bx[1]-26,0),bx[0]+330,max(bx[1]-26,0)+24],fill=(255,255,255))
pd.text((bx[0]+4,max(bx[1]-24,2)),f"заменяем: {tgt['ru']} {zone_w}×{zone_d} см",font=F(16,1),fill=(180,60,60))
# --- карточки товаров справа ---
CW,CH=520,760; card=Image.new("RGB",(CW,CH),(247,248,250)); cd=ImageDraw.Draw(card)
cd.rectangle([0,0,CW,54],fill=(28,30,34))
cd.text((14,8),f"Подходят под зону {zone_w}×{zone_d} см",font=F(17,1),fill=(255,255,255))
cd.text((14,32),f"3 реальных товара, которые ВЛЕЗУТ · цена · магазин · ссылка",font=F(12),fill=(170,200,235))
COLS=[(70,130,200),(90,170,90),(210,120,60)]
y=66
if not top: cd.text((14,80),"нет подходящих в каталоге под эту зону",font=F(14),fill=(150,80,80))
for i,p in enumerate(top):
    c=COLS[i%3]; ch=210; cd.rectangle([12,y,CW-12,y+ch],fill=(255,255,255),outline=(220,224,230),width=2)
    cd.rectangle([12,y,20,y+ch],fill=c)                       # цветная полоса-категория
    cd.rectangle([28,y+16,150,y+ch-16],fill=(238,241,245),outline=(210,214,220))  # плейсхолдер фото (реальный фид даст картинку)
    cd.text((60,y+90),"фото",font=F(12),fill=(160,166,175))
    cd.text((168,y+14),p["name"],font=F(17,1),fill=(30,34,40))
    cd.text((168,y+44),f"{p['w']}×{p['d']}×{p['h']} см",font=F(14),fill=(70,76,84))
    cd.text((168,y+70),f"{p['price']:,} ₽".replace(","," "),font=F(22,1),fill=(20,120,40))
    cd.text((168,y+104),f"✓ влезет · {p['note']}",font=F(13,1),fill=(20,130,40))
    cd.text((168,y+128),f"магазин: {p['shop']}",font=F(13),fill=(70,76,84))
    cd.text((168,y+152),f"🔗 {p['url']}",font=F(12),fill=(60,110,200))
    cd.text((168,y+176),f"заполняет зону на {round(p['use']*100)}%",font=F(12),fill=(120,126,134))
    y+=ch+12
# --- склейка фото | карточки ---
Hc=card.height; wp=int(photo.width*Hc/photo.height); photo=photo.resize((wp,Hc))
comb=Image.new("RGB",(wp+CW,Hc),(247,248,250)); comb.paste(photo,(0,0)); comb.paste(card,(wp,0))
out=f"{RUN}/match.jpg"; comb.save(out,quality=90)
print(f"зона {tgt['ru']} {zone_w}×{zone_d} → подошло {len(top)}:")
for p in top: print(f"  {p['name']:28s} {p['w']}×{p['d']}×{p['h']}  {p['price']}₽  {p['shop']}  ({p['note']})")
print("saved",out)
