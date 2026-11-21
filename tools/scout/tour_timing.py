#!/usr/bin/env python3
"""РАЗБОР ВРЕМЕНИ ТУРА ПО ЖУРНАЛАМ (T-20261118-22/8, tour-speed-01): «взятие → v1 → v2 → v3 → первый кадр → последний кадр».

Источники (только чтение):
- журнал воркера `~/remlab-logs/trial/worker.log` — строки с временем `ГГГГ-ММ-ДД ЧЧ:ММ:СС` (местное): «<тур>: взял», «conveyor <тур>: v1-walls/v2-living/v3-bedrooms … принята»,
  «тур <тур>: фото получено — машина рендера … started»;
- журнал сервиса кадров `~/scout-scenes/dev-render.log` — строки `<ISO-время> [<задание>|tour:<тур>] …` (с T-22/8; строки старше штампов без времени не читаются):
  «тур <тур>: фото в заготовки … поставлено N» и «рендер <задание>: готов за N с» — по ним первый/последний кадр.
Критерий плана: «все фото» ≤ 9 мин — от «взятия» до последнего кадра.

  tour_timing.py <номер тура или его начало> [--worker путь] [--render путь] [--json]     код 0 — разобран; 2 — тура нет в журнале воркера
  tour_timing.py --selftest"""
import datetime
import json
import os
import re
import sys

WORKER = os.path.expanduser('~/remlab-logs/trial/worker.log')
RENDER = os.path.expanduser('~/scout-scenes/dev-render.log')
W_TS = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (.*)$')
R_TS = re.compile(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}) \[([^\]|\s]*)\|([^\]|\s]*)\] (.*)$')
STAGES = [('v1', r'v1-walls: версия \d+ принята'), ('v2', r'v2-living: версия \d+ принята'), ('v3', r'v3-bedrooms: версия \d+ принята')]


def _w_time(s: str) -> float:
    return datetime.datetime.strptime(s, '%Y-%m-%d %H:%M:%S').astimezone().timestamp()      # журнал воркера — местное время без пояса


def _r_time(s: str) -> float:
    return datetime.datetime.fromisoformat(s).timestamp()


def read_lines(path: str) -> list:
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return f.read().splitlines()
    except OSError:
        return []


def full_id(lines: list, prefix: str) -> str | None:
    """Номер тура по началу: самое позднее упоминание в журнале воркера (`<тур>: взял`)."""
    found = None
    for ln in lines:
        m = W_TS.match(ln)
        if m:
            mm = re.match(r'(\S+): взял', m.group(2))
            if mm and mm.group(1).startswith(prefix):
                found = mm.group(1)
    return found


def worker_events(lines: list, jid: str) -> dict:
    """Последний заход тура: время «взял» и первых принятых v1/v2/v3 после него; машина — «started/already» за N с."""
    take = None
    for ln in lines:
        m = W_TS.match(ln)
        if m and re.match(re.escape(jid) + r': взял', m.group(2)):
            take = _w_time(m.group(1))
    ev: dict = {'take': take}
    if take is None:
        return ev
    for ln in lines:
        m = W_TS.match(ln)
        if not m or jid not in m.group(2):
            continue
        t = _w_time(m.group(1))
        if t < take - 1:
            continue
        body = m.group(2)
        for name, pat in STAGES:
            if name not in ev and re.search(re.escape(jid) + r': ' + pat, body):
                ev[name] = t
        mm = re.search(r'машина рендера \([^)]*\) → (\w+) за ([\d.]+) с', body)
        if mm and jid in body and 'machine' not in ev:
            ev['machine'], ev['machine_at'] = mm.group(1), t
    return ev


def render_events(lines: list, jid: str) -> dict:
    """Кадры тура по строкам с штампом: поставлено N (время постановки), первый/последний «готов», число готовых."""
    tag = f'tour:{jid}'
    done, queued = [], []
    for ln in lines:
        m = R_TS.match(ln)
        if not m:
            continue
        t, job, tour, text = _r_time(m.group(1)), m.group(2), m.group(3), m.group(4)
        mq = re.match(r'тур ' + re.escape(jid) + r': фото в заготовки — .*поставлено (\d+)', text)
        if mq and int(mq.group(1)) > 0:
            queued.append((t, int(mq.group(1))))
        if tour == tag and re.match(r'рендер ' + re.escape(job) + r': готов за ', text):
            done.append(t)
    out: dict = {'frames': len(done), 'queued_at': queued[0][0] if queued else None, 'queued_n': sum(n for _, n in queued)}
    if done:
        out['first'], out['last'] = min(done), max(done)
    return out


def analyse(wlines: list, rlines: list, prefix: str) -> dict | None:
    jid = full_id(wlines, prefix)
    if not jid:
        return None
    w, r = worker_events(wlines, jid), render_events(rlines, jid)
    t0 = w['take']
    pts = [('взятие', t0), ('машина: включение', w.get('machine_at')), ('v1 (стены)', w.get('v1')), ('v2 (гостиная)', w.get('v2')), ('v3 (спальни)', w.get('v3')),
           ('фото поставлены', r.get('queued_at')), ('первый кадр', r.get('first')), ('последний кадр', r.get('last'))]
    res = {'tour': jid, 'machine': w.get('machine'), 'frames': r['frames'], 'queued': r['queued_n'],
           'stages': [{'name': n, 'at': t, 'from_take_s': (round(t - t0, 1) if t is not None else None)} for n, t in pts]}
    res['all_photos_min'] = round((r['last'] - t0) / 60, 2) if r.get('last') else None
    res['v3_min'] = round((w['v3'] - t0) / 60, 2) if w.get('v3') else None
    if r['frames'] > 1:
        res['frame_interval_s'] = round((r['last'] - r['first']) / (r['frames'] - 1), 1)
    return res


