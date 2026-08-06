#!/usr/bin/env python3
"""Ф1 catalog-freshness: свежие фиды (feeds2/*.zip) → upsert в products.
- direct_url: полноценный unquote goto= (бага %21 закрыта);
  mnogomebeli/divanboss: SPA-карточки 404 → режем до живого уровня (серия).
- Товары магазинов свежих фидов, ИСЧЕЗНУВШИЕ из фида → in_stock=false (снят с продажи).
- Магазины без свежего фида (nonton, h-f-l) не трогаем — наличие проверит health-цикл.
Запуск: python3 load3.py"""
import zipfile, glob, os, re, sys, json, subprocess, urllib.parse, hashlib
import xml.etree.ElementTree as ET

HERE=os.path.dirname(os.path.abspath(__file__))
FEEDS=os.path.join(HERE,'feeds2')
PSQL=["docker","exec","-i","remlab-devdb","psql","-U","remlab","-d","remlab","-q","-v","ON_ERROR_STOP=1"]
def sql(q,inp=None):
    r=subprocess.run(PSQL,input=inp if inp is not None else q,capture_output=True,text=True)
    if r.returncode!=0: print(r.stderr[:600]); sys.exit(1)
    return r.stdout
def esc(v):
    if v is None: return r'\N'
    return str(v).replace('\\','\\\\').replace('\t','\\t').replace('\n','\\n').replace('\r',' ')

sql("alter table products add column if not exists direct_url text;"
    "alter table products add column if not exists last_seen date;"
    "alter table products add column if not exists description text;")

# --- дельта: ЧТО именно изменилось у товара (ADR-0068) ---------------------------------------
# Раньше признаком изменения был сам факт присутствия в фиде, поэтому «пересчитывать или нет»
# решалось грубо: цена сдвинулась на рубль — и товар считался новым для всей семантики.
# Три дешёвых хеша считаются прямо при разборе; четвёртый (перцептивный, по самой картинке) —
# отдельно в `phash.py`, он требует скачивания файла.
_WS=re.compile(r'\s+')
def _h(*parts):
    s='\x1f'.join('' if p is None else str(p) for p in parts)
    return hashlib.sha1(s.encode('utf-8')).hexdigest()[:20]
def _norm(t):
    return _WS.sub(' ',(t or '').strip().lower())
def commercial_hash(price,oldp,in_stock,url): return _h(price,oldp,in_stock,url)
def text_hash(name,desc):                     return _h(_norm(name),_norm(desc))
def geometry_hash(w,d,h,ln,dia):
    # округляем до сантиметра: фид иногда шлёт 60.0 и 60, это не изменение товара
    return _h(*[None if v is None else round(float(v)) for v in (w,d,h,ln,dia)])
def image_hash(url):                          return _h(_norm(url))

# Берём из фида ТОЛЬКО категории, признанные нужными (`category-roles.json`, category_map.py).
# Иначе завтрашний прогон вернёт в базу посуду, матрасы и садовую технику, которые мы вычистили
# (решение владельца 2026-08-06: «остальное неактуальное удали и только их обновляй»).
# Карта не читается → СТОП, а не «грузим всё»: молчаливый fallback возвращал бы мусор в базу (А1).
_CATROLE={}
try:
    for _c in json.load(open(os.path.join(HERE,'category-roles.json'))).values():
        if _c.get('role'): _CATROLE[(int(_c['mid']), str(_c['id']))]=_c['role']
except Exception as _e:
    print(f'СТОП: карта категорий не читается ({_e}) — прогон отменён', flush=True); sys.exit(1)
if not _CATROLE:
    print('СТОП: карта категорий пуста — прогон отменён', flush=True); sys.exit(1)
print(f'карта категорий: {len(_CATROLE)} нужных категорий', flush=True)
from category_map import is_kids  # noqa: E402 — детское ловим по названию и в ежедневном пути

SPA_CUT=re.compile(r'/!.*$')  # mnogomebeli/divanboss: вариант после /! — серверу неизвестен
def direct(url):
    m=re.search(r'goto=(.+)$',url or '')
    u=urllib.parse.unquote(m.group(1)) if m else (url or '')
    u=u.replace(':443/','/')
    host=urllib.parse.urlparse(u).netloc.lower()
    if 'mnogomebeli' in host or 'divanboss' in host:
        u=SPA_CUT.sub('/',u)
        u=re.sub(r'/[^/]+/$','/',u)  # карточка 404 → родитель (серия) жив
    return u

