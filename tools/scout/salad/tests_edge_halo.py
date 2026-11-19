#!/usr/bin/env python3
"""Чистка светлого ореола по кромке вырезки (T-20261119-99). Без сети и без моделей: синтетические RGBA.
  python tools/scout/salad/tests_edge_halo.py"""
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edge_halo as EH  # noqa: E402


def canvas(body_rgb, size=(400, 300), box=(60, 80, 340, 260)):
    a = np.zeros((size[1], size[0], 4), np.uint8)
    a[..., :3] = 255
    x0, y0, x1, y1 = box
    a[y0:y1, x0:x1, :3] = body_rgb
    a[y0:y1, x0:x1, 3] = 255
    return a


def with_dash(a, x=120, w=8, y=77, h=3, lum=225, alpha=226):
    """Светлая чёрточка над верхней кромкой тела: тот же вид, что у «ушек» дивана."""
    a = a.copy()
    a[y:y + h, x:x + w, :3] = lum
    a[y:y + h, x:x + w, 3] = alpha
    return a


def test_broken_thin_wire_kept():
    """Свободный тонкий светлый трос/провод (нет тёмного соседа, рвётся на обрывки по 3 px) — товар, а не ореол."""
    a = canvas((60, 60, 62))
    for i, y in enumerate(range(10, 66)):          # вертикальный свободный провод над телом (до тела 14 px); обрывки через каждые 4 px
        if i % 4 != 3:
            a[y, 200, :3] = 225
            a[y, 200, 3] = 255
    out, info = EH.clean_edge_halo(Image.fromarray(a, 'RGBA'))
    assert (np.asarray(out)[10:80, 200, 3] == a[10:80, 200, 3]).all(), 'свободный провод порезан'


def test_thin_legs_halo_not_rolled_back_by_area():
    """Тонконогий товар: ореол у ножек по длине границы большой, по площади мал — откат по площади срабатывал зря (стул 227×305); теперь откат — по длине границы."""
    a = np.zeros((300, 227, 4), np.uint8)
    a[..., :3] = 255
    for x in (60, 100, 140, 180):                 # четыре чёрные ножки 4 px × 200 px
        a[80:280, x:x + 4, :3] = 30
        a[80:280, x:x + 4, 3] = 255
        for y in range(90, 280, 7):               # светлые точки-«крошки» рядом с ножкой (1 px, α 255)
            a[y, x - 2, :3] = 235
            a[y, x - 2, 3] = 255
    solid0 = int((a[..., 3] > 128).sum())
    out, info = EH.clean_edge_halo(Image.fromarray(a, 'RGBA'))
    assert info['removed'] >= 100 and not info['skipped'], info
    o = np.asarray(out)
    assert (o[80:280, 60:64, 3] == 255).all(), 'ножка тронута'


def test_dash_above_dark_edge_removed():
    a = with_dash(canvas((110, 110, 112)))
    out, info = EH.clean_edge_halo(Image.fromarray(a, 'RGBA'))
    o = np.asarray(out)
    assert o[77:80, 120:128, 3].max() == 0, 'чёрточка осталась'
    assert info['removed'] >= 16 and info['iters'] >= 1
    assert (o[80:260, 60:340, 3] == 255).all(), 'тело тронуто'


def test_body_untouched_when_no_halo():
    a = canvas((110, 110, 112))
    out, info = EH.clean_edge_halo(Image.fromarray(a, 'RGBA'))
    assert info['removed'] == 0
    assert (np.asarray(out) == a).all()


def test_light_trim_inside_dark_body_kept():
    """Светлый кант/деталь не у границы (глубже полосы) — не трогается; цветное (не бесцветное) у границы тоже."""
    a = canvas((70, 70, 72))
    a[150:154, 100:300, :3] = 225                                    # светлая полоска внутри тела
    a[80:83, 100:200, :3] = (230, 200, 120)                          # тёплая (цветная) полоска на самой кромке
    out, info = EH.clean_edge_halo(Image.fromarray(a, 'RGBA'))
    o = np.asarray(out)
    assert o[150:154, 100:300, 3].min() == 255
    assert o[80:83, 100:200, 3].min() == 255


def test_dark_legs_and_thin_dark_parts_kept():
    a = canvas((110, 110, 112))
    a[260:290, 100:110, :3] = 30                                    # тёмная ножка ниже тела
    a[260:290, 100:110, 3] = 255
    out, info = EH.clean_edge_halo(Image.fromarray(a, 'RGBA'))
    assert (np.asarray(out)[260:290, 100:110, 3] == 255).all()


