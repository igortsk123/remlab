"""Тесты shadow_leak (T-20261124-15, R-SHADOW-LEAK): признак «тень щели запеклась в известное» и мерка. Синтетика, без GPU и сети.
Сцена: кадр 220×220, две грани (id 0 слева, id 1 справа) встречаются по колонке x=110 под углом 60° (излом формы), светлая ткань L≈170, тёмная линия-«тень щели» шириной 4 px по излому.
Запуск: python tests_shadow_leak.py → «ошибок 0»."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE), os.path.dirname(os.path.dirname(HERE))]
import numpy as np
import shadow_leak as SL

bad = 0


def ok(cond, msg):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + msg)
    if not cond:
        bad += 1


N, X0 = 220, 110
R = dict(SL.DEFAULTS, enabled=True)


def geoms(angle_deg: float = 60.0) -> list:
    a = np.radians(angle_deg)
    V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 0], [np.cos(a), 0, -np.sin(a)], [0, 1, 0]], float)
    F = np.array([[0, 1, 2], [3, 5, 4]], np.int64)
    return [{'V': V, 'F': F}]


def stage(crease: bool = True) -> dict:
    ids = np.zeros((N, N), np.int32)
    if crease:
        ids[:, X0:] = 1
    return {'mask': np.ones((N, N), bool), 'ids': ids, 'depth': np.full((N, N), 5.0, np.float32), 'px': N, 'px_len': 1.0, 'iou_frame': 0.9}


def photo(line_x: int = X0, width: int = 4, level: int = 105) -> np.ndarray:
    p = np.full((N, N, 3), 170, np.uint8)
    p[:, line_x - width // 2: line_x + (width + 1) // 2] = level
    return p


PM = np.ones((N, N), bool)
PM[0, :] = PM[-1, :] = False
PM[:, 0] = PM[:, -1] = False


def test_positive():
    p = photo()
    res = SL.run(p, PM, stage(), geoms(), 'мягкое', R)
    i = res['info']
    ok(i['applied'] and i['leak_px'] > 100, f'щель у излома найдена и вылечена (утечка {i["leak_px"]} px)')
    new = res['prgb']
    line = new[60:160, X0 - 1:X0 + 1].astype(float).mean()
    ok(line > 105 + 35, f"тёмная линия поднята к ткани ({line:.0f} против 105)")
    far = np.ones((N, N), bool)
    far[:, X0 - 14:X0 + 14] = False
    ok(np.array_equal(new[far], p[far]), 'вне щели (дальше 14 px) байты те же')
    ok(res['outside_changed_px'] == 0, 'изменённых пикселей вне зоны щели нет')
    ok(i['excess_pp_before'] is not None and i['excess_pp_before'] > 5 and i['excess_pp_if_applied'] < i['excess_pp_before'] / 3, f'избыток тёмного в щели {i["excess_pp_before"]} → {i["excess_pp_if_applied"]} п.п.')
    ok(res['maps'] is not None and res['maps']['leak'].any(), 'карты для кадра «до|после» отданы')


def test_disabled_and_family():
    p = photo()
    off = SL.run(p, PM, stage(), geoms(), 'мягкое', dict(R, enabled=False))
    ok(off['prgb'] is p and not off['info']['applied'], 'правило выключено: prgb тот же объект, лечения нет')
    ok(off['info']['leak_px'] > 100 and off['info']['excess_pp_if_applied'] < off['info']['excess_pp_before'], 'выключенное — мерка «если применить» всё равно считается')
    for fam in ('корпусное', 'каркасное', None):
        o = SL.run(p, PM, stage(), geoms(), fam, R)
        ok(o['prgb'] is p and o['info'].get('abstain') == 'family' and not o['info']['applied'], f'семья {fam!r}: воздержание, prgb тот же объект')


def test_negatives():
    p = photo()
    r1 = SL.run(p, PM, stage(crease=False), geoms(), 'мягкое', R)
    ok(r1['info']['leak_px'] == 0 and r1['prgb'] is p, 'тёмная линия без излома формы (рисунок ткани) — не утечка')
    wide = photo(width=26)
    r2 = SL.run(wide, PM, stage(), geoms(), 'мягкое', R)
    ok(r2['info']['leak_px'] == 0 and not r2['info']['applied'], 'широкая тёмная полоса (тёмная ткань) — не щель')
    side = np.full((N, N, 3), 170, np.uint8)
    side[:, :X0] = 60
    r3 = SL.run(side, PM, stage(), geoms(), 'мягкое', R)
    ok(r3['info']['leak_px'] == 0, 'край тёмного/светлого (светлая только с одной стороны) — не щель')
    pat = np.full((N, N, 3), 170, np.uint8)
    for x in range(20, N - 20, 14):
        pat[:, x:x + 3] = 60
    r4 = SL.run(pat, PM, stage(), geoms(), 'мягкое', R)
    ok(r4['info'].get('abstain') == 'pattern' and r4['prgb'] is pat, f'полосатая ткань: страж узора, воздержание (доля {r4["info"]["pattern_share_pct"]} %)')
    edge = photo(line_x=12)
    r5 = SL.run(edge, PM, stage(), geoms(), 'мягкое', R)
    ok(r5['info']['leak_px'] == 0, 'у самого края силуэта (глубже edge_px) — не берём')


def test_grow_and_ragged():
    """Шов из сильной части (строки 60–100, уровень 105) и слабого хвоста (строки 100–160, уровень 140: мягко-тёмный, строгий порог не берёт). Без роста хвост остаётся, с ростом — поднят."""
    p = photo()
    p[100:160, X0 - 2:X0 + 2] = 140
    r0 = dict(R)
    r1 = dict(R, grow_dark_px=12, grow_free=True)
    a = SL.run(p, PM, stage(), geoms(), 'мягкое', r0)
    b = SL.run(p, PM, stage(), geoms(), 'мягкое', r1)
    tail0 = a['prgb'][104:112, X0 - 1:X0 + 1].astype(float).mean()
    tail1 = b['prgb'][104:112, X0 - 1:X0 + 1].astype(float).mean()
    ok(tail1 > tail0 + 15, f'рост маски поднял слабый хвост шва у найденной полосы ({tail0:.0f} → {tail1:.0f})')
    ok(b['info']['leak_grown_px'] > b['info']['leak_px'], 'маска выросла по связанным тёмным пикселям')
    ok(b['info']['dark_left_pct'] < a['info']['dark_left_pct'], f'остаток тёмного вокруг шва меньше: {a["info"]["dark_left_pct"]} → {b["info"]["dark_left_pct"]} %')
    far = np.ones((N, N), bool)
    far[:, X0 - 14:X0 + 14] = False
    ok(np.array_equal(b['prgb'][far], p[far]), 'вне щели байты те же и при росте')

    g1 = SL.run(p, PM, stage(), geoms(), 'мягкое', dict(r1, ragged_max_left_pct=0.0001))
    ok(g1['info'].get('abstain') == 'ragged' and not g1['info']['applied'] and g1['prgb'] is p, 'самопроверка: остаток выше порога → воздержание «ragged», кадр тот же объект')
    g2 = SL.run(p, PM, stage(), geoms(), 'мягкое', dict(r1, ragged_max_left_pct=50.0))
    ok(g2['info']['applied'] and g2['info'].get('abstain') is None, 'самопроверка: остаток ниже порога → применено')
    c = SL.run(p, PM, stage(), geoms(), 'мягкое', dict(r1, enabled=False))
    ok(c['prgb'] is p and not c['info']['applied'], 'выключено — кадр тот же объект и при росте')


def test_rules():
    r = SL.load_rules()
    ok(r['enabled'] is False and 'мягкое' in r['families'], 'в rules/tex-visible.json правило выключено, семья — мягкое')
    ok(SL.load_rules('/нет/такого.json')['enabled'] is False, 'нет файла правил — умолчания, выключено')


def test_tex_visible_glue():
    import tex_visible as TV
    ok(TV.role_family('диван') == 'мягкое' and TV.role_family('шкаф') == 'корпусное' and TV.role_family('') is None and TV.role_family('нет такой роли') is None, 'роль → семья паспорта типа (нет роли/типа — None)')


def main():
    test_positive()
    test_disabled_and_family()
    test_negatives()
    test_grow_and_ragged()
    test_rules()
    test_tex_visible_glue()
    print(f'tests_shadow_leak: ошибок {bad}')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