total=0; per={}
rows=[]; erows=[]; mids=set()
for z in sorted(glob.glob(os.path.join(FEEDS,'*.zip'))):
    zf=zipfile.ZipFile(z); name=zf.namelist()[0]
    cats={}
    with zf.open(name) as f:
        for _,el in ET.iterparse(f):
            if el.tag=='category': cats[el.get('id')]=el.text or ''
            if el.tag!='offer': continue
            url=el.findtext('url') or ''
            m=re.search(r'mid=(\d+)',url) or re.search(r'mid%3D(\d+)',url)
            if not m: el.clear(); continue
            mid=int(m.group(1)); mids.add(mid)
            eid=el.get('id') or ''
            nm=(el.findtext('name') or el.findtext('model') or '').strip()
            price=el.findtext('price'); oldp=el.findtext('oldprice')
            pic=el.findtext('picture'); cid=el.findtext('categoryId')
            if pic and '/None/' in pic: pic=None   # битый URL из фида — не скачается никогда (А2)
            # роль из категории пишем сразу при загрузке
            if _CATROLE and (mid, str(cid)) not in _CATROLE:
                el.clear(); continue          # категория не нужна гостиной — товар не грузим
            params={p.get('name'):(p.text or '') for p in el.findall('param')}
            desc=re.sub(r'<[^>]+>',' ',el.findtext('description') or '')
            desc=re.sub(r'\s+',' ',desc).strip()[:1500] or None
            shop=urllib.parse.urlparse(direct(url)).netloc.replace('www.','') or str(mid)
            def dim(keys):
                for k in keys:
                    v=params.get(k)
                    if v:
                        m2=re.search(r'\d+(?:[.,]\d+)?',v)
                        if m2:
                            try: x=float(m2.group(0).replace(',','.'))
                            except ValueError: return None
                            return x/10 if x>400 else x  # мм → см
                return None
            w=dim(['Ширина','Ширина, см','Ширина, мм']); d=dim(['Глубина','Глубина, см','Глубина, мм'])
            h=dim(['Высота','Высота, см','Высота, мм']); ln=dim(['Длина','Длина, см']); dia=dim(['Диаметр','Диаметр, см'])
            p_int=int(float(price)) if price else None
            o_int=int(float(oldp)) if oldp else None
            # детское внутри разрешённых категорий — роль зануляем (иначе upsert вернул бы её)
            role=None if is_kids(nm) else _CATROLE.get((mid,str(cid)))
            rows.append('\t'.join(esc(x) for x in (mid,eid,shop,cid,cats.get(cid,''),nm,el.findtext('vendor'),
                url,pic,p_int,o_int,None,
                't',w,d,h,ln,dia,None,json.dumps(params,ensure_ascii=False),direct(url),desc,
                role)))
            erows.append('\t'.join(esc(x) for x in (mid,eid,
                commercial_hash(p_int,o_int,bool(p_int),direct(url)),
                text_hash(nm,desc), geometry_hash(w,d,h,ln,dia), image_hash(pic),
                'active' if p_int else 'out_of_stock')))
            per[shop]=per.get(shop,0)+1; total+=1
            el.clear()
print('офферов в свежих фидах:',total,per,flush=True)
print('строк с description:',sum(1 for r in rows if not r.endswith('\\N')),flush=True)

# Предохранитель от «похудевшего» фида (А1): урезанный/битый фид иначе молча увёл бы тысячи
# товаров в missing→archived. Порог 70% от вчерашнего непархивного числа; осознанный обход —
# FORCE_SHRINK=1 (например, магазин реально закрыл категорию).
if mids:
    _prev_out=sql(f"select count(*) from product_enrichment where shop_mid in ({','.join(map(str,sorted(mids)))})"
                  " and status<>'archived';")
    _m=re.search(r'\d+',_prev_out)   # sql() здесь без -tA: вывод psql с заголовком
    _prev=int(_m.group(0)) if _m else 0
    if _prev and total < 0.7*_prev and os.environ.get('FORCE_SHRINK')!='1':
        print(f'СТОП: офферов сегодня {total} < 70% от вчерашних {_prev} — фид похудел, статусы не трогаю '
              f'(осознанно — FORCE_SHRINK=1)', flush=True)
        sys.exit(2)

sql("drop table if exists products_new; create table products_new (like products including all);")
cols=("shop_mid,external_id,shop,category_id,category_path,name,brand,url,image_url,price_rub,"
      "old_price_rub,charge_rub,in_stock,w_cm,d_cm,h_cm,len_cm,dia_cm,dims_source,params,direct_url,"
      "description,cat_role")
