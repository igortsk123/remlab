#!/usr/bin/env python3
"""Каталожная карточка или рекламный коллаж — определяем по САМОМУ фото.

ЗАЧЕМ (владелец 01.09): «пусть модель делает такое, просто помечай все меши в базе, которые
из коллажей сделаны; определять коллаж просто надо как-то — везде, где фон не белый».

ПОЧЕМУ НЕ НЕЙРОСЕТЬЮ. Вырезка живёт на нодах и стоит GPU-времени; здесь нужен признак,
который можно посчитать по всем 20 тысячам товаров на обычной машине и пересчитывать
ночью. Поэтому смотрим на рамку кадра — там у карточки фон, а у коллажа сцена и плашки.

ЧТО МЕРЯЕМ (по рамке шириной 4% кадра, где товара почти наверняка нет):
  1) `white` — доля почти белых пикселей. Главный признак, как и просил владелец;
  2) `spread` — разброс яркости по рамке. Ровный фон дают и белый, и светло-серый —
     а вот сцена с полом, стеной и плинтусом даёт большой разброс;
  3) `colored` — доля насыщенных пикселей. Плашки, флаги, цветной текст;
  4) `edges` — плотность резких перепадов. Текст и плашки дают частые контрастные границы,
     а гладкая штора или стена — нет.

РАЗЛИЧАЕМ ДВЕ РАЗНЫЕ ВЕЩИ (уточнение после проверки глазами 01.09):
  * `scene` — товар снят в интерьере: фон не белый, но никаких надписей нет. Вырезать
    сложнее, но фото честное. Первая версия признака считала «тёмное по краям» текстом и
    записывала такие в коллажи — тёмная штора набирала 54% «текста».
  * `collage` — рекламный баннер: надписи, плашки, врезки. Это и есть грязный вход.
Поэтому текст ищем по ПЛОТНОСТИ ГРАНИЦ, а не по темноте, и коллажем зовём только то, где
к «фон не белый» добавились надписи или плашки.

  ~/venvs/scout/bin/python photo_bg.py --sample 40      # проверить на выборке, без записи
  ~/venvs/scout/bin/python photo_bg.py --run --limit 500  # посчитать и записать в базу
  ~/venvs/scout/bin/python photo_bg.py --sku a:1,b:2    # разобрать конкретные товары
"""
import io
import os
import subprocess
import sys
import urllib.request

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

PARAMS = {
    'frame': 0.04,        # ширина рамки, доля от стороны кадра
    'white_lo': 0.75,     # белого по рамке меньше этого → фон не белый
    'spread_hi': 28.0,    # разброс яркости выше → фон неровный (сцена)
    'colored_hi': 0.06,   # доля насыщенных пикселей выше → плашки/флаги
    'edges_hi': 0.09,     # плотность резких границ выше → надписи/плашки, а не гладкий фон
}


