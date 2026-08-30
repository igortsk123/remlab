#!/usr/bin/env python3
"""Страница ремонтов: пары «оригинал → кандидат после ножей». Владелец сверяет глазами."""
import glob
import html
import json
import os
import time

VER = int(time.time())

SRC = os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2')
OUT = os.path.expanduser('~/scout-scenes/mesh-repairs')

cards = []
os.makedirs(OUT, exist_ok=True)
for mp in sorted(glob.glob(os.path.join(SRC, '*/*/manifest.json'))):
    d = os.path.dirname(mp)
    rep = os.path.join(d, 'model.repaired.glb')
    if not os.path.exists(rep):
        continue
    man = json.load(open(mp, encoding='utf-8'))
    sku = man['sku'].replace(':', '_')
    idir = os.path.join(OUT, sku)
    os.makedirs(idir, exist_ok=True)
    for name, srcf in (('orig.glb', 'model.glb'), ('fixed.glb', 'model.repaired.glb')):
        open(os.path.join(idir, name), 'wb').write(open(os.path.join(d, srcf), 'rb').read())
    cards.append(f"""
<div class="c"><h3>{html.escape(man.get('role') or '?')} <span>{sku}</span></h3>
 <div class="row">
  <figure><model-viewer src="{sku}/orig.glb?v={VER}" camera-controls style="width:100%;height:300px;background:#f4f4f2"></model-viewer><figcaption>до</figcaption></figure>
  <figure><model-viewer src="{sku}/fixed.glb?v={VER}" camera-controls style="width:100%;height:300px;background:#eef4ee"></model-viewer><figcaption>после ножей</figcaption></figure>
 </div></div>""")
open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(f"""<!doctype html><meta charset=utf-8>
<title>Ремонт мешей — до/после</title>
<script type="module" src="https://unpkg.com/@google/model-viewer@3.5.0/dist/model-viewer.min.js"></script>
<style>body{{font:15px system-ui;margin:20px}}.c{{border:1px solid #ddd;border-radius:8px;padding:12px;margin:14px 0;max-width:1000px}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}figure{{margin:0}}figcaption{{font-size:12px;color:#666}}span{{color:#999;font-size:12px}}</style>
<h1>Кандидаты ремонта: {len(cards)}</h1><p>Слева оригинал генератора, справа после ножей. Одобряете — кандидат заменит оригинал в галерее.</p>
{''.join(cards)}""")
print('пар на странице:', len(cards), '→', OUT)
