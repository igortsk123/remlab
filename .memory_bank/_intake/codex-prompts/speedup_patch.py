"""Патч ускорения (применять ПОСЛЕ экзамена): acceptance_run (подмножество/манифест, отдельный отчёт,
duration_s, тяжёлые первыми, снимок банков), solver_run (SETS_SNAPSHOT + render через render_plan),
run.sh (smoke/perf/render, flock)."""
import re
p='/home/pakar/igor/remlab/tools/scout/acceptance_run.py'; s=open(p).read()
a="""mode = sys.argv[1] if len(sys.argv) > 1 else 'ab'
nums = [a for a in sys.argv[2:] if a.isdigit()]
if len(nums) >= 2:
    a, b = int(nums[0]), int(nums[1])
    SCENES = [sc for sc in SCENES if a <= sc['set'] <= b]
"""
b="""mode = sys.argv[1] if len(sys.argv) > 1 else 'ab'
nums = [a for a in sys.argv[2:] if a.isdigit()]
if len(nums) >= 2:
    a, b = int(nums[0]), int(nums[1])
    SCENES = [sc for sc in SCENES if a <= sc['set'] <= b]
# УСКОРЕНИЕ 17.08 (Codex): ACC_MANIFEST=<json-список id> или ACC_SCENES=id1,id2 — подмножество сцен
# (смоук/perf/репро); ACC_REPORT_SUFFIX — отчёт не затирает полный (acceptance-report-zoned-smoke.jsonl)
_man = os.environ.get('ACC_MANIFEST')
_ids = os.environ.get('ACC_SCENES')
if _man or _ids:
    _want = set(json.load(open(_man, encoding='utf-8'))) if _man else set(x.strip() for x in _ids.split(',') if x.strip())
    SCENES = [sc for sc in SCENES if sc['id'] in _want]
    print(f'подмножество сцен: {len(SCENES)}', flush=True)
REPORT_SUFFIX = os.environ.get('ACC_REPORT_SUFFIX', '')
# СНИМОК БАНКОВ: экзамен читает sets3.json, замороженный на старте (heal/сборка не меняют банки под
# воркерами — 17.08 утренний heal переписал sets3.json посреди экзамена)
_SNAP = os.path.join(HERE, 'sets3.snapshot.json')
try:
    import shutil as _sh
    _sh.copyfile(os.path.join(HERE, 'sets3.json'), _SNAP)
    os.environ['SETS_SNAPSHOT'] = _SNAP
except Exception as _e:
    print(f'снимок банков не создан ({_e}) — читаем живой sets3.json', flush=True)
"""
assert a in s; s=s.replace(a,b,1)
a="""    jl_path = os.path.join(HERE, f'acceptance-report-{engine}.jsonl')"""
b="""    jl_path = os.path.join(HERE, f'acceptance-report-{engine}{REPORT_SUFFIX}.jsonl')"""
assert a in s; s=s.replace(a,b,1)
a="""    todo = [sc for sc in SCENES if sc['id'] not in done]"""
b="""    todo = [sc for sc in SCENES if sc['id'] not in done]
    # тяжёлые сцены — первыми (по duration_s прошлого полного отчёта): хвост из XL не держит воркеры пустыми
    _dur = {}
    try:
        for line in open(os.path.join(HERE, 'scene-durations.json'), encoding='utf-8'):
            _dur = json.loads(line); break
    except Exception:
        _dur = {}
    todo.sort(key=lambda sc: -float(_dur.get(sc['id'], 0)))"""
assert a in s; s=s.replace(a,b,1)
a="""    try:
        # W5 (урок 213 + 10.08): при >2 воркерах контеншн замедляет тяжёлые сцены —"""
b="""    import time as _tm
    _t0 = _tm.time()
    try:
        # W5 (урок 213 + 10.08): при >2 воркерах контеншн замедляет тяжёлые сцены —"""
assert a in s; s=s.replace(a,b,1)
a="""    if r.returncode != 0:   # крэш без FAIL-строк иначе неотличим от «просто не ok»"""
b="""    rec['duration_s'] = round(_tm.time() - _t0, 1)   # телеметрия времени (ускорение 17.08)
    if r.returncode != 0:   # крэш без FAIL-строк иначе неотличим от «просто не ok»"""
assert a in s; s=s.replace(a,b,1)
a="""    report = [done[sc['id']] for sc in SCENES if sc['id'] in done]
    json.dump(report, open(os.path.join(HERE, f'acceptance-report-{engine}.json'), 'w'),
              ensure_ascii=False, indent=1)"""
b="""    report = [done[sc['id']] for sc in SCENES if sc['id'] in done]
    json.dump(report, open(os.path.join(HERE, f'acceptance-report-{engine}{REPORT_SUFFIX}.json'), 'w'),
              ensure_ascii=False, indent=1)
    if not REPORT_SUFFIX:   # длительности — только с полного прогона (для порядка и perf-manifest)
        try:
            _prev = {}
            _dp = os.path.join(HERE, 'scene-durations.json')
            if os.path.exists(_dp):
                _prev = json.loads(open(_dp, encoding='utf-8').read() or '{}')
            _prev.update({r['scene']: r.get('duration_s') for r in report if r.get('duration_s')})
            json.dump(_prev, open(_dp, 'w', encoding='utf-8'), ensure_ascii=False)
        except Exception:
            pass"""
assert a in s; s=s.replace(a,b,1)
open(p,'w').write(s); print('acceptance_run ok')

