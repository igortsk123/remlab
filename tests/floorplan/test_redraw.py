"""Перерисовка шумного листа (T-20261110-17, `tools/floorplan/redraw.py`, `pipeline.redraw_stage`): выключатель, когда звать,
приёмка дверей/окон/связности против разбора оригинала.

Лёгкие — синтетика моделей разбора (комнаты-прямоугольники, проёмы в метрах панели): потерянная дверь/окно → отказ, обрезок
шума между комнатами убран → принято, выдуманная дверь → отказ, слитая комната разрезана без двери → отказ.
Тяжёлые (DEV: лист A стенда и кэш VLM) — `FP_REDRAW=force` с бесплатной «перерисовкой»-тождеством: итог = разбор оригинала +
флаг, 0 $; без выключателя — папки `redraw/` нет и результат тот же (без поля времени и флага).
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.insert(1, str(ROOT / 'tools' / 'ops'))
import pipeline as pl  # noqa: E402
import redraw as rd  # noqa: E402

BBOX = [0, 0, 400, 200]


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def model(rooms, openings):
    """rooms: [(id, [имена], (x0, y0, x1, y1) м)], openings: [(kind, (x, y) м, exterior)] → (log, models, res)."""
    m = {'ppm': 50.0, 'bbox_px': BBOX,
         'rooms': [{'id': i, 'names': n, 'area_m2': (b[2] - b[0]) * (b[3] - b[1])} for i, n, b in rooms],
         'floors': [{'room': i, 'outer': rect(*b), 'holes': []} for i, _n, b in rooms],
         'openings': [{'kind': k, 'c': list(c), 'width_m': 0.8, 'exterior': e} for k, c, e in openings]}
    labs = [{'name': n, 'room': i} for i, ns, _b in rooms for n in ns]
    log = {'thickness_px': 10.0, 'panels': [{'bbox_px': BBOX, 'ppm': 50.0, 'label_report': labs}]}
    res = {'scale': {'status': 'area'}, 'flags': [], 'panels': [{
        'rooms': [{'name': ' + '.join(n), 'areaM2': (b[2] - b[0]) * (b[3] - b[1]),
                   'flags': (['unlabeled'] if not n else []) + (['merged'] if len(n) > 1 else [])} for _i, n, b in rooms],
        'openings': [{'kind': k, 'widthCm': 80.0} for k, _c, _e in openings]}]}
    return log, {tuple(BBOX): m}, res


A, B = (1, ['A'], (0.1, 0.1, 1.9, 1.9)), (2, ['B'], (2.1, 0.1, 3.9, 1.9))
DOOR_AB, WIN_A, DOOR_OUT = ('door', (2.0, 1.0), False), ('window', (1.0, 0.0), True), ('door', (3.0, 2.0), True)


def decide(orig, clean):
    lo, mo, ro = model(*orig)
    lc, mc, rc = model(*clean)
    return rd.decide(ro, lo, mo, rc, lc, mc)


def test_same_plan_is_not_better():
    d = decide(([A, B], [DOOR_AB, WIN_A, DOOR_OUT]), ([A, B], [DOOR_AB, WIN_A, DOOR_OUT]))
    assert not d['accept'] and d['why'] == 'not_better'
    assert d['openings'] == {'orig': 3, 'clean': 3, 'matched': 3} and d['links_orig'] == 2  # A–B, B–OUT


def test_lost_door_is_rejected():
    d = decide(([A, B], [DOOR_AB, WIN_A, DOOR_OUT]), ([A, B], [WIN_A, DOOR_OUT]))
    assert not d['accept'] and d['why'] == 'door_lost' and d['lost_doors_px'] == [[100, 50]]


def test_lost_window_is_rejected():
    d = decide(([A, B], [DOOR_AB, WIN_A, DOOR_OUT]), ([A, B], [DOOR_AB, DOOR_OUT]))
    assert not d['accept'] and d['why'] == 'window_lost'


def test_invented_window_and_door_are_rejected():
    d = decide(([A, B], [DOOR_AB, DOOR_OUT]), ([A, B], [DOOR_AB, DOOR_OUT, WIN_A]))
    assert d['why'] == 'window_new'
    d = decide(([A, B], [DOOR_AB, DOOR_OUT]), ([A, B], [DOOR_AB, DOOR_OUT, ('door', (2.0, 0.4), False)]))
    assert d['why'] == 'door_new'                          # вторая дверь A–B дальше допуска (0,35 м) — выдумана


def test_noise_fragment_removed_is_accepted():
    """Оригинал: обрезок шума F (без подписи) режет A, ложная дверь A–F; связь A–B идёт через F. Чистый: A целиком, та же
    дверь к B. Связность та же (обрезок прозрачен), ложная дверь в обрезок — не «потеря», безымянных меньше → принято."""
    a_part, frag = (1, ['A'], (0.1, 0.1, 1.0, 1.9)), (3, [], (1.2, 0.8, 1.9, 1.9))
    d = decide(([a_part, frag, B], [('door', (1.1, 1.4), False), DOOR_AB, WIN_A, DOOR_OUT]),
               ([A, B], [DOOR_AB, WIN_A, DOOR_OUT]))
    assert d['accept'] and d['why'] is None, d
    assert 'small_unlabeled' in d['better'] and d['lost_links'] == []


def test_merged_room_split():
    """Слитая «A + B» (стена потерялась на шуме): чистый разрезал её — части обязаны сообщаться; дверь между частями —
    не «выдуманная», рёбра второго имени — не «потерянные» (имена слитой комнаты — одна вершина графа)."""
    merged = (1, ['A', 'B'], (0.1, 0.1, 3.9, 1.9))
    d = decide(([merged], [WIN_A, DOOR_OUT]), ([A, B], [WIN_A, DOOR_OUT]))
    assert not d['accept'] and d['why'] == 'link_lost' and ['split', 'A+B'] in d['lost_links']
    d = decide(([merged], [WIN_A, DOOR_OUT]), ([A, B], [DOOR_AB, WIN_A, DOOR_OUT]))
    assert d['accept'] and d['better'] == ['merged'], d


def test_fragment_inside_named_room_of_other_parse_is_that_room():
    """Оригинал: середина — безымянный обрезок F (подпись «B» комнату не нашла), связь A–F–C даёт ребро A–C. Чистый: на
    месте F — названная B, рёбра A–B, B–C. Без `absorb` это «потеря A–C»; F лежит в B чистого — значит, F и есть B."""
    a, f, c = (1, ['A'], (0.1, 0.1, 1.9, 1.9)), (2, [], (2.1, 0.1, 3.9, 1.9)), (3, ['C'], (4.1, 0.1, 5.9, 1.9))
    doors = [('door', (2.0, 1.0), False), ('door', (4.0, 1.0), False)]
    d = decide(([a, f, c], doors), ([a, (2, ['B'], f[2]), c], doors))
    assert d['accept'] and d['lost_links'] == [] and 'unlabeled' in d['better'], d


def test_worse_labels_is_rejected():
    d = decide(([A, B], [DOOR_AB, DOOR_OUT]), ([A, (2, [], B[2])], [DOOR_AB, DOOR_OUT]))
    assert not d['accept'] and d['why'] in ('link_lost', 'worse:labels_found+unlabeled')


def test_alarm_reasons():
    log, _m, res = model([A, B], [DOOR_AB])
    assert rd.alarm(res, log) == []
    res['panels'][0]['rooms'].append({'name': '', 'areaM2': 0.6, 'flags': ['unlabeled']})
    res['panels'][0]['rooms'][0]['flags'].append('merged')
    res['panels'][0]['openings'].append({'kind': 'door', 'widthCm': 40.0})
    log['panels'][0]['label_report'].append({'name': 'C', 'room': None})
    assert rd.alarm(res, log) == ['small_unlabeled:1', 'merged:1', 'labels_lost:1/3', 'narrow_doors:1']


def test_mode_and_cap(monkeypatch):
    assert rd.mode({}) == 'off' and rd.mode({'FP_REDRAW': '0'}) == 'off'
    assert rd.mode({'FP_REDRAW': '1'}) == 'on' and rd.mode({'FP_REDRAW': 'force'}) == 'force'
    assert rd.cap_usd({}) == rd.CAP_USD and rd.cap_usd({'FP_REDRAW_CAP_USD': '0.05'}) == 0.05
    assert rd.CAP_USD >= rd.PRICE_USD[rd.ENGINE]          # одна картинка входит в свой потолок, вторая — нет


def test_add_flag_first_and_capped():
    res = {'flags': [f'f{i}' for i in range(30)]}
    rd.add_flag(res, 'redraw_rejected:door_lost')
    assert res['flags'][0] == 'redraw_rejected:door_lost' and len(res['flags']) == 30


def test_attempt_budget_and_cache_only_ask_nothing(tmp_path):
    """Потолок ниже цены картинки — платного вызова нет; `cache_only` без кэша — тоже нет; сбой — не исключение."""
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (300, 200), 'white')
    ImageDraw.Draw(im).rectangle([20, 20, 280, 180], outline='black', width=8)
    p = tmp_path / 'sheet.png'
    im.save(p)

    def boom(*a, **kw):
        raise AssertionError('платный вызов в тесте')
    a = rd.attempt(p, tmp_path / 'vlm', 'T', tmp_path / 'r1', draw=boom, cap=0.01, cache_root=tmp_path / 'c')
    assert a['why'] == 'budget' and a['usd'] == 0 and a['clean'] is None
    a = rd.attempt(p, tmp_path / 'vlm', 'T', tmp_path / 'r2', draw=boom, cache_only=True, cache_root=tmp_path / 'c')
    assert a['why'] == 'cache_only' and (tmp_path / 'r2' / 'redraw.json').exists()
    # тождество: «перерисовка» = отправленный лист → подгонка ~1, стены честные, ответ — в кэш; повтор — из кэша (0 $)
    calls = []

    def ident(sent, prompt, ar, engine):
        calls.append(ar)
        return sent, 0.0
    a = rd.attempt(p, tmp_path / 'vlm', 'T', tmp_path / 'r3', draw=ident, cache_root=tmp_path / 'c')
    assert a['clean'] and a['align']['ok'] and a['walls']['f_wall'] > 0.97, a
    b = rd.attempt(p, tmp_path / 'vlm', 'T', tmp_path / 'r4', draw=boom, cache_root=tmp_path / 'c')
    assert b['cached'] and b['clean'] and len(calls) == 1


def test_redraw_stage_failure_keeps_original(tmp_path, monkeypatch):
    """Перерисовка не удалась (модель ответила ошибкой, деньги списаны) → итог — разбор оригинала, флаг, цена учтена."""
    log, _m, res = model([A, B, (3, [], (2.1, 2.1, 2.6, 2.6))], [DOOR_AB])
    res.update(timings={'walls': 1.0}, costUsd=0.03)
    monkeypatch.setattr(rd, 'attempt', lambda *a, **kw: {'clean': None, 'usd': 0.1, 'why': 'model'})
    paid = []
    out = pl.redraw_stage(res, 'on', image=tmp_path / 'x.png', vlm_dir=tmp_path, plan='T', G={'rooms': []}, log=log,
                          out=tmp_path / 'bench', workdir=tmp_path, slot=False, job='-', vlm_usd=0.03, T={}, fl=[],
                          area=None, source={}, spent=paid.append)
    assert out['flags'][0] == 'redraw_rejected:model' and out['panels'] == res['panels']
    assert out['costUsd'] == pytest.approx(0.13) and paid == [pytest.approx(0.13)] and 'redraw' in out['timings']
    d = json.loads((tmp_path / 'redraw' / 'decision.json').read_text())
    assert d['alarm'] == ['small_unlabeled:1']
    # спокойный разбор при FP_REDRAW=1 — перерисовку не зовём, результат тот же объект
    log2, _m2, res2 = model([A, B], [DOOR_AB])
    monkeypatch.setattr(rd, 'attempt', lambda *a, **kw: pytest.fail('звать не должны'))
    assert pl.redraw_stage(res2, 'on', image=tmp_path / 'x.png', vlm_dir=tmp_path, plan='T', G={'rooms': []}, log=log2,
                           out=tmp_path, workdir=tmp_path, slot=False, job='-', vlm_usd=0.0, T={}, fl=[], area=None,
                           source={}) is res2


# ── тяжёлые: лист A стенда, кэш VLM (0 $) ──

BENCH = Path('/home/pakar/remlab-logs/floorplan-bench')
IMG_A, VLM = BENCH / 'inputs' / 'A-uk-house-125m2.jpg', BENCH / 'vlm-t04'
heavy = pytest.mark.skipif(not (IMG_A.exists() and VLM.is_dir()), reason='нет листа A/кэша VLM стенда (только DEV)')


def _forbid(*a, **kw):
    raise AssertionError('платный вызов VLM в тесте')


@heavy
def test_force_with_identity_redraw_keeps_original_result(tmp_path, monkeypatch):
    monkeypatch.delenv('FP_REDRAW', raising=False)
    base = pl.run(IMG_A, '', tmp_path / 'off', vlm_dir=VLM, plan='A', ask=_forbid, slot=False)
    assert not (tmp_path / 'off' / 'redraw').exists()
    monkeypatch.setenv('FP_REDRAW', 'force')
    monkeypatch.setattr(rd, 'CACHE_ROOT', tmp_path / 'rcache')
    monkeypatch.setattr(rd, 'draw_gateway', lambda sent, prompt, ar, engine: (sent, 0.0))
    res = pl.run(IMG_A, '', tmp_path / 'force', vlm_dir=VLM, plan='A', ask=_forbid, slot=False)
    d = json.loads((tmp_path / 'force' / 'redraw' / 'decision.json').read_text())
    assert d['redraw']['clean'], d
    assert res['flags'][0].startswith(('redraw_rejected:', 'redraw_used')) and res['costUsd'] == 0
    if res['flags'][0].startswith('redraw_rejected:'):
        strip = {k: v for k, v in res.items() if k != 'timings'}
        strip['flags'] = res['flags'][1:]
        assert json.dumps(strip, sort_keys=True) == json.dumps({k: v for k, v in base.items() if k != 'timings'},
                                                               sort_keys=True)
