"""T-20261116-60: сверка площади этажа с напечатанной (`tools/floorplan/area_checks.py`, этап 1 — «тень»). Лёгкие: без сети,
без стенда, на синтетических панелях и золоте A/B/C (`tools/floorplan/gold/*.json` — только строки `areas`).
Мера (gia / rooms / unknown, × k²), привязка (заголовок, единственный рисунок, повторы, First Floor / First Wing, House /
Outbuildings, куски), порог (ровно 5 % / 3 м²), золото, сквозной `pipeline.to_result` (лист без площадей — результат прежний)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import area_checks as ac  # noqa: E402
import pipeline as pl  # noqa: E402
from test_pipeline import SRC, area_synth, assert_contract, synth, write_models  # noqa: E402

GOLD = ROOT / 'tools' / 'floorplan' / 'gold'


def pan(i, title, gia=None, k=1.0):
    return {'panel': f'panel{i}', 'vlm_title': title, 'bbox_px': [i * 100, 0, i * 100 + 90, 90], 'ppm': 50.0, 'gia_m2': gia}


def one(areas, panels, **kw):
    return ac.floor_area_checks(areas, panels, **kw)


def by_label(res):
    return {c['label']: c for c in res}


# ── мера ────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('label, measure', [
    ('Ground Floor', 'gia'), ('GIA', 'gia'), ('Gross Internal Area', 'gia'), ('Total floor area', 'gia'),
    ('Общая площадь', 'rooms'), ('Площадь этажа', 'rooms'), ('1 этаж', 'rooms'),
    ('NIA', 'unknown'), ('Net internal area', 'unknown'), ('Living area', 'unknown'), ('Usable area', 'unknown'),
    ('Total (inc. restricted head height)', 'unknown'), ('Жилая площадь', 'unknown'), ('Площадь кухни', 'unknown'),
])
def test_measure_by_printed_wording(label, measure):
    assert ac.measure_of(label) == measure


def test_measure_gia_uses_panel_gia_and_k_squared():
    # gia_m2 панели не умножена на k (модели — уже): при масштабе по площади нужен gia × k²
    P = pan(0, 'Ground Floor', gia=30.0)
    assert ac.reconstructed_m2(P, 'gia', None, 1.0, []) == 30.0
    assert ac.reconstructed_m2(P, 'gia', None, 4.0, []) == 120.0
    r = one([{'label': 'Ground Floor', 'm2': 120.0}], [P, pan(1, 'First Floor', gia=30.0)], k={tuple(P['bbox_px']): 2.0})[0]
    assert r['reconstructedM2'] == 120.0 and r['status'] == 'ok' and r['measure'] == 'gia'


def test_measure_rooms_sums_geometric_rooms_not_printed_areas():
    # русская «общая» — сумма геометрических комнат модели (уже × k²); балкон и «excl.» вычитаются; печатные площади комнат не участвуют
    P = pan(0, 'Этаж 1', gia=999.0)
    models = {tuple(P['bbox_px']): {'rooms': [{'names': ['Кухня'], 'area_m2': 20.0}, {'names': ['Спальня'], 'area_m2': 30.0},
                                              {'names': ['Балкон'], 'area_m2': 5.0}]}}
    r = one([{'label': 'Этаж 1', 'm2': 50.0}], [P], models=models)[0]
    assert (r['measure'], r['reconstructedM2'], r['status']) == ('rooms', 50.0, 'ok')      # gia_m2 игнорируется, балкон не в счёте
    assert one([{'label': 'Этаж 1', 'm2': 50.0}], [P])[0]['status'] == 'inconclusive'        # моделей нет — нечем сверять
    assert one([{'label': 'Этаж 1', 'm2': 50.0}], [P])[0]['note'] == 'no_geometry'


def test_measure_unknown_not_compared():
    r = one([{'label': 'Ground Floor NIA', 'm2': 10.0}], [pan(0, 'Ground Floor', gia=60.0)])[0]
    assert r['status'] == 'inconclusive' and r['measure'] == 'unknown' and 'reconstructedM2' not in r and r['note'] == 'measure_unknown'


def test_excl_in_label_removes_named_rooms_from_gia():
    P = pan(0, 'Plan', gia=100.0)
    models = {tuple(P['bbox_px']): {'rooms': [{'names': ['Garage'], 'area_m2': 20.0}, {'names': ['Lounge'], 'area_m2': 70.0}]}}
    r = one([{'label': 'Total area (excl. garage)', 'm2': 80.0}], [P], models=models)[0]
    assert r['reconstructedM2'] == 80.0 and r['status'] == 'ok'


# ── привязка ────────────────────────────────────────────────────────────────────────────────────

def test_assoc_exact_title():
    ps = [pan(0, 'Ground Floor', 60.0), pan(1, 'First Floor', 60.0)]
    r = by_label(one([{'label': 'ground  floor.', 'm2': 60.0}, {'label': 'First Floor', 'm2': 60.0}], ps))
    assert r['ground floor.']['panelIds'] == ['p0'] and r['ground floor.']['association'] == 'title'
    assert r['First Floor']['panelIds'] == ['p1']


def test_assoc_title_inside_label():
    ps = [pan(0, 'Ground Floor', 60.0), pan(1, 'First Floor', 60.0)]
    r = one([{'label': 'Ground Floor GIA', 'm2': 60.0}], ps)[0]
    assert r['panelIds'] == ['p0'] and r['association'] == 'title_in_label' and r['status'] == 'ok'
    # в подписи два заголовка — не знаем чей: без привязки
    r = one([{'label': 'Ground Floor + First Floor', 'm2': 120.0}], ps)[0]
    assert r['panelIds'] == [] and r['status'] == 'inconclusive'


def test_first_floor_vs_first_wing_never_confused():
    ps = [pan(0, 'First Floor', 60.0), pan(1, 'First Wing', 20.0)]
    r = by_label(one([{'label': 'First Floor', 'm2': 60.0}, {'label': 'First Wing', 'm2': 20.0}], ps))
    assert r['First Floor']['panelIds'] == ['p0'] and r['First Wing']['panelIds'] == ['p1']
    # «Floor» — не подпись «First Wing» и не «First Floor» целиком: к «First Floor» только по полному заголовку
    r = one([{'label': 'Floor', 'm2': 60.0}], ps)[0]
    assert r['panelIds'] == [] and r['status'] == 'inconclusive'
    # заголовок «Floor» внутри подписи «First Floor»: берётся полный («First Floor»), а не короткий
    ps = [pan(0, 'Floor', 10.0), pan(1, 'First Floor', 60.0)]
    r = one([{'label': 'First Floor area', 'm2': 60.0}], ps)[0]
    assert r['panelIds'] == ['p1']


def test_duplicate_titles_not_assigned():
    ps = [pan(0, 'Floor', 60.0), pan(1, 'Floor', 60.0)]
    r = one([{'label': 'Floor', 'm2': 60.0}], ps)[0]
    assert r['panelIds'] == [] and r['status'] == 'inconclusive'
    # коды `Floor 1`/`Floor 2` из `bench.panels_by_titles` печатной «Floor» не отвечают
    ps = [pan(0, 'Floor 1', 60.0), pan(1, 'Floor 2', 60.0)]
    assert one([{'label': 'Floor', 'm2': 60.0}], ps)[0]['panelIds'] == []


def test_single_drawing_single_area():
    ps = [pan(0, 'Floor 1', 97.8)]
    r = one([{'label': 'Approximate total area (excl. balconies)', 'm2': 90.3}], ps)[0]
    assert r['association'] == 'single' and r['panelIds'] == ['p0']
    # одна нетотальная площадь + «Total» на одном рисунке — «своя» нетотальная
    r = by_label(one([{'label': 'Plan', 'm2': 90.0}, {'label': 'Total', 'm2': 90.0}], [pan(0, None, 90.0)]))
    assert list(r) == ['Plan'] and r['Plan']['association'] == 'single'
    # две нетотальные площади на одном рисунке — не угадываем
    r = one([{'label': 'A', 'm2': 40.0}, {'label': 'B', 'm2': 50.0}], [pan(0, None, 90.0)])
    assert [c['status'] for c in r] == ['inconclusive', 'inconclusive'] and not any(c['panelIds'] for c in r)


def test_two_drawings_unmatched_area_is_inconclusive_and_total_skipped():
    ps = [pan(0, 'Ground Floor', 60.0), pan(1, 'First Floor', 60.0)]
    r = one([{'label': 'Total', 'm2': 120.0}], ps)
    assert r == []                                           # агрегат листа — `pipeline.scale_of`
    r = one([{'label': 'Garage', 'm2': 20.0}], ps)[0]
    assert r['scope'] == 'sheet' and r['status'] == 'inconclusive' and r['association'] == 'none'


def test_house_and_outbuildings_are_groups_never_a_floor():
    ps = [pan(0, 'House', 600.0), pan(1, 'Outbuildings', 180.0)]
    r = by_label(one([{'label': 'House', 'm2': 611.0}, {'label': 'Outbuildings', 'm2': 184.0}], ps))
    for c in r.values():
        assert c['scope'] == 'group' and c['status'] == 'inconclusive' and c['panelIds'] == [] and c['association'] == 'group'
    # и при единственном рисунке «House» не становится его площадью
    r = one([{'label': 'House', 'm2': 611.0}], [pan(0, 'Ground Floor', 300.0)])[0]
    assert r['scope'] == 'group' and r['panelIds'] == []


def test_outdoor_only_area_is_not_a_floor():
    # тень T-60 (лист giraffe): VLM положил в areas «Balconies and terraces 3,5» — к единственному рисунку это не привязывается
    r = one([{'label': 'Balconies and terraces', 'm2': 3.5}], [pan(0, None, 61.8)])
    assert len(r) == 1 and r[0]['status'] == 'inconclusive' and r[0]['panelIds'] == [] and r[0]['note'] == 'outdoor_not_floor'
    # и не мешает «своей» площади единственного рисунка; «excl. balconies» в подписи — пояснение, не балкон
    r = by_label(one([{'label': 'Balcony', 'm2': 3.5}, {'label': 'Total area (excl. balconies)', 'm2': 60.0}], [pan(0, None, 61.8)]))
    assert r['Balcony']['status'] == 'inconclusive' and r['Total area (excl. balconies)']['association'] == 'single'
    assert r['Total area (excl. balconies)']['status'] == 'ok'
    assert ac.is_outdoor('Лоджия') and not ac.is_outdoor('Approx. area (excluding balconies)')


def test_pieces_of_one_drawing_never_checked_alone():
    ps = [pan(0, None, 30.0), pan(1, None, 28.0)]
    r = one([{'label': 'Plan', 'm2': 58.0}], ps, panels_src='pieces')[0]
    assert r['status'] == 'inconclusive' and r['panelIds'] == []
    # один кусок — это весь рисунок
    r = one([{'label': 'Plan', 'm2': 30.0}], [pan(0, None, 30.0)], panels_src='pieces')[0]
    assert r['status'] == 'ok' and r['association'] == 'single'
    # заголовки есть, но куски — всё равно не выше inconclusive
    ps = [pan(0, 'Ground Floor', 30.0), pan(1, 'First Floor', 28.0)]
    r = one([{'label': 'Ground Floor', 'm2': 30.0}], ps, panels_src='pieces')[0]
    assert r['status'] == 'inconclusive' and r['note'] == 'pieces'


@pytest.mark.parametrize('flag', ['panel_title_guess', 'panel_titles_merged', 'vlm_panels_disagree', 'area_pages_skipped'])
def test_blockers_cap_status_at_inconclusive(flag):
    ps = [pan(0, 'Ground Floor', 30.0), pan(1, 'First Floor', 28.0)]
    r = one([{'label': 'Ground Floor', 'm2': 10.0}], ps, blockers=[flag])[0]
    assert r['status'] == 'inconclusive' and r['note'] == f'blocked:{flag}' and r['reconstructedM2'] == 30.0
    assert one([{'label': 'Ground Floor', 'm2': 10.0}], ps)[0]['status'] == 'mismatch'


def test_two_different_areas_for_one_drawing_ambiguous():
    ps = [pan(0, 'Ground Floor', 60.0), pan(1, 'First Floor', 60.0)]
    r = one([{'label': 'Ground Floor', 'm2': 60.0}, {'label': 'Ground Floor GIA', 'm2': 30.0}], ps)
    assert all(c['status'] == 'inconclusive' and c['note'] == 'ambiguous_rows' for c in r)
    r = one([{'label': 'Ground Floor', 'm2': 60.0}, {'label': 'Ground Floor GIA', 'm2': 60.04}], ps)
    assert all(c['status'] == 'ok' for c in r)


def test_area_scale_single_drawing_is_circular():
    r = one([{'label': 'Total', 'm2': 120.0}], [pan(0, 'Plan', 120.0)], scale_status='area')[0]
    assert r['status'] == 'inconclusive' and r['note'] == 'circular_area_scale'
    ps = [pan(0, 'Ground Floor', 60.0), pan(1, 'First Floor', 60.0)]
    assert one([{'label': 'Ground Floor', 'm2': 60.0}], ps, scale_status='area')[0]['status'] == 'ok'   # этажей несколько — есть что сверять


# ── порог ───────────────────────────────────────────────────────────────────────────────────────

def test_threshold_exactly_5_percent_and_3_m2_is_not_mismatch():
    # 5 % линейно: 100 → 110,25 (√1,1025 = 1,05); разница 10,25 м² > 3
    assert ac.compare(100.0, 110.25)[0] == 'ok'
    assert ac.compare(100.0, 110.3)[0] == 'mismatch'
    assert ac.compare(100.0, 90.25)[0] == 'ok' and ac.compare(100.0, 90.2)[0] == 'mismatch'
    # разница ровно 3,0 м² (а линейно далеко за 5 %): 10 → 13
    assert ac.compare(10.0, 13.0)[0] == 'ok'
    assert ac.compare(10.0, 13.01)[0] == 'mismatch'
    assert ac.compare(10.0, 7.0)[0] == 'ok' and ac.compare(10.0, 6.99)[0] == 'mismatch'
    # «примерно» — 7,5 % и 5 м²
    assert ac.compare(100.0, 114.0, approx=True)[0] == 'ok' and ac.compare(100.0, 116.0, approx=True)[0] == 'mismatch'
    assert ac.compare(100.0, 114.0)[0] == 'mismatch'


def test_missing_room_is_caught_and_reported_in_check():
    ps = [pan(0, 'Ground Floor', 50.0), pan(1, 'First Floor', 60.0)]
    r = by_label(one([{'label': 'Ground Floor', 'm2': 64.0}, {'label': 'First Floor', 'm2': 61.0}], ps))
    assert r['Ground Floor']['status'] == 'mismatch' and r['Ground Floor']['scaleDelta'] < -0.05
    assert r['First Floor']['status'] == 'ok'


# ── золото A/B/C ────────────────────────────────────────────────────────────────────────────────

def gold_areas(name):
    return [{'label': a['label'], 'm2': a['m2']} for a in json.loads((GOLD / f'{name}.json').read_text())['areas']]


def test_gold_A_both_floors_ok_total_skipped():
    ps = [pan(0, 'Ground Floor', 64.637), pan(1, 'First Floor', 63.677)]     # GIA стенда (метрики t38 bench-after3)
    r = one(gold_areas('A'), ps)
    assert [c['label'] for c in r] == ['Ground Floor', 'First Floor']
    assert [c['status'] for c in r] == ['ok', 'ok'] and [c['association'] for c in r] == ['title', 'title']
    assert [c['panelIds'] for c in r] == [['p0'], ['p1']]


def test_gold_B_plus_8_3_percent_is_not_mismatch():
    r = one(gold_areas('B'), [pan(0, 'Floor 1', 97.827)])
    assert len(r) == 1 and r[0]['status'] == 'ok' and r[0]['association'] == 'single'
    assert abs(r[0]['reconstructedM2'] / r[0]['printedM2'] - 1 - 0.0833) < 0.001 and 0 < r[0]['scaleDelta'] < 0.05


def test_gold_C_house_and_outbuildings_inconclusive():
    ps = [pan(0, 'Ground Floor', 300.0), pan(1, 'First Floor', 200.0), pan(2, 'Outbuildings', 180.0)]
    r = by_label(one(gold_areas('C'), ps))
    assert set(r) == {'House', 'Outbuildings'}
    assert all(c['status'] == 'inconclusive' and c['panelIds'] == [] and c['scope'] == 'group' for c in r.values())


# ── сквозной pipeline.to_result ─────────────────────────────────────────────────────────────────

def test_sheet_without_areas_result_unchanged(tmp_path):
    log, models, G = synth()
    write_models(tmp_path, models)
    base = pl.to_result(log, tmp_path, 'T', G, SRC, 0.01, {'labels': 1.0}, [], False)
    assert 'areaChecks' not in base
    for none in ([], None, [{'label': 'x', 'm2': 0}, {'label': 'y', 'm2': 'нет'}]):
        res = pl.to_result(log, tmp_path, 'T', G, SRC, 0.01, {'labels': 1.0}, [], False, None, none)
        assert json.dumps(res, sort_keys=True) == json.dumps(base, sort_keys=True)


def test_areas_only_add_the_optional_field(tmp_path):
    log, models, G = area_synth(gia_m2=30.0)
    log['panels'][0]['inliers'] = [('Lounge', 'p95', 0), ('Bedroom #2', 'p95', 0)]      # масштаб по подписям: listing
    write_models(tmp_path, models)
    base = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], False)
    res = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], False, None, [{'label': 'GIA', 'm2': 30.0}])
    assert_contract(res)
    ck = res.pop('areaChecks')
    assert json.dumps(res, sort_keys=True) == json.dumps(base, sort_keys=True)       # остальное — как было
    assert len(ck) == 1 and ck[0]['status'] == 'ok' and ck[0]['reconstructedM2'] == 30.0 and ck[0]['association'] == 'single'
    bad = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], False, None, [{'label': 'GIA', 'm2': 20.0}])
    assert_contract(bad)
    assert bad['areaChecks'][0]['status'] == 'mismatch'
    assert not any(f.startswith('area_') and 'mismatch' in f for f in bad['flags'])     # без новых флагов: только запись
    assert all('awaiting' not in f for f in bad['flags'])


def test_area_scale_multiplies_gia_by_k_squared_and_is_circular_for_one_drawing(tmp_path):
    log, models, G = area_synth()                                 # ppm угадан 50 → по площади 120 м² 25 px/м: метры × 2, площадь × 4
    write_models(tmp_path, models)
    a = {'m2': 120.0, 'src': 'text', 'approx': True, 'excl': [], 'conv': 'gia', 'raw': '', 'flags': []}
    res = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], True, a, [{'label': 'Total', 'm2': 120.0}])
    assert_contract(res)
    ck = res['areaChecks'][0]
    assert res['scale']['status'] == 'area' and ck['reconstructedM2'] == 120.0          # 30 × 2², а не 30
    assert ck['status'] == 'inconclusive' and ck['note'] == 'circular_area_scale'


def test_pages_skipped_blocks(tmp_path):
    log, models, G = area_synth(gia_m2=30.0)
    log['panels'][0]['inliers'] = [('Lounge', 'p95', 0), ('Bedroom #2', 'p95', 0)]
    write_models(tmp_path, models)
    res = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, ['pages_skipped'], False, None, [{'label': 'GIA', 'm2': 20.0}])
    assert res['areaChecks'][0]['status'] == 'inconclusive' and res['areaChecks'][0]['note'] == 'blocked:area_pages_skipped'
