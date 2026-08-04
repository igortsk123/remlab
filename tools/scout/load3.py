#!/usr/bin/env python3
"""Ф1 catalog-freshness: свежие фиды (feeds2/*.zip) → upsert в products.
- direct_url: полноценный unquote goto= (бага %21 закрыта);
  mnogomebeli/divanboss: SPA-карточки 404 → режем до живого уровня (серия).
- Товары магазинов свежих фидов, ИСЧЕЗНУВШИЕ из фида → in_stock=false (снят с продажи).
- Магазины без свежего фида (nonton, h-f-l) не трогаем — наличие проверит health-цикл.
Запуск: python3 load3.py"""
import zipfile, glob, os, re, sys, json, subprocess, urllib.parse
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
rows=[]; mids=set()
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
            rows.append('\t'.join(esc(x) for x in (mid,eid,shop,cid,cats.get(cid,''),nm,el.findtext('vendor'),
                url,pic,int(float(price)) if price else None,int(float(oldp)) if oldp else None,None,
                't',w,d,h,ln,dia,None,json.dumps(params,ensure_ascii=False),direct(url),desc)))
            per[shop]=per.get(shop,0)+1; total+=1
            el.clear()
print('офферов в свежих фидах:',total,per,flush=True)
print('строк с description:',sum(1 for r in rows if not r.endswith('\\N')),flush=True)

sql("drop table if exists products_new; create table products_new (like products including all);")
cols=("shop_mid,external_id,shop,category_id,category_path,name,brand,url,image_url,price_rub,"
      "old_price_rub,charge_rub,in_stock,w_cm,d_cm,h_cm,len_cm,dia_cm,dims_source,params,direct_url,description")
sql(None, f"copy products_new({cols}) from stdin;\n"+"\n".join(rows)+"\n\\.\n")
mlist=",".join(map(str,sorted(mids)))
out=sql(f"""
begin;
update products p set in_stock=false
 where p.shop_mid in ({mlist})
   and not exists (select 1 from products_new n where n.shop_mid=p.shop_mid and n.external_id=p.external_id);
insert into products as p (shop_mid,external_id,shop,category_id,category_path,name,brand,url,image_url,
  price_rub,old_price_rub,charge_rub,in_stock,w_cm,d_cm,h_cm,len_cm,dia_cm,dims_source,params,direct_url,description,last_seen)
select shop_mid,external_id,shop,category_id,category_path,name,brand,url,image_url,
  price_rub,old_price_rub,charge_rub,true,w_cm,d_cm,h_cm,len_cm,dia_cm,dims_source,params,direct_url,description,current_date
from products_new
on conflict (shop_mid,external_id) do update set
  name=excluded.name,url=excluded.url,image_url=excluded.image_url,price_rub=excluded.price_rub,
  old_price_rub=excluded.old_price_rub,in_stock=true,direct_url=excluded.direct_url,last_seen=current_date,
  w_cm=coalesce(p.w_cm,excluded.w_cm),d_cm=coalesce(p.d_cm,excluded.d_cm),
  h_cm=coalesce(p.h_cm,excluded.h_cm),params=excluded.params,description=excluded.description;
drop table products_new;
commit;
select 'снято с наличия: '||count(*) from products where shop_mid in ({mlist}) and not in_stock;
""")
print(out.strip())
print(sql("select shop, count(*) filter (where in_stock) live, count(*) filter (where not in_stock) dead from products group by 1 order by 2 desc;"))
