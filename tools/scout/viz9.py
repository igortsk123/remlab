#!/usr/bin/env python3
"""gpt-image-2 + авто-инварианты формы от VLM + имена/размеры всех предметов + назначение. viz9.py <сет>"""
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
 'торшер':'floor lamp','ковёр':'rug','люстра':'chandelier','кашпо':'planter pot','лампа':'table lamp',
 'плед':'throw blanket','подушка':'decorative cushion','ваза':'vase','растение':'decorative hanging plant'}
PURPOSE={'плед':'draped over the sofa seat/armrest','подушка':'placed on the sofa',
 'ваза':'standing on the coffee table','кашпо':'WITH a green plant planted in it, on the floor by the window',
 'растение':'mounted on a wall bracket beside the window, below the ceiling','лампа':'on the TV stand',
 'люстра':'centered on the ceiling','торшер':'standing in the corner near the sofa'}
def vlm_invariants(im,role_en,name):
    """3-4 буллета неизменяемых черт формы от дешёвой vision-модели."""
    buf=io.BytesIO(); im.save(buf,'JPEG',quality=85)
    b64=base64.b64encode(buf.getvalue()).decode()
    body={"model":"gpt-5-mini","messages":[{"role":"user","content":[
        {"type":"text","text":f"This is a product photo of a {role_en} ('{name}'). List 3-4 short bullet invariants of its SHAPE that a renderer must not change (armrests or lack thereof, back height/style, legs, silhouette). English, terse, one line each, no intro."},
        {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+b64}}]}]}
    req=urllib.request.Request("https://api.openai.com/v1/chat/completions",data=json.dumps(body).encode(),
        headers={"Authorization":f"Bearer {KEY}","Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=90) as r:
            out=json.loads(r.read())
        return out['choices'][0]['message']['content'].strip()
    except Exception as e:
        print("vlm skip:",str(e)[:120]); return ""
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
for role,it in items:
    u=it['img']
    if u.startswith('//'): u='https:'+u
    req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
    im=Image.open(io.BytesIO(urllib.request.urlopen(req,timeout=25).read())).convert('RGB')
    im.thumbnail((640,640)); im=clean_bg(im)
    idx+=1
    buf=io.BytesIO(); im.save(buf,'JPEG',quality=88)
    files.append((f"i{idx}.jpg",buf.getvalue()))
    dims=""
    if it.get('w'):
        parts_d=[str(int(it['w']))]
        if it.get('d') or it.get('dia'): parts_d.append(str(int(it.get('d') or it.get('dia'))))
        if it.get('h'): parts_d.append(str(int(it['h'])))
        dims=f", size {'x'.join(parts_d)} cm"
    d=f"image {idx}: {ROLE_EN[role]} «{it['name'][:45]}»{dims}"
    if role in PURPOSE: d+=f" — {PURPOSE[role]}"
    descs.append(d)
    if role in HERO:
        iv=vlm_invariants(im,ROLE_EN[role],it['name'][:50])
        if iv: inv.append(f"{ROLE_EN[role]}: "+iv.replace('\n','; '))
        rgb=dom_rgb(im)
        sw=Image.new('RGB',(256,256),rgb)
        idx+=1
        b2=io.BytesIO(); sw.save(b2,'JPEG',quality=90)
        files.append((f"i{idx}.jpg",b2.getvalue()))
        descs.append(f"image {idx}: flat swatch = EXACT colour of the {ROLE_EN[role]}")
m2=s['m2']
prompt=("Furnish and photograph a REAL living room using the referenced products as EXACT items. "
 f"Room: {m2:.0f} sq m, 3.8 x 4.0 m, ceiling 2.7 m, one window, natural daylight, laminate floor, warm light walls; "
 "add a plain light-grey low-pile rug in the seating zone (no reference). Products (respect each item's real size "
 "relative to the room, use each according to its purpose): "+"; ".join(descs)+". "
 "Arrange it as a professional interior designer would for a living room: sofa against the long wall, armchair "
 "angled beside it, coffee table on the rug, TV stand with a TV opposite the sofa, pouf near the table. "
 "PRESERVE EXACTLY, do not redesign or simplify: "+" | ".join(inv)+" | every product keeps the silhouette and "
 "colour of its photo; hero colours must match their swatches. Wide-angle corner view. No people, no text, no logos.")
print("инварианты от VLM:\n","\n ".join(inv)[:600],flush=True)
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
    open(os.path.join(HERE,f"set{n}-v9.jpg"),'wb').write(base64.b64decode(out['data'][0]['b64_json']))
    print("saved",f"set{n}-v9.jpg","рефов:",min(len(files),16))
except urllib.error.HTTPError as e:
    print("HTTP",e.code,e.read()[:300])
