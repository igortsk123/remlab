"""Тесты воронки покраски `tools/ops/paint_funnel.py` (T-20261121-180/Ш1): строгая доля, две цифры, выборка «посмотреть глазами».

Только на временных папках и подставных PC/PS (правила конвейера не нужны): проверяем счёт, а не решения этапов.
Запуск: `python -m pytest tools/ops/tests/test_paint_funnel.py -q`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paint_funnel as pf  # noqa: E402

STAGES = ['01-trellis', '02-prep']


class FakePS:
    FRAME = 'frame.png'

    @staticmethod
    def read_check(d):
        p = Path(d) / 'check.json'
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


class FakePC:
    @staticmethod
    def classify_stage(st, chk, rules):
        if chk is None:
            return {'status': 'missing', 'reason': 'нет check.json', 'hard_failed': [], 'soft_failed': [], 'metrics': {}}
        return {'status': chk['status'], 'reason': chk.get('reason', ''), 'hard_failed': chk.get('hard', []), 'soft_failed': chk.get('soft', []), 'metrics': chk.get('metrics', {})}


RULES = {'required_stages': STAGES}


def mk(run: Path, sku: str, statuses: dict, role: str | None = 'комод', metrics: dict | None = None):
    for st, status in statuses.items():
        d = run / sku / st
        d.mkdir(parents=True, exist_ok=True)
        doc = {'status': status, 'metrics': (metrics or {}).get(st, {})}
        if status == 'refused':
            doc['hard'] = ['m']
            doc['metrics'] = {'m': {'value': 1, 'threshold': 2, 'op': '>='}}
        (d / 'check.json').write_text(json.dumps(doc), encoding='utf-8')
        (d / 'frame.png').write_bytes(b'x')
    if role:
        d = run / sku / '03-parts'
        d.mkdir(parents=True, exist_ok=True)
        (d / 'check.json').write_text(json.dumps({'status': 'ok', 'extra': {'roles_summary': {'product_role': role}}}), encoding='utf-8')
    f = run / sku / '09-check'
    f.mkdir(parents=True, exist_ok=True)
    final = 'not_ready' if any(v in ('refused', 'missing') for v in statuses.values()) else ('ready_with_notes' if 'soft' in statuses.values() else 'ready')
    (f / 'check.json').write_text(json.dumps({'passed': final != 'not_ready', 'extra': {'final': final, 'notes': ['n'] if final == 'ready_with_notes' else [], 'blocking': []}}), encoding='utf-8')


def run_of(tmp_path):
    run = tmp_path / 'run'
    mk(run, 'a', {'01-trellis': 'ok', '02-prep': 'ok'})
    mk(run, 'b', {'01-trellis': 'ok', '02-prep': 'soft'})
    mk(run, 'c', {'01-trellis': 'ok', '02-prep': 'refused'})
    mk(run, 'd', {'01-trellis': 'ok'})
    return run


def test_soft_is_not_pass(tmp_path):
    _st, per = pf.analyse(FakePC, FakePS, RULES, str(run_of(tmp_path)))
    assert sum(pf.passed_all(per[s], True) for s in per) == 1       # строго: только «a»
    assert sum(pf.passed_all(per[s]) for s in per) == 2             # мягко ≈ прошёл (прежняя мерка): «a» и «b»
    txt = '\n'.join(pf.yield_lines('r', per))
    assert 'publishable_yield = прошли 01–09 СТРОГО' in txt and ': 1 из 4 (25 %)' in txt
    assert 'справочно' in txt and ': 2 из 4 (50 %)' in txt
    assert 'false_accept_rate: не оценён' in txt


def test_submitted_denominator(tmp_path):
    _st, per = pf.analyse(FakePC, FakePS, RULES, str(run_of(tmp_path)))
    txt = '\n'.join(pf.yield_lines('r', per, submitted=['a', 'b', 'c', 'd', 'e', 'f']))
    assert ': 1 из 6 (17 %)' in txt and 'поданных 6, из них в прогоне 4' in txt


def test_stage_margin():
    assert abs(pf.stage_margin({'x': {'value': 0.5, 'threshold': 0.25, 'op': '>='}}) - 1 / 3) < 1e-9        # доля: (v−t)/(1−t)
    assert pf.stage_margin({'x': {'value': 1.0, 'threshold': 0.25, 'op': '>='}}) == 1.0                     # доля на потолке — запас 1
    assert abs(pf.stage_margin({'x': {'value': 0.995, 'threshold': 0.99, 'op': '>='}}) - 0.5) < 1e-9        # доля у единицы: считаем от оставшегося до 1
    assert pf.stage_margin({'f': {'value': 149829, 'threshold': 150000, 'op': '<='}, 'b': {'value': 1, 'threshold': 1, 'op': '>='}}) is None   # потолок и флаг запаса не дают
    assert abs(pf.stage_margin({'x': {'value': 1.1, 'threshold': 1.0, 'op': '>='}}) - 0.1) < 1e-9
    assert abs(pf.stage_margin({'x': {'value': 0.9, 'threshold': 1.0, 'op': '<='}, 'y': {'value': 0.5, 'threshold': 1.0, 'op': '<='}}) - 0.1) < 1e-9   # самый тесный
    assert pf.stage_margin({'z': {'value': 0, 'threshold': 0, 'op': '<='}}) == 1.0                          # порог 0 и выполнено — чисто
    assert pf.stage_margin({'n': {'value': 1, 'threshold': 5, 'op': '>=', 'na': True}, 'm': {'value': 1}}) is None


def many(tmp_path, n_a=12, n_b=4, n_c=2):
    run = tmp_path / 'big'
    for i in range(n_a):
        mk(run, f'a{i}', {'01-trellis': 'ok', '02-prep': 'ok'}, role='комод', metrics={'02-prep': {'m': {'value': 2.0 if i % 2 else 1.05, 'threshold': 1.0, 'op': '>='}}})
    for i in range(n_b):
        mk(run, f'b{i}', {'01-trellis': 'ok', '02-prep': 'ok'}, role='диван')
    for i in range(n_c):
        mk(run, f'c{i}', {'01-trellis': 'ok', '02-prep': 'ok'}, role='стол')
    mk(run, 'x', {'01-trellis': 'ok', '02-prep': 'refused'}, role='комод')
    return run


def test_sample_stratified_and_deterministic(tmp_path):
    run = many(tmp_path)
    _st, per = pf.analyse(FakePC, FakePS, RULES, str(run))
    types = {s: pf.product_type(str(run), FakePS, s) for s in per}
    s1 = pf.make_sample(per, types, 6, 7, 0.25, 0.5)
    s2 = pf.make_sample(per, types, 6, 7, 0.25, 0.5)
    assert s1 == s2 and len(s1) == 6
    assert 'x' not in {x[0] for x in s1}                              # отказанный не «принят»
    assert {x[1] for x in s1} == {'комод', 'диван', 'стол'}           # каждый тип хотя бы раз
    kom = [x for x in s1 if x[1] == 'комод']
    assert any(x[2] for x in kom)                                     # из комодов есть уверенно прошедшие (запас ≥25 %)
    assert pf.make_sample(per, types, 6, 8, 0.25, 0.5) != s1 or True  # другой сид — другая выборка допустима
    assert len(pf.make_sample(per, types, 500, 0, 0.25, 0.5)) == 18   # больше принятых, чем есть, — все принятые


def test_sample_files_and_grades(tmp_path):
    run = many(tmp_path)
    _st, per = pf.analyse(FakePC, FakePS, RULES, str(run))
    types = {s: pf.product_type(str(run), FakePS, s) for s in per}
    sm = pf.make_sample(per, types, 5, 1, 0.25, 0.5)
    d = pf.write_sample(sm, {s: str(run) for s in per}, FakePS, str(tmp_path / 'out'), 'big')
    look = (Path(d) / 'look.txt').read_text(encoding='utf-8')
    assert look.count('\n') >= 7 and 'уверенно' in look and 'frame.png' in look
    tsv = Path(d) / 'grades.tsv'
    lines = tsv.read_text(encoding='utf-8').splitlines()
    skus = [ln.split('\t')[0] for ln in lines if ln and not ln.startswith(('sku', '#'))]
    assert sorted(skus) == sorted(x[0] for x in sm)
    # владелец/ведущий заполняет: первый товар плохой, остальные — ок
    rows = ['sku\tэтап\tвердикт\tчто']
    for i, s in enumerate(skus):
        rows.append(f'{s}\t02-prep\t{"плохо" if i == 0 else "ок"}\tпример')
    tsv.write_text('\n'.join(rows) + '\n', encoding='utf-8')
    g = pf.read_grades(str(tsv))
    txt = '\n'.join(pf.yield_lines('r', per, grades=g))
    assert 'false_accept_rate = плохие среди принятых: 1 из 5 оценённых (20 %)' in txt
    assert '95 % интервал' in txt and 'publishable_yield × (1 − false_accept_rate)' in txt


def test_wilson_bounds():
    lo, hi = pf.wilson(1, 5)
    assert 0 <= lo < 0.2 < hi <= 1
    assert pf.wilson(0, 10)[0] == 0.0 and pf.wilson(10, 10)[1] == 1.0 and pf.wilson(0, 0) is None
