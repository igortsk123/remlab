#!/usr/bin/env python3
"""Тест-страница /test/topview-test/: наш вид сверху из меша рядом с фото товара.

Владелец решает, годятся ли виды сверху вместо спрайтов (план topview-from-mesh).
Бейдж ориентации: confident — фронт откалиброван по фото; symmetric — предмету всё
равно; unobservable/unknown — фронт не определить, повёрнут как есть.
"""
import html
import json
import os
import shutil

SRC = os.path.expanduser('~/scout-scenes/mesh-topview')
V2 = os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2')
OUT = os.path.expanduser('~/scout-scenes/topview-test')

CHECKER = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAHUlEQVQoz2P8'
           'z8DAwMDAxMDAwMDAwPD//38GBgYGBgYAJRcDJcOB/xkAAAAASUVORK5CYII=')


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    man = json.load(open(os.path.join(SRC, 'topview.json'), encoding='utf-8'))
    cards = []
    import glob as g
    for sku, info in sorted(man.items(), key=lambda kv: (kv[1].get('role') or '', kv[0])):
        shutil.copy(os.path.join(SRC, info['png']), os.path.join(OUT, info['png']))
        cut = ''
        hits = sorted(g.glob(os.path.join(V2, sku, '*', 'cutout.png')), key=os.path.getmtime)
        if hits:
            shutil.copy(hits[-1], os.path.join(OUT, f'{sku}.photo.png'))
            cut = f'<img class="ph" src="{sku}.photo.png" loading="lazy">'
        badge = {'confident': '✓ фронт по фото', 'symmetric': '⊙ симметричен',
                 }.get(info.get('orient'), '? фронт не определён')
        wd = f"{info.get('w') or '?'}×{info.get('d') or '?'} см"
        cards.append(f"""
<div class="card">
 <h3>{html.escape(info.get('role') or '?')} <span class="sku">{sku}</span></h3>
 <div class="pair">
  <div><div class="lbl">вид сверху из модели · {wd} · {badge}</div>
   <img class="top" src="{info['png']}" loading="lazy"></div>
  <div><div class="lbl">фото товара</div>{cut}</div>
 </div>
</div>""")
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Вид сверху из мешей — тест</title><style>
body{{font:15px/1.5 system-ui;margin:24px;background:#fafaf8;color:#1c1c1a}}
.card{{background:#fff;border:1px solid #e5e5e0;border-radius:10px;padding:14px;margin:12px 0;max-width:900px}}
.sku{{font-size:12px;color:#999;font-weight:400}} .lbl{{font-size:12px;color:#666;margin-bottom:4px}}
.pair{{display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap}}
.top,.ph{{max-width:340px;max-height:260px;border-radius:6px;background:url('{CHECKER}') repeat}}
</style></head><body>
<h1>Вид сверху из наших 3D-моделей</h1>
<p>Механика планировщика прежняя: это лёгкие картинки, поворот — картинкой. Где модели нет — остаётся спрайт.</p>
{''.join(cards)}
</body></html>"""
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(page)
    print(f'карточек: {len(cards)} → {OUT}')


if __name__ == '__main__':
    main()
