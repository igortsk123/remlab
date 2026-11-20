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


def _bed():
    """Кровать: тёмное основание 150..260 × 40..360, белый щит 60..150 × 40..360 (цвет 228, светлее тела, темнее фона 255), сеть щит потеряла."""
    r, _ = white()
    r[150:260, 40:360] = (120, 90, 60)
    r[110:150, 40:360] = (228, 228, 230)
    return r


def test_propose_white_headboard_recovered():
    r = _bed()
    a = np.zeros((H, W), np.float32)
    a[150:260, 40:360] = 1.0
    raw = a.copy()
    bg, rcore, rsoft = regs(r)
    out, info = S.propose(a, raw, r, bg, rsoft)
    assert (out[115:145, 50:350] > 0.5).all(), f'щит не возвращён: {info}'
    assert (out[10:50, :] == 0).all() and (out[:, :30] == 0).all(), 'добавлен фон'
    assert info['prop_px'] >= 40 * 320 * 0.95, info


def test_propose_rejects_shadow_small_and_frame():
    r, dark = white()
    r[100:200, 100:300] = dark
    a = np.zeros((H, W), np.float32)
    a[100:200, 100:300] = 1.0
    r[200:230, 100:300] = (205, 205, 205)          # тень на полу под тележкой
    bg, rcore, rsoft = regs(r)
    out, info = S.propose(a, a.copy(), r, bg, rsoft)
    assert (out == a).all(), f'тень добавлена: {info}'
    r2, dark = white()
    r2[100:200, 100:300] = dark
    r2[60:64, 100:104] = (200, 200, 200)           # мелочь
    a2 = np.zeros((H, W), np.float32)
    a2[100:200, 100:300] = 1.0
    bg, rcore, rsoft = regs(r2)
    out2, _ = S.propose(a2, a2.copy(), r2, bg, rsoft)
    assert (out2 == a2).all(), 'мелочь добавлена'
    r3, dark = white()
    r3[100:200, 100:300] = dark
    r3[0:100, :] = (230, 230, 230)                 # серая полоса через весь кадр до рамки — не тело
    a3 = np.zeros((H, W), np.float32)
    a3[100:200, 100:300] = 1.0
    bg, rcore, rsoft = regs(white()[0])               # области фона — как у чистого кадра: полоса «не фон» для propose
    rsoft = rsoft & ~(np.abs(r3.astype(np.float32) - 255).max(axis=2) > 16)
    out3, info3 = S.propose(a3, a3.copy(), r3, bg, rsoft)
    assert (out3 == a3).all() and 'упирается в рамку' in str(info3), f'компонент, упирающийся в рамку, добавлен: {info3}'


def test_detect_relaxes_when_product_touches_ring():
    r = _bed()
    r[110:150, :40] = (228, 228, 230)               # щит вплотную к левой рамке (кольцо 4 % его захватывает)
    r[:, :14] = np.where(np.arange(H)[:, None, None] % 2 == 0, 255, 255)
    bg, st = S.detect(r)
    assert bg is not None and float(bg.min()) >= 245, st
    full = np.full((H, W, 3), 255, np.uint8)
    full[:, :200] = (228, 228, 230)                # половина рамки — товар: фон НЕ принимается
    assert S.detect(full)[0] is None


def test_contrast_cut_dark_sofa_grey_strip():
    r, dark = white((70, 60, 55))
    r[100:200, 100:300] = dark
    r[150:200, 94:100] = (200, 200, 200)           # серая полоса-тень вплотную к тёмному телу, внутри маски сети
    a = np.zeros((H, W), np.float32)
    a[100:200, 100:300] = 1.0
    a[150:200, 94:100] = 1.0
    bg, rcore, rsoft = regs(r)
    out, info = S.contrast_cut(a, r, bg, rsoft)
    assert (out[150:200, 94:100] == 0).all(), f'полоса осталась: {info}'
    assert (out[100:200, 100:300] == 1.0).all(), 'тело тронуто'


def test_contrast_cut_light_body_with_dark_specks_untouched():
    r, _ = white()
    r[100:200, 100:300] = 235                       # светлый шкаф
    for x in range(110, 290, 6):
        r[110:190, x:x + 1] = 120                   # тёмные канавки/ручки
    a = np.zeros((H, W), np.float32)
    a[100:200, 100:300] = 1.0
    r[150:160, 96:100] = 225
    a[150:160, 96:100] = 1.0
    bg, rcore, rsoft = regs(r)
    out, info = S.contrast_cut(a, r, bg, rsoft)
    assert (out == a).all(), f'светлое тело с тёмными пятнами изменено: {info}'


