#!/usr/bin/env python3
"""Ф1 sets-style-v3: стиль-скоринг товаров гостиной (0–10 по каждому из 6 стилей).
Три ступени, от бесплатной к дешёвой:
  1) правила — style_tags + pos/neg-regex паспортов по name+params+description;
  2) CLIP zero-shot (fastembed, бесплатно) — косинус фото товара к текст-фразам стиля;
  3) gpt-5-mini батчами по 25 — основной сигнал (текст товара, БЕЗ фото).
Итог: style-scores.json {"mid-eid": {"сканди": 7.2, ..., "universal": true}}.
Кэш: повторный прогон скорит только новые товары (детерминизм и ноль лишних трат).
Запуск (venv!): ~/venvs/scout/bin/python style_score.py [--report] [--limit N]
"""
import subprocess, sys, os, re, json, urllib.error, urllib.request
import numpy as np
from style_tags import tag

HERE=os.path.dirname(os.path.abspath(__file__))
STYLES=json.load(open(os.path.join(HERE,'styles.json')))['styles']
SNAMES=list(STYLES)  # порядок фиксирован
OUT=os.path.join(HERE,'style-scores.json')
cache=json.load(open(OUT)) if os.path.exists(OUT) else {}
# Ключ — общим резолвером (свой .env первым): жёсткий путь в чужой проект умер молча,
# и добивка 29.08 прошла с 401 — записи легли «правила+CLIP» без LLM вообще.
from golden_label import _key as _oai_key
OAI=_oai_key()

PSQL=["docker","exec","-i","remlab-devdb","psql","-U","remlab","-d","remlab","-q","-v","ON_ERROR_STOP=1","-t","-A","-F","\x1f"]
def rows(q):
    r=subprocess.run(PSQL,input=q,capture_output=True,text=True)
    if r.returncode!=0: print(r.stderr[:400]); sys.exit(1)
    return [l.split('\x1f') for l in r.stdout.strip().split('\n') if l]

# тот же дедуп, что в compose2 (model_key): скорим то, из чего реально собираем
STOP=re.compile(r'\b(беж\w*|сер\w*|син\w*|зел[её]н\w*|коричн\w*|ч[её]рн\w*|бел\w*|графит\w*|латте|мокко|изумруд\w*|горчичн\w*|пудр\w*|роз\w*|голуб\w*|фиолет\w*|бордо\w*|венге|дуб\s?\w*|орех\w*|ясень|сонома|капучино|шоколад\w*|молочн\w*|крем\w*|песочн\w*|терракот\w*|оливк\w*|мятн\w*|лаванд\w*|карбон|антрацит|жемчужн\w*|сливов\w*|вельвет\w*|велюр\w*|шенилл\w*|рогожк\w*|экокож\w*|микровелюр\w*|правый|левый|угол|бархат\w*|тёмн\w*|темн\w*|светл\w*|глосс|люкс|найс|плюш\w*)\b', re.I)
def model_key(name):
    n=STOP.sub(' ', name.lower()); n=re.sub(r'[^а-яa-z0-9 ]',' ',n)
    return ' '.join(re.sub(r'\s+',' ',n).strip().split()[:6])

print("Каталог гостиной...",flush=True)
raw=rows("""select l.role, l.shop_mid, l.external_id, l.name,
 coalesce(p.params->>'Материал',''), coalesce(p.params->>'Цвет',''), coalesce(p.params->>'Обивка',''),
 coalesce(p.params->>'Стиль',''),
 case when count(*) over (partition by p.shop_mid, p.description) > 5 then ''  -- шаблонка (один текст у >5 товаров) — не сигнал, в LLM не подаём
      else coalesce(left(p.description,220),'') end, l.shop
 from lr_roles l join products p using (shop_mid, external_id)
 where l.role is not null and l.price_rub is not null and l.image_url is not null and p.in_stock
 order by l.shop_mid, l.external_id""")
assert len(raw)>1000, f"каталог-запрос вернул {len(raw)} строк — SQL сломан, СТОП"
pool={}
for r in raw:
    k=(r[9],model_key(r[3]))
    if k in pool: continue
    pool[k]=dict(role=r[0],mid=int(r[1]),eid=r[2],name=r[3],mat=r[4],col=r[5],uph=r[6],stp=r[7],desc=r[8])
