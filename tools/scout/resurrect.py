"""Воскрешение наличия после битого маркера: перепроверка ПОЧИНЕННОЙ пробой всех членов сетов.

health.py умеет только гасить наличие и никогда не возвращает — поэтому после починки маркера
жертвы остаются погашенными навсегда, если их не поднять отдельно. Проверяем каждым запросом
к живой странице (fixed alive: корзина сильнее текста, сбой = не знаю), пишем только True.
"""
import json, re, subprocess, sys, time, urllib.request
P=['docker','exec','-i','remlab-devdb','psql','-U','remlab','-d','remlab','-q','-t','-A','-F','\x1f']
def rows(q):
    r=subprocess.run(P,capture_output=True,text=True,input=q)
    return [l.split('\x1f') for l in r.stdout.strip().split('\n') if l]
# fixed alive — парсингом файла, БЕЗ import health (модуль исполняется при импорте!)
src=open('health.py').read()
ns={'__file__': '/home/pakar/igor/remlab/tools/scout/health.py'}
exec(compile(src[:src.index('sets2=json.load')], 'health_head', 'exec'), ns)   # только функции
alive=ns['alive']
skus=set()
for f in ('sets.json','sets2.json','sets3.json'):
    try:
        for s in json.load(open(f)):
            for it in (s.get('items') or {}).values():
                if it and it.get('mid'): skus.add(f"{it['mid']}:{it['eid']}")
    except Exception: pass
ok=dead=unk=0
todo=[]
for sku in sorted(skus):
    mid,eid=sku.split(':')
    r=rows(f"select shop, coalesce(direct_url,url), name from products where shop_mid={mid} and external_id='{eid}' and not in_stock and status='active'")
    if r and len(r[0])==3: todo.append((mid,eid,*r[0]))
print(f'к перепроверке погашенных: {len(todo)}', flush=True)
for i,(mid,eid,shop,du,name) in enumerate(todo,1):
    a,why=alive(shop,du,name)
    if a is True:
        rows(f"update products set in_stock=true where shop_mid={mid} and external_id='{eid}'")
        ok+=1
    elif a is False: dead+=1
    else: unk+=1
    if i%25==0: print(f'{i}/{len(todo)}: живых {ok}, мёртвых {dead}, неясно {unk}', flush=True)
    time.sleep(2.0)
print(f'ИТОГ: воскрешено {ok}, реально мертво {dead}, не проверилось {unk}')