sql(None, f"copy products_new({cols}) from stdin;\n"+"\n".join(rows)+"\n\\.\n")
mlist=",".join(map(str,sorted(mids)))
out=sql(f"""
begin;
update products p set in_stock=false
 where p.shop_mid in ({mlist})
   and not exists (select 1 from products_new n where n.shop_mid=p.shop_mid and n.external_id=p.external_id);
insert into products as p (shop_mid,external_id,shop,category_id,category_path,name,brand,url,image_url,
  price_rub,old_price_rub,charge_rub,in_stock,w_cm,d_cm,h_cm,len_cm,dia_cm,dims_source,params,direct_url,description,cat_role,last_seen)
select shop_mid,external_id,shop,category_id,category_path,name,brand,url,image_url,
  price_rub,old_price_rub,charge_rub,true,w_cm,d_cm,h_cm,len_cm,dia_cm,dims_source,params,direct_url,description,cat_role,current_date
from products_new
on conflict (shop_mid,external_id) do update set
  name=excluded.name,url=excluded.url,image_url=excluded.image_url,price_rub=excluded.price_rub,
  old_price_rub=excluded.old_price_rub,in_stock=true,direct_url=excluded.direct_url,last_seen=current_date,
  w_cm=coalesce(p.w_cm,excluded.w_cm),d_cm=coalesce(p.d_cm,excluded.d_cm),
  h_cm=coalesce(p.h_cm,excluded.h_cm),params=excluded.params,description=excluded.description,
  cat_role=excluded.cat_role,
  category_id=excluded.category_id,category_path=excluded.category_path;
drop table products_new;
commit;
select 'снято с наличия: '||count(*) from products where shop_mid in ({mlist}) and not in_stock;
""")
print(out.strip())
print(sql("select shop, count(*) filter (where in_stock) live, count(*) filter (where not in_stock) dead from products group by 1 order by 2 desc;"))

# ---------- дельта и жизненный цикл (ADR-0068) ------------------------------------------------
# Считаем ДО обновления: сколько товаров реально сменили семантику (текст, размеры, картинку).
# Смена цены и наличия семантику не меняет и повторного анализа не требует — это и есть экономия.
sql("drop table if exists enrich_new;"
    "create table enrich_new (shop_mid int, external_id text, commercial_hash text, text_hash text,"
    " geometry_hash text, image_hash text, feed_status text);")
sql(None, "copy enrich_new(shop_mid,external_id,commercial_hash,text_hash,geometry_hash,image_hash,"
          "feed_status) from stdin;\n"+"\n".join(erows)+"\n\\.\n")
delta=sql("""
select 'новых: '||count(*) filter (where e.shop_mid is null)
     ||'; сменили текст: '||count(*) filter (where e.text_hash is distinct from n.text_hash and e.shop_mid is not null)
     ||'; размеры: '||count(*) filter (where e.geometry_hash is distinct from n.geometry_hash and e.shop_mid is not null)
     ||'; картинку(URL): '||count(*) filter (where e.image_hash is distinct from n.image_hash and e.shop_mid is not null)
     ||'; только цена/наличие: '||count(*) filter (where e.shop_mid is not null
           and e.text_hash is not distinct from n.text_hash
           and e.geometry_hash is not distinct from n.geometry_hash
           and e.image_hash is not distinct from n.image_hash
           and e.commercial_hash is distinct from n.commercial_hash)
from enrich_new n left join product_enrichment e using (shop_mid, external_id);
""")
print('ДЕЛЬТА', delta.strip())
sql(f"""
begin;
insert into product_enrichment as e (shop_mid,external_id,commercial_hash,text_hash,geometry_hash,
       image_hash,status,missing_runs,missing_since,last_seen)
select shop_mid,external_id,commercial_hash,text_hash,geometry_hash,image_hash,feed_status,0,null,current_date
from enrich_new
on conflict (shop_mid,external_id) do update set
  commercial_hash=excluded.commercial_hash, text_hash=excluded.text_hash,
  geometry_hash=excluded.geometry_hash, image_hash=excluded.image_hash,
  status=excluded.status, missing_runs=0, missing_since=null,
  -- сменился смысл (текст/размеры) → версия сбрасывается, todo() возьмёт товар в переобогащение;
  -- payload остаётся до нового ответа. Раньше дельта только печаталась и ничего не запускала (А1).
  enrichment_version=case when e.text_hash is distinct from excluded.text_hash
                            or e.geometry_hash is distinct from excluded.geometry_hash
                          then null else e.enrichment_version end,
  last_seen=current_date, updated_at=now();
-- пропал из свежего фида: помечаем, но обогащение НЕ трогаем. Три пропуска подряд → в архив.
update product_enrichment e set missing_runs=e.missing_runs+1,
       missing_since=coalesce(e.missing_since,current_date),
       status=case when e.missing_runs+1>=3 then 'archived' else 'missing' end,
       updated_at=now()
 where e.shop_mid in ({mlist})
   and not exists (select 1 from enrich_new n
                   where n.shop_mid=e.shop_mid and n.external_id=e.external_id);
-- products.status — копия для совместимости: скрипты смотрят на in_stock, ломать их незачем
update products p set status=e.status, in_stock=(e.status='active')
  from product_enrichment e
 where p.shop_mid=e.shop_mid and p.external_id=e.external_id and p.shop_mid in ({mlist})
   and (p.status is distinct from e.status or p.in_stock is distinct from (e.status='active'));
drop table enrich_new;
commit;
""")
print('СТАТУСЫ', sql("select status||': '||count(*) from product_enrichment"
                     " group by status order by count(*) desc;").strip())
