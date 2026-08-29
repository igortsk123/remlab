#!/usr/bin/env python3
"""Ф2 catalog-freshness: health-check товаров сетов по КАРТОЧКАМ (фид наличие не отражает).
Домен-правила: nonton/gipfel/sanok — текстовый маркер; tvoydom — поля остатков в инлайн-JSON;
mnogomebeli/divanboss — SPA: живость = модель упоминается на странице серии (direct_url).
Мёртвые: products.in_stock=false; в sets2.json — автозамена из alternates (с проверкой замены).
Отчёт: health-report.json. Запуск: python3 health.py [--limit N]"""
import json, os, re, sys, time, subprocess, urllib.request, urllib.parse

HERE=os.path.dirname(os.path.abspath(__file__))
PSQL=["docker","exec","-i","remlab-devdb","psql","-U","remlab","-d","remlab","-q","-v","ON_ERROR_STOP=1","-t","-A","-F","\x1f"]
def rows(q):
    r=subprocess.run(PSQL,input=q,capture_output=True,text=True)
    return [l.split('\x1f') for l in r.stdout.strip().split('\n') if l]
def fetch(u,limit=1500000):
    if 'tvoydom' in u: limit=6000000  # поля остатков лежат глубоко в 4МБ-странице
    req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    r=urllib.request.urlopen(req,timeout=25)
    return r.status, r.read(limit).decode('utf-8','ignore')

MARK=re.compile(r'нет в наличии|не в наличии|товар не найден|снят с продаж|распродан|товара нет',re.I)
def alive(shop,du,name):
    """→ (bool|None, причина). None = «не смог проверить» — это НЕ приговор (урок 320/326).

    Прежняя версия убила 119 товаров divan.ru за одну ночь: фраза «Нет в наличии» есть в
    ШАБЛОНЕ каждой страницы divan.ru (переключатель вариантов), и маркер OOS срабатывал на
    живых товарах с кнопкой «В корзину». Проверка на пяти заведомо живых: маркер соврал 5/5.
    Правило: положительный признак (корзина/qty) сильнее любого текстового маркера.
    """
    try:
        st,txt=fetch(du)
    except Exception as e:
        return None, f"не проверилось: HTTP {str(e)[:40]}"
    if 'tvoydom' in shop:
        qs=[int(x) for x in re.findall(r'"quantity"\s*:\s*(\d+)',txt)]
        if qs and max(qs)>0: return True,'qty>0'
        if qs: return False,'qty=0'
        return (not MARK.search(txt[:200000])), 'по маркеру (qty не найден)'
    if 'mnogomebeli' in shop or 'divanboss' in shop:
        key=' '.join(re.sub(r'[^а-яa-z0-9 ]',' ',name.lower()).split()[1:4])
        return (key and key in txt.lower()), f"модель на серии: {key!r}"
    if MARK.search(txt): return False,'маркер OOS'
    return True,'200 без маркера'

sets2=json.load(open(os.path.join(HERE,'sets2.json')))
sets1=json.load(open(os.path.join(HERE,'sets.json')))
# W5 (аудит 10.08): боевое поколение sets3 раньше НЕ проверялось на живость карточек
sets3=json.load(open(os.path.join(HERE,'sets3.json'))) \
    if os.path.exists(os.path.join(HERE,'sets3.json')) else []
todo={}
for src,ss in (('v1',sets1),('v2',sets2),('v3',sets3)):
    for si,s in enumerate(ss):
        for role,it in s['items'].items():
            todo.setdefault((it['mid'],it['eid']),{'name':it['name'],'refs':[]})['refs'].append((src,si,role))
print('уникальных товаров на проверку:',len(todo),flush=True)
limit=int(sys.argv[sys.argv.index('--limit')+1]) if '--limit' in sys.argv else 10**9
status={}
for i,((mid,eid),info) in enumerate(list(todo.items())[:limit]):
    r=rows(f"select shop, coalesce(direct_url,url) from products where shop_mid={mid} and external_id='{eid}'")
    if not r:
        status[(mid,eid)]=(False,'нет в products'); continue
    shop,du=r[0]
    ok,why=alive(shop,du,info['name'])
    status[(mid,eid)]=(ok,why)
    print(f"[{i+1}/{min(len(todo),limit)}] {'OK ' if ok else 'DEAD'} {shop:16s} {info['name'][:44]} — {why}",flush=True)
    time.sleep(2.2)
dead=[k for k,(ok,_) in status.items() if ok is False]   # None = «не знаю», наличие не трогаем
if dead:
    vals=",".join(f"({m},'{e}')" for m,e in dead)
    subprocess.run(PSQL,input=f"update products set in_stock=false where (shop_mid,external_id) in ({vals});",
                   capture_output=True,text=True)
print(f"мёртвых: {len(dead)} из {len(status)}",flush=True)

# автозамена в sets2 (v1 утверждённый НЕ трогаем — только отчёт)
def fetch_item(mid,eid):
    r=rows(f"""select shop_mid, external_id, name, w_cm, d_cm, dia_cm, h_cm, price_rub, shop, image_url,
     coalesce(direct_url,url) from products where shop_mid={mid} and external_id='{eid}' and in_stock""")
    if not r: return None
    x=r[0]
    return dict(mid=int(x[0]),eid=x[1],name=x[2],w=float(x[3]) if x[3] else None,d=float(x[4]) if x[4] else None,
                dia=float(x[5]) if x[5] else None,h=float(x[6]) if x[6] else None,price=int(x[7]),shop=x[8],
                img=x[9],url=x[10],qty=1)
report={'checked':len(status),'dead':[],'swaps_v2':[],'v1_problems':[]}
for (m,e) in dead:
    report['dead'].append({'mid':m,'eid':e,'name':todo[(m,e)]['name'][:60],
                           'used_in':[f"{src}:сет{si+1}:{role}" for src,si,role in todo[(m,e)]['refs']]})
for si,s in enumerate(sets2):
    for role,it in list(s['items'].items()):
        if (it['mid'],it['eid']) not in dead: continue
        alts=(s.get('alternates') or {}).get(role) or []
        swapped=False
        for a in alts:
            cand=fetch_item(a['mid'],a['eid'])
            if not cand: continue
            ok,why=alive(cand['shop'],cand['url'],cand['name']); time.sleep(2.2)
            if not ok: continue
            keep_q=it.get('qty',1)
            s['items'][role]=dict(cand,qty=keep_q,why=f"автозамена: прежний недоступен")
            report['swaps_v2'].append(f"сет{si+1} {role}: {it['name'][:40]} → {cand['name'][:40]}")
            swapped=True; break
        if not swapped:
            report['swaps_v2'].append(f"сет{si+1} {role}: НЕТ живой замены (alternates пусты/мертвы)")
    s['total']=sum(x['price']*x.get('qty',1) for x in s['items'].values())
for si,s in enumerate(sets1):
    for role,it in s['items'].items():
        if (it['mid'],it['eid']) in dead:
            report['v1_problems'].append(f"сет{si+1} {role}: {it['name'][:50]}")
json.dump(sets2,open(os.path.join(HERE,'sets2.json'),'w'),ensure_ascii=False,indent=1)
json.dump(report,open(os.path.join(HERE,'health-report.json'),'w'),ensure_ascii=False,indent=1)
print("замен в v2:",len([x for x in report['swaps_v2'] if 'НЕТ' not in x]),
      "| без замены:",len([x for x in report['swaps_v2'] if 'НЕТ' in x]),
      "| проблем в утверждённых v1:",len(report['v1_problems']))
print("OK: health-report.json")