prods=list(pool.values())
if '--limit' in sys.argv: prods=prods[:int(sys.argv[sys.argv.index('--limit')+1])]
key=lambda p: f"{p['mid']}-{re.sub(r'[^A-Za-z0-9]','_',p['eid'])[:40]}"
todo=[p for p in prods if key(p) not in cache]
print(f"пул {len(prods)} (дедуп из {len(raw)}), в кэше {len(prods)-len(todo)}, скорить {len(todo)}",flush=True)

# ---------- ступень 1: правила ----------
def rule_score(p):
    txt=' '.join((p['name'],p['mat'],p['uph'],p['stp'],p['desc'])).lower()
    t=tag(p['name'])
    out={}
    for st in SNAMES:
        sc=STYLES[st]['score']; s=0.0
        if re.search(sc['pos'],txt): s+=2.5
        if re.search(sc['neg'],txt): s-=2.5
        for dim in ('wood','metal','fabric'):
            v=t.get(dim)
            if v and v in sc.get(dim,{}): s+=sc[dim][v]*0.6
        if t.get('style'):
            s+= 2.0 if t['style']==st else 0.0
        out[st]=s
    return out

# ---------- ступень 2: CLIP zero-shot (бесплатно, по кэшу фото-векторов) ----------
EMB=os.path.join(HERE,'embeddings.npz')
_img={}
if os.path.exists(EMB):
    z=np.load(EMB); _img={k:z[k] for k in z.files}
_txt=None
def clip_scores():
    global _txt
    try:
        from fastembed import TextEmbedding
        tm=TextEmbedding('Qdrant/clip-ViT-B-32-text',cache_dir=os.path.expanduser('~/.cache/fastembed'))
        phrases=[ph for st in SNAMES for ph in STYLES[st]['clip']]
        vecs=list(tm.embed(phrases))
        _txt={}
        i=0
        for st in SNAMES:
            n=len(STYLES[st]['clip'])
            m=np.mean([np.asarray(v,dtype=np.float32) for v in vecs[i:i+n]],axis=0); i+=n
            _txt[st]=m/ (np.linalg.norm(m)+1e-8)
        return True
    except Exception as e:
        print("CLIP text недоступен, ступень 2 пропущена:",str(e)[:120],flush=True)
        return False
HAVE_CLIP=clip_scores()
def clip_score(p):
    if not HAVE_CLIP: return {}
    v=_img.get(key(p))
    if v is None: return {}
    v=v.astype(np.float32); v/=(np.linalg.norm(v)+1e-8)
    cs={st:float(np.dot(v,_txt[st])) for st in SNAMES}
    lo,hi=min(cs.values()),max(cs.values())
    if hi-lo<1e-6: return {}
    return {st:(c-lo)/(hi-lo)*2-1 for st,c in cs.items()}  # относительная шкала −1..+1

# ---------- ступень 3: gpt-5-mini батчами (основной сигнал) ----------
SH={'сканди':'sk','современный':'sv','минимализм':'mn','лофт':'lf','неоклассика':'nk','джапанди':'jp'}
RSH={v:k for k,v in SH.items()}
def llm_batch(batch):
    lines=[]
    for i,p in enumerate(batch):
        extra='; '.join(x for x in (p['mat'],p['uph'],p['col'],p['stp']) if x)[:110]
        d=p['desc'][:130]
        lines.append(f"{i}. [{p['role']}] {p['name'][:90]}"+(f" ({extra})" if extra else "")+(f" — {d}" if d else ""))
    txt=("Ты интерьерный дизайнер. Оцени КАЖДЫЙ товар: насколько он уместен в каждом стиле, 0-10 "
     "(0 — противоречит стилю, 5 — нейтрален, 10 — икона стиля). Стили: sk=сканди(светлое дерево, "
     "простые формы), sv=современный(чистые линии, нейтраль+акцент), mn=мягкий минимализм(гладкое, "
     "монохром), lf=лофт(чёрный металл, бетон, тёмное дерево), nk=неоклассика(классические силуэты, "
     "латунь, бархат, симметрия), jp=джапанди(низкие силуэты, тёплый монохром, натуральные материалы, "
     "ротанг). u=true если товар стилистически нейтральный (впишется куда угодно, стиля не создаёт). "
     "Суди по названию, материалу и описанию. Ответ STRICT JSON: "
     '{"items":[{"i":0,"sk":5,"sv":5,"mn":5,"lf":5,"nk":5,"jp":5,"u":false},...]} — ровно '
     f"{len(batch)} элементов.\nТовары:\n"+"\n".join(lines))
    # reasoning low: длинные рассуждения не нужны для тегирования, выходные токены ×3-4 дешевле
    # (замер 2026-08-02: с дефолтным reasoning 3200 из 4014 токенов ответа — «думающие»)
    # luna вместо mini — бенч 29.08 на комплекте №1 (13 товаров, style_model_bench.py):
    # ответы совпадают в пределах ~1 балла, на спорной лампе luna точнее terra (та увидела
    # неоклассику в плетёной керамике), а стоит вызов в 2.6 раза дешевле ($0.0010 против $0.0026).
    body={"model":os.environ.get("STYLE_MODEL","gpt-5.6-luna"),"reasoning_effort":"low",
          "messages":[{"role":"user","content":txt}]}
    # Канал по умолчанию — Vercel AI Gateway, фолбэк — OpenAI (правило владельца 29.08,
    # ADR-0181): прямые кредиты OpenAI кончились молча, и добивка стилей встала при живых
    # кредитах на шлюзе. Повтор на 429 внутри chat() — молчаливая деградация до
    # «правила+CLIP» уже портила кэш.
    from llm_gateway import chat as _chat
    out=_chat(body["model"], body["messages"], reasoning_effort=body.get("reasoning_effort","low"))
    m=re.search(r'\{.*\}',out['choices'][0]['message']['content'],re.S)
    items=json.loads(m.group(0))['items']
    res={}
    for it in items:
        if not isinstance(it,dict) or 'i' not in it: continue
        i=int(it['i'])
        if 0<=i<len(batch):
            res[i]={RSH[s]:float(it.get(s,5)) for s in SH.values()} | {'universal':bool(it.get('u'))}
    return res

