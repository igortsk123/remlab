#!/usr/bin/env python3
"""Z5: прогон зафиксированного приёмочного набора (acceptance-scenes.json) одним или двумя
движками (A/B: beam vs zoned). Для каждой сцены — solver_run --v3 с геометрией сцены; итог —
acceptance-report-<engine>.json + сводка: чистых / hard-провалов / неразмещённых / медиана soft.

Запуск: ~/venvs/scout/bin/python acceptance_run.py [beam|zoned|ab] [N_from N_to]
По умолчанию ab (оба движка). Сцены режутся диапазоном НОМЕРОВ СЕТОВ (не сцен).
"""
import concurrent.futures as cf
import json
import os
import re
import statistics
import subprocess
import sys
import threading

WORKERS = int(os.environ.get('ACC_WORKERS', '4'))   # RAM 4 ГБ: 4 солвера параллельно — безопасно

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.expanduser('~/venvs/scout/bin/python')
SCENES = json.load(open(os.path.join(HERE, 'acceptance-scenes.json')))

# Ф2 (план cwd-free-tooling): АБСОЛЮТНЫЙ путь отчёта на старте + возраст прежнего файла —
# защита от «смотрю старый отчёт как новый» (13.08 это стоило получаса ложных выводов)
def _announce_report(engine: str) -> None:
    import time
    p = os.path.join(HERE, f'acceptance-report-{engine}.jsonl')
    print(f'ОТЧЁТ: {os.path.abspath(p)}', flush=True)
    if os.path.exists(p):
        age = time.time() - os.path.getmtime(p)
        print(f'  ВНИМАНИЕ: прежний отчёт существует, возраст {age/60:.0f} мин — '
              f'дозапись/резюм по нему', flush=True)
mode = sys.argv[1] if len(sys.argv) > 1 else 'ab'
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


def _one(engine, sc):
    """Один прогон сцены; уникальный LAYOUT_SUFFIX на СЦЕНУ — параллельные воркеры не дерутся
    за файлы раскладок (set3-base и set3-pylons писали бы в один v3set3-layout-*.json)."""
    env = dict(os.environ, LAYOUT_ENGINE=engine, LAYOUT_SUFFIX=f"-acc-{engine}-{sc['id']}")
    args = [PY, os.path.join(HERE, 'solver_run.py'), str(sc['set']), '--v3']
    if sc['kind'] == 'contour':
        xs = [p[0] for p in sc['contour']]; ys = [p[1] for p in sc['contour']]
        env['SCENE_CONTOUR'] = json.dumps(sc['contour'])
        args += [str(max(xs)), str(max(ys))]
    elif 'w' in sc:
        args += [str(sc['w']), str(sc['d'])]
    # Пакет H свода №8: сцены №253+ задают СВОИ проёмы (2 двери, балкон, 2-3 окна…) —
    # solver_run строит Room из SCENE_OPENINGS (та же ветка, что у артефакта)
    if sc.get('openings'):
        env['SCENE_OPENINGS'] = json.dumps(sc['openings'])
    import time as _tm
    _t0 = _tm.time()
    try:
        # W5 (урок 213 + 10.08): при >2 воркерах контеншн замедляет тяжёлые сцены —
        # таймаут 600, чтобы они ДОСЧИТЫВАЛИСЬ, а не падали ложным TIMEOUT
        r = subprocess.run(args, capture_output=True, text=True, timeout=900, env=env)  # P2/P3 свода №12: beam ×1.5 — порог 600 введён при greedy
    except subprocess.TimeoutExpired:
        return dict(scene=sc['id'], set=sc['set'], ok=False,
                    fails=['TIMEOUT'], missing=[], soft_score=None)
    out = r.stdout
    fails = [l.strip() for l in out.splitlines() if l.startswith('FAIL')]
    m = re.search(r'НЕ размещены: (\[.*\])', out)
    missing = eval(m.group(1)) if m else []
    msoft = re.search(r'^SOFT (\{.*\})$', out, re.M)
    soft = json.loads(msoft.group(1)) if msoft else {}
    dumb = round(sum(soft.get('terms', {}).values()), 1)
    mfill = re.search(r'^FILL ([\d.]+)$', out, re.M)
    mtpl = re.search(r'зонная группа: (\S+)', out)          # какие ШАБЛОНЫ применены
    msur = re.search(r'^UNUSED (\[.*\])$', out, re.M)   # не вошло в ЭТУ расстановку
    mused = re.search(r'^USED (\d+)/(\d+)$', out, re.M)  # задействовано из банка сета
    mskip = re.search(r'^SKIPPED (\[.*\])$', out, re.M)
    skipped = json.loads(mskip.group(1)) if mskip else []
    ok = not fails and not missing and r.returncode == 0
    rec = dict(scene=sc['id'], set=sc['set'], ok=ok, fails=fails,
               missing=missing, skipped=skipped, soft_score=dumb,
               fill_pct=(float(mfill.group(1)) if mfill else None),
               templates=(mtpl.group(1) if mtpl else None),
               unused=(json.loads(msur.group(1)) if msur else []),
               used_of_bank=([int(mused.group(1)), int(mused.group(2))] if mused else None),
               group=(re.search(r'зонная группа: (\S+)', out) or [None, None])[1],
               topo=(re.search(r'^TOPO (.+)$', out, re.M) or [None, None])[1])
    rec['duration_s'] = round(_tm.time() - _t0, 1)   # телеметрия времени (ускорение 17.08)
    if r.returncode != 0:   # крэш без FAIL-строк иначе неотличим от «просто не ok»
        rec['rc'] = r.returncode
        rec['err'] = (r.stderr or '').strip()[-400:]
    return rec


