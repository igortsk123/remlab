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
    ok=not fails and not missing and r.returncode==0
    report.append(dict(set=i,band=s['band'],tier=s['tier'],style=s.get('style'),
                       ok=ok,fails=fails,missing=missing))
    print(f"сет {i} ({s['band']} {s['tier']} {s.get('style','')}): "
          +("OK" if ok else f"FAIL {fails} missing={missing}"),flush=True)
_out=os.environ.get('CHECK_REPORT') or 'solver-check-report.json'
json.dump(report,open(os.path.join(HERE,_out),'w'),ensure_ascii=False,indent=1)
bad=[r for r in report if not r['ok']]
print(f"\nИтого: {len(report)-len(bad)}/{len(report)} влезают; проблемных {len(bad)}")
for r in bad: print(f"  сет {r['set']} {r['band']} {r['tier']} {r['style']}: {r['fails']} {r['missing']}")
