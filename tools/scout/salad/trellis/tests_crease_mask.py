"""Тесты crease_mask (T-194/1, T-194/2): мерки «тёмные полосы у изломов» и карта уверенности. Синтетика, без GPU и сети.
Сцена: кадр 160×160, две грани (id 0 слева, id 1 справа) встречаются по колонке x=80 под углом 60° (излом), гладкая панель L≈150, тёмная линия-«тень щели» шириной 2 px со сдвигом 5 px от излома.
Запуск: python tests_crease_mask.py → «ошибок 0»."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np
import crease_mask as CM

bad = 0


def ok(cond, msg):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + msg)
    if not cond:
        bad += 1


N, X0 = 160, 80


def geoms(angle_deg: float) -> list:
    """Один геом из двух треугольников: нормаль первого (0,0,1), второго — повёрнута на angle_deg вокруг оси Y."""
    a = np.radians(angle_deg)
    V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0],
                  [0, 0, 0], [np.cos(a), 0, -np.sin(a)], [0, 1, 0]], float)
    F = np.array([[0, 1, 2], [3, 5, 4]], np.int64)
    return [{'V': V, 'F': F}]


def stage(iou: float = 0.70) -> dict:
    ids = np.zeros((N, N), np.int32)
    ids[:, X0:] = 1
    mask = np.ones((N, N), bool)
    return {'mask': mask, 'ids': ids, 'depth': np.full((N, N), 5.0, np.float32), 'px': N, 'px_len': 1.0, 'iou_frame': iou}


def photo(line_x: int | None = 85, line_w: int = 2, wide: int = 0, tone: int = 150) -> np.ndarray:
    rng = np.random.RandomState(3)
    L = np.clip(tone + rng.normal(0, 1.5, (N, N)), 0, 255)
    rgb = np.repeat(L[..., None], 3, axis=2).astype(np.uint8)
    if line_x is not None:
        rgb[:, line_x:line_x + line_w] = 55                 # тонкая тёмная линия (тень щели), смещена от излома
    if wide:
        rgb[20:60, 100:100 + wide] = 55                    # широкий тёмный участок (рисунок/узор), не щель
    return rgb


def test_crease_found_and_flat_has_none():
    print('излом по растру камеры:')
    r = CM.load_rules()
    c = CM.crease_pixels(stage()['ids'], stage()['depth'], stage()['mask'], CM.face_normals(geoms(60)), 1.0, r)
    cols = sorted(set(np.nonzero(c)[1].tolist()))
    ok(cols == [X0 - 1, X0], f'излом по колонкам {X0 - 1},{X0} (получили {cols})')
    c0 = CM.crease_pixels(stage()['ids'], stage()['depth'], stage()['mask'], CM.face_normals(geoms(5)), 1.0, r)
    ok(not c0.any(), '± контроль: грани почти в одной плоскости (5° < порога) — излома нет')
    st = stage()
    st['depth'][:, X0:] = 80.0                              # разрыв глубины = край заслонения, не излом
    c1 = CM.crease_pixels(st['ids'], st['depth'], st['mask'], CM.face_normals(geoms(60)), 1.0, r)
    ok(not c1.any(), 'разрыв глубины (край силуэта/заслонение) — не излом')


def test_groove_and_measures():
    print('щель по форме при тёмной линии на фото; мерки:')
    st, prgb = stage(), photo()
    pm = np.ones((N, N), bool)
    valid = np.ones((N, N), bool)
    cs = CM.crease_shadow(prgb, pm, st, geoms(60))
    s = cs['stats']
    ok(cs['groove'][:, X0].all() and cs['groove'][:, X0 - 1].all(), 'щель (колонки излома) отмечена по всей высоте')
    ok(not cs['groove'][:, 85:87].any(), 'щель — по форме меша, не на смещённой линии фото')
    ok(cs['slit_rgb'] is not None and abs(cs['slit_rgb'][0] - 55) < 3, f'тон щели = медиана тёмной линии фото ({cs["slit_rgb"]})')
    ok(s['groove_px'] > 0 and s['k'] >= 2 and s['evidence_components'] >= 1, f'счётчики: groove_px={s["groove_px"]}, k={s["k"]}')
    before = CM.dark_streak_share(prgb, cs['band'], cs['groove'], valid, st['mask'])
    ok(before['share_pct'] is not None and before['share_pct'] > 1.0, f'dark_streak_share на фото = {before["share_pct"]} % (тёмная линия вне щели)')
    clean = prgb.copy()
    clean[:, 85:87] = 150                                    # «итог» без тёмных полос
    after = CM.dark_streak_share(clean, cs['band'], cs['groove'], valid, st['mask'])
    ok(after['share_pct'] is not None and after['share_pct'] <= 0.2, f'dark_streak_share у чистого итога = {after["share_pct"]} % (≤ 0,2)')
    painted = clean.copy()
    painted[cs['groove']] = np.clip(cs['slit_rgb'], 0, 255).astype(np.uint8)
    sc = CM.slit_contrast_ratio(prgb, painted, cs, st['mask'], valid)
    ok(sc['ratio'] is not None and sc['ratio'] >= 0.5, f'контраст щели: ratio {sc["ratio"]} ≥ 0,5 (щель по форме темна, как на фото)')
    sc0 = CM.slit_contrast_ratio(prgb, clean, cs, st['mask'], valid)
    ok(sc0['ratio'] is not None and sc0['ratio'] < 0.5, f'щель пропала в итоге — ratio {sc0["ratio"]} < 0,5')


def test_controls():
    print('± контроль: широкое тёмное, нет линии, нет излома:')
    st = stage()
    pm = np.ones((N, N), bool)
    cn = CM.crease_shadow(photo(line_x=None), pm, st, geoms(60))
    ok(not cn['groove'].any() and cn['slit_rgb'] is None, 'излом есть, а тёмной линии на фото нет — щели нет')
    cf = CM.crease_shadow(photo(), pm, st, geoms(5))
    ok(not cf['groove'].any() and cf['stats']['crease_px'] == 0 and not cf['band'].any(), 'гладкий предмет без изломов (стул/диван без бороздок) — полосы и щели нет')
    ok(CM.dark_streak_share(photo(), cf['band'], cf['groove'], pm, st['mask'])['share_pct'] is None, 'без полосы мерка None (нечего мерить)')
    cw = CM.crease_shadow(photo(line_x=None, wide=20), pm, st, geoms(60))
    ok(not cw['groove'].any(), 'широкий тёмный участок (рисунок ткани/узор) не считается щелью — не тонкий')


def test_band():
    print('полоса растёт с остатком силуэта:')
    r = CM.load_rules()
    ok(CM.band_k(1536, 0.99, r) < CM.band_k(1536, 0.80, r) <= r['k_max'], 'хуже остаток силуэта — шире полоса, не больше k_max')
    ok(CM.band_k(1536, None, r) == r['k_min'], 'нет IoU — k_min')


def test_confidence():
    print('уверенность пикселя: у излома и блика ниже, на гладкой панели 1,0:')
    st, pm = stage(), np.ones((N, N), bool)
    prgb = photo(line_x=None)
    prgb[100:110, 20:30] = 250                                   # блик на панели далеко от излома
    cs = CM.crease_shadow(prgb, pm, st, geoms(60))
    cf = CM.frame_confidence(prgb, pm, st, cs)
    r = CM.load_rules()
    ok(abs(float(cf[40, 20]) - 1.0) < 1e-6, 'гладкая панель вдали от излома и бликов — 1,0')
    ok(abs(float(cf[40, X0]) - r['conf_band']) < 1e-6, f'у излома — conf_band ({r["conf_band"]})')
    ok(abs(float(cf[105, 25]) - r['conf_highlight']) < 1e-6, f'блик — conf_highlight ({r["conf_highlight"]})')
    ok(float(cf.min()) > 0.0 and float(cf.max()) <= 1.0, 'значения в (0, 1]')


def test_dark_streak_new():
    print('мерка «тёмное у излома, которого нет на фото» (T-194/2):')
    H, Wd = 120, 160
    band = np.zeros((H, Wd), bool)
    band[:, 70:90] = True
    mask = np.ones((H, Wd), bool)
    valid = np.ones((H, Wd), bool)
    groove = np.zeros((H, Wd), bool)
    photo0 = np.full((H, Wd, 3), 150, np.uint8)
    r = CM.load_rules()
    d0 = CM.dark_streak_new(photo0.copy(), photo0, mask, band, groove, valid, mask, r)
    ok(d0['share_pct'] == 0.0 and d0['streak_px'] == 0, 'ровная панель: брака нет')
    after1 = photo0.copy()
    after1[:, 78:80] = 60                                                   # тёмная полоса есть в итоге…
    d1 = CM.dark_streak_new(after1, photo0, mask, band, groove, valid, mask, r)
    ok(d1['share_pct'] > 5 and d1['streak_in_photo_px'] == 0, f'…а на фото её нет — это брак ({d1["share_pct"]} %)')
    p2 = photo0.copy()
    p2[:, 78:80] = 60                                                       # дизайнерский зазор есть и на фото
    d2 = CM.dark_streak_new(after1, p2, mask, band, groove, valid, mask, r)
    ok(d2['share_pct'] == 0.0 and d2['streak_px'] > 0, 'такая же полоса на фото — дизайн, не брак (streak есть, new = 0)')
    p3 = photo0.copy()
    p3[:, 80:82] = 60                                                       # фото-щель сдвинута на 2 px от меша
    d3 = CM.dark_streak_new(after1, p3, mask, band, groove, valid, mask, r)
    ok(d3['share_pct'] == 0.0, 'сдвиг щели фото ≤ photo_dark_grow_px не считается браком')
    p4 = photo0.copy()
    p4[:, 90:94] = 60                                                       # на фото тёмное, но дальше photo_dark_grow_px от полосы итога
    d4 = CM.dark_streak_new(after1, p4, mask, band, groove, valid, mask, dict(r, photo_dark_grow_px=3))
    ok(d4['share_pct'] > 5, 'тёмное на фото далеко от полосы итога — брак остаётся')
    d5 = CM.dark_streak_new(after1, photo0, mask, band, groove, valid & False, mask, r)
    ok(d5['share_pct'] is None, 'нет валидных пикселей — мерка None')


def test_body_zone():
    print('зона корпуса (T-194/4): ножки и кромка вне корпуса, мерка ножек отдельно:')
    H, Wd = 200, 200
    mask = np.zeros((H, Wd), bool)
    mask[20:140, 20:180] = True                                             # корпус: строки 20…139, ширина 160
    mask[140:200, 25:35] = True                                             # две ножки по 10 px
    mask[140:200, 165:175] = True
    zone, cut = CM.body_zone(mask)
    ok(zone[20, 100] and zone[100, 100] and not zone[199, 30] and not zone[150, 170], 'верх корпуса — в зоне, ножки — вне зоны')
    ok(120 < cut <= 140, f'граница зоны выше низа корпуса на запас (cut={cut}; низ корпуса 139)')
    zc, cc = CM.body_zone(mask, cut_row=60)
    ok(cc == 60 and zc[59, 100] and not zc[60, 100], 'cut_row (body_only) ниже по смыслу не расширяет, а сужает зону')
    mf = np.zeros((H, Wd), bool)
    mf[20:200, 20:180] = True                                               # шкаф до пола: ножек нет
    zf, cf = CM.body_zone(mf)
    ok(cf < 200 and cf > 150, f'без ножек граница = низ − запас ({cf})')
    band = np.zeros((H, Wd), bool)
    band[:, 90:110] = True                                                   # полоса изломов на корпусе
    band[:, 26:34] = True                                                    # и вдоль ножки
    valid = np.ones((H, Wd), bool)
    groove = np.zeros((H, Wd), bool)
    photo = np.full((H, Wd, 3), 150, np.uint8)
    after = photo.copy()
    after[145:195, 28:32] = 40                                               # тёмное у ножки (ниже корпуса), на фото его нет
    full = np.ones((H, Wd), bool)
    r = CM.load_rules()
    nb = CM.dark_streak_new(after, photo, full, band & mask, groove, valid, mask, r, zone=zone)
    ok(nb['streak_px'] == 0, 'тёмное ниже корпуса не попадает в мерку корпуса')
    nl = CM.dark_streak_new(after, photo, full, band & mask, groove, valid, mask, r, zone=~zone)
    ok(nl['streak_px'] > 0 and nl['share_pct'] is not None, f'то же тёмное — в мерке ножек ({nl["share_pct"]} %)')
    after2 = photo.copy()
    after2[40:80, 98:102] = 40                                               # тёмное на корпусе, на фото нет
    nb2 = CM.dark_streak_new(after2, photo, full, band & mask, groove, valid, mask, r, zone=zone)
    ok(nb2['share_pct'] is not None and nb2['share_pct'] > 1, f'тёмное на корпусе без пары на фото — брак корпуса ({nb2["share_pct"]} %)')


def main():
    test_crease_found_and_flat_has_none()
    test_groove_and_measures()
    test_controls()
    test_band()
    test_confidence()
    test_dark_streak_new()
    test_body_zone()
    print(f'tests_crease_mask: ошибок {bad}')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