def run_engine(engine):
    """Параллельно (ACC_WORKERS), с покадровой записью в jsonl: упавший/убитый прогон
    не теряет готовые сцены — при рестарте они читаются из jsonl и не пересчитываются."""
    jl_path = os.path.join(HERE, f'acceptance-report-{engine}{REPORT_SUFFIX}.jsonl')
    done = {}
    if os.path.exists(jl_path):
        for line in open(jl_path):
            try:
                rec = json.loads(line); done[rec['scene']] = rec
            except Exception:
                pass
        if done:
            print(f'[{engine}] из jsonl подхвачено готовых: {len(done)}', flush=True)
    _announce_report(engine)
    todo = [sc for sc in SCENES if sc['id'] not in done]
    # тяжёлые сцены — первыми (по duration_s прошлого полного отчёта): хвост из XL не держит воркеры пустыми
    _dur = {}
    try:
        _dur = json.load(open(os.path.join(HERE, 'scene-durations.json'), encoding='utf-8'))
    except Exception:
        _dur = {}
    todo.sort(key=lambda sc: -float(_dur.get(sc['id'], 0)))
    lock = threading.Lock()
    jl = open(jl_path, 'a')
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(_one, engine, sc): sc for sc in todo}
        for fut in cf.as_completed(futs):
            rec = fut.result()
            with lock:
                done[rec['scene']] = rec
                jl.write(json.dumps(rec, ensure_ascii=False) + '\n'); jl.flush()
            print(f"{rec['scene']} [{engine}]: "
                  + ('OK' if rec['ok'] else f"FAIL {rec['fails']} miss={rec['missing']}")
                  + f" soft={rec['soft_score']} [{len(done)}/{len(SCENES)}]", flush=True)
    jl.close()
    report = [done[sc['id']] for sc in SCENES if sc['id'] in done]
    # ТЕЛЕМЕТРИЯ ДЛЯ ШЕДУЛЕРА (22.08): длительности сцен — в scene-durations.json;
    # сортировка «тяжёлые первыми» выше читает именно его (файл прежде никем не писался —
    # сортировка была мёртвой, и XL-хвост ловил TIMEOUT при пустеющем пуле воркеров)
    try:
        _prev_d = {}
        _dp0 = os.path.join(HERE, 'scene-durations.json')
        if os.path.exists(_dp0):
            _prev_d = json.load(open(_dp0, encoding='utf-8'))
        for rec0 in report:
            if rec0.get('duration_s'):
                _prev_d[rec0['scene']] = rec0['duration_s']
            elif 'TIMEOUT' in str(rec0.get('fails')):
                _prev_d[rec0['scene']] = 1800.0      # таймаут = максимальный приоритет
        json.dump(_prev_d, open(_dp0, 'w', encoding='utf-8'), ensure_ascii=False)
    except Exception:
        pass
    json.dump(report, open(os.path.join(HERE, f'acceptance-report-{engine}{REPORT_SUFFIX}.json'), 'w'),
              ensure_ascii=False, indent=1)
    if not REPORT_SUFFIX:   # длительности — только с полного прогона (для порядка и perf-manifest)
        try:
            _prev = {}
            pass          # 22.08: телеметрия длительностей пишется выше (единый writer,
                          # TIMEOUT=1800 приоритет); прежний дубль удалён
        except Exception:
            pass
    return report


def summary(engine, rep):
    okc = sum(1 for r in rep if r['ok'])
    softs = [r['soft_score'] for r in rep if r['ok'] and r['soft_score'] is not None]
    med = statistics.median(softs) if softs else 0
    dumb = sum(1 for x in softs if x > float(os.environ.get('DUMB_T', '12')))
    print(f'\n[{engine}] чистых {okc}/{len(rep)}; медиана soft {med}; «глупых» {dumb}')
    return okc, med, dumb


engines = ['beam', 'zoned'] if mode == 'ab' else [mode]
results = {e: run_engine(e) for e in engines}
for e in engines:
    summary(e, results[e])
if len(engines) == 2:
    flips = [(r1['scene'], r1['ok'], r2['ok'])
             for r1, r2 in zip(results['beam'], results['zoned']) if r1['ok'] != r2['ok']]
    print(f'разошлись по чистоте: {len(flips)}')
    for sc, b1, b2 in flips[:20]:
        print(f'  {sc}: beam={"OK" if b1 else "fail"} zoned={"OK" if b2 else "fail"}')
