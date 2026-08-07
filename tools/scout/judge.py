#!/usr/bin/env python3
"""Ф6 «взгляд дизайнера»: gpt-5-mini смотрит коллаж сета, называет выбивающиеся предметы,
замена — из alternates (запасных кандидатов compose2). ~0.2–0.4 ₽/сет.
Вход/выход: sets2.json (правится на месте) + judge-report.json."""
import os, io, re, json, base64, subprocess, urllib.request
from PIL import Image, ImageDraw

HERE=os.path.dirname(os.path.abspath(__file__))
THUMBS=os.path.join(HERE,'thumbs')
OAI=None
for line in open('/home/pakar/igor/v0-health-card/backend/.env'):
    m=re.match(r'OPENAI_API_KEY=(.+)',line.strip())
    if m: OAI=m.group(1).strip().strip('"')
SETS_FILE='sets3.json' if '--v3' in __import__('sys').argv else 'sets2.json'
sets=json.load(open(os.path.join(HERE,SETS_FILE)))
# Политика замен (владелец 2026-08-02): менять состав ТОЛЬКО если style_grade < порога;
# замену выбирать из запасных по МАКСИМАЛЬНОМУ стиль-вектору (оценки уже посчитаны — вслепую можно).
_OCC=json.load(open(os.path.join(HERE,'occupancy.json')))['dynamic'] if os.path.exists(os.path.join(HERE,'occupancy.json')) else {}
STYLE_THR=_OCC.get('judge_style_thr',6)  # эмпирика 2026-08-02 (медиана style_grade); источник — occupancy.json
SS=json.load(open(os.path.join(HERE,'style-scores.json'))) if os.path.exists(os.path.join(HERE,'style-scores.json')) else {}
def skey(mid,eid): return f"{mid}-{re.sub(r'[^A-Za-z0-9]','_',str(eid))[:40]}"
def _overlap_ok_swap(cand,set_i):
    """Замена не должна ломать лимиты разнообразия (≤3 между стилями, ≤5 внутри) против ДРУГИХ сетов."""
    ck=f"{cand['mid']}-{cand['eid']}"
    cur={f"{it['mid']}-{it['eid']}" for it in sets[set_i]['items'].values()}
    for j,o in enumerate(sets):
        if j==set_i or not o.get('style'): continue
        ok_={f"{it['mid']}-{it['eid']}" for it in o['items'].values()}
        lim=5 if o['style']==sets[set_i].get('style') else 3
        if len(cur&ok_)+(1 if (ck in ok_ and ck not in cur) else 0)>lim: return False
    return True
def _style_of(mid,eid):
    """Стиль-вектор: обогащение (attrs, ADR-0071) первым, старый style-scores — фолбэк (06.08)."""
    try:
        import enrich_bridge as _EB
        sc=_EB.style_scores(mid,eid)
        if sc: return sc
    except Exception: pass  # noqa: BLE001 — нет БД/моста: работаем по старому файлу
    return SS.get(skey(mid,eid),{})
def best_alt(alts,style,set_i=None):
    """Запасной с максимальным стиль-скором под стиль сета (alts уже из нужного ценового сегмента);
    кандидаты, ломающие лимиты разнообразия, отбрасываются."""
    pool=[a for a in alts if set_i is None or _overlap_ok_swap(a,set_i)]
    if not pool: return None
    if not style: return pool[0]
    return sorted(pool,key=lambda a:-(_style_of(a['mid'],a['eid']).get(style,0) or 0))[0]
PSQL=["docker","exec","-i","remlab-devdb","psql","-U","remlab","-d","remlab","-q","-v","ON_ERROR_STOP=1","-t","-A","-F","\x1f"]
def thumb_path(mid,eid): return os.path.join(THUMBS,f"{mid}-{re.sub(r'[^A-Za-z0-9]','_',eid)[:40]}.png")
def fetch_alt(mid,eid):
    q=f"""select shop_mid, external_id, name, w_cm, d_cm, dia_cm, h_cm, price_rub, shop, image_url,
     replace(replace(replace(substring(url from 'goto=([^&]+)'),'%3A',':'),'%2F','/'),'%3F','?')
     from lr_roles where shop_mid={int(mid)} and external_id='{eid}' limit 1"""
    r=subprocess.run(PSQL,input=q,capture_output=True,text=True)
    ln=[l.split('\x1f') for l in r.stdout.strip().split('\n') if l]
    if not ln: return None
    x=ln[0]
    return dict(mid=int(x[0]),eid=x[1],name=x[2],w=float(x[3]) if x[3] else None,
                d=float(x[4]) if x[4] else None,dia=float(x[5]) if x[5] else None,
                h=float(x[6]) if x[6] else None,price=int(x[7]),shop=x[8],img=x[9],url=x[10],qty=1)
