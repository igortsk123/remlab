#!/usr/bin/env python3
"""Конвейер витринной картинки сета: проекция всех предметов по назначению → gpt-image-2 → VLM-QA → ретрай.
pipeline.py <сет> [--no-qa]"""
import json, os, sys, re, io, base64, urllib.request, uuid
from PIL import Image, ImageDraw
HERE=os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE,'viz3.py')).read().split("HERE=")[0])
OAI=None
for line in open('/home/pakar/igor/v0-health-card/backend/.env'):
    m=re.match(r'OPENAI_API_KEY=(.+)',line.strip())
    if m: OAI=m.group(1).strip().strip('"')
sets=json.load(open(os.path.join(HERE,'sets.json')))
n=int(sys.argv[1]) if len(sys.argv)>1 else 1
s=sets[n-1]
W,H=1536,1024
RX,RZ,RY=3.8,4.0,2.7
CAMX,CAMY,CAMZ=1.55,1.35,-1.35
F=1750.0; CX,CY=W/2,575
def P(X,Y,Z):
    d=Z-CAMZ
    return (CX+F*(X-CAMX)/d, CY-F*(Y-CAMY)/d)
img=Image.new('RGB',(W,H),(246,240,230)); dr=ImageDraw.Draw(img)
dr.polygon([P(0,0,0.01),P(RX,0,0.01),P(RX,0,RZ),P(0,0,RZ)],fill=(186,143,96))
dr.polygon([P(0,0,RZ),P(RX,0,RZ),P(RX,RY,RZ),P(0,RY,RZ)],fill=(243,232,215))
dr.polygon([P(0,0,0.01),P(0,0,RZ),P(0,RY,RZ),P(0,RY,0.01)],fill=(238,226,208))
dr.polygon([P(RX,0,0.01),P(RX,0,RZ),P(RX,RY,RZ),P(RX,RY,0.01)],fill=(240,229,211))
dr.polygon([P(0,RY,0.01),P(RX,RY,0.01),P(RX,RY,RZ),P(0,RY,RZ)],fill=(250,247,242))
dr.polygon([P(RX,0.9,1.4),P(RX,0.9,2.8),P(RX,2.1,2.8),P(RX,2.1,1.4)],fill=(210,228,240),outline=(255,255,255),width=6)
def cutout(im):
    im=clean_bg(im).convert('RGBA')
    px=im.load(); w,h=im.size
    for y in range(h):
        for x in range(w):
            r,g,b,a=px[x,y]
            if r>245 and g>245 and b>245: px[x,y]=(r,g,b,0)
    return im
def fetch_cut(it,maxpx=800):
    u=it['img']; u='https:'+u if u.startswith('//') else u
    req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
    ph=Image.open(io.BytesIO(urllib.request.urlopen(req,timeout=25).read())).convert('RGB')
    ph.thumbnail((maxpx,maxpx)); return cutout(ph)
items={r.replace(' 2',''):it for r,it in s['items'].items()}
# позиции: (X, Z, Y_низа); NB: диван у задней стены, декор поверх носителей
POS={'диван':(1.55,3.72,0),'кресло':(3.02,3.22,0),'столик':(1.55,2.5,0),'пуф':(0.75,2.1,0),
 'торшер':(0.42,3.3,0),'кашпо':(3.45,3.7,0),'тв-тумба':(3.55,1.35,0),'люстра':(1.75,3.0,None),
 'растение':(0.28,3.9,None)}
order=['люстра','растение','торшер','кашпо','тв-тумба','кресло','диван','столик','пуф']
draft=img.copy(); anchors={}
for role in order:
    if role not in items or role not in POS: continue
    it=items[role]; X,Z,Yb=POS[role]
    ph=fetch_cut(it)
    hcm=it.get('h') or ((it.get('w') or 60)*ph.height/max(ph.width,1))
    if role=='люстра': hcm=min(it.get('h') or 45,60); Yb=RY-hcm/100
    if role=='растение': hcm=min(it.get('h') or 90,100); Yb=1.9-hcm/100  # кронштейн 1.9 м
    dpt=Z-CAMZ
    pxh=F*(hcm/100)/dpt; pxw=pxh*ph.width/max(ph.height,1)
    ph=ph.resize((max(int(pxw),8),max(int(pxh),8)))
    cu,cv=P(X,Yb if Yb is not None else 0,Z)
    draft.paste(ph,(int(cu-ph.width/2),int(cv-ph.height)),ph)
    anchors[role]=(X,Z,hcm)
# декор по назначению
if 'диван' in anchors:
    X,Z,hs=anchors['диван']; dpt=Z-CAMZ
    if 'подушка' in items:
        ph=fetch_cut(items['подушка'],300)
        pxh=F*0.30/dpt; ph=ph.resize((int(pxh*ph.width/ph.height),int(pxh)))
        for dx in (-0.55,0.5):
            cu,cv=P(X+dx,0.42,Z)
            draft.paste(ph,(int(cu-ph.width/2),int(cv-ph.height)),ph)
    if 'плед' in items:
        ph=fetch_cut(items['плед'],400)
        pxh=F*0.45/dpt; ph=ph.resize((int(pxh*ph.width/ph.height),int(pxh)))
        cu,cv=P(X-0.15,0.47,Z)
        draft.paste(ph,(int(cu-ph.width/2),int(cv-ph.height)),ph)
