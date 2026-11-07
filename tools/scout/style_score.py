#!/usr/bin/env python3
"""Ф1 sets-style-v3: стиль-скоринг товаров гостиной (0–10 по каждому из 6 стилей).
Три ступени, от бесплатной к дешёвой:
  1) правила — style_tags + pos/neg-regex паспортов по name+params+description;
  2) CLIP zero-shot (fastembed, бесплатно) — косинус фото товара к текст-фразам стиля;
  3) LLM батчами по 25 (`STYLE_MODEL`, по умолчанию gpt-6-luna через шлюз) — основной сигнал (текст товара, БЕЗ фото).
Итог: style-scores.json {"mid-eid": {"сканди": 7.2, ..., "universal": true}}.
Кэш: повторный прогон скорит только новые товары (детерминизм и ноль лишних трат).
Запуск (venv!): ~/venvs/scout/bin/python style_score.py [--report] [--limit N] [--dry] [--source living|room_catalog]
--source room_catalog (onb-06 Т1) — товары спальни (кровать, тумба, шкаф, комод) из `room_catalog`: та же логика оценки, свой
пул, дедуп по семейству (без размера и цвета — `room_catalog.family`), файл ТОЛЬКО свой (`STYLE_OUT`, по умолчанию
style-scores-bedroom.json; живой style-scores.json — отказ), в базу — только с `--db` и без перезаписи чужих строк.
--dry — пул, сколько скорить и прикидка цены; без LLM и без записи.
ШУМ (T-20261105-24, `style_noise.py`): новая модель — среднее двух прогонов нейросети (дробный балл); оценённая (кэш или
база у близнеца модели) не пересчитывается — ни одного платного прогона ради старых; смена правил по материалу двигает итог
без прогона. --rescore — явный платный пересчёт оценённых: тройка меняется, только если новый балл обходит прежний ≥ 1,0.
--fresh — не брать оценки гостиной из базы (опыт с пересчётом впрок); STYLE_MODEL не по умолчанию — берём только свои.
--source hall (T-20261105-48/2) — товары ПРИХОЖЕЙ (`room_catalog` room='hall', условие показа `hall_catalog.shown_where`, все
роли `rules/hall-roles.json` roles_enabled): всё как у спальни — дедуп по семейству, оценка из базы у близнеца своей комнаты
без платы, файл только свой (`STYLE_OUT`, по умолчанию style-scores-hall.json), в базу — только `--db` без перезаписи чужих строк.
"""
import subprocess, sys, os, re, json, urllib.error, urllib.request
import numpy as np
from style_tags import tag

HERE=os.path.dirname(os.path.abspath(__file__))
STYLES=json.load(open(os.path.join(HERE,'styles.json')))['styles']
SNAMES=list(STYLES)  # порядок фиксирован
# STYLE_OUT — отдельный файл оценок для опытов (сравнение моделей, пересчёт впрок): пока дневной
# конвейер пишет свой style-scores.json, опыт считается рядом и подменяется одним mv, когда готов.
# Без этого два прогона затирали друг друга — оценки терялись молча (11.10).
SOURCE=sys.argv[sys.argv.index('--source')+1] if '--source' in sys.argv else 'living'
assert SOURCE in ('living','room_catalog','hall'), f"--source {SOURCE}: только living | room_catalog | hall"
ROOMS=('room_catalog','hall')   # источники комнат room_catalog: спальня и прихожая (одна логика, свой модуль правил)
OUT=os.path.join(HERE,os.environ.get('STYLE_OUT',{'living':'style-scores.json','hall':'style-scores-hall.json'}.get(SOURCE,'style-scores-bedroom.json')))
if SOURCE!='living' and os.path.basename(OUT)=='style-scores.json':
    sys.exit("СТОП: спальня в живой style-scores.json гостиной — задай свой STYLE_OUT")
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

def bedroom_raw():
    """Показываемые товары спальни (`room_catalog`, те же условия показа и флаг ролей, что у демо) в раскладке строк
    гостиной: роль, mid, eid, название, материал, цвет, обивка, стиль, описание (у room_catalog его нет), магазин.
    Детское общих ролей (`child_only`) — не спальня пары, не скорим."""
    import room_catalog as RC
    R=RC.rules()
    roles=[r for r in ('кровать','тумба прикроватная','шкаф','комод') if r in RC.enabled(R)]
    pj=lambda *ks: "coalesce("+",".join(f"params->>'{k}'" for k in ks)+",'')"
    out=rows(f"""select role, shop_mid, external_id, name,
 concat_ws(' / ', nullif({pj('Материал','Материал корпуса','Материал каркаса')},''), nullif({pj('Материал фасада')},''),
           nullif({pj('Материал ножек (опор)')},'')),
 {pj('Цвет','Цвет основной')}, {pj('Материал обивки','Обивка: Ткань 1','Обивка')}, {pj('Стиль')}, '', shop
 from room_catalog where {RC.shown_where(R)} and role in ({','.join(RC._lit(r) for r in roles)})
 order by shop_mid, external_id""")
    return [r for r in out if not RC.child_only(r[0], r[3], R)]

