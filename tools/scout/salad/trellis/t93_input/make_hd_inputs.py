#!/usr/bin/env python3
"""T-93: вход пробы с ФОТО ПОКРУПНЕЕ (`products.image_url_hd`, при отсутствии — `image_url`) и шагом чистки островков после гибрида.
Та же цепочка, что `make_inputs.py` (`preprocess._cut_chain` → BiRefNet + гибрид + components), но:
  1) адрес фото — общее правило «HD, иначе обычный» (адреса берёт из `catalog_media.media()`; если там нет `img_hd` — из `db_photos.json` пробы);
  2) после `_cut_chain` — `clean_islands.clean_islands` (отдельные светлые бесцветные островки у низа предмета);
  3) в `inputs.json` пишутся `hybrid_error` и `islands_removed` (сбой гибрида больше не молчит).
  ~/venvs/scout/bin/python make_hd_inputs.py --out <папка> --src hd|feed <sku> […]     (тяжёлое — под tools/ops/heavy-slot.sh)"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TRELLIS = os.path.dirname(HERE)
SALAD = os.path.dirname(TRELLIS)
for p in (HERE, TRELLIS, SALAD, os.path.dirname(SALAD)):
    sys.path.insert(0, p)

PHOTOS = '/home/pakar/remlab-logs/t93-1119/db_photos.json'
INPUTS30 = '/home/pakar/remlab-logs/mesh-models-1118/trellis/inputs30/inputs.json'      # роли и «было» — оттуда (роль боевой конвейер берёт из набора)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('skus', nargs='+')
    ap.add_argument('--out', required=True)
    ap.add_argument('--src', default='hd', choices=('hd', 'feed'))
    ap.add_argument('--no-clean', action='store_true')
    a = ap.parse_args()
    import catalog_media as CM
    import preprocess as PRE
    from clean_islands import clean_islands
    from make_inputs import cpu_cutout
    from PIL import Image
    PRE.cutout = cpu_cutout
    os.makedirs(a.out, exist_ok=True)
    db = json.load(open(PHOTOS, encoding='utf-8'))
    old = json.load(open(INPUTS30, encoding='utf-8'))
    jp = os.path.join(a.out, 'inputs.json')
    res = json.load(open(jp, encoding='utf-8')) if os.path.exists(jp) else {}      # возобновление: готовое не пересчитываем
    for sku in a.skus:
        mid, eid = sku.split(':', 1)
        name = sku.replace(':', '_')
        if res.get(sku, {}).get('input_png_sha256') and os.path.exists(os.path.join(a.out, f'{name}.rgba.png')):
            print(sku, 'уже есть — пропуск', flush=True)
            continue
        m = CM.media(mid, eid) or {}
        hd = m.get('img_hd') or (db.get(sku) or {}).get('image_url_hd')
        if a.src == 'hd' and not hd:                                  # общее правило: HD нет — честно «HD нет», вход не меняем
            res[sku] = {'no_hd': True, 'role': old.get(sku, {}).get('role')}
            print(sku, 'HD нет — пропуск', flush=True)
            json.dump(res, open(jp, 'w'), ensure_ascii=False, indent=1)
            continue
        url = (hd if a.src == 'hd' else None) or m.get('img') or (db.get(sku) or {}).get('image_url')
        role = old.get(sku, {}).get('role')
        try:
            shape_img, cut, input_hash, info = PRE._cut_chain(url, role=role)
        except Exception as e:  # noqa: BLE001 — один плохой товар не должен класть набор; причина — в отчёт
            res[sku] = {'error': f'{type(e).__name__}: {str(e)[:120]}', 'image_url': url, 'role': role}
            print(f'!! {sku}: вырезка упала — {res[sku]["error"]}', flush=True)
            json.dump(res, open(jp, 'w'), ensure_ascii=False, indent=1)
            continue
        rep = {}
        if not a.no_clean:
            shape_img, rep = clean_islands(shape_img)
            cut = PRE.trim_alpha(shape_img)
        buf = io.BytesIO()
        shape_img.save(buf, 'PNG')
        open(os.path.join(a.out, f'{name}.rgba.png'), 'wb').write(buf.getvalue())
        cut.save(os.path.join(a.out, f'{name}.cut-preview.png'))
        res[sku] = {'role': role, 'image_url': url, 'src': a.src, 'size': list(shape_img.size), 'input_png_sha256': hashlib.sha256(buf.getvalue()).hexdigest(),
                    'hybrid_error': info.get('hybrid_error'), 'uniform_bg': info.get('uniform_bg'), 'islands_removed': rep.get('removed'),
                    'mask': {k: info.get(k) for k in ('verdict', 'reason')}}
        print(sku, shape_img.size, 'hybrid_error:', info.get('hybrid_error'), '| срезано островков:', len(rep.get('removed') or []), flush=True)
        json.dump(res, open(jp, 'w'), ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
