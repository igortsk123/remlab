#!/usr/bin/env python3
"""«Известный студийный фон», Ч.1 (T-20261119-104/5): строгий признак фона, вычитатель крупы у кромки, сторож close_edge_gaps, аналитический
мягкий край. Тело правило не добавляет. Без сети и моделей.
  python tools/scout/salad/tests_studio_bg.py"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import components as C  # noqa: E402
import studio_bg as S  # noqa: E402

H, W = 300, 400


def white(c=(60, 50, 40)):
    return np.full((H, W, 3), 255, np.uint8), np.array(c, np.uint8)


def regs(r):
    bg, st = S.detect(r)
    assert bg is not None, st
    rcore, rsoft = S.regions(r, bg, st['t_core'], st['t_soft'])
    return bg, rcore, rsoft


def test_detect_strict():
    r, _ = white()
    r[100:200, 100:300] = (150, 100, 60)
    bg, st = S.detect(r)
    assert bg is not None and float(bg.min()) >= 245, st
    grad = np.tile(np.linspace(200, 255, W, dtype=np.uint8)[None, :, None], (H, 1, 3))
    b, st = S.detect(grad)
    assert b is None, st
    assert S.detect(np.full((H, W, 3), 120, np.uint8))[0] is None, 'серый фон принят'
    yel = np.full((H, W, 3), (255, 250, 235), np.uint8)
    assert S.detect(yel)[0] is None, 'кремовый фон принят'
    assert S.detect(np.full((H, W, 3), 244, np.uint8))[0] is None, 'фон < 245 принят'
    touch, _ = white()
    touch[:, :150] = (80, 60, 50)                  # товар занимает рамку слева и справа
    touch[:, 250:] = (80, 60, 50)
    assert S.detect(touch)[0] is None, 'товар у рамки принят за фон'


def test_subtract_crumbs_keep_tube():
    r, dark = white()
    r[20:280, 198:202] = dark
    r[260:290, 150:250] = dark
    a = np.zeros((H, W), np.float32)
    a[20:280, 198:202] = 1.0
    a[260:290, 150:250] = 1.0
    a[100:120, 196:198] = 1.0                      # крупа фона по бокам трубки
    a[100:120, 202:204] = 1.0
    bg, rcore, _ = regs(r)
    out, info = S.subtract(a, r, bg, rcore)
    assert (out[30:250, 198:202] > 0.5).all(), 'трубка съедена'
    assert int((out[100:120, 196:198] > 0.5).sum()) == 0 and int((out[100:120, 202:204] > 0.5).sum()) == 0, 'крупа осталась'
    assert info['subtract_px'] == 80, info
    assert (a[100:120, 196:198] > 0.5).all()       # контроль: без шага крупа в маске


def test_subtract_white_product_untouched():
    r, _ = white()
    r[100:200, 100:300] = 250                      # белый шкаф ≈ цвет фона
    a = np.zeros((H, W), np.float32)
    a[100:200, 100:300] = 1.0
    bg, rcore, _ = regs(r)
    out, info = S.subtract(a, r, bg, rcore)
    assert (out == a).all() and 'subtract_skipped' in info, info


def test_subtract_cap():
    r, dark = white()
    r[100:200, 100:300] = dark
    a = np.zeros((H, W), np.float32)
    a[100:200, 100:300] = 1.0
    a[98:100, 100:300] = 1.0                       # 2 строки фона над телом = 400 px > 3 % тела (20 000 → 600)? нет — добавим больше
    a[200:202, 100:300] = 1.0
    a[96:98, 100:300] = 1.0                        # всего ≈ 800 px (4 %)
    bg, rcore, _ = regs(r)
    out, info = S.subtract(a, r, bg, rcore)
    assert 'subtract_skipped' in info and (out == a).all(), info


def test_subtract_interior_hole_untouched():
    r, dark = white()
    r[100:200, 100:300] = dark
    r[140:150, 150:160] = 255                      # замкнутая светлая дыра внутри: не связана с рамкой → не Rcore
    a = np.zeros((H, W), np.float32)
    a[100:200, 100:300] = 1.0
    bg, rcore, _ = regs(r)
    out, info = S.subtract(a, r, bg, rcore)
    assert (out[140:150, 150:160] > 0.5).all(), 'внутренняя дырка стёрта'


def test_subtract_and_soft_keep_light_fabric_edge():
    """Белая ткань (237: ‖F−B‖=18 < 20, но вне Rsoft) поверх тёмной кровати: край ткани в сети «пробит» бликами 252 (≈ фон) — не вычитать и не смягчать (правки 104/5)."""
    r, dark = white()
    r[130:230, 100:300] = dark                      # тёмная рама
    r[100:130, 100:300] = 237                       # светлая ткань сверху
    r[96:100, 100:300] = 252                        # блики по самому краю ткани: «как фон» по цвету
    a = np.zeros((H, W), np.float32)
    a[96:230, 100:300] = 1.0
    bg, rcore, rsoft = regs(r)
    out, info = S.subtract(a, r, bg, rcore)
    assert (out[96:100, 100:300] > 0.5).all(), f'край светлой ткани стёсан: {info}'
    al, _, info2 = S.soft_alpha(a, r, bg, rsoft)
    assert (al[96:100, 100:300] > 0.99).all(), f'край светлой ткани смягчён: {info2}'


def test_soft_alpha_highlight_rim_no_gap():
    """Светлое ребро (205) поверх более тёмного тела (150): внешний ряд — смесь, второй — блик; щели во втором ряду быть не должно (правки 104/5)."""
    r, _ = white()
    body = np.array([150, 142, 136], np.uint8)
    r[100:200, 100:300] = body
    r[100:102, 100:300] = (205, 198, 192)           # ребро-блик в 2 верхних рядах
    a = np.zeros((H, W), np.float32)
    a[100:200, 100:300] = 1.0
    _, _, rsoft = regs(r)
    bg = np.array([255, 255, 255], np.float32)
    al, _, info = S.soft_alpha(a, r, bg, rsoft)
    assert (al[101, 110:290] > 0.95).all(), f'второй ряд ребра продавлен (щель): {al[101, 110:112]} {info}'


def test_close_edge_gaps_guard():
    r, dark = white()
    r[100:200, 100:300] = dark
    a = np.zeros((H, W), np.float32)
    a[100:200, 100:300] = 1.0
    a[100:102, 150] = 0                            # щель 1 px, в ней фон (255) — это Rcore
    a[100:102, 200] = 0
    r[100:102, 150] = 255                          # в щели чистый фон
    r[100:102, 200] = (20, 20, 20)                 # здесь в щели тёмный пиксель товара
    bg, rcore, _ = regs(r)
    out, _, info = C.close_edge_gaps(a, r, gap_px=2, rcore=rcore)
    assert out[100, 150] < 0.5, f'щель с фоном склеена: {info}'
    assert out[100, 200] > 0.5, 'щель с товаром не закрыта'
    out2, _, _ = C.close_edge_gaps(a, r, gap_px=2)        # как в /2 (без rcore): склеивает обе
    assert out2[100, 150] > 0.5


def test_close_edge_gaps_rollback_lamp_like():
    r, dark = white()
    r[20:280, 198:202] = dark                      # тонкая трубка
    a = np.zeros((H, W), np.float32)
    a[20:280, 198:202] = 1.0
    for y in range(22, 278, 3):                    # зубцы крупы по обе стороны: закрытие склеит их (много добавок в фоне)
        a[y:y + 1, 195:198] = 1.0
        a[y:y + 1, 202:205] = 1.0
    bg, rcore, _ = regs(r)
    out, _, info = C.close_edge_gaps(a, r, gap_px=2, rcore=rcore)
    assert 'edge_gap_rollback' in info, info
    assert (out == a).all(), 'шаг откатан не целиком'


def test_close_edge_gaps_light_furniture_allowed():
    r, _ = white()
    r[100:200, 100:300] = (235, 232, 228)          # светлый шкаф
    a = np.zeros((H, W), np.float32)
    a[100:200, 100:300] = 1.0
    a[100, 150:152] = 0                            # пунктир по верхней кромке
    a[100, 200:202] = 0
    bg, rcore, _ = regs(r)
    out, _, info = C.close_edge_gaps(a, r, gap_px=2, rcore=rcore)
    assert 'edge_gap_rollback' not in info, info
    assert out[100, 150] > 0.5 and out[100, 200] > 0.5, f'щели светлого шкафа не закрыты: {info}'


def test_soft_alpha_edge_and_controls():
    r, dark = white()
    r[100:200, 100:300] = dark
    r[100:200, 99] = (157, 152, 147)               # переходный пиксель кромки: смесь тела (60,50,40) и белого ≈ 50/50
    a = np.zeros((H, W), np.float32)
    a[100:200, 99:300] = 1.0
    bg, rcore, rsoft = regs(r)
    al, rg, info = S.soft_alpha(a, r, bg, rsoft)
    assert 0.3 < al[150, 99] < 0.7, f'переход не стал мягким: {al[150, 99]} {info}'
    assert np.abs(rg[150, 99].astype(int) - dark.astype(int)).max() <= 2, f'цвет перехода не очищен от белого: {rg[150, 99]}'
    assert (al[110:190, 110:290] == 1.0).all() and al[10, 10] == 0, 'внутренность/фон тронуты'
    # контроль: белый товар (F ≈ B) — α сети не трогаем
    r2, _ = white()
    r2[100:200, 100:300] = 248
    r2[100:200, 99] = 251
    al2, _, info2 = S.soft_alpha(a, r2, bg, rsoft)
    assert (al2 == a).all(), f'товар цвета фона изменён: {info2}'


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