def hall_raw():
    """Показываемые товары прихожей (`room_catalog` room='hall', `hall_catalog.shown_where` — как адаптер `catalog_items`),
    все роли `roles_enabled`, в раскладке строк спальни. Фильтра детского нет — адаптер прихожей его тоже не ставит."""
    import room_catalog as RC, hall_catalog as HC
    R=HC.rules()
    roles=RC.enabled(R)
    pj=lambda *ks: "coalesce("+",".join(f"params->>'{k}'" for k in ks)+",'')"
    return rows(f"""select role, shop_mid, external_id, name,
 concat_ws(' / ', nullif({pj('Материал','Материал корпуса','Материал каркаса')},''), nullif({pj('Материал фасада')},''),
           nullif({pj('Материал ножек (опор)')},'')),
 {pj('Цвет','Цвет основной')}, {pj('Материал обивки','Обивка: Ткань 1','Обивка')}, {pj('Стиль')}, '', shop
 from room_catalog where {HC.shown_where(R)} and role in ({','.join(RC._lit(r) for r in roles)})
 order by shop_mid, external_id""")

# ПРАВИЛА ПО МАТЕРИАЛУ — только спальня (`rules/bedroom-roles.json` style_material_rules; гостиная их не читает)
MRULES=[]
if SOURCE=='room_catalog':
    import room_catalog as _RC
    MRULES=_RC.rules().get('style_material_rules',[])
elif SOURCE=='hall':   # у прихожей правил по материалу нет (rules/hall-roles.json) — список пуст, модуль нужен для ROOM
    import hall_catalog as _RC
    MRULES=_RC.rules().get('style_material_rules',[])
def mfired(p):
    """id сработавших правил по материалу: материал из фида, цвет и название — чтобы золото/хром не ушли в лофт."""
    return [r['id'] for r in MRULES if re.search(r['mat'],p['mat'],re.I) and not re.search(r['not'],p['mat'],re.I)
            and not re.search(r['not_col'],p['col']+' '+p['name'],re.I) and re.search(r.get('col',''),p['col']+' '+p['name'],re.I)]

if SOURCE=='room_catalog':
    print("Каталог спальни (room_catalog)...",flush=True)
    raw=bedroom_raw()
    assert len(raw)>500, f"каталог спальни вернул {len(raw)} строк — SQL сломан, СТОП"
elif SOURCE=='hall':
    print("Каталог прихожей (room_catalog room='hall')...",flush=True)
    raw=hall_raw()
    assert len(raw)>300, f"каталог прихожей вернул {len(raw)} строк — SQL сломан, СТОП"
else:
  print("Каталог гостиной...",flush=True)
  raw=rows("""select l.role, l.shop_mid, l.external_id, l.name,
 coalesce(p.params->>'Материал',''), coalesce(p.params->>'Цвет',''), coalesce(p.params->>'Обивка',''),
 coalesce(p.params->>'Стиль',''),
 case when count(*) over (partition by p.shop_mid, p.description) > 5 then ''  -- шаблонка (один текст у >5 товаров) — не сигнал, в LLM не подаём
      else coalesce(left(p.description,220),'') end, l.shop
 from lr_roles l join products p using (shop_mid, external_id)
 where l.role is not null and l.price_rub is not null and l.image_url is not null and p.in_stock
   and coalesce(p.photo_alive, true)  -- фото реально скачивается (conv-05, catalog_rules.PHOTO_OK_SQL)
 order by l.shop_mid, l.external_id""")
  assert len(raw)>1000, f"каталог-запрос вернул {len(raw)} строк — SQL сломан, СТОП"
if SOURCE in ROOMS:
    # модель спальни = семейство: «Кровать divan.ru Кейт 140 Велюр Серый» и «… Кейт 160 Букле Бежевый» — одна (размер и
    # цвет стиля не меняют); model_key гостиной оставляет размер — платили бы за каждый
    from room_catalog import family as _family
    model_key=lambda name: _family(name)  # noqa: E731