import concurrent.futures as cf, threading
B=25; done=0; fails=0; _lock=threading.Lock()
batches=[todo[bi:bi+B] for bi in range(0,len(todo),B)]
def run_batch(batch):
    try: return batch,llm_batch(batch)
    except Exception as e: return batch,{'__err':str(e)[:80]}
_pool=cf.ThreadPoolExecutor(8)
for batch,llm in _pool.map(run_batch,batches):
    if '__err' in llm:
        print(f"LLM fail {llm['__err']} — правила+CLIP",flush=True); llm={}; fails+=1
        if fails>15: print("слишком много отказов LLM — СТОП, кэш сохранён"); break
    for i,p in enumerate(batch):
        rs=rule_score(p); cs=clip_score(p)
        base=llm.get(i)
        if base:
            fin={st:max(0,min(10, base[st] + rs[st]*0.5 + cs.get(st,0)*0.5)) for st in SNAMES}
            fin['universal']=base['universal']; src='llm+rules+clip' if cs else 'llm+rules'
        else:  # фолбэк без LLM: правила+CLIP вокруг нейтральной 5
            fin={st:max(0,min(10, 5 + rs[st] + cs.get(st,0)*1.5)) for st in SNAMES}
            fin['universal']=all(abs(v-5)<1.2 for k,v in fin.items() if k!='universal'); src='rules+clip'
        cache[key(p)]={**{st:round(fin[st],1) for st in SNAMES},'universal':fin['universal'],'src':src}
    done+=len(batch)
    if done%1000<B:
        with _lock: json.dump(cache,open(OUT,'w'),ensure_ascii=False)
        print(f"{done}/{len(todo)}...",flush=True)
json.dump(cache,open(OUT,'w'),ensure_ascii=False)
print(f"OK: style-scores.json — {len(cache)} товаров",flush=True)

# ---------- отчёт покрытия: товаров с фитом ≥6.5 на стиль × роль ----------
if '--report' in sys.argv or True:
    CORE=['диван','столик','тв-тумба','ковёр','люстра','плед','подушка','кресло','торшер','лампа','кашпо','ваза','комод','стеллаж','пуф']
    print("\nПокрытие (товаров со стиль-фитом ≥6.5), ядро гостиной:")
    hdr="роль".ljust(12)+"".join(st[:7].ljust(9) for st in SNAMES)
    print(hdr)
    gaps={st:[] for st in SNAMES}
    for role in CORE:
        cnt={st:0 for st in SNAMES}
        for p in prods:
            c=cache.get(key(p))
            if not c or p['role']!=role: continue
            for st in SNAMES:
                if c[st]>=6.5 or c['universal']: cnt[st]+=1
        print(role.ljust(12)+"".join(str(cnt[st]).ljust(9) for st in SNAMES))
        for st in SNAMES:
            if cnt[st]==0: gaps[st].append(role)
    for st in SNAMES:
        if gaps[st]: print(f"ДЫРКИ {st}: {', '.join(gaps[st])}")
