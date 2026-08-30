#!/usr/bin/env python3
"""Локальный проход по фото плана: где на карточке ПАРА предметов — кроп до одного.

Порядок владельца (30.08): сначала параллельный проход по всем фото с бэкапом и страницей
до/после на проверку, в пайплайн — после его ОК. Исходники не трогаются вообще: кропы
пишутся ОТДЕЛЬНЫМИ файлами (fixphotos/), оригиналы остаются на CDN и рядом (orig/).

Маска — аналитическая, без нейронки: карточки сняты на ровном белом, объект = пиксели,
далёкие от цвета фона (медиана пограничной полосы, как в гибриде вырезки). Сценовые фото
(фон неровный) пропускаем молча — там детектору веры нет.

Пара: два крупных компонента, меньший ≥40% большего, пересечение по X <25%. Берём больший.
"""
import io
import json
import os
import sys
import urllib.request

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, '..', 'mesh-pilot-sample.json')
OUT = os.path.expanduser('~/scout-scenes/pair-fix')


def fetch(url):
    u = 'https:' + url if url.startswith('//') else url
    req = urllib.request.Request(u, headers={'User-Agent': 'remlab/1'})
    return Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=40).read())).convert('RGB')


def detect(img):
    rgb = np.asarray(img).astype(np.float32)
    h, w = rgb.shape[:2]
    b = max(2, int(min(h, w) * 0.04))
    band = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
                           rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])
    med = np.median(band, axis=0)
    if np.linalg.norm(med - 255) > 60 or (np.linalg.norm(band - med, axis=1) > 25).mean() > 0.35:
        return None                                  # сценовое фото — пропуск
    mask = np.linalg.norm(rgb - med, axis=2) > 28
    mask = ndimage.binary_opening(mask, np.ones((3, 3)))
    lab, n = ndimage.label(mask)
    if n < 2:
        return None
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    order = np.argsort(sizes)[::-1]
    if sizes[order[1]] < 0.40 * sizes[order[0]] or sizes[order[0]] < 0.02 * h * w:
        return None
    boxes = ndimage.find_objects(lab)
    b1, b2 = boxes[order[0]], boxes[order[1]]
    ov = max(0, min(b1[1].stop, b2[1].stop) - max(b1[1].start, b2[1].start))
    if ov / max(1, min(b1[1].stop - b1[1].start, b2[1].stop - b2[1].start)) > 0.25:
        return None
    pad = int(0.07 * max(b1[1].stop - b1[1].start, b1[0].stop - b1[0].start))
    return (max(0, b1[1].start - pad), max(0, b1[0].start - pad),
            min(w, b1[1].stop + pad), min(h, b1[0].stop + pad))


def main():
    os.makedirs(f'{OUT}/fixphotos', exist_ok=True)
    os.makedirs(f'{OUT}/orig', exist_ok=True)
    jobs = json.load(open(SAMPLE, encoding='utf-8'))['jobs']
    seen, found, rows = set(), 0, []
    for j in jobs:
        sku = j['sku'].replace(':', '_')
        if sku in seen or j.get('strata', {}).get('source') == 'fixphoto':
            continue
        if j.get('role') != 'стул':   # ТОЛЬКО стулья — просьба владельца; люстра-коллаж 30.08 попала самовольно
            continue
        seen.add(sku)
        try:
            img = fetch(j['image_url'])
        except Exception:
            continue
        box = detect(img)
        if not box:
            continue
        found += 1
        img.save(f'{OUT}/orig/{sku}.jpg', quality=90)
        img.crop(box).save(f'{OUT}/fixphotos/{sku}.jpg', quality=92)
        rows.append({'sku': sku, 'role': j.get('role')})
        print(f'  пара: {j.get("role", "?"):12s} {sku}', flush=True)
    cards = ''.join(
        f'<div class="c"><h3>{r["role"]} <span>{r["sku"]}</span></h3>'
        f'<img src="orig/{r["sku"]}.jpg"><img src="fixphotos/{r["sku"]}.jpg"></div>'
        for r in rows)
    open(f'{OUT}/index.html', 'w', encoding='utf-8').write(
        '<!doctype html><meta charset=utf-8><title>Пары: до/после</title>'
        '<style>body{font:15px system-ui;margin:20px}.c{margin:14px 0;padding:10px;'
        'border:1px solid #ddd;border-radius:8px;max-width:960px}img{max-height:220px;'
        'margin-right:12px;vertical-align:top}span{color:#999;font-size:12px}</style>'
        f'<h1>Найдено пар: {len(rows)}</h1><p>Слева оригинал, справа кроп. '
        f'Ошибся детектор — пришлите код.</p>{cards}')
    json.dump(rows, open(f'{OUT}/pairs.json', 'w'), ensure_ascii=False)
    print(f'проверено {len(seen)}, пар найдено {found} → {OUT}')


if __name__ == '__main__':
    main()
