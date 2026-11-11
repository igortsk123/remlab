"""T-20261111-20: балкон/лоджия за наружной стеной — комната результата (`tools/floorplan/outdoor.py`, `pipeline.outdoor_room`).

Синтетический лист: дом — толстая стена (модель панели: пол и полоса стен в метрах), снаружи — балкон тонкими линиями, подпись VLM
`balcony` без комнаты модели (`label_report.room is None`). Лёгкие: без сети, без стенда."""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.append(str(ROOT / 'tools' / 'scout'))          # в конец: у scout свой pipeline.py
import outdoor as OD  # noqa: E402
import pipeline as pl  # noqa: E402
import trial_bundle as TB  # noqa: E402

PPM = 50.0                       # px на метр листа
X0, Y0 = 0, 0


def m(px):
    return px / PPM


def sheet(gap=False):
    """Лист 600×600: дом 100..500 × 250..550 (стена 10 px), балкон 200..400 × 130..250 тонкой линией (gap — линия разорвана)."""
    g = np.full((600, 600), 255, np.uint8)
    cv2.rectangle(g, (100, 250), (500, 550), 40, 10)
    cv2.line(g, (200, 250), (200, 130), 90, 2)
    cv2.line(g, (400, 250), (400, 130), 90, 2)
    cv2.line(g, (200, 130), (400, 130) if not gap else (330, 130), 90, 2)
    cv2.putText(g, '2.40', (270, 190), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 90, 1)
    return g


def model():
    ring = [[m(105), m(255)], [m(495), m(255)], [m(495), m(545)], [m(105), m(545)]]
    wall = {'outer': [[m(95), m(245)], [m(505), m(245)], [m(505), m(555)], [m(95), m(555)]], 'holes': [ring]}
    return {'floors': [{'outer': ring, 'holes': [], 'room': 1}], 'bands': [{'z0': 0, 'z1': 2.6, 'polys': [wall]}],
            'rooms': [{'id': 1, 'names': ['Bedroom'], 'area_m2': 45.0}]}


P = {'bbox_px': [X0, Y0, 600, 600], 'ppm': PPM, 'label_report': [
    {'name': 'Balcony', 'pt': [300, 185], 'dims': None, 'room': None, 'space': True},
    {'name': 'Bedroom', 'pt': [300, 400], 'dims': None, 'room': 1, 'space': True}]}
G_BY = {'Balcony': {'name': 'Balcony', 'name0': 'Balcony', 'vtype': 'balcony', 'vtype_src': 'position', 'area_m2': 9.6,
                    'area_reduced_m2': 2.9, 'name_src': 'type'}}


def test_balcony_built_outside_wall():
    got, fl = OD.build(P, model(), G_BY, sheet(), 10.0)
    assert fl == [] and len(got) == 1
    b = got[0]
    assert 0.8 <= b['area_m2'] / 9.6 <= 1.2                # 4 × 2,4 м по линиям
    xs, ys = [p[0] for p in b['contour_m']], [p[1] for p in b['contour_m']]
    assert abs(min(xs) - 4.0) < 0.15 and abs(max(xs) - 8.0) < 0.15 and abs(min(ys) - 2.6) < 0.15
    assert max(ys) <= 5.0 + 0.05                          # до наружной грани стены, не внутрь дома
    room = pl.outdoor_room(0, 0, b, G_BY, {}, True)
    assert room['kind'] == 'other' and room['name'] == 'Balcony' and room['areaM2'] == 9.6
    assert {'outdoor', 'outdoor_outline', 'area_reduced', 'kind_by_position'} <= set(room['flags'])


def test_open_outline_not_built():
    got, fl = OD.build(P, model(), G_BY, sheet(gap=True), 10.0)
    assert got == [] and fl == ['outdoor_not_built']


def test_area_far_from_label_not_built():
    g = dict(G_BY['Balcony'], area_m2=30.0)              # контур втрое меньше подписи — это не он
    got, fl = OD.build(P, model(), {'Balcony': g}, sheet(), 10.0)
    assert got == [] and fl == ['outdoor_not_built']


def test_found_room_untouched():
    p = dict(P, label_report=[dict(P['label_report'][0], room=1)])
    assert OD.build(p, model(), G_BY, sheet(), 10.0) == ([], [])


def test_name_only_without_area_not_built():
    g = {'Balcony': dict(G_BY['Balcony'], area_m2=None)}      # «Terrace» без площади: сад за домом не отличить
    assert OD.build(P, model(), g, sheet(), 10.0) == ([], ['outdoor_not_built'])


def test_printed_dims_stand_for_area():
    g = {'Balcony': dict(G_BY['Balcony'], area_m2=None, dims_m=[4.0, 2.4])}  # «4.00 x 2.40 m» без площади (Giraffe360)
    got, fl = OD.build(P, model(), g, sheet(), 10.0)
    assert fl == [] and len(got) == 1 and 0.8 <= got[0]['area_m2'] / 9.6 <= 1.2
    assert OD.printed_area({'dims_m': [1.34, 2.62]}) == 3.51 and OD.printed_area({'dims_m': None}) is None


def test_label_on_furniture_picks_best_candidate():
    s = sheet()
    cv2.rectangle(s, (240, 150), (270, 175), 90, 1)        # «кресло» под точкой подписи — маленькая замкнутая петля
    p = dict(P, label_report=[dict(P['label_report'][0], pt=[255, 162])])
    got, fl = OD.build(p, model(), G_BY, s, 10.0)
    assert fl == [] and len(got) == 1 and 0.8 <= got[0]['area_m2'] / 9.6 <= 1.2


def test_is_outdoor_names():
    assert OD.is_outdoor(None, 'Roof Terrace') and OD.is_outdoor(None, 'Лоджия') and OD.is_outdoor(None, 'Decking')
    assert not OD.is_outdoor(None, 'Garden room') and not OD.is_outdoor(None, 'Bedroom')