pool={}
# БЛИЗНЕЦЫ МОДЕЛИ. Скорим один товар на модель (дедуп по model_key — цвета и обивки одной модели
# стилистически одинаковы и платить за них отдельно незачем), но в БАЗУ оценка едет ВСЕМ товарам
# модели: иначе в витрине `catalog_ready` 4 491 товар выглядел бы «ждёт стиль», хотя стиль у его
# модели посчитан (11.10).
twins={}
for r in raw:
    k=(r[9],model_key(r[3]))
    twins.setdefault(k,[]).append((int(r[1]),r[2]))
    if k in pool: continue
    pool[k]=dict(role=r[0],mid=int(r[1]),eid=r[2],name=r[3],mat=r[4],col=r[5],uph=r[6],stp=r[7],desc=r[8],mkey=k)
prods=list(pool.values())
STYLE_MODEL=os.environ.get("STYLE_MODEL","gpt-6-luna")
RUNS=2   # прогонов нейросети на новую модель: среднее двух гасит скачок ±1 целого балла (T-20/2)
from style_noise import avg_runs, settle, rule_shift

# ---------- ступень 1: правила (выше переиспользования: смена правил по материалу считается без прогона) ----------
def rule_score(p, fired=None):
    """fired — id правил по материалу; по умолчанию сработавшие сейчас, прежний список — для сдвига без прогона."""
    fired=mfired(p) if fired is None else fired
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
    for r in MRULES:
        if r['id'] in fired:
            for st,v in r['add'].items(): out[st]+=v
    return out

key=lambda p: f"{p['mid']}-{re.sub(r'[^A-Za-z0-9]','_',p['eid'])[:40]}"
reused=0; shifted=0; scored_now=[]
def put_rules(p, prev, old):
    """Правила по материалу сменились (old → сейчас): итог сдвигается на разницу правил, нейросеть не зовём (T-24;
    раньше запись удалялась и модель шла на платный пересчёт — новый шум ±1 вместо старой оценки)."""
    f=mfired(p)
    rec=rule_shift(prev, rule_score(p, old), rule_score(p, f), SNAMES)
    rec.pop('mrules',None)
    if f: rec['mrules']=f
    cache[key(p)]=rec
    for tw in twins.get(p['mkey'],[(p['mid'],p['eid'])]): scored_now.append((*tw,rec))
if SOURCE in ROOMS:
    # товар спальни уже оценён как товар гостиной (комод, шкаф есть в обоих каталогах) — та же оценка, без платы и без
    # расхождения: берём её у любого близнеца модели из базы (только чтение)
    # только товары СВОЕЙ комнаты (`catalog_rules.twin_scores_sql`): строки прихожей сюда не попадают (T-20261105-34/2)
    from catalog_rules import twin_scores_sql
    have={(int(r[0]),r[1]):r for r in rows(twin_scores_sql(_RC.ROOM))}
    for p in prods:
        f=mfired(p); c=cache.get(key(p))
        if c is not None:
            # сработало правило по материалу, а запись посчитана без него (или с другим) — сдвиг без прогона; правило
            # перестало срабатывать — запись не трогаем, как и раньше
            if f and c.get('mrules',[])!=f: put_rules(p, c, c.get('mrules',[])); shifted+=1
            continue
        hit=next((have[t] for t in twins[p['mkey']] if t in have), None)
        if hit:
            sc=json.loads(hit[2])
            rec={**{st:sc[st] for st in SNAMES},'universal':hit[3]=='t','src':'living:'+hit[4]}
            # у гостиной правил по материалу нет — сработало правило спальни: оценка гостиной + сдвиг на правило
            if f: put_rules(p, rec, []); shifted+=1
            else: cache[key(p)]=rec
            reused+=1
elif '--fresh' not in sys.argv:
    # ГОСТИНАЯ: модель уже оценена в базе у близнеца (представитель модели сменился — первый товар ушёл из наличия, или
    # кэш потерян) — та же оценка без платы. Опыт с другой моделью (STYLE_MODEL задан) берёт только строки своей модели.
    miss=[p for p in prods if key(p) not in cache]
    if miss:
        own=" where model='"+STYLE_MODEL.replace("'","''")+"'" if os.environ.get('STYLE_MODEL') else ''
        have={(int(r[0]),r[1]):r for r in rows("select shop_mid, external_id, scores, universal, src from product_style_scores"+own)}
        for p in miss:
            tws=twins[p['mkey']]
            hit=next((have[t] for t in tws if t in have), None)
            if not hit: continue
            sc=json.loads(hit[2])
            rec={**{st:sc[st] for st in SNAMES},'universal':hit[3]=='t','src':hit[4]}
            cache[key(p)]=rec; reused+=1
            # близнецы модели без строки в базе (новый цвет) получают ту же оценку
            scored_now+=[(*t,rec) for t in tws if t not in have]
