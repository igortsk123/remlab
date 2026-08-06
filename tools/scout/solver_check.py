#!/usr/bin/env python3
"""room-size-fit Ф3: батч-проверка «сет влезает в свою комнату» — каждый сет из sets3.json
прогоняется солвером (solver_run.py --v3), собираются hard-нарушения и неразмещённые роли.
Итог: solver-check-report.json + сводка в stdout.
Запуск (venv!): ~/venvs/scout/bin/python solver_check.py [N_from N_to]"""
import json, os, sys, subprocess, re

HERE=os.path.dirname(os.path.abspath(__file__))
PY=os.path.expanduser('~/venvs/scout/bin/python')
sets=json.load(open(os.path.join(HERE,'sets3.json')))
a,b=(int(sys.argv[1]),int(sys.argv[2])) if len(sys.argv)>2 else (1,len(sets))
report=[]
for i in range(a,b+1):
    s=sets[i-1]
    try:  # перебор сидов может идти до ~6×25 с — таймаут щедрый, и он НЕ роняет весь батч
        # суффикс уникален на диапазон: параллельные воркеры не дерутся за одни файлы раскладок
        env=dict(os.environ,LAYOUT_SUFFIX=f"-check{os.environ.get('CHECK_TAG','')}")
        r=subprocess.run([PY,os.path.join(HERE,'solver_run.py'),str(i),'--v3'],
                         capture_output=True,text=True,timeout=300,env=env)
    except subprocess.TimeoutExpired:
        report.append(dict(set=i,band=s['band'],tier=s['tier'],style=s.get('style'),
                           ok=False,fails=['TIMEOUT солвера'],missing=[]))
        print(f"сет {i}: TIMEOUT",flush=True); continue
    out=r.stdout
    fails=[l.strip() for l in out.splitlines() if l.startswith('FAIL')]
    m=re.search(r'НЕ размещены: (\[.*\])',out)
    missing=eval(m.group(1)) if m else []
    # Зрячая метрика (А3): hard-чистота — ещё не логичность. Солвер печатает SOFT {json}
    # с score-термами и soft-нарушениями; порог «глупости» — сумма штрафов (калибруется
    # вердиктами владельца: сеты с dumb>DUMB_T показывать первыми).
    msoft=re.search(r'^SOFT (\{.*\})$',out,re.M)
    soft=json.loads(msoft.group(1)) if msoft else {}
    dumb=round(sum(soft.get('terms',{}).values()),1)
    ok=not fails and not missing and r.returncode==0
    report.append(dict(set=i,band=s['band'],tier=s['tier'],style=s.get('style'),
                       ok=ok,fails=fails,missing=missing,
                       soft_score=dumb,soft=soft.get('terms',{}),
                       soft_violations=soft.get('soft_violations',[])))
    print(f"сет {i} ({s['band']} {s['tier']} {s.get('style','')}): "
          +("OK" if ok else f"FAIL {fails} missing={missing}")
          +(f" soft={dumb}" if soft else ""),flush=True)
_out=os.environ.get('CHECK_REPORT') or 'solver-check-report.json'
json.dump(report,open(os.path.join(HERE,_out),'w'),ensure_ascii=False,indent=1)
bad=[r for r in report if not r['ok']]
print(f"\nИтого: {len(report)-len(bad)}/{len(report)} влезают; проблемных {len(bad)}")
for r in bad: print(f"  сет {r['set']} {r['band']} {r['tier']} {r['style']}: {r['fails']} {r['missing']}")
DUMB_T=float(os.environ.get('DUMB_T','12'))   # стартовый порог; калибровать вердиктами владельца
dumbs=sorted([r for r in report if r['ok'] and r.get('soft_score',0)>DUMB_T],
             key=lambda r:-r['soft_score'])
if dumbs:
    print(f"валидных, но подозрительных на «глупую» схему (soft>{DUMB_T}): {len(dumbs)}")
    for r in dumbs[:15]:
        worst=sorted(r['soft'].items(),key=lambda kv:-kv[1])[:3]
        print(f"  сет {r['set']} soft={r['soft_score']}: "+", ".join(f"{k}={v}" for k,v in worst))