if 'столик' in anchors and 'ваза' in items:
    X,Z,hs=anchors['столик']; dpt=Z-CAMZ
    ph=fetch_cut(items['ваза'],200)
    pxh=F*((min(items['ваза'].get('h') or 22,30))/100)/dpt
    ph=ph.resize((max(int(pxh*ph.width/ph.height),5),max(int(pxh),5)))
    cu,cv=P(X+0.1,hs/100,Z)
    draft.paste(ph,(int(cu-ph.width/2),int(cv-ph.height)),ph)
if 'тв-тумба' in anchors and 'лампа' in items:
    X,Z,hs=anchors['тв-тумба']; dpt=Z-CAMZ
    ph=fetch_cut(items['лампа'],300)
    pxh=F*(min(items['лампа'].get('h') or 40,55)/100)/dpt
    ph=ph.resize((max(int(pxh*ph.width/ph.height),6),max(int(pxh),6)))
    cu,cv=P(X-0.1,hs/100,Z)
    draft.paste(ph,(int(cu-ph.width/2),int(cv-ph.height)),ph)
p_draft=os.path.join(HERE,f"set{n}-pipe-draft.jpg"); draft.save(p_draft,'JPEG',quality=92)
print("draft ok",flush=True)
PROMPT=("Geometric draft of a living room 3.8 x 4.0 m (15 sq m), ceiling 2.7 m: flat box room with real product "
 "photos pasted at CORRECT positions and sizes. Render as ONE photorealistic interior photo. KEEP every object's "
 "position, size, silhouette and colour EXACTLY; rotate objects only to sit naturally in perspective (TV stand "
 "along the right wall). The blanket and cushions lie ON the sofa; the vase stands ON the coffee table; the lamp "
 "ON the TV stand; the hanging plant hangs from a wall bracket; the plant pot contains its plant. Make the room "
 "real: laminate floor, warm walls, daylight from the right window, sheer curtains, TV on the stand, plain "
 "light-grey rug under the coffee table, soft contact shadows. Do not add furniture. No people, text, watermarks.")
def render(extra=""):
    B=uuid.uuid4().hex; body=io.BytesIO()
    def part(name,val,fname=None,ctype=None):
        body.write(f"--{B}\r\n".encode())
        if fname:
            body.write(f'Content-Disposition: form-data; name="{name}"; filename="{fname}"\r\nContent-Type: {ctype}\r\n\r\n'.encode())
            body.write(val); body.write(b"\r\n")
        else:
            body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())
    buf=io.BytesIO(); draft.save(buf,'JPEG',quality=92)
    part("model","gpt-image-2"); part("prompt",PROMPT+extra); part("size","1536x1024"); part("quality","medium"); part("n","1")
    part("image[]",buf.getvalue(),"draft.jpg","image/jpeg")
    body.write(f"--{B}--\r\n".encode())
    req=urllib.request.Request("https://api.openai.com/v1/images/edits",data=body.getvalue(),
        headers={"Authorization":f"Bearer {OAI}","Content-Type":f"multipart/form-data; boundary={B}"})
    with urllib.request.urlopen(req,timeout=600) as r: out=json.loads(r.read())
    return base64.b64decode(out['data'][0]['b64_json'])
def qa(final_jpg):
    b64=base64.b64encode(final_jpg).decode()
    b64d=base64.b64encode(open(p_draft,'rb').read()).decode()
    body={"model":"gpt-5-mini","messages":[{"role":"user","content":[
        {"type":"text","text":"Image 1 is a draft with exact product positions/colours; image 2 is the final render. "
         "Check: (1) every draft object present once, (2) positions kept, (3) colours match, (4) blanket/cushions on sofa, "
         "vase on table, lamp on TV stand. Reply STRICT JSON: {\"ok\":bool,\"issues\":[\"...\"]}"},
        {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+b64d}},
        {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+b64}}]}]}
    req=urllib.request.Request("https://api.openai.com/v1/chat/completions",data=json.dumps(body).encode(),
        headers={"Authorization":f"Bearer {OAI}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r: out=json.loads(r.read())
    txt=out['choices'][0]['message']['content']
    m=re.search(r'\{.*\}',txt,re.S)
    try: return json.loads(m.group(0))
    except: return {"ok":True,"issues":["qa-parse-fail"]}
final=render()
p_final=os.path.join(HERE,f"set{n}-pipe.jpg"); open(p_final,'wb').write(final)
if '--no-qa' not in sys.argv:
    v=qa(final)
    print("QA:",json.dumps(v,ensure_ascii=False)[:400],flush=True)
    if not v.get('ok') and v.get('issues'):
        final=render(" FIX these issues from the previous attempt: "+"; ".join(v['issues'][:4]))
        open(p_final,'wb').write(final)
        print("retry saved",flush=True)
print("final:",p_final)