p='/home/pakar/igor/remlab/tools/scout/solver_run.py'; s=open(p).read()
a="SETS_FILE='sets3.json' if '--v3' in sys.argv else ('sets2.json' if '--v2' in sys.argv else 'sets.json')"
b="SETS_FILE=(os.environ.get('SETS_SNAPSHOT') if (os.environ.get('SETS_SNAPSHOT') and '--v3' in sys.argv) else ('sets3.json' if '--v3' in sys.argv else ('sets2.json' if '--v2' in sys.argv else 'sets.json')))   # SETS_SNAPSHOT: замороженный банк экзамена (17.08)"
assert a in s; s=s.replace(a,b,1)
# render: replace section 'top-down PNG' … img.save(...) with call to render_plan
i=s.index("# top-down PNG — В НОРМАЛИЗОВАННОМ ВИДЕ")
j=s.index("img.save(os.path.join(HERE,f'{TAG}{n}-layout{_sfx}.png'))")
j_end=s.index('\n', j)+1
new="""# top-down PNG — ЕДИНЫЙ рендер из артефакта (render_plan.py; тот же код — для render-only без
# пересчёта, ускорение 17.08). placed/подписи/нормализацию делает render_plan по данным out.
try:
    from render_plan import render_artifact as _render_artifact
    _render_artifact(out, os.path.join(HERE,f'{TAG}{n}-layout{_sfx}.png'), band=BAND)
except Exception as _re_:
    print(f'render: ошибка ({_re_}) — PNG не записан', file=sys.stderr, flush=True)
"""
s=s[:i]+new+s[j_end:]
open(p,'w').write(s); print('solver_run ok')

p='/home/pakar/igor/remlab/tools/scout/run.sh'; s=open(p).read()
a="""  exam)
    rm -f acceptance-report-zoned.jsonl
    # ЗАМОК (17.08): пока идёт экзамен, конвейер (refresh_daily/enrich_wait) НЕ трогает sets3.json —
    # утренний heal переписал банки под бегущими воркерами (pod-комплекты 72→17), экзамен стал смешанным
    touch "$HERE/exam.lock"; trap 'rm -f "$HERE/exam.lock"' EXIT
    set +e; env ACC_WORKERS="${ACC_WORKERS:-10}" "$PY" acceptance_run.py zoned; rc=$?; rm -f "$HERE/exam.lock"; exit $rc ;;"""
b="""  exam)
    rm -f acceptance-report-zoned.jsonl
    # ЗАМОК (17.08): пока идёт экзамен, конвейер (refresh_daily/enrich_wait) НЕ трогает sets3.json —
    # утренний heal переписал банки под бегущими воркерами (pod-комплекты 72→17), экзамен стал смешанным.
    # flock: второй экзамен/сборка не стартуют параллельно; exam.lock — сигнал для cron
    exec 9>"$HERE/exam.flock"; flock -n 9 || { echo "экзамен уже идёт (exam.flock)"; exit 3; }
    touch "$HERE/exam.lock"; trap 'rm -f "$HERE/exam.lock"' EXIT
    set +e; env ACC_WORKERS="${ACC_WORKERS:-10}" "$PY" acceptance_run.py zoned; rc=$?; rm -f "$HERE/exam.lock"; exit $rc ;;
  smoke)
    # БЫСТРЫЙ СМОУК (~40 сцен, ≈5 мин): обратная связь по правке, НЕ гейт (полный — exam/ночью)
    exec 9>"$HERE/exam.flock"; flock -n 9 || { echo "экзамен уже идёт (exam.flock)"; exit 3; }
    "$PY" smoke_manifest.py >/dev/null
    rm -f acceptance-report-zoned-smoke.jsonl
    touch "$HERE/exam.lock"; trap 'rm -f "$HERE/exam.lock"' EXIT
    set +e; env ACC_WORKERS="${ACC_WORKERS:-10}" ACC_MANIFEST="$HERE/smoke-manifest.json" ACC_REPORT_SUFFIX=-smoke "$PY" acceptance_run.py zoned; rc=$?; rm -f "$HERE/exam.lock"; exit $rc ;;
  perf)
    # PERF-СМОУК: 3 самые тяжёлые сцены — замер времени (не для гейта/галереи)
    rm -f acceptance-report-zoned-perf.jsonl
    exec env ACC_WORKERS=3 ACC_MANIFEST="$HERE/perf-manifest.json" ACC_REPORT_SUFFIX=-perf "$PY" acceptance_run.py zoned ;;
  scenes)
    # точечный реплей: run.sh scenes set16-base,set28-base
    exec env ACC_WORKERS="${ACC_WORKERS:-6}" ACC_SCENES="$2" ACC_REPORT_SUFFIX=-scenes "$PY" acceptance_run.py zoned ;;
  render)
    # RENDER-ONLY: перерисовать PNG всех артефактов из JSON без пересчёта (подписи/подача)
    exec "$PY" render_plan.py --all -j "${ACC_WORKERS:-6}" ;;"""
assert a in s; s=s.replace(a,b,1)
s=s.replace("""#   tools/scout/run.sh exam            # экзамен 252 сцены (6 воркеров)""","""#   tools/scout/run.sh exam            # полный экзамен 272 сцены (10 воркеров) — гейт/ночью
#   tools/scout/run.sh smoke           # быстрый смоук ~40 сцен (обратная связь, не гейт)
#   tools/scout/run.sh perf            # 3 самые тяжёлые сцены — замер времени
#   tools/scout/run.sh scenes a,b,c    # точечный реплей сцен
#   tools/scout/run.sh render          # перерисовать PNG из артефактов без пересчёта""")
open(p,'w').write(s); print('run.sh ok')
