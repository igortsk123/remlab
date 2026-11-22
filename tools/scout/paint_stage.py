#!/usr/bin/env python3
"""Общий модуль «проверка на каждом этапе» пути покраски (план paint-photo-fill-01 § «Проверка на каждом этапе», владелец TG 187).
Каждый этап пишет в папку товара `<run>/<sku>/NN-<этап>/` свой выход, `check.json` (прошёл / не прошёл, мерки с порогами, причина) и один контрольный кадр `frame.png`.
Не прошёл — товар дальше не идёт. Этот файл — ЕДИНСТВЕННЫЙ писатель и читатель `check.json`; своих форматов этапы не заводят. Только стандартная библиотека.

Схема `check.json` (version 1):
  {"version": 1, "stage": "07-fill", "sku": "<sku>", "passed": true,
   "metric": {"name": "...", "value": 0.997, "threshold": 0.99, "op": ">=", "ok": true},            # главная мерка этапа (нет — null)
   "metrics": {"имя": {"value": …, "threshold": …, "op": "<=", "ok": true}, …},                       # остальные мерки (каждая со своим порогом; `passed` = все ok, если не задано явно)
   "extra": {…любые числа этапа…}, "reason": "", "seconds": 71.2, "outputs": ["файл", …], "frame": "frame.png"}
Использование:
  from paint_stage import stage_dir, write_check, judge, read_check, summary
  d = stage_dir(run, sku, '07-fill')                       # создаёт папку, имя sku безопасно для файловой системы
  ok = judge(0.0, '<=', 0.0)                              # сравнение по op: '>=', '<=', '>', '<', '=='
  write_check(d, '07-fill', sku, passed=None, metric={'name': 'empty_share', 'value': 0.0, 'threshold': 0.0, 'op': '<='}, metrics={…}, reason='', seconds=12.3, outputs=['tex.png'], frame='frame.png', faces=149800)
  python3 tools/scout/paint_stage.py table <run>          # сводная таблица товар × этап (md)
  python3 tools/scout/paint_stage.py --selftest
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile

VERSION = 1
OPS = {'>=': lambda a, b: a >= b, '<=': lambda a, b: a <= b, '>': lambda a, b: a > b, '<': lambda a, b: a < b, '==': lambda a, b: a == b}
FILE = 'check.json'
FRAME = 'frame.png'


def safe_name(s: str) -> str:
    """sku `mid:eid` и подобное → имя папки без `:`/`/`/пробелов."""
    return re.sub(r'[^0-9A-Za-zА-Яа-я_.@+-]+', '_', str(s)).strip('_') or 'x'


def stage_dir(run: str, sku: str, stage: str) -> str:
    """`<run>/<sku>/<stage>/` (создаётся)."""
    d = os.path.join(run, safe_name(sku), stage)
    os.makedirs(d, exist_ok=True)
    return d


def judge(value, op: str, threshold) -> bool:
    """Мерка прошла? `value` None или не число → не прошла (нет измерения — не «ок»)."""
    if op not in OPS:
        raise ValueError(f'op {op!r}: ждём одно из {sorted(OPS)}')
    if value is None or threshold is None:
        return False
    try:
        return bool(OPS[op](value, threshold))
    except TypeError:
        return False


def _norm_metric(m: dict | None) -> dict | None:
    if m is None:
        return None
    out = dict(m)
    if 'value' not in out:
        raise ValueError('мерка без value')
    if 'ok' not in out:
        out['ok'] = judge(out['value'], out.get('op', '>='), out.get('threshold')) if out.get('threshold') is not None else None
    return out


def write_check(stage_dir_: str, stage: str, sku: str, passed: bool | None = None, metric: dict | None = None, reason: str = '', *,
                metrics: dict | None = None, seconds: float | None = None, outputs: list | None = None, frame: str | None = None, **extra) -> dict:
    """Пишет `<stage_dir>/check.json` атомарно, возвращает словарь. `passed=None` — вывести: все мерки (главная и `metrics`) с порогом прошли и хотя бы одна есть.
    Мерка без порога (`threshold` нет) — справочная, на `passed` не влияет. Не прошёл и нет причины → причина собирается из непрошедших мерок."""
    m1 = _norm_metric(metric)
    ms = {k: _norm_metric(v) for k, v in (metrics or {}).items()}
    judged = [m['ok'] for m in ([m1] if m1 else []) + list(ms.values()) if m and m.get('ok') is not None]
    if passed is None:
        passed = bool(judged) and all(judged)
    failed = [f"{(m1 or {}).get('name', 'metric')} {m1['value']} {m1.get('op', '>=')} {m1.get('threshold')}"] if m1 and m1.get('ok') is False else []
    failed += [f"{k} {m['value']} {m.get('op', '>=')} {m.get('threshold')}" for k, m in ms.items() if m and m.get('ok') is False]
    if not passed and not reason:
        reason = 'не прошли: ' + '; '.join(failed) if failed else 'нет измерений'
    doc = {'version': VERSION, 'stage': stage, 'sku': sku, 'passed': bool(passed), 'metric': m1, 'metrics': ms, 'extra': extra, 'reason': reason,
           'seconds': None if seconds is None else round(float(seconds), 2), 'outputs': list(outputs or []), 'frame': frame}
    os.makedirs(stage_dir_, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.check-', suffix='.tmp', dir=stage_dir_)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=False, default=_json_default)
        f.write('\n')
    os.replace(tmp, os.path.join(stage_dir_, FILE))
    return doc


def _json_default(o):
    """numpy-числа и массивы — в обычные."""
    for attr in ('item', 'tolist'):
        if hasattr(o, attr):
            return getattr(o, attr)()
    raise TypeError(f'{type(o).__name__} не сериализуется')


def read_check(stage_dir_: str) -> dict | None:
    """Прочитать `check.json` этапа; нет файла или он битый → None (этап считается не пройденным)."""
    try:
        with open(os.path.join(stage_dir_, FILE), encoding='utf-8') as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) and 'passed' in doc else None
    except (OSError, ValueError):
        return None


def gate(run: str, sku: str, stages: list) -> tuple[bool, str]:
    """Можно ли товару идти дальше: все этапы `stages` (имена папок) имеют `check.json` с passed. → (да/нет, первая причина)."""
    for st in stages:
        c = read_check(os.path.join(run, safe_name(sku), st))
        if c is None:
            return False, f'{st}: нет check.json'
        if not c['passed']:
            return False, f"{st}: {c.get('reason') or 'не прошёл'}"
    return True, ''


def summary(run: str) -> str:
    """Таблица товар × этап по всем `check.json` под `<run>/<sku>/NN-*/`: ✓ — прошёл, ✗ — нет (+причина), · — этапа нет."""
    skus = sorted(d for d in os.listdir(run) if os.path.isdir(os.path.join(run, d))) if os.path.isdir(run) else []
    stages, rows = set(), {}
    for s in skus:
        cur = {}
        for st in sorted(os.listdir(os.path.join(run, s))):
            if re.match(r'^\d\d-', st) and os.path.isdir(os.path.join(run, s, st)):
                c = read_check(os.path.join(run, s, st))
                cur[st] = c
                stages.add(st)
        if cur:
            rows[s] = cur
    stages = sorted(stages)
    out = ['| товар | ' + ' | '.join(stages) + ' |', '|' + '---|' * (len(stages) + 1)]
    for s, cur in rows.items():
        cells = []
        for st in stages:
            c = cur.get(st)
            cells.append('·' if st not in cur else ('?' if c is None else ('✓' if c['passed'] else '✗ ' + (c.get('reason') or '')[:60])))
        out.append(f'| {s} | ' + ' | '.join(cells) + ' |')
    return '\n'.join(out)


def selftest() -> int:
    import remlab_tmp  # временное самопроверки — в REMLAB_TMP, не в /tmp
    remlab_tmp.use("paint_stage_selftest")
    bad = 0

    def ok(c, name):
        nonlocal bad
        print(('  ✓ ' if c else '  ✗ ') + name)
        bad += 0 if c else 1
    with tempfile.TemporaryDirectory() as run:
        d = stage_dir(run, '114667:838', '07-fill')
        ok(os.path.basename(os.path.dirname(d)) == '114667_838', 'имя sku безопасно')
        doc = write_check(d, '07-fill', '114667:838', None, {'name': 'empty_share', 'value': 0.0, 'threshold': 0.0, 'op': '<='},
                          metrics={'dE00_front_back': {'value': 2.1, 'threshold': 6.0, 'op': '<='}, 'info_only': {'value': 5}}, seconds=3.14159, outputs=['t.png'], frame=FRAME, faces=10)
        ok(doc['passed'] is True and read_check(d)['metric']['ok'] is True, 'все мерки с порогом прошли → passed; справочная мерка не мешает')
        ok(read_check(d)['seconds'] == 3.14 and read_check(d)['extra'] == {'faces': 10}, 'seconds и extra записаны')
        d2 = stage_dir(run, '114667:838', '02-prep')
        bad_doc = write_check(d2, '02-prep', '114667:838', None, {'name': 'color_texel_share', 'value': 0.9, 'threshold': 0.99, 'op': '>='})
        ok(bad_doc['passed'] is False and 'color_texel_share' in bad_doc['reason'], 'не прошла мерка → passed false, причина из мерок')
        ok(write_check(stage_dir(run, 'x', '01-trellis'), '01-trellis', 'x', None)['reason'] == 'нет измерений', 'нет измерений — не «ок»')
        ok(judge(None, '<=', 1) is False and judge(1, '>=', 1) and judge(1, '<', 2), 'judge: None не проходит, операторы работают')
        try:
            judge(1, '=>', 1)
            ok(False, 'неверный op отвергнут')
        except ValueError:
            ok(True, 'неверный op отвергнут')
        g, why = gate(run, '114667:838', ['07-fill'])
        ok(g and why == '', 'gate: этап прошёл — можно дальше')
        g, why = gate(run, '114667:838', ['07-fill', '02-prep'])
        ok(not g and why.startswith('02-prep'), 'gate: не прошёл этап — стоп с причиной')
        ok(not gate(run, '114667:838', ['09-qa'])[0], 'gate: нет check.json — стоп')
        t = summary(run)
        ok('✓' in t and '✗' in t and '07-fill' in t, 'сводная таблица товар × этап')
        try:
            import numpy as np
        except ImportError:
            np = None
        if np is not None:
            d3 = stage_dir(run, 'np', '07-fill')
            write_check(d3, '07-fill', 'np', None, {'name': 'a', 'value': np.float64(0.5), 'threshold': 1.0, 'op': '<='}, k=np.int64(3))
            ok(read_check(d3)['extra']['k'] == 3, 'numpy-числа сериализуются')
    print(f'paint_stage selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--selftest':
        raise SystemExit(selftest())
    if len(sys.argv) > 2 and sys.argv[1] == 'table':
        print(summary(sys.argv[2]))
        raise SystemExit(0)
    print(__doc__)
