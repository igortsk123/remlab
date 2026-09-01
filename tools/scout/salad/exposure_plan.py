#!/usr/bin/env python3
"""Насколько двигать экспозицию входа у каждого товара — замер, а не догадка.

Метод (по разбору Codex 01.09): модель рендерим БЕЗ света (`UNLIT=1`, только baseColor)
с того же ракурса, что и фото, и сравниваем медианную ЛИНЕЙНУЮ яркость товара с
яркостью фото. Разница в СТОПАХ (log2) — это и есть, на сколько ступеней промахнулась
покраска. Столько же ступеней и просим у входа, но не больше ±0.7: Codex прямо
предупредил, что за этими пределами вход уезжает в клиппинг, а мы получаем не
компенсацию, а новый брак.

Со светом мерить нельзя: тогда меряется наш собственный ламберт, а не покраска.

  UNLIT=1 ~/venvs/scout/bin/python exposure_plan.py marks.txt
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
CAP = float(os.environ.get('EV_CAP', 0.7))


def one(args):
    import numpy as np
    from PIL import Image
    import photo_color as PC
    sku, d = args
    os.environ['UNLIT'] = '1'                      # рендер без света — только цвет покраски
    from topview_render import render_front
    png = os.path.join('/tmp', f'unlit_{sku.replace(":", "_")}.png')
    render_front(os.path.join(d, 'model.glb'), 0.0, png)
    y_model = PC.luminance(Image.open(png))
    y_photo = PC.luminance(Image.open(os.path.join(d, 'cutout.png')))
    os.remove(png)
    if y_model <= 1e-5 or y_photo <= 1e-5:
        # чёрный коллапс: log2 не берётся, но это и есть самый тяжёлый случай — просим потолок
        return {'sku': sku, 'dir': d, 'y_photo': y_photo, 'y_model': y_model,
                'stops_raw': None, 'stops': CAP if y_model <= y_photo else -CAP,
                'note': 'коллапс в чёрное' if y_model <= 1e-5 else 'фото пустое'}
    raw = float(np.log2(y_photo / y_model))
    return {'sku': sku, 'dir': d, 'y_photo': round(y_photo, 4), 'y_model': round(y_model, 4),
            'stops_raw': round(raw, 2), 'stops': safe_stops(d, raw)}


def safe_stops(d: str, raw: float) -> float:
    """Сколько ступеней реально можно дать входу, не сломав его.

    Предел несимметричен, и это не придирка. В ТЁМНУЮ сторону клиппинга не бывает — теряется
    лишь глубина теней, поэтому потолок мягкий (−2 ступени). В СВЕТЛУЮ упираемся в белое:
    выжженное пятно назад не вернуть, а именно светлые товары мы просим темнее. Поэтому
    вверх идём ровно до тех пор, пока в колено светов не попало больше 3% пикселей товара.
    """
    import numpy as np
    from PIL import Image
    import photo_color as PC
    if raw <= 0:
        return round(float(max(raw, -2.0)), 2)
    img = Image.open(os.path.join(d, 'cutout.png'))
    best = 0.0
    for s in np.arange(0.2, min(raw, 2.0) + 1e-6, 0.2):
        _, rep = PC.shift_exposure(img, float(s))
        if rep['в_колене'] > 0.03:
            break
        best = float(s)
    return round(best, 2)


def main() -> None:
    import concurrent.futures as cf
    from color_test_page import newest_dirs, read_marks
    marks = read_marks(sys.argv[1] if len(sys.argv) > 1 else None)
    best = newest_dirs()
    todo = [(s, best[s][0]) for s in (marks or best) if s in best]
    print(f'меряю {len(todo)} товаров (рендер без света)', flush=True)
    out = []
    with cf.ProcessPoolExecutor(max_workers=4) as ex:
        for f in cf.as_completed([ex.submit(one, t) for t in todo]):
            try:
                out.append(f.result())
            except Exception as e:  # noqa: BLE001
                print('  сбой:', str(e)[:80], flush=True)
    json.dump({r['sku']: r for r in out}, open(os.path.join(HERE, 'exposure_plan.json'), 'w'),
              ensure_ascii=False, indent=1)
    import numpy as np
    st = np.array([r['stops'] for r in out])
    print(f'светлее нужно {int((st > 0).sum())}, темнее {int((st < 0).sum())}; '
          f'модуль сдвига: медиана {np.median(np.abs(st)):.2f} ст., в потолок уперлись '
          f'{int((np.abs(st) >= CAP - 1e-6).sum())} из {len(st)}')
    for r in sorted(out, key=lambda x: -abs(x['stops']))[:12]:
        print(f"  {r['sku'].split(':')[1][-6:]}  нужно {r['stops']:+.2f} ст. "
              f"(замер {r.get('stops_raw')}) {r.get('note', '')}")


if __name__ == '__main__':
    main()