def test_propose_rejects_gradient_shadow():
    r, dark = white()
    r[60:220, 100:160] = dark                       # две «ножки»-стойки (тело), между ними — столбцы без маски
    r[60:220, 240:300] = dark
    a = np.zeros((H, W), np.float32)
    a[60:220, 100:160] = 1.0
    a[60:220, 240:300] = 1.0
    for i in range(140):                            # плавная тень между стойками: шатёр 255 → 205 → 255 (не ниже пола тела: колонок маски там нет)
        v = int(255 - 50 * (1 - abs(i - 70) / 70))
        r[60 + i, 160:240] = v
    bg, rcore, rsoft = regs(r)
    out, info = S.propose(a, a.copy(), r, bg, rsoft)
    assert (out == a).all() and 'плавная граница' in str(info), f'градиентная тень добавлена: {info}'
    # контроль: тот же участок, но ровный (резкий край) — это тело (щит между стойками) и оно возвращается
    r[60:220, 160:240] = 255
    r[60:60 + 100, 160:240] = (228, 228, 230)
    bg, rcore, rsoft = regs(r)
    out2, info2 = S.propose(a, a.copy(), r, bg, rsoft)
    assert (out2[70:150, 165:235] > 0.5).all(), f'ровное тело не возвращено: {info2}'


def test_propose_rejects_thin_cord_at_frame():
    r, dark = white()
    r[60:220, 100:160] = dark
    a = np.zeros((H, W), np.float32)
    a[60:220, 100:160] = 1.0
    r[198:203, 160:] = dark                         # провод 5 px от тела до правого края кадра
    bg, rcore, rsoft = regs(r)
    out, info = S.propose(a, a.copy(), r, bg, rsoft)
    assert (out == a).all() and 'тонкая добавка' in str(info), f'провод добавлен: {info}'
    # контроль: та же добавка толщиной 12 px (тело, а не нить) — возвращается
    r[198:203, 160:] = 255
    r[188:200, 160:] = dark
    bg, rcore, rsoft = regs(r)
    out2, info2 = S.propose(a, a.copy(), r, bg, rsoft)
    assert (out2[190:198, 170:390] > 0.5).all(), f'толстое тело у рамки не возвращено: {info2}'


def _bar_legs(wedge_grey=(185, 185, 188)):
    r, _ = white()
    wood = (200, 150, 80)
    r[10:100, 50:350] = wood                        # «рама кровати»
    r[100:200, 50:70] = wood                        # ножки
    r[100:200, 330:350] = wood
    a = np.zeros((H, W), np.float32)
    a[10:100, 50:350] = 1.0
    a[100:200, 50:70] = 1.0
    a[100:200, 330:350] = 1.0
    return r, a


def test_hang_wedge_cuts_grey_wedge_between_legs():
    r, a = _bar_legs()
    for i in range(30):                             # серый клин под рамой между ножками (две грани разной яркости), сужается вниз
        r[100 + i, 170 + i // 2:230 - i // 2] = (185, 185, 188) if i % 2 == 0 else (160, 160, 162)
        a[100 + i, 170 + i // 2:230 - i // 2] = 1.0
    bg, rcore, rsoft = regs(r)
    out, info = S.hang_wedge(a, r, bg, rsoft)
    assert (out[102:126, 190:210] < 0.5).all() and info.get('hw_px', 0) > 300, f'клин не срезан: {info}'
    assert (out[10:100, 50:350] > 0.5).all() and (out[110:195, 52:68] > 0.5).all(), 'срезано тело'


def test_hang_wedge_keeps_panel_between_legs_and_bottom_body():
    r, a = _bar_legs()
    r[100:160, 70:330] = (240, 240, 240)            # белая панель между ножками (примыкает к ножкам по бокам) — тело
    a[100:160, 70:330] = 1.0
    bg, rcore, rsoft = regs(r)
    out, info = S.hang_wedge(a, r, bg, rsoft)
    assert (out == a).all(), f'панель срезана: {info}'
    r2, _ = white()                                 # светлое тело под тёмным верхом, без ножек по бокам (низ тела — само светлое)
    r2[60:100, 50:350] = (50, 50, 50)
    r2[100:160, 50:350] = (235, 235, 235)
    a2 = np.zeros((H, W), np.float32)
    a2[60:160, 50:350] = 1.0
    bg, rcore, rsoft = regs(r2)
    out2, info2 = S.hang_wedge(a2, r2, bg, rsoft)
    assert (out2 == a2).all(), f'светлый низ срезан: {info2}'


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
