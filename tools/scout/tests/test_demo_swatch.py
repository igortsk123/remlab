"""Тон кружка цвета — цвет ткани, а не среднее по фото (demo-28, ведущий 23.10: «Молочный» кружок заметно темнее дивана). Без сети.

Синтетическое фото карточки: белый фон, молочная обивка, тень под ней и чёрные ножки. Стенд проверяет:
  1) образец (`_swatch_tone`) — светлый, как обивка; прежнее среднее (`_tone`) серит — тень и ножки в нём;
  2) белая обивка внутри предмета не считается фоном (фон — только почти белое, связанное с краем кадра);
  3) тёмный предмет остаётся тёмным, цветной — своего цвета (не высветляется до белого);
  4) `annotate_swatch` кладёт образец каждому товару с фото (цвет предмета на плане, T-20261112-29); нет плитки — без образца.
    ~/venvs/scout/bin/python tools/scout/tests/test_demo_swatch.py"""
import os
import sys
import tempfile
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_demo_swatch')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'services', 'planner-solver'))
fails = 0


def check(name, cond, info=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
    fails += 0 if cond else 1


def sofa(path, body, shade=None, legs=(20, 20, 20), hole=False):
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (400, 300), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([60, 250, 340, 270], fill=(200, 200, 200))                     # тень на полу
    d.rectangle([40, 90, 360, 240], fill=body)                                 # обивка
    d.rectangle([40, 200, 360, 240], fill=shade or tuple(int(c * 0.7) for c in body))   # затенённый низ
    for x in (60, 330):
        d.rectangle([x, 240, x + 12, 262], fill=legs)                          # ножки
    if hole:
        d.rectangle([150, 120, 250, 160], fill=(255, 255, 255))               # блик/белая вставка внутри предмета
    im.save(path)


def main():
    import flat215_demo as F
    tmp = tempfile.mkdtemp(prefix='swatch-')
    lum = lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]                # noqa: E731
    milk = os.path.join(tmp, 'milk.jpg')
    sofa(milk, (236, 232, 226))
    new, old = F._swatch_tone(milk), F._tone(milk)
    check('молочный: образец светлый, как обивка (яркость ≥ 0,88)', new and lum(new) >= 0.88, new)
    check('молочный: прежнее среднее темнее образца на ≥ 0,05', old and lum(new) - lum(old) >= 0.05, (old, new))
    holed = os.path.join(tmp, 'hole.jpg')
    sofa(holed, (236, 232, 226), hole=True)
    h = F._swatch_tone(holed)
    check('белая вставка внутри предмета — не фон, тон не уходит в серое', h and abs(lum(h) - lum(new)) < 0.04, (h, new))
    dark = os.path.join(tmp, 'dark.jpg')
    sofa(dark, (60, 58, 56))
    k = F._swatch_tone(dark)
    check('графит остаётся тёмным (яркость ≤ 0,3)', k and lum(k) <= 0.3, k)
    red = os.path.join(tmp, 'red.jpg')
    sofa(red, (120, 40, 50))
    r = F._swatch_tone(red)
    check('бордовый — своего цвета: красный канал заметно больше зелёного', r and r[0] - r[1] >= 0.2, r)
    # T-20261112-29: стол-рамка — тёмный контур, внутри белый просвет (≈30 % предмета): просвет — фон, образец тёмный, не белый
    from PIL import Image, ImageDraw
    frame = os.path.join(tmp, 'frame.jpg')
    im = Image.new('RGB', (400, 300), (255, 255, 255))
    ImageDraw.Draw(im).rectangle([40, 60, 360, 240], fill=(40, 40, 42))
    ImageDraw.Draw(im).rectangle([100, 110, 300, 200], fill=(255, 255, 255))
    im.save(frame)
    t = F._swatch_tone(frame)
    check('тёмная рамка с белым просветом — образец тёмный (яркость ≤ 0,3)', t and lum(t) <= 0.3, t)
    data = {'variants': [{'items': [{'sku': {'sid': 'a', 'msid': 'm', 'img': 'milk.jpg'}}]}],
            'feeds': {'f': [{'sid': 'b', 'msid': 'm', 'img': 'dark.jpg'}, {'sid': 'c', 'msid': 'solo', 'img': 'red.jpg'}]}}
    n = F.annotate_swatch(data, tmp)
    feed = data['feeds']['f']
    # T-20261112-29: образец — у каждого товара с фото (цвет предмета на плане); кружки по-прежнему только у моделей с ≥ 2 цветами
    check('annotate_swatch: образец у каждого товара с фото, у одиночки тоже — своего цвета', n == 3
          and feed[1]['swatch'].startswith('#') and int(feed[1]['swatch'][1:3], 16) > int(feed[1]['swatch'][3:5], 16) + 40
          and feed[0]['swatch'].startswith('#') and data['variants'][0]['items'][0]['sku']['swatch'] > '#d0', (n, data))
    nophoto = {'variants': [{'items': [{'sku': {'sid': 'z', 'msid': 'z', 'img': 'nope.jpg'}}, {'sku': {'sid': 'y', 'img': 'https://x/y.jpg'}}]}]}
    check('annotate_swatch: нет файла плитки или адрес в сети — без образца', F.annotate_swatch(nophoto, tmp) == 0
          and all('swatch' not in it['sku'] for it in nophoto['variants'][0]['items']), nophoto)
    check('annotate_swatch: семья не та, что у модели, — поля fam нет', all('fam' not in p for p in feed), feed)
    # T-20261106-77/5: у цвета своя 3D-модель (правило привязки) — семья та же, по представителю; кружки не пропадают
    keep = F._MESH_REP
    F._MESH_REP = {'x1': 'x1', 'x2': 'x1', 'x3': 'x1'}
    try:
        data = {'variants': [], 'feeds': {'f': [{'sid': 'x1', 'msid': 'x1', 'img': 'milk.jpg'},
                                                {'sid': 'x2', 'msid': 'x2', 'img': 'dark.jpg'},
                                                {'sid': 'x3', 'msid': 'x1', 'img': 'red.jpg'}]}}
        n = F.annotate_swatch(data, tmp)
        f = data['feeds']['f']
    finally:
        F._MESH_REP = keep
    check('своя модель у цвета: образец у всех трёх цветов семьи', n == 3 and all(p.get('swatch') for p in f), (n, f))
    check('своя модель у цвета: fam = представитель только там, где msid другой',
          f[1].get('fam') == 'x1' and 'fam' not in f[0] and 'fam' not in f[2], f)
    print('fails', fails)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
