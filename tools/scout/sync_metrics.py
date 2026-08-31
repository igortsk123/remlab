#!/usr/bin/env python3
"""Автопересчёт метрик сетов из свежего каталога (требование владельца 2026-08-02):
- цены/размеры/площадь (footprint) каждой позиции sets.json и sets2.json ← products;
- границы тиров эконом/комфорт/премиум пересчитываются по актуальным перцентилям цен роли;
- позиция выпала из полосы своего тира (>±20%) → в отчёт tier-outliers (замена — по команде).
Запуск: python3 sync_metrics.py (входит в refresh_daily)."""
import json, os, math, subprocess, sys

HERE=os.path.dirname(os.path.abspath(__file__))
PSQL=["docker","exec","-i","remlab-devdb","psql","-U","remlab","-d","remlab","-q","-v","ON_ERROR_STOP=1","-t","-A","-F","\x1f"]
def rows(q):
    r=subprocess.run(PSQL,input=q,capture_output=True,text=True)
    return [l.split('\x1f') for l in r.stdout.strip().split('\n') if l]

# перцентили цен по ролям (как в compose2), на ЖИВЫХ товарах
role_prices={}
for role,price in rows("select role, price_rub from lr_roles where role is not null and price_rub is not null and in_stock"):
    role_prices.setdefault(role,[]).append(int(price))
for v in role_prices.values(): v.sort()
def band(role,tier):
    ps=role_prices.get(role) or []
    if not ps: return (0,10**9)
    def pc(p): return ps[max(0,min(len(ps)-1,int(p*len(ps))))]
    return {'эконом':(pc(.05),pc(.45)),'комфорт':(pc(.35),pc(.80)),'премиум':(pc(.70),pc(.97))}[tier]

report={'updated':0,'price_changes':[],'tier_outliers':[],'missing':[]}
for fname in ('sets.json','sets2.json','sets3.json'):  # W5: sets3 раньше не обновлялся
    path=os.path.join(HERE,fname)
    if not os.path.exists(path): continue
    sets=json.load(open(path))
    for si,s in enumerate(sets):
        for role,it in s['items'].items():
            r=rows(f"""select price_rub, w_cm, d_cm, dia_cm, h_cm, len_cm, in_stock,
                coalesce(direct_url,url) from products
                where shop_mid={it['mid']} and external_id='{it["eid"]}'""")
            if not r:
                report['missing'].append(f"{fname}:сет{si+1}:{role}"); continue
            p,w,d,dia,h,ln,ins,du=r[0]
            newp=int(p) if p else it['price']
            if newp!=it['price']:
                report['price_changes'].append(f"{fname}:сет{si+1}:{role}: {it['price']}→{newp} ₽")
            it['price']=newp; it['url']=du
            it['w']=float(w) if w else it.get('w'); it['d']=float(d) if d else (float(ln) if ln else it.get('d'))
            it['dia']=float(dia) if dia else it.get('dia'); it['h']=float(h) if h else it.get('h')
            fp=None
            if it.get('w') and it.get('d'): fp=it['w']*it['d']/10000
            elif it.get('dia'): fp=math.pi*(it['dia']/200)**2
            it['fp']=fp
            base=role.replace(' 2','').rstrip('0123456789 ')
            lo,hi=band(base if base in role_prices else role, s['tier'])
            if newp<lo*0.8 or newp>hi*1.2:
                report['tier_outliers'].append(f"{fname}:сет{si+1}:{role}: {newp} ₽ вне полосы «{s['tier']}» [{lo}..{hi}]")
            report['updated']+=1
        s['total']=sum(x['price']*x.get('qty',1) for x in s['items'].values())
        # свежая площадь пола сета
        floor=[x for rl,x in s['items'].items() if x.get('fp') and rl not in
               ('люстра','плед','подушка','подушка 2','ваза','лампа','растение','ковёр','зеркало','шторы','бра','полка','часы','статуэтка')]
        if floor and s.get('m2'):
            s['fill_pct']=round(sum(x['fp']*x.get('qty',1) for x in floor)/s['m2']*100,1)
    json.dump(sets,open(path,'w'),ensure_ascii=False,indent=1)
# ПОКРЫТИЕ ПРОВЕРКОЙ КАРТОЧЕК (31.08). Дыру наличия было не видно именно потому, что никто не
# мерил, какая доля каталога вообще проверена и сколько снятий дошло до конца. Теперь — в отчёте.
cov=rows("""select
  count(*) filter (where ps.checked_at > now() - interval '8 days'),
  count(*),
  count(*) filter (where ps.state='gone'), count(*) filter (where ps.state='oos'),
  count(*) filter (where ps.state='suspect'), count(*) filter (where ps.state='alive'),
  count(*) filter (where ps.state='unknown')
 from products p left join product_page_status ps
   on ps.shop_mid=p.shop_mid and ps.external_id=p.external_id
 where coalesce(p.status,'active')='active'""")
if cov and len(cov[0])>=7:
    c=[int(x or 0) for x in cov[0]]
    report['stock_check']={'проверено за 8 дней':c[0],'товаров активных':c[1],
                           'покрытие_%':round(c[0]*100/max(c[1],1),1),
                           'снято gone':c[2],'снято oos':c[3],'ждут подтверждения':c[4],
                           'подтверждено живых':c[5],'неизвестно':c[6]}
    print(f"покрытие проверкой карточек за 8 дней: {report['stock_check']['покрытие_%']}% "
          f"({c[0]}/{c[1]}) | снято: gone {c[2]}, oos {c[3]} | ждут второго голоса: {c[4]}")
json.dump(report,open(os.path.join(HERE,'metrics-report.json'),'w'),ensure_ascii=False,indent=1)
print(f"обновлено позиций: {report['updated']} | цен изменилось: {len(report['price_changes'])} | "
      f"тир-выбросов: {len(report['tier_outliers'])} | не найдено: {len(report['missing'])}")
