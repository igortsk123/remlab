#!/usr/bin/env python3
"""R-FRONT-PHOTO-WITNESS (T-20261123-34/6, trial): «перёд» по долям известного/перевороту не спорит с фото (камерой 06).
Три случая круга 3 как заглушки (без ID товаров): стул/кресло с photo_side, перевёрнутая лампа без второго свидетеля, known_share с Δ0 — не трогаем.
Запуск: python tools/scout/tests/test_front_axis_witness.py   (нужен numpy)"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_front_axis_witness')
import front_axis as FA  # noqa: E402

G = FA.load_guard()


def res(**k):
    return FA.front_axis_resolved(R=G, **k)


# доли «перед/бок/зад/др. бок» относительно камеры 06
SIDE_MAX = {'перед': 0.49, 'бок': 0.35, 'зад': 0.35, 'др. бок': 0.68}      # кресло: боковая грань набирает долю (Δ270 от камеры)
FRONT_MAX = {'перед': 0.76, 'бок': 0.64, 'зад': 0.56, 'др. бок': 0.66}     # доли на стороне камеры (Δ0)
FLIP = {'перед': 0.29, 'бок': 0.26, 'зад': 0.40, 'др. бок': 0.23}          # зад известен больше перёда


def test_ambiguous_positive():
    """photo_side: доли указывают на 270° от камеры (стул/кресло, фото 3/4) → перёд = камера 06, пометка и запись в rules[]; доли с запасом 0,19 не спасают."""
    r = res(orient={'status': 'vlm_pending'}, shares=SIDE_MAX, photo_frontal=None, cam_az=326.0)
    assert r['theta'] == 326.0 and r['source'] == 'camera_ambiguous' and r['flags'] == ['front_ambiguous:photo_side'], r
    assert r['rules'][0]['rule_id'] == 'R-FRONT-PHOTO-WITNESS' and r['rules'][0]['rejected'] == {'source': 'known_share', 'theta': 236.0, 'delta': 90.0}, r
    r2 = res(orient={'status': 'vlm_pending'}, shares=FLIP, photo_frontal=True, cam_az=0.5, edge_agree=0.5587)
    assert r2['theta'] == 0.5 and r2['source'] == 'camera_ambiguous' and r2['rules'][0]['rejected']['source'] == 'camera04_flipped', r2     # переворот без свидетеля: кромки согласны с камерой
    r3 = res(orient={'status': 'vlm_pending'}, shares=FLIP, photo_frontal=True, cam_az=0.5)
    assert r3['source'] == 'camera_ambiguous', r3                                                                                       # кромок нет — свидетеля нет


def test_ambiguous_negative():
    """Не трогаем: known_share с Δ0; переворот со вторым свидетелем (кромки хуже edge_ref); orient-решение; правило выключено флагом — как до правила."""
    r = res(orient={'status': 'vlm_pending'}, shares=FRONT_MAX, photo_frontal=None, cam_az=55.5)
    assert r['theta'] == 55.5 and r['source'] == 'known_share' and r['flags'] == [] and 'rules' not in r, r
    r = res(orient={'status': 'vlm_pending'}, shares=FLIP, photo_frontal=True, cam_az=171.0, edge_agree=0.3)
    assert r['theta'] == 351.0 and r['source'] == 'camera04_flipped' and r['flags'] == [] and 'rules' not in r, r
    r = res(orient={'status': 'auto_resolved', 'source': 'orienter+seat_agree', 'legacy_front_yaw': 240}, shares=SIDE_MAX, photo_frontal=None, cam_az=326.0)
    assert r['theta'] == 240.0 and r['source'] == 'orient' and 'rules' not in r, r                                                       # решение orient — не долей
    import json
    import tempfile
    with open(FA.AXIS_RULES, encoding='utf-8') as f:
        rules = json.load(f)
    rules['photo_witness'] = False
    p = os.path.join(tempfile.mkdtemp(prefix='fawit-'), 'front-axis.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(rules, f)
    old, FA.AXIS_RULES = FA.AXIS_RULES, p
    try:
        r = res(orient={'status': 'vlm_pending'}, shares=SIDE_MAX, photo_frontal=None, cam_az=326.0)
    finally:
        FA.AXIS_RULES = old
    assert r['source'] == 'known_share' and r['theta'] == 236.0 and r['flags'] == ['photo_side'], r                                    # выключено флагом — поведение до правила


if __name__ == '__main__':
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith('test_') and callable(v):
            v()
            n += 1
            print('  ✓', k)
    print('OK: test_front_axis_witness %d проверок' % n)