BAL = {'contour': [[400, 260], [800, 260], [800, 500], [400, 500]], 'flags': ['outdoor']}
HOST = {'contour': [[100, 510], [900, 510], [900, 1000], [100, 1000]], 'flags': []}
PPM_CM = 0.5                     # px листа на см результата


def host_sheet(arc_at=None):
    """Лист 600×600 под HOST/BAL в px (= см × 0,5); arc_at — x конца проёма (px), у которого внутри комнаты нарисована дуга двери."""
    g = np.full((600, 600), 255, np.uint8)
    if arc_at is not None:
        cv2.ellipse(g, (arc_at, 255), (37, 37), 0, 0, 90 if arc_at < 300 else 180, 60, 2)
        cv2.line(g, (arc_at, 255), (arc_at, 292), 60, 2)
    return g


def test_exit_block_split_at_arc_door_appended():
    ops = [{'kind': 'window', 'c': [600, 505], 'widthCm': 150.0, 'exterior': True},
           {'kind': 'door', 'c': [100, 800], 'widthCm': 80.0, 'exterior': False}]
    out, how = OD.exits(ops, [HOST], BAL, host_sheet(arc_at=263), PPM_CM, 0, 0)   # дуга у левого конца (525 см → 262 px)
    assert how == 'block' and [o['kind'] for o in out] == ['window', 'door', 'door']
    assert out[0]['widthCm'] == 75.0 and out[2]['widthCm'] == OD.DOOR_W_CM
    assert out[2]['c'][0] < out[0]['c'][0] and abs(out[0]['c'][0] - out[2]['c'][0]) == 75.0
    assert out[1] == ops[1]                                # номера прежних проёмов не сдвинулись


def test_exit_no_arc_unresolved():
    ops = [{'kind': 'window', 'c': [600, 505], 'widthCm': 150.0, 'exterior': True}]
    assert OD.exits(ops, [HOST], BAL, host_sheet(), PPM_CM, 0, 0) == (ops, 'unresolved')


def test_exit_narrow_window_kept():
    ops = [{'kind': 'window', 'c': [600, 505], 'widthCm': 90.0, 'exterior': True}]
    assert OD.exits(ops, [HOST], BAL, host_sheet(arc_at=278), PPM_CM, 0, 0) == (ops, 'unresolved')


def test_exit_door_present_unchanged():
    ops = [{'kind': 'window', 'c': [500, 505], 'widthCm': 150.0, 'exterior': True},
           {'kind': 'door', 'c': [700, 505], 'widthCm': 80.0, 'exterior': True}]
    assert OD.exits(ops, [HOST], BAL, host_sheet(), PPM_CM, 0, 0) == (ops, None)


def test_far_window_not_exit():
    ops = [{'kind': 'window', 'c': [600, 900], 'widthCm': 150.0, 'exterior': True}]
    assert OD.exits(ops, [HOST], BAL, host_sheet(), PPM_CM, 0, 0) == (ops, 'unresolved')


def test_outdoor_excluded_from_scale_by_labels():
    rooms = [{'areaM2': 10.0, 'areaContourM2': 10.0, 'flags': ['area_from_label']} for _ in range(3)]
    rooms.append({'areaM2': 2.7, 'areaContourM2': 5.0, 'flags': ['area_from_label', 'outdoor']})
    assert pl.scale_by_labels([{'rooms': rooms}]) == ['scale_labels_ok']


def test_bundle_marks_outdoor_not_furnished():
    def room(rid, kind, contour, name, flags=()):
        xs, ys = [p[0] for p in contour], [p[1] for p in contour]
        return {'id': rid, 'name': name, 'kind': kind, 'contour': contour, 'areaM2': 20.0, 'flags': list(flags),
                'bbox': {'x': min(xs), 'y': min(ys), 'w': max(xs) - min(xs), 'd': max(ys) - min(ys)}}
    res = {'version': 1, 'units': 'cm', 'source': {'mime': 'image/png', 'pages': 1, 'usedPages': 1, 'imageW': 1, 'imageH': 1},
           'scale': {'status': 'listing', 'ppm': 50, 'inliers': 3, 'n': 3}, 'flags': [], 'timings': {}, 'costUsd': 0,
           'panels': [{'id': 'p0', 'title': 'Plan', 'walls': [{'z0': 0, 'z1': 270, 'polys': []}],
                       'rooms': [room('r1', 'living', [[0, 0], [500, 0], [500, 400], [0, 400]], 'Lounge'),
                                 room('o0', 'other', [[100, -200], [400, -200], [400, 0], [100, 0]], 'Balcony', ['outdoor'])],
                       'openings': [{'kind': 'window', 'c': [250, 400], 'widthCm': 120, 'exterior': True},
                                    {'kind': 'door', 'c': [500, 200], 'widthCm': 90, 'exterior': False}]}]}
    ctx = {'rules': {'sofa_tv_cm': [180, 300]}, 'msid_of': lambda s: f'm-{s}', 'slot_band': lambda g: {'диван': {'min': g['w']}},
           'quiz': {'questions': [{'id': 'style', 'ru': 'Стиль?', 'en': 'Style?'}]}}
    d = TB.build('AbCdEfGhIjKlMnOpQrStUv', res, None, ctx=ctx)
    bal = next(r for r in d['apartment_rooms'] if r['id'] == 'outdoor-1')
    assert bal['kind'] == 'other' and bal['outdoor'] is True and bal['furniture_state'] == 'not_furnished' and bal['titleRu'] == 'Балкон'
    assert not any(r.get('outdoor') for r in d['apartment_rooms'] if r['id'] != 'outdoor-1')
