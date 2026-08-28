#!/usr/bin/env python3
"""Пост-процессор вердиктов судьи (политика владельца 2026-08-02) — БЕЗ новых вызовов API:
- style_grade >= STYLE_THR → состав сета НЕ трогаем (откат к оригиналу, если старый код успел заменить);
- style_grade < STYLE_THR → до 3 замен из outliers судьи; замена = запасной с МАКСИМАЛЬНЫМ
  стиль-вектором под стиль сета (оценки предзачтены в style-scores.json — можно вслепую).
Вход: sets3-prejudge.json (составы ДО замен) + judge-report3.json. Выход: sets3.json + отчёт.
Запуск (venv!): ~/venvs/scout/bin/python judge_apply.py"""
import os, sys, json

HERE=os.path.dirname(os.path.abspath(__file__))
sys.argv=['judge_apply','--v3']
head=open(os.path.join(HERE,'judge.py')).read().split('report=[]')[0]
exec(head)  # даёт: fetch_alt, best_alt, skey, SS, STYLE_THR (единый источник — judge.py)

pre=json.load(open(os.path.join(HERE,'sets3-prejudge.json')))
report=json.load(open(os.path.join(HERE,'judge-report3.json')))
kept=swapped=0; swaps_n=0
for r in report:
    i=r['set']-1; s=pre[i]
    sg=r.get('style_grade'); r['swaps']=[]
    if s.get('style') and sg is not None and sg>=STYLE_THR:
        kept+=1; r['policy']='kept (style_grade>=THR)'
        continue
    for o in (r.get('outliers') or [])[:3]:
        role=o.get('role')
        alts=(s.get('alternates') or {}).get(role) or []
        ba=best_alt(alts,s.get('style'))
        if role in s['items'] and ba:
            alt=fetch_alt(ba['mid'],ba['eid'])
            if alt:
                old=s['items'][role]['name'][:45]
                keep_q=s['items'][role].get('qty',1)
                from judge import _style_of
                sc=_style_of(ba['mid'],ba['eid']).get(s.get('style'),'—')
                s['items'][role]=dict(alt,qty=keep_q,why=f"замена по судье (стиль-вектор {sc}): {o.get('why','')[:70]}")
                r['swaps'].append(f"{role}: {old} → {alt['name'][:45]}")
                swaps_n+=1
    s['total']=sum(it['price']*it.get('qty',1) for it in s['items'].values())
    if r['swaps']: swapped+=1; r['policy']='swapped (style_grade<THR)'
    else: r['policy']='no-alt'
import sys as _sys; _sys.path.insert(0,HERE)
from set_identity import ensure_ids as _ensure_ids  # стабильный id не теряем при применении вердиктов
_ensure_ids(pre)
json.dump(pre,open(os.path.join(HERE,'sets3.json'),'w'),ensure_ascii=False,indent=1)
json.dump(report,open(os.path.join(HERE,'judge-report3.json'),'w'),ensure_ascii=False,indent=1)
gr=[r.get('style_grade') for r in report if r.get('style_grade') is not None]
print(f"style_grade: мин {min(gr)} сред {sum(gr)/len(gr):.1f} макс {max(gr)}; порог {STYLE_THR}")
print(f"OK: нетронуто {kept}, с заменами {swapped} (замен {swaps_n}); sets3.json финализирован")
