#!/usr/bin/env python3
"""ВХОДЫ ПРОБЫ ГЕНЕРАТОРОВ (T-20261118-91): вырезка товара тем же путём, что и у боевого Hunyuan (`preprocess._cut_chain` → BiRefNet + гибрид
`hybrid_mask.refine`, ADR-0133 — RGBA с настоящей альфой), но на ПРОЦЕССОРЕ DEV: видеокарты тут нет, а проба — три товара.

ЗАЧЕМ ОДИН ВХОД. Сравнение моделей честно только на ОДНОЙ и той же вырезке: отдаём её и TRELLIS.2, и Hunyuan 2.1 для пары. Хеш (sha256 PNG) и адрес
фото пишутся в `inputs.json` — в отчёте пробы он обязан быть.

  ~/venvs/scout/bin/python make_inputs.py --out ~/remlab-logs/mesh-models-1118/trellis/inputs 112923:13224664101879413845 [...]
  (тяжёлое — под `tools/ops/heavy-slot.sh`; сеть — только фото магазина, ключей не читает)
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.dirname(HERE)
sys.path.insert(0, SALAD)
sys.path.insert(0, os.path.dirname(SALAD))        # tools/scout — catalog_media, mesh_queue


def cpu_cutout(img):
    """`preprocess.cutout` на процессоре: BiRefNet из кэша Hugging Face DEV (`ZhengPeng7/BiRefNet`, float32) — тот же вход и тот же порядок
    операций, что в образе (там `.half()` на видеокарте)."""
    import numpy as np
    import torch
    from PIL import Image
    from torchvision import transforms
    from transformers import AutoModelForImageSegmentation
    global _M
    if '_M' not in globals():
        _M = AutoModelForImageSegmentation.from_pretrained('ZhengPeng7/BiRefNet', trust_remote_code=True).float().eval()     # веса в кэше half — на процессоре нужен float32
    tf = transforms.Compose([transforms.Resize((1024, 1024)), transforms.ToTensor(),
                             transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
    src = img.convert('RGB')
    with torch.no_grad():
        pred = _M(tf(src).unsqueeze(0))[-1].sigmoid().cpu()[0].squeeze()
    mask = Image.fromarray((pred.numpy() * 255).astype(np.uint8)).resize(src.size)
    out = src.convert('RGBA')
    out.putalpha(mask)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('skus', nargs='+', help='mid:eid')
    ap.add_argument('--out', required=True)
    ap.add_argument('--role', default=None)
    a = ap.parse_args()
    import catalog_media as CM
    import preprocess as PRE
    PRE.cutout = cpu_cutout                      # `_cut_chain` берёт `cutout` из модуля при вызове
    os.makedirs(a.out, exist_ok=True)
    res = {}
    for sku in a.skus:
        mid, eid = sku.split(':', 1)
        m = CM.media(mid, eid) or {}
        url = m.get('img')
        if not url:
            print(f'!! {sku}: адреса фото нет — пропуск', flush=True)
            res[sku] = {'error': 'no_image_url'}
            continue
        shape_img, cut, input_hash, info = PRE._cut_chain(url, role=a.role)
        buf = io.BytesIO()
        shape_img.save(buf, 'PNG')
        sha = hashlib.sha256(buf.getvalue()).hexdigest()
        name = sku.replace(':', '_')
        open(os.path.join(a.out, f'{name}.rgba.png'), 'wb').write(buf.getvalue())
        cut.save(os.path.join(a.out, f'{name}.cut-preview.png'))
        res[sku] = {'image_url': url, 'input_png_sha256': sha, 'input_hash_generator': input_hash, 'size': list(shape_img.size),
                    'mask': {k: info.get(k) for k in ('verdict', 'reason') if k in info}}
        print(f'{sku}: {shape_img.size} sha256 {sha[:16]} маска {res[sku]["mask"]}', flush=True)
    json.dump(res, open(os.path.join(a.out, 'inputs.json'), 'w'), ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