# --rescore — явный платный пересчёт оценённых: прежняя оценка держит тройку (порог `style_noise.settle`)
prev_of={key(p):cache[key(p)] for p in prods if key(p) in cache} if '--rescore' in sys.argv else {}
todo=[p for p in prods if key(p) not in cache or key(p) in prev_of]
# --limit — ПОТОЛОК ДНЕВНОЙ ДОБИВКИ, а не обрезка пула (11.10). Раньше лимит резал начало `prods`,
# а начало пула давно в кэше: `--limit 300` на полном кэше давало «скорить 0» — дневной шаг месяцами
# ничего не добивал, и это выглядело как «всё уже посчитано». Режем именно несосчитанные.
if '--limit' in sys.argv:
    LIMIT=int(sys.argv[sys.argv.index('--limit')+1])
    # Само правило — в `catalog_rules.daily_todo`: оттуда его проверяет `tests_chain.py` тем же
    # кодом, что работает в бою (13.10). Здесь остаётся только сообщение человеку.
    from catalog_rules import daily_todo
    if len(todo)>LIMIT:
        print(f"дневной потолок {LIMIT}: из {len(todo)} несосчитанных беру первые {LIMIT}",flush=True)
    todo=daily_todo(todo, LIMIT)
print(f"пул {len(prods)} (дедуп из {len(raw)}), в кэше {len(prods)-len([p for p in prods if key(p) not in cache])}, скорить {len(todo)}"
      +(f" (пересчёт оценённых: {len(prev_of)})" if prev_of else ""),flush=True)
