#!/usr/bin/env python3
"""Галерея пилота мешей: исходник → вырезка → вертящаяся 3D-модель. Публикуется на /test/.

Зачем страница, а не файлы. Владелец оценивает ДВЕ вещи, и обе — глазами: качественно ли
режется фото (просьба 29.08: «проверь фотки, что качественно режутся») и похож ли меш на
товар со всех сторон. Рендеры с фиксированных углов прячут спину и бока — поэтому модель
вертится в браузере (<model-viewer>, GLB как есть); вырезка — на клетчатом фоне, где виден
каждый съеденный пиксель и каждый прилипший кусок фона.

  ~/venvs/scout/bin/python gallery_build.py           # собрать в ~/scout-scenes/mesh-pilot-gallery
"""
import base64
import glob
import html
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

SRC = os.environ.get('GALLERY_SRC', os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2'))
OUT = os.path.expanduser('~/scout-scenes/mesh-pilot-gallery')

CHECKER = ('data:image/png;base64,' + base64.b64encode(bytes.fromhex(
    '89504e470d0a1a0a0000000d494844520000001000000010080200000090916836000000'
    '1d49444154289163fccfc0c0f09f818181f93f0323430323430323835d0d00a67b032500'
    'b7ac7e9c0000000049454e44ae426082')).decode()).replace('\n', '')


def build() -> str:
    rows = []
    for d in sorted(glob.glob(os.path.join(SRC, '*/*/'))):
        man_p = os.path.join(d, 'manifest.json')
        if not os.path.exists(man_p):
            continue
        man = json.load(open(man_p, encoding='utf-8'))
        sku = man['sku'].replace(':', '_')
        item_dir = os.path.join(OUT, sku)
        os.makedirs(item_dir, exist_ok=True)
        for f in ('model.glb', 'cutout.png', 'input.png'):
            s = os.path.join(d, f)
            if os.path.exists(s):
                open(os.path.join(item_dir, f), 'wb').write(open(s, 'rb').read())
        # PBR-приёмка — на месте, по свежему GLB
        try:
            import mesh_gate_pbr as PBR
            st = PBR.status(os.path.join(d, 'model.glb'), role=man.get('role'))
            pbr = {'status': st['status'],
                   'problems': (st.get('pbr') or {}).get('problems', []),
                   'tris': (st.get('runtime') or {}).get('triangles'),
                   'size_mb': (st.get('runtime') or {}).get('size_mb')}
        except Exception as e:  # noqa: BLE001 — приёмка не должна валить галерею
            pbr = {'status': 'gate_error', 'problems': [str(e)[:100]]}
        rows.append({'sku': sku, 'man': man, 'pbr': pbr})

    cards = []
    for r in rows:
        m, p = r['man'], r['pbr']
        t = m.get('timings_s') or {}
        mask = m.get('mask') or {}
        probs = ''.join(f'<li>{html.escape(x)}</li>' for x in p['problems'][:4])
        cards.append(f"""
<div class="card">
  <h3>{html.escape(m.get('role') or '?')} <span class="sku">{r['sku']}</span></h3>
  <div class="tri">
    <figure><img src="{r['sku']}/input.png" loading="lazy"><figcaption>вход генератора</figcaption></figure>
    <figure class="checker"><img src="{r['sku']}/cutout.png" loading="lazy"><figcaption>вырезка (гибрид)</figcaption></figure>
    <figure><model-viewer src="{r['sku']}/model.glb" camera-controls auto-rotate shadow-intensity="1"
      style="width:100%;height:280px;background:#f4f4f2"></model-viewer>
      <figcaption>меш — крутится мышью</figcaption></figure>
  </div>
  <p class="meta">форма {t.get('shape')}с · покраска {t.get('paint')}с · всего {t.get('total')}с ·
     VRAM пик {(m.get('gpu') or {}).get('paint_gb')} ГБ ·
     маска: возвращено {mask.get('restored_px')} px, фон {'ровный' if mask.get('uniform_bg') else 'сцена'} ·
     приёмка: <b>{p['status']}</b> · трис {p.get('tris')} · {p.get('size_mb')} МБ</p>
  {f'<ul class="probs">{probs}</ul>' if probs else ''}
</div>""")

    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Пилот мешей — 10 товаров</title>
<script type="module" src="https://unpkg.com/@google/model-viewer@3.5.0/dist/model-viewer.min.js"></script>
<style>
 body{{font:15px/1.5 system-ui;margin:24px;background:#fafaf8;color:#1c1c1a}}
 h1{{font-size:22px}} .card{{background:#fff;border:1px solid #e5e5e0;border-radius:10px;
 padding:16px;margin:18px 0;max-width:1180px}}
 .tri{{display:grid;grid-template-columns:1fr 1fr 1.2fr;gap:14px;align-items:start}}
 figure{{margin:0}} img{{max-width:100%;border-radius:6px}}
 .checker img{{background:url({CHECKER});background-size:16px 16px}}
 figcaption{{font-size:12px;color:#666;margin-top:4px}}
 .sku{{font-size:12px;color:#999;font-weight:400}} .meta{{font-size:13px;color:#444}}
 .probs{{font-size:13px;color:#a33;margin:4px 0 0 18px}}
 @media(max-width:900px){{.tri{{grid-template-columns:1fr}}}}
</style></head><body>
<h1>Пилот 3D-мешей: Hunyuan3D 2.1 на Salad — 10 товаров</h1>
<p>Вырезка — наш гибрид поверх BiRefNet (клетка = прозрачность). Меш вертится мышью;
автоповорот выключается кликом. Партия v1: меши пока БЕЗ текстур (баг конвертации, починен) — оцениваются вырезка и форма; текстурные модели придут после пополнения Salad и перегона v2.</p>
{''.join(cards)}
</body></html>"""
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(page)
    print(f'карточек: {len(rows)} → {OUT}/index.html')
    for r in rows:
        print(f"  {r['man'].get('role'):14s} приёмка={r['pbr']['status']:12s} "
              f"{(r['pbr']['problems'] or ['—'])[0][:60]}")
    return OUT


if __name__ == '__main__':
    build()