def test_border_lum_and_empty():
    assert EH.border_lum(np.full((20, 20, 3), 200, np.uint8)) == 200.0
    out, info = EH.clean_edge_halo(Image.fromarray(np.zeros((10, 10, 4), np.uint8), 'RGBA'))
    assert info['skipped'] == 'пустая маска'


def test_bounded_shrink():
    """Правило не «съедает» тело: на теле с краем без ореола убрано 0 px; с ореолом — только ореол (площадь тела −<1 %)."""
    a = with_dash(canvas((110, 110, 112)), w=8, h=4)
    b0 = int((a[..., 3] > 128).sum())
    out, _ = EH.clean_edge_halo(Image.fromarray(a, 'RGBA'))
    b1 = int((np.asarray(out)[..., 3] > 128).sum())
    assert 0 < b0 - b1 < 0.01 * b0

def test_long_light_edge_is_product_not_halo():
    """Длинная светлая кромка (стекло/абажур) — сам товар: куски длиннее 3 % ширины тела не режем."""
    a = canvas((110, 110, 112))
    a[80:83, 70:330, :3] = 235                                         # светлая кромка вдоль всего верха
    out, info = EH.clean_edge_halo(Image.fromarray(a, 'RGBA'))
    assert (np.asarray(out)[80:83, 70:330, 3] == 255).all() and info['removed'] == 0


def test_audit_counts_and_status():
    clean = canvas((110, 110, 112))
    assert EH.audit(Image.fromarray(clean, 'RGBA'))['status'] == 'clean'
    dirty = clean.copy()
    dirty[40:60, 20:40] = (110, 110, 112, 255)                          # отдельный островок вне тела
    r = EH.audit(Image.fromarray(dirty, 'RGBA'))
    assert r['status'] == 'dirty' and r['islands'] == 1
    r2 = EH.audit(Image.fromarray(with_dash(clean, w=8), 'RGBA'))       # короткая светлая чёрточка на кромке — считается
    assert r2['light_edge'] >= 16


def test_audit_after_clean_is_clean():
    a = with_dash(canvas((110, 110, 112)), w=8)
    out, _ = EH.clean_edge_halo(Image.fromarray(a, 'RGBA'))
    assert EH.audit(out)['light_edge'] == 0


def test_defringe_cleans_halo_and_reports():
    """Вход генератора: `preprocess.defringe` убирает чёрточки и пишет счётчики/статус сторожа в info['edge_clean']; без torch — пропуск."""
    try:
        import preprocess as PRE
    except Exception as e:      # noqa: BLE001 — нет torch/transformers в окружении
        print('skip: preprocess не импортируется:', type(e).__name__)
        return
    a = with_dash(canvas((110, 110, 112)), w=8)
    info = {}
    out = PRE.defringe(Image.fromarray(a, 'RGBA'), info)
    o = np.asarray(out)
    assert o[77:80, 120:128, 3].max() == 0
    ec = info['edge_clean']
    assert ec['halo_removed_px'] >= 16 and ec['status'] == 'clean' and ec['light_edge'] == 0
    # светлый фон не однотонный (цветной) — чистка кромки не применяется, но вырезка отдаётся как раньше
    b = a.copy()
    b[:4, :4, :3] = (30, 60, 200)
    inf2 = {}
    PRE.defringe(Image.fromarray(b, 'RGBA'), inf2)
    assert 'skipped' in inf2['edge_clean']


def test_crumbs_removed_any_colour():
    """T-99/2: отдельные крошки до CRUMB_MIN px (серые/светлые у углов белого комода) срезаются при ЛЮБОМ цвете; крупнее — по прежнему правилу «тень-подобные»."""
    try:
        import clean_islands as CI
    except Exception as e:      # noqa: BLE001
        print('skip:', e)
        return
    d = canvas((235, 232, 226))
    d[30, 30, :3] = (243, 244, 238)                                    # одиночная крошка вдали от тела, цвет почти как у тела
    d[30, 30, 3] = 238
    d[40:42, 300:302, :3] = (200, 190, 180)
    d[40:42, 300:302, 3] = 255
    d[20:30, 200:210, :3] = (120, 80, 60)                              # крупный цветной кусок (100 px) — не крошка и не тень → остаётся
    d[20:30, 200:210, 3] = 255
    out, rep = CI.clean_islands(Image.fromarray(d, 'RGBA'))
    o = np.asarray(out)
    assert o[30, 30, 3] == 0 and o[40:42, 300:302, 3].max() == 0 and o[20:30, 200:210, 3].min() == 255, rep