def collage(s):
    items=list(s['items'].items())
    cols=5; rows=(len(items)+cols-1)//cols; CW,CH=150,130
    im=Image.new('RGB',(cols*CW,rows*CH),(255,255,255)); dr=ImageDraw.Draw(im)
    for i,(role,it) in enumerate(items):
        x,y=(i%cols)*CW,(i//cols)*CH
        p=thumb_path(it['mid'],it['eid'])
        if os.path.exists(p):
            ph=Image.open(p).convert('RGB'); ph.thumbnail((CW-10,CH-32))
            im.paste(ph,(x+(CW-ph.width)//2,y+4))
        dr.text((x+4,y+CH-24),role[:18],fill=(0,0,0))
    buf=io.BytesIO(); im.save(buf,'JPEG',quality=85); return buf.getvalue()
def ask(s,jpg):
    b64=base64.b64encode(jpg).decode()
    c=s['capsule']
    listing="; ".join(f"{r}: {it['name'][:50]}" for r,it in s['items'].items())
    body={"model":"gpt-5-mini","messages":[{"role":"user","content":[  # reasoning дефолтный: качество вердикта важнее (решение владельца 2026-08-02); скорость дают 8 потоков
        {"type":"text","text":
         f"Ты опытный интерьерный дизайнер. Комплект для гостиной {s['m2']} м², сегмент «{s['tier']}». "
         f"Задуманная капсула: стиль {c.get('style') or 'любой'}, дерево {c.get('wood') or '—'}, "
         f"металл {c.get('metal') or '—'}, гамма {c.get('temp')}, акценты {'+'.join(s['pair'])}. "
         f"Состав: {listing}. На коллаже — фото предметов с подписями ролей. "
         +(f"ЗАЯВЛЕННЫЙ СТИЛЬ сета: «{s['style']}» — оцени отдельно, насколько АНСАМБЛЬ читается как этот "
           f"стиль (style_grade 1-10), и выбивающихся из СТИЛЯ отмечай в первую очередь. " if s.get('style') else "")+
         "Какие предметы ВЫБИВАЮТСЯ из ансамбля (цвет, стиль, форма, «дешёвый вид» на фоне остальных)? "
         "Строго не больше 3, только реально мешающие. Ответ STRICT JSON: "
         '{"grade":1-10,'+('"style_grade":1-10,' if s.get('style') else '')+'"outliers":[{"role":"роль как в списке","why":"коротко почему"}]}'},
        {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+b64}}]}]}
    req=urllib.request.Request("https://api.openai.com/v1/chat/completions",data=json.dumps(body).encode(),
        headers={"Authorization":f"Bearer {OAI}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r: out=json.loads(r.read())
    txt=out['choices'][0]['message']['content']
    m=re.search(r'\{.*\}',txt,re.S)
    try: return json.loads(m.group(0))
    except Exception: return {"grade":None,"outliers":[]}
report=[]
# вердикты параллельно (8 потоков; раньше последовательно — 126 сетов шли ~45 мин вместо ~6)
import concurrent.futures as _cf
with _cf.ThreadPoolExecutor(8) as _ex:
    _verdicts=list(_ex.map(lambda s: ask(s,collage(s)), sets))
for i,s in enumerate(sets):
    v=_verdicts[i]
    swaps=[]
    # стилевой сет с достойным style_grade не трогаем (порог); без стиля — старое поведение
    sg=v.get('style_grade')
    outliers=(v.get('outliers') or [])[:3]
    if s.get('style') and sg is not None and sg>=STYLE_THR: outliers=[]
    for o in outliers:
        role=o.get('role')
        alts=(s.get('alternates') or {}).get(role) or []
        ba=best_alt(alts,s.get('style'),set_i=i)
        if role in s['items'] and ba:
            alt=fetch_alt(ba['mid'],ba['eid'])
            if alt:
                old=s['items'][role]['name'][:45]
                keep_q=s['items'][role].get('qty',1)
                s['items'][role]=dict(alt,qty=keep_q,why=f"замена по вердикту дизайнера: {o.get('why','')[:80]}")
                swaps.append(f"{role}: {old} → {alt['name'][:45]}")
    s['total']=sum(it['price']*it.get('qty',1) for it in s['items'].values())
    report.append(dict(set=i+1,band=s['band'],tier=s['tier'],style=s.get('style'),
                       grade=v.get('grade'),style_grade=v.get('style_grade'),
                       outliers=v.get('outliers'),swaps=swaps))
    print(f"сет {i+1} ({s['band']} {s['tier']}{' '+s['style'] if s.get('style') else ''}): "
          f"оценка {v.get('grade')}"+(f", стиль {v.get('style_grade')}" if s.get('style') else "")+
          f", замен {len(swaps)}"+(": "+"; ".join(swaps) if swaps else ""),flush=True)
_tmp=os.path.join(HERE,SETS_FILE+'.tmp')
json.dump(sets,open(_tmp,'w'),ensure_ascii=False,indent=1); os.replace(_tmp,os.path.join(HERE,SETS_FILE))
json.dump(report,open(os.path.join(HERE,'judge-report3.json' if SETS_FILE=='sets3.json' else 'judge-report.json'),'w'),ensure_ascii=False,indent=1)
grades=[r['grade'] for r in report if r['grade']]
print(f"OK: средняя оценка дизайнера {sum(grades)/len(grades):.1f}/10, замен {sum(len(r['swaps']) for r in report)}")