def db(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:300])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def q(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def measure(img: Image.Image) -> dict:
    """Замеры по рамке кадра. Возвращает четыре числа и вердикт."""
    im = img.convert('RGB')
    im.thumbnail((640, 640))
    a = np.asarray(im).astype(np.float32)
    h, w = a.shape[:2]
    m = max(2, int(min(h, w) * PARAMS['frame']))
    ring = np.concatenate([a[:m].reshape(-1, 3), a[-m:].reshape(-1, 3),
                           a[:, :m].reshape(-1, 3), a[:, -m:].reshape(-1, 3)])
    lum = ring.mean(axis=1)
    mx, mn = ring.max(axis=1), ring.min(axis=1)
    sat = (mx - mn)
    # НАДПИСИ ИЩЕМ НЕ ПО РАМКЕ. На баннере текст лежит не по самому краю, а внутри кадра
    # (у стола TC Vox — сверху и справа), поэтому узкая рамка его не видела вовсе. Режем кадр
    # на плитки 8×8 и смотрим ВНЕШНЕЕ кольцо плиток: там товара обычно нет, а надписи и
    # плашки есть. Признак текста — частые резкие перепады внутри плитки.
    g = np.asarray(im.convert('L')).astype(np.float32)
    gh, gw = g.shape
    ty, tx = gh // 8, gw // 8
    busy = []
    for iy in range(8):
        for ix in range(8):
            if 1 <= iy <= 6 and 1 <= ix <= 6:
                continue                      # середина — это сам товар, её не судим
            t = g[iy * ty:(iy + 1) * ty, ix * tx:(ix + 1) * tx]
            if t.size < 16:
                continue
            busy.append(float((np.abs(np.diff(t, axis=1)) > 26).mean()))
    edges = float(np.mean(sorted(busy)[-6:])) if busy else 0.0   # самые «шумные» плитки
    out = {'white': float((lum > 235).mean()),
           'spread': float(lum.std()),
           'colored': float((sat > 40).mean()),
           'edges': edges}
    not_white = out['white'] < PARAMS['white_lo']
    overlays = []
    if out['edges'] > PARAMS['edges_hi']:
        overlays.append(f'надписи или плашки по краям (границ {out["edges"]:.0%})')
    if out['colored'] > PARAMS['colored_hi']:
        overlays.append(f'цветные плашки ({out["colored"]:.0%})')
    reasons = []
    if not_white:
        reasons.append(f'фон не белый ({out["white"]:.0%} белого)')
    if out['spread'] > PARAMS['spread_hi']:
        reasons.append(f'фон неровный (разброс {out["spread"]:.0f})')
    reasons += overlays
    # ПРАВИЛО ВЛАДЕЛЬЦА: «везде, где фон не белый». Оно и стоит в основе метки.
    # Попытка отделить рекламный баннер от честной съёмки в интерьере по надписям НЕ
    # получилась и оставлена как вспомогательный признак: на баннере стола TC Vox текст
    # светлый на светлой стене и по контрасту не отличается от складок шторы (6% против 4%
    # у чистой карточки — разделения нет). Поэтому метку ставим по фону, а `overlay`
    # держим отдельным полем: когда появится надёжный детектор текста, уточним не ломая.
    out['collage'] = not_white
    out['overlay'] = bool(overlays)
    out['bg'] = 'white' if not not_white else 'scene'
    out['reason'] = '; '.join(reasons)
    return out


def fetch(url: str, timeout: int = 40) -> Image.Image:
    req = urllib.request.Request(url, headers={'User-Agent': 'remlab-scout/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return Image.open(io.BytesIO(r.read()))


def rows_for(where: str, limit: int) -> list:
    return db("select shop_mid||':'||external_id, coalesce(name,''), "
              "coalesce(image_url_hd, image_url), coalesce(mesh_status,'none') "
              f"from products where {where} limit {int(limit)};")


def main() -> None:
    write = '--run' in sys.argv
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 300
    if '--sku' in sys.argv:
        skus = sys.argv[sys.argv.index('--sku') + 1].split(',')
        rows = rows_for("shop_mid||':'||external_id in ("
                        + ','.join(q(s) for s in skus) + ')', len(skus))
    elif '--sample' in sys.argv:
        n = int(sys.argv[sys.argv.index('--sample') + 1])
        rows = rows_for("in_stock and coalesce(image_url_hd, image_url) is not null "
                        "order by random()", n)
    else:
        rows = rows_for("in_stock and coalesce(image_url_hd, image_url) is not null "
                        "and photo_bg_at is null", limit)

    seen = collage = 0
    for sku, name, url, mesh_status in rows:
        try:
            r = measure(fetch(url))
        except Exception as e:  # noqa: BLE001 — одно недоступное фото не валит прогон
            print(f'  {sku}: фото не получено ({type(e).__name__})')
            continue
        seen += 1
        collage += bool(r['collage'])
        mark = ('НЕ БЕЛЫЙ' if r['collage'] else 'карточка') + ('+текст' if r.get('overlay') else '')
        print(f'  {mark:9s} {name[:42]:42s} белого {r["white"]:.0%} разброс {r["spread"]:.0f}'
              f' цвет {r["colored"]:.0%} границы {r["edges"]:.0%}'
              + (f'  ← {r["reason"]}' if r['reason'] else ''))
        if write:
            mid, eid = sku.split(':', 1)
            db(f"update products set photo_bg={q(r['bg'])}, "
               f"photo_bg_score={r['white']:.4f}, photo_collage={str(r['collage']).lower()}, "
               f"photo_bg_at=now(), mesh_from_collage="
               f"{'true' if (r['collage'] and mesh_status == 'ready') else 'false'} "
               f"where shop_mid={int(mid)} and external_id={q(eid)};")
    print(f'\nпросмотрено {seen}, с небелым фоном {collage}'
          + (f' ({collage / max(seen, 1):.0%})' if seen else ''))
    if not write:
        print('это разбор без записи. Записать в базу: --run')


if __name__ == '__main__':
    main()