def fmt(res: dict) -> str:
    out = [f'тур {res["tour"]} · машина: {res.get("machine") or "—"} · кадров готово {res["frames"]} из поставленных {res["queued"]}']
    prev = None
    for s in res['stages']:
        if s['at'] is None:
            out.append(f'  {s["name"]:<20} —')
            continue
        hhmmss = datetime.datetime.fromtimestamp(s['at']).strftime('%H:%M:%S')
        step = '' if prev is None else f'  (+{s["at"] - prev:.0f} с)'
        out.append(f'  {s["name"]:<20} {hhmmss}  {s["from_take_s"]:>6.0f} с от взятия{step}')
        prev = s['at']
    if res.get('v3_min') is not None:
        out.append(f'  v3: {res["v3_min"]} мин (цель ≤ 5)')
    if res.get('all_photos_min') is not None:
        out.append(f'  все фото: {res["all_photos_min"]} мин (цель ≤ 9)' + (f'; интервал кадра {res["frame_interval_s"]} с' if 'frame_interval_s' in res else ''))
    else:
        out.append('  все фото: в журнале сервиса кадров нет проштампованных строк «готов» этого тура')
    return '\n'.join(out)


def _selftest() -> int:
    import tempfile
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import remlab_tmp
    remlab_tmp.use('tour_timing-selftest')
    bad = 0

    def ok(c, name):
        nonlocal bad
        print(('ok   ' if c else 'FAIL ') + name)
        bad += 0 if c else 1
    j = 'AbCdEf0123456789xyzABC'
    w = ['2026-11-21 10:00:00 ' + j + ': взял (попытка 1, image/png, 1000 Б)',
         '2026-11-21 10:00:02 тур ' + j + ': фото получено — машина рендера (tour-AbCdEf01) → started за 2.0 с: Включаю',
         '2026-11-21 10:02:30 conveyor ' + j + ': v1-walls: версия 1 принята, 30381 Б, complete=False',
         '2026-11-21 10:03:50 conveyor ' + j + ': v2-living: версия 2 принята, 172148 Б, complete=False',
         '2026-11-21 10:05:00 conveyor ' + j + ': v3-bedrooms: версия 3 принята, 351700 Б, complete=True',
         '2026-11-21 10:05:00 conveyor ZZZZ: v3-bedrooms: версия 3 принята, 1 Б, complete=True']
    tz = datetime.datetime.now().astimezone().strftime('%z')
    tz = tz[:3] + ':' + tz[3:]
    r = [f'2026-11-21T10:03:55{tz} [-|tour:{j}] тур {j}: фото в заготовки — вариантов 6, уже готово/в очереди 0, поставлено 6, пропущено 0',
         f'2026-11-21T10:04:10{tz} [aaa111|tour:{j}] рендер aaa111: готов за 12 с ({{}})',
         f'2026-11-21T10:04:22{tz} [bbb222|tour:{j}] рендер bbb222: готов за 12 с ({{}})',
         f'2026-11-21T10:09:00{tz} [ccc333|tour:{j}] рендер ccc333: готов за 12 с ({{}})',
         f'2026-11-21T10:09:30{tz} [ddd444|tour:other] рендер ddd444: готов за 12 с ({{}})',
         'строка без штампа рендер eee555: готов за 1 с']
    res = analyse(w, r, 'AbCdEf')
    st = {s['name']: s['from_take_s'] for s in res['stages']}
    ok(res['tour'] == j and st['v1 (стены)'] == 150 and st['v2 (гостиная)'] == 230 and st['v3 (спальни)'] == 300, 'стадии: v1 150 с, v2 230 с, v3 300 с от взятия')
    ok(st['первый кадр'] == 250 and st['последний кадр'] == 540 and res['frames'] == 3, 'кадры: только этого тура и только со штампом (3), первый 250 с, последний 540 с')
    ok(res['all_photos_min'] == 9.0 and res['v3_min'] == 5.0 and res['machine'] == 'started', 'все фото 9,0 мин, v3 5,0 мин, машина started')
    ok('все фото: 9.0 мин' in fmt(res) and 'v3: 5.0 мин' in fmt(res), 'текст отчёта')
    ok(analyse(w, r, 'Nope') is None, 'нет тура — None')
    res2 = analyse(w[:2], [], 'AbCdEf')
    ok(res2['all_photos_min'] is None and 'нет проштампованных' in fmt(res2), 'нет кадров в журнале — честное «нет проштампованных строк»')
    d = tempfile.mkdtemp()
    p = os.path.join(d, 'w.log')
    open(p, 'w', encoding='utf-8').write('\n'.join(w))
    ok(read_lines(p)[0].startswith('2026-11-21 10:00:00') and read_lines(os.path.join(d, 'нет')) == [], 'чтение файла; нет файла — пусто')
    print('ИТОГО:', 'ЧИСТО' if not bad else f'{bad} FAIL')
    return 1 if bad else 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    args = [a for a in argv if not a.startswith('--')]
    opt = {argv[i]: argv[i + 1] for i in range(len(argv) - 1) if argv[i] in ('--worker', '--render')}
    skip = set(opt.values())
    args = [a for a in args if a not in skip]
    if not args:
        print(__doc__)
        return 2
    res = analyse(read_lines(opt.get('--worker', WORKER)), read_lines(opt.get('--render', RENDER)), args[0])
    if res is None:
        print(f'тур «{args[0]}» в журнале воркера не найден (нет строки «<тур>: взял»)')
        return 2
    print(json.dumps(res, ensure_ascii=False, indent=1) if '--json' in argv else fmt(res))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
