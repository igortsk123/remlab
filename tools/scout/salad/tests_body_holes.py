#!/usr/bin/env python3
"""Дыры внутри тела корпусной мебели (T-20261119-104/3): потерянный фасад комода (внутри дыры НЕ фон) возвращается; просвет, где виден фон кадра
(ножки пуфа, ажур консоли, стул/стеллаж), и вырез к внешнему фону остаются. Без сети и моделей.
  python tools/scout/salad/tests_body_holes.py"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import components as C  # noqa: E402

H, W = 300, 400
BOX = (60, 60, 340, 260)
FACADE = (100, 150, 200, 300)    # y0, y1, x0, x1 — потерянный фасад ящика
SMALL = (180, 200, 100, 140)


def body():
    a = np.zeros((H, W), np.float32)
    x0, y0, x1, y1 = BOX
    a[y0:y1, x0:x1] = 1.0
    return a


def holed(a):
    a = a.copy()
    for y0, y1, x0, x1 in (FACADE, SMALL):
        a[y0:y1, x0:x1] = 0
    return a


def photo(seethrough: bool):
    """Исходное фото: фон белый 255; тело светло-серое 235; фасад в дыре — белый, но чуть серее фона (240, как у белого ящика на белом),
    просвет — ровно фон 255 (виден сквозь ножки/ажур)."""
    r = np.full((H, W, 3), 255, np.uint8)
    x0, y0, x1, y1 = BOX
    r[y0:y1, x0:x1] = 235
    inner = 255 if seethrough else 240
    for y0_, y1_, x0_, x1_ in (FACADE, SMALL):
        r[y0_:y1_, x0_:x1_] = inner
    return r


def test_lost_facade_returned_and_control():
    a = holed(body())
    assert int((a[100:150, 200:300] == 0).sum()) == 5000, 'контроль: у синтетики нет дыры'
    out, info = C.fill_body_holes(a, photo(False), role='комод')
    assert (out[100:150, 200:300] > 0.5).all() and (out[180:200, 100:140] > 0.5).all(), 'потерянный фасад не возвращён'
    assert info == {'body_holes_filled': 2, 'body_holes_filled_px': 5800}, info
    for role in ('тумба прикроватная', 'тв-тумба', 'пуф', 'шкаф'):
        o, _ = C.fill_body_holes(a, photo(False), role=role)
        assert (o[100:150, 200:300] > 0.5).all(), role


def test_seethrough_hole_kept():
    """Настоящий просвет (ножки пуфа, ажурный каркас, рама): внутри ровно фон — не залить, иначе вместо ножек получится белая плита."""
    a = holed(body())
    out, info = C.fill_body_holes(a, photo(True), role='пуф')
    assert (out == a).all(), 'просвет с фоном внутри залит'
    assert info == {'body_holes_seethrough': 2}, info


def test_nonsolid_roles_untouched():
    a = holed(body())
    for role in ('стул', 'стеллаж', 'стол обеденный', 'столик', 'люстра', 'торшер', 'кровать', 'кресло', None, ''):
        out, info = C.fill_body_holes(a, photo(False), role=role)
        assert (out == a).all() and info == {}, f'роль {role!r} тронута: {info}'


def test_open_notch_not_a_hole():
    """Вырез, открытый к внешнему фону (проём между ножками, угол), — не замкнутая дыра: не трогаем даже у комода."""
    a = body()
    a[200:260, 150:190] = 0
    out, info = C.fill_body_holes(a, photo(False), role='комод')
    assert (out == a).all() and info == {}, info


def test_switch_off_cap_and_bg_threshold():
    a = holed(body())
    out, info = C.fill_body_holes(a, photo(False), role='комод', max_share=0)
    assert (out == a).all() and info.get('body_holes_off'), info
    # порог по площади: тело ≈ 56000 px, дыры 5000 (9 %) и 800 (1,4 %); при пороге 5 % крупная остаётся, мелкая возвращается
    out2, info2 = C.fill_body_holes(a, photo(False), role='комод', max_share=0.05)
    assert (out2[100:150, 200:300] == 0).all(), 'крупнее порога — залита'
    assert (out2[180:200, 100:140] > 0.5).all() and info2['body_holes_filled'] == 1, info2
    # порог «фона»: bg_max=0 — ничего не считается просветом… и наоборот, 1.01 — залито всё, где фон не 100 %
    o3, i3 = C.fill_body_holes(a, photo(True), role='комод', bg_max=1.01)
    assert (o3[100:150, 200:300] > 0.5).all() and i3['body_holes_filled'] == 2, i3


def test_glass_roles_and_old_list_unchanged():
    a = holed(body())
    out, _ = C.fill_body_holes(a, photo(False), role='ваза')
    assert (out[100:150, 200:300] > 0.5).all()
    assert C.SOLID_SILHOUETTE_ROLES == {'ваза', 'кашпо', 'статуэтка'} and C.SOLID_SILHOUETTE_ROLES < C.SOLID_BODY_ROLES, 'старый список менять нельзя (меши)'


def test_alpha_soft_values_kept_and_empty():
    a = body()
    a[70:80, 70:80] = 0.8
    a = holed(a)
    out, _ = C.fill_body_holes(a, photo(False), role='комод')
    assert np.allclose(out[70:80, 70:80], 0.8)
    e = np.zeros((H, W), np.float32)
    o2, i2 = C.fill_body_holes(e, photo(False), role='комод')
    assert (o2 == 0).all() and i2 == {}


if __name__ == '__main__':
    bad = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('  ok ', name)
            except AssertionError as e:
                bad += 1
                print('  FAIL', name, '-', e)
    print('итог:', 'OK' if not bad else f'{bad} провалов')
    sys.exit(1 if bad else 0)