if reused: print(f"из базы (модель уже оценена у близнеца): {reused}",flush=True)
if shifted: print(f"сменились правила по материалу — сдвиг без прогона: {shifted}",flush=True)
from openai_budget import allow as _budget_allow, estimate_request as _est, log_spend as _log_spend
if '--dry' in sys.argv:
    nb=-(-len(todo)//25)*RUNS
    print(f"СУХОЙ ПРОГОН: моделей {len(prods)}, скорить {len(todo)} — {nb} запросов ({RUNS} прогона на партию) {STYLE_MODEL} ≈ ${nb*_est(STYLE_MODEL):.3f} "
          f"(оценка по типовым токенам rules/openai_prices.json); без LLM и без записи",flush=True)
    if SOURCE in ROOMS:
        by={}
        for p in prods: by[p['role']]=by.get(p['role'],0)+1
        print("моделей по ролям:", by, flush=True)
    sys.exit(0)

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

# ---------- ступень 3: LLM (`STYLE_MODEL`) батчами (основной сигнал) ----------
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
    # gpt-6-luna вместо gpt-5.6-luna — бенч 11.10 на 180 товарах (решение владельца, ADR-0231):
    # главный стиль совпал у 63%, средняя разница 1.05 балла из 10 — та же полоса равенства, что
    # и в августе. Ручная сверка 30 товаров по фото: новая лучше у 7 (узнаёт неоклассику в
    # хрустале и завитках, где старая говорила «современный»), хуже у 2, вровень 21. Замер цены
    # на батче 25: $0.024 против $0.052 за 1000 товаров, скорость та же (~8 с на батч).
    body={"model":os.environ.get("STYLE_MODEL","gpt-6-luna"),"reasoning_effort":"low",
          "messages":[{"role":"user","content":txt}]}
    # Канал по умолчанию — Vercel AI Gateway, фолбэк — OpenAI (правило владельца 29.08,
    # ADR-0181): прямые кредиты OpenAI кончились молча, и добивка стилей встала при живых
    # кредитах на шлюзе. Повтор на 429 внутри chat() — молчаливая деградация до
    # «правила+CLIP» уже портила кэш.
    from llm_gateway import chat as _chat
    out=_chat(body["model"], body["messages"], reasoning_effort=body.get("reasoning_effort","low"))
    _log_spend(body["model"], out.get('usage'), 1, f'style_score {SOURCE}')   # учёт: openai_budget (урок 462)
    m=re.search(r'\{.*\}',out['choices'][0]['message']['content'],re.S)
    items=json.loads(m.group(0))['items']
    res={}
    for it in items:
        if not isinstance(it,dict) or 'i' not in it: continue
        i=int(it['i'])
        if 0<=i<len(batch):
            res[i]={RSH[s]:float(it.get(s,5)) for s in SH.values()} | {'universal':bool(it.get('u'))}
    return res

# ОЦЕНКИ ЕДУТ И В БАЗУ (11.10). Файл — кэш прогона, но связать стиль с мешем одним запросом по
# нему нельзя: ключ `mid-eid` теряет символы (`[^A-Za-z0-9]→_`). В базе ключ тот же, что у товара,
# поэтому витрина `catalog_ready` показывает рядом роль, стиль, размеры и ссылку на меш.
def save_to_db(rows, keep=False):
    """keep — не перезаписывать уже записанные оценки (спальня: строки гостиной не трогаем)."""
    if not rows: return 0
    esc=lambda x: str(x).replace("'","''")
    model=os.environ.get("STYLE_MODEL","gpt-6-luna")
    n=0
    for i in range(0,len(rows),1000):
        vals=[]
        for mid,eid,rec in rows[i:i+1000]:
            sc={st:rec[st] for st in SNAMES}
            top=max(sc,key=sc.get)
            vals.append(f"({int(mid)},'{esc(eid)}','{esc(json.dumps(sc,ensure_ascii=False))}','{esc(top)}',"
                        f"{str(bool(rec['universal'])).lower()},'{esc(rec['src'])}','{esc(model)}',now())")
        sql=("insert into product_style_scores (shop_mid, external_id, scores, top_style, universal, src, model, scored_at)"
             " values "+",".join(vals)+
             (" on conflict (shop_mid, external_id) do nothing" if keep else
             " on conflict (shop_mid, external_id) do update set scores=excluded.scores,"
             " top_style=excluded.top_style, universal=excluded.universal, src=excluded.src,"
             " model=excluded.model, scored_at=excluded.scored_at"))
        r=subprocess.run(PSQL,input=sql,capture_output=True,text=True)
        if r.returncode:
            print(f"WARN:style_db: оценки не записаны в базу — {r.stderr[:160]}",flush=True); return n
        n+=len(vals)
    return n

import concurrent.futures as cf, threading
B=25; done=0; fails=0; half=0; held=0; _lock=threading.Lock()
batches=[todo[bi:bi+B] for bi in range(0,len(todo),B)]
# ДНЕВНОЙ ЛИМИТ ДЕНЕГ (урок 462): до первого платного запроса; нет — ничего не отправляем, кэш как был
if batches and not _budget_allow(STYLE_MODEL, len(batches)*RUNS, note=f'style_score {SOURCE} {len(todo)} моделей'):
    print("СТОП: дневной лимит OpenAI — стили не считаю",flush=True); sys.exit(2)
def run_batch(batch):
    """RUNS прогонов одной партии → среднее (`style_noise.avg_runs`); упал один — берём ответ второго (счёт `__single`)."""
    outs=[]; err=''
    for _ in range(RUNS):
        try: outs.append(llm_batch(batch))
        except Exception as e:
            # НЕТ ДЕНЕГ НА КАНАЛАХ LLM (13.10) — не «отказ партии»: фолбэк «правила+CLIP» лёг бы в кэш НАВСЕГДА
            # (кэш не пересчитывается), и каждую ночь без кредитов портил бы оценки. Стоп без записи.
            if type(e).__name__=='NoCredits': return batch,{'__nocredit':str(e)[:160]}
            outs.append({}); err=str(e)[:80]
    if not any(outs): return batch,{'__err':err}
    avg,single=avg_runs(outs,len(batch),SNAMES)
    return batch,{**avg,'__single':single}
_pool=cf.ThreadPoolExecutor(8)
for batch,llm in _pool.map(run_batch,batches):
    if '__nocredit' in llm:
        print(f"WARN:llm_no_credits: {llm['__nocredit']} — стили новых товаров не считаю, кэш не трогаю",flush=True)
        break
    if '__err' in llm:
        print(f"LLM fail {llm['__err']} — правила+CLIP",flush=True); llm={}; fails+=1
        if fails>15: print("слишком много отказов LLM — СТОП, кэш сохранён"); break
    half+=llm.pop('__single',0)
    for i,p in enumerate(batch):
        rs=rule_score(p); cs=clip_score(p)
        base=llm.get(i)
        if base:
            fin={st:max(0,min(10, base[st] + rs[st]*0.5 + cs.get(st,0)*0.5)) for st in SNAMES}
            fin['universal']=base['universal']; src='llm+rules+clip' if cs else 'llm+rules'
        else:  # фолбэк без LLM: правила+CLIP вокруг нейтральной 5
            fin={st:max(0,min(10, 5 + rs[st] + cs.get(st,0)*1.5)) for st in SNAMES}
            fin['universal']=all(abs(v-5)<1.2 for k,v in fin.items() if k!='universal'); src='rules+clip'
        rec={**{st:round(fin[st],1) for st in SNAMES},'universal':fin['universal'],'src':src}
        if mfired(p): rec['mrules']=mfired(p)
        rec,h=settle(prev_of.get(key(p)), rec, SNAMES); held+=h
        cache[key(p)]=rec
        for tw_mid,tw_eid in twins.get(p['mkey'],[(p['mid'],p['eid'])]):
            scored_now.append((tw_mid,tw_eid,rec))
    done+=len(batch)
    if done%1000<B:
        with _lock: json.dump(cache,open(OUT,'w'),ensure_ascii=False)
        print(f"{done}/{len(todo)}...",flush=True)
json.dump(cache,open(OUT,'w'),ensure_ascii=False)
print(f"OK: {os.path.basename(OUT)} — {len(cache)} товаров; отказов LLM (партий): {fails}; с одним ответом из {RUNS}: {half}"
      +(f"; пересчёт: тройка удержана порогом у {held}" if prev_of else ""),flush=True)
if SOURCE=='living':
    print(f"OK: в базу записано оценок — {save_to_db(scored_now)}",flush=True)
elif '--db' in sys.argv and SOURCE=='hall' and fails:
    # запись в базу без перезаписи (keep): фолбэк «правила+CLIP» лёг бы туда навсегда — следующий прогон его не исправит
    print(f"СТОП база: отказов LLM {fails} — оценки прихожей остались только в {os.path.basename(OUT)}, в базу не пишу",flush=True)
elif '--db' in sys.argv and SOURCE=='hall':
    print(f"OK: в базу записано оценок прихожей (чужие строки не трогаем) — {save_to_db(scored_now, keep=True)}",flush=True)
elif '--db' in sys.argv:
    print(f"OK: в базу записано оценок спальни (чужие строки не трогаем) — {save_to_db(scored_now, keep=True)}",flush=True)
else:
    print("база: "+("прихожая" if SOURCE=='hall' else "спальня")+" не пишется без --db",flush=True)

# ---------- отчёт покрытия: товаров «в стиле» на стиль × роль ----------
# правило «в стиле» — ОДНО со сборщиками и квотой мешей (room_profile.in_style, T-20261106-90): балл ≥ in_style_min (6,6,
# rules/demo-swap.json); universal сам по себе не засчитывается (раньше здесь было «≥ 6,5 или universal» — отчёт расходился с квотой)
if '--report' in sys.argv or True:
    import room_profile as _RP
    THR=float(json.load(open(os.path.join(HERE,'rules','demo-swap.json')))['in_style_min'])
    CORE=['диван','столик','тв-тумба','ковёр','люстра','плед','подушка','кресло','торшер','лампа','кашпо','ваза','комод','стеллаж','пуф']
    if SOURCE=='room_catalog': CORE=['кровать','тумба прикроватная','шкаф','комод']
    if SOURCE=='hall': CORE=['шкаф-купе','шкаф','прихожая','обувница','банкетка','консоль','вешалка','зеркало']
    print(f"\nПокрытие (товаров «в стиле»: балл ≥ {THR:g}, universal не в счёт), ядро "+{'living':"гостиной:",'hall':"прихожей (моделей):"}.get(SOURCE,"спальни (моделей):"))
    hdr="роль".ljust(12)+"".join(st[:7].ljust(9) for st in SNAMES)
    print(hdr)
    gaps={st:[] for st in SNAMES}
    for role in CORE:
        cnt={st:0 for st in SNAMES}
        for p in prods:
            c=cache.get(key(p))
            if not c or p['role']!=role: continue
            for st in SNAMES:
                if _RP.in_style(c, st, THR): cnt[st]+=1
        print(role.ljust(12)+"".join(str(cnt[st]).ljust(9) for st in SNAMES))
        for st in SNAMES:
            if cnt[st]==0: gaps[st].append(role)
    for st in SNAMES:
        if gaps[st]: print(f"ДЫРКИ {st}: {', '.join(gaps[st])}")