def test_light_body_locally_decided():
    """T-99/3: решение «светлое — не трогать» локальное. (а) белое тело, светлая чёрточка без тёмного соседа — не тронуто; (б) белый фасад с ДУБОВОЙ боковиной: чёрточка над дубом снята,
    над белым — нет; (в) белая трубка вплотную к чёрному кольцу (край трубки ≈ как тело) не режется — кандидат ближе к телу, чем к фону."""
    a = with_dash(canvas((235, 232, 226)), lum=250)
    out, info = EH.clean_edge_halo(Image.fromarray(a, 'RGBA'))
    assert info['removed'] == 0 and (np.asarray(out) == a).all(), info
    c = canvas((235, 232, 226))
    c[80:260, 60:90, :3] = (150, 110, 70)                              # дубовая боковина слева (на 90 px тёмнее фона)
    c[77:80, 64:72, :3] = 250                                          # светлая чёрточка над дубом
    c[77:80, 64:72, 3] = 226
    c[77:80, 200:208, :3] = 250                                        # такая же над белым фасадом — не трогаем
    c[77:80, 200:208, 3] = 226
    out, info = EH.clean_edge_halo(Image.fromarray(c, 'RGBA'))
    o = np.asarray(out)
    assert o[77:80, 64:72, 3].max() == 0 and o[77:80, 200:208, 3].min() == 226, info
    d = canvas((30, 30, 32), box=(60, 120, 340, 140))                   # чёрное кольцо-полоска
    d[100:120, 150:166, :3] = 240                                      # белая трубка (≈ как тело трубки) (16 px шириной) уходит вверх от кольца
    d[100:120, 150:166, 3] = 255
    d[100:120, 150, :3] = 245                                          # её край чуть светлее тела, но ближе к телу (240), чем к фону (255)
    out, info = EH.clean_edge_halo(Image.fromarray(d, 'RGBA'))
    assert (np.asarray(out)[100:120, 150:166, 3] == 255).all(), info


def test_fg_estimate_recolours_edge_not_alpha():
    """T-99/2: оценка цвета предмета (blur fusion, порт BiRefNet.refine_foreground) убирает подмешанный фон из цвета кромки и НЕ меняет α; интерьер не трогает."""
    import fg_estimate as FE
    h, w = 120, 160
    rgb = np.full((h, w, 3), 255.0, np.float32)
    al = np.zeros((h, w), np.float32)
    rgb[30:90, 40:120] = (60, 70, 90)                                  # тёмное тело
    al[30:90, 40:120] = 1.0
    for x, t in ((38, 0.3), (39, 0.7)):                                 # полупрозрачная кромка слева: цвет = смесь тела и белого фона
        al[30:90, x] = t
        rgb[30:90, x] = t * np.array([60, 70, 90]) + (1 - t) * 255.0
    out, n = FE.refine_edges(rgb, al)
    assert n > 0
    before = float(rgb[50, 39].mean()); after = float(out[50, 39].mean())
    assert after < before - 30 and abs(after - 73) < 25, (before, after)      # вернулся к цвету тела (≈73), а не остался светло-серым (≈ 112)
    assert (out[40:80, 60:100] == rgb[40:80, 60:100]).all(), 'интерьер тронут'
    out2, n2 = FE.refine_edges(np.full((20, 20, 3), 255.0, np.float32), np.zeros((20, 20), np.float32))
    assert n2 == 0


def test_components_clean_keeps_diagonal_wire():
    """T-99/3: диагональный трос 1 px, соединяющий плафон и кольцо, — одна часть товара (8-связность). При 4-связности он рассыпался на одиночные пиксели
    и середина срезалась как мусор (люстра 99272_11551104666593844009: огрызки у плафона и кольца). Отдельная пылинка вдали по-прежнему срезается."""
    try:
        import components as CO
    except Exception as e:      # noqa: BLE001
        print('skip:', e)
        return
    h, w = 200, 200
    al = np.zeros((h, w), np.float32)
    al[10:30, 80:120] = 1.0                                            # плафон
    al[170:190, 20:180] = 1.0                                          # кольцо
    for i in range(140):                                               # диагональный трос (по пикселю на строку, шаг по x — 8-связный)
        al[30 + i, 100 + int(i * 0.5)] = 1.0
    al[100, 20] = 1.0                                                  # пылинка вдали
    out, rep = CO.clean(al)
    assert (out[31:170, :] > 0.5).sum() >= 139 + 0, 'трос порван'
    assert out[100, 20] == 0, 'пылинка осталась'
    out4, _ = CO.clean(al, eight=False)
    assert (out4[40:160, :] > 0.5).sum() < 20, 'контроль: при 4-связности трос рассыпался бы (проверка, что тест различает)'


if __name__ == '__main__':
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('ok  ', name)
            except AssertionError as e:
                fails += 1
                print('FAIL', name, e)
    sys.exit(1 if fails else 0)
