#!/usr/bin/env python3
"""T-93/2: страница `/test/cutout-hd/` — вырезка «было» (вход пробы, фото 450 px) и «стало» (HD из `image_url_hd` → BiRefNet → гибрид → чистка островков)
на ОДНОМ розовом фоне, рядом размеры в пикселях. По образцу `tools/scout/mask_bench/build_page.py` (картинки отдельными файлами, не data-URI).
  ~/venvs/scout/bin/python build_cutout_hd_page.py [--publish]     → ~/scout-scenes/cutout-hd/ ; --publish → /opt/remlab/test/cutout-hd/ (как set_changes_page)
Входы: ~/remlab-logs/mesh-models-1118/trellis/inputs30 («было») и ~/remlab-logs/t93-1119/hd20 («стало», inputs.json c no_hd/error/islands_removed)."""
import html
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

OLD = '/home/pakar/remlab-logs/mesh-models-1118/trellis/inputs30'
NEW = '/home/pakar/remlab-logs/t93-1119/hd20'
OUT = os.path.expanduser('~/scout-scenes/cutout-hd')
PINK = np.array([255, 0, 170], np.float32)
MAXSIDE = 2560
ORDER = ['диван', 'кресло', 'кровать', 'стул', 'шкаф', 'стол обеденный', 'столик', 'комод', 'торшер', 'лампа', 'ваза']     # обивка — первой

SKUS = ['112923:16411672175141188566', '114667:8635337701646277566', '114082:10587794773481498560', '112923:1167444740116678789', '99272:607007941975253599',
        '112923:6031416063270639272', '112923:18087345950380988674', '112923:7957884067802792858', '112923:12914633732121796450', '112923:6479217809722640202',
        '112923:4765265273857423596', '112923:10551627698909366429', '112923:2876576317701299983', '112923:13879590536077663447', '112923:321183910010607839',
        '112923:3635164205624916724', '99272:10280649775260801227', '99272:9526407298450590277', '99272:17636404049075357658', '99272:2992974214342169827']


def pink(rgba):
    a = np.asarray(rgba.convert('RGBA')).astype(np.float32)
    al = a[..., 3:4] / 255.0
    return Image.fromarray((a[..., :3] * al + PINK * (1 - al)).clip(0, 255).astype(np.uint8))


def bottom_crop(rgba, comp):
    """нижние 35 % габарита предмета, на всю ширину предмета (та же ОТНОСИТЕЛЬНАЯ область у «было» и «стало»)."""
    al = np.asarray(rgba.convert('RGBA'))[..., 3] > 20
    ys, xs = np.where(al)
    if not len(ys):
        return comp
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
    h = y1 - y0 + 1
    pad = max(2, int(0.02 * (x1 - x0)))
    return comp.crop((max(0, x0 - pad), max(0, int(y1 - 0.35 * h)), min(comp.width, x1 + pad), min(comp.height, y1 + pad)))


def save(im, path):
    if max(im.size) > MAXSIDE:
        k = MAXSIDE / max(im.size)
        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    im.save(path, 'JPEG', quality=90)
    return os.path.getsize(path)


def main():
    old = json.load(open(f'{OLD}/inputs.json', encoding='utf-8'))
    new = json.load(open(f'{NEW}/inputs.json', encoding='utf-8'))
    os.makedirs(f'{OUT}/img', exist_ok=True)
    cards, stats = [], {'ok': 0, 'no_hd': 0, 'error': 0, 'missing': 0, 'islands': 0}
    for i, sku in enumerate(sorted(SKUS, key=lambda s: (ORDER.index(old[s]['role']) if old[s]['role'] in ORDER else 99, SKUS.index(s)))):
        key = sku.replace(':', '_')
        o, n = old[sku], new.get(sku) or {}
        rw = Image.open(f'{OLD}/{key}.rgba.png')
        cw = pink(rw)
        save(cw, f'{OUT}/img/{key}_was.jpg')
        save(bottom_crop(rw, cw), f'{OUT}/img/{key}_was_b.jpg')
        name = html.escape(o.get('name') or sku)
        was_px = f'{rw.width}×{rw.height}'
        right, note = '', ''
        if n.get('no_hd'):
            stats['no_hd'] += 1
            right = '<div class="nohd"><b>HD нет</b>в базе у этого товара нет фото крупнее; вход остаётся прежним</div>'
            cap = f'было {was_px} px · HD нет'
        elif n.get('error') or not os.path.exists(f'{NEW}/{key}.rgba.png'):
            stats['error' if n.get('error') else 'missing'] += 1
            right = f'<div class="nohd"><b>не получилось</b>{html.escape(n.get("error") or "вырезка ещё не посчитана")}</div>'
            cap = f'было {was_px} px · HD: сбой'
        else:
            stats['ok'] += 1
            rn = Image.open(f'{NEW}/{key}.rgba.png')
            cn = pink(rn)
            save(cn, f'{OUT}/img/{key}_now.jpg')
            save(bottom_crop(rn, cn), f'{OUT}/img/{key}_now_b.jpg')
            k = len(n.get('islands_removed') or [])
            stats['islands'] += k
            right = (f'<a class="im" href="img/{key}_now.jpg" target="_blank" rel="noopener"><img src="img/{key}_now.jpg" alt="стало: {name}" loading="lazy" style="aspect-ratio:{rn.width}/{rn.height}"></a>'
                     f'<a class="im crop" href="img/{key}_now_b.jpg" target="_blank" rel="noopener"><img src="img/{key}_now_b.jpg" alt="низ крупно: {name}" loading="lazy"></a>')
            cap = f'было {was_px} px → стало {rn.width}×{rn.height} px (×{rn.width / rw.width:.1f})'
            if k:
                note = f'<span class="cut">срезано клочков тени у низа: {k}</span>'
            if n.get('hybrid_error'):
                note += f'<span class="warn">гибрид упал: {html.escape(n["hybrid_error"])}</span>'
        left = (f'<a class="im" href="img/{key}_was.jpg" target="_blank" rel="noopener"><img src="img/{key}_was.jpg" alt="было: {name}" loading="lazy" style="aspect-ratio:{rw.width}/{rw.height}"></a>'
                f'<a class="im crop" href="img/{key}_was_b.jpg" target="_blank" rel="noopener"><img src="img/{key}_was_b.jpg" alt="низ крупно: {name}" loading="lazy"></a>')
        cards.append(f'<article class="pair" data-role="{html.escape(o["role"])}"><h3>{name}</h3><p class="cap">{html.escape(o["role"])} · {cap}</p>{note}'
                     f'<div class="cols"><div class="col"><b class="lab">было</b>{left}</div><div class="col"><b class="lab">стало</b>{right}</div></div></article>')
    roles = [r for r in ORDER if any(old[s]['role'] == r for s in SKUS)]
    chips = ''.join(f'<button class="chip" data-f="{html.escape(r)}">{html.escape(r)}</button>' for r in roles)
    page = TEMPLATE.replace('{cards}', '\n'.join(cards)).replace('{chips}', chips).replace('{n}', str(len(cards)))
    page = page.replace('{ok}', str(stats['ok'])).replace('{nohd}', str(stats['no_hd'])).replace('{bad}', str(stats['error'] + stats['missing']))
    open(f'{OUT}/index.html', 'w', encoding='utf-8').write(page)
    print('OK →', OUT, stats)
    if '--publish' in sys.argv:
        subprocess.run(f'tar -C {OUT} -czf /tmp/cutout-hd.tgz . && scp -q -P 22222 /tmp/cutout-hd.tgz root@89.167.127.0:/tmp/cutout-hd.tgz', shell=True, check=True)
        subprocess.run(['ssh', '-p', '22222', 'root@89.167.127.0',
                        'mkdir -p /opt/remlab/test/cutout-hd && tar -xzf /tmp/cutout-hd.tgz -C /opt/remlab/test/cutout-hd && '
                        'chmod -R a+rX /opt/remlab/test/cutout-hd'], check=True)      # без удаления: файлы поверх прежних (имена по ключу товара)
        print('опубликовано: /test/cutout-hd/')


TEMPLATE = r"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Вырезка: было и стало</title>
<style>
:root{--paper:#f6f7f8;--card:#fff;--ink:#151d24;--ink-2:#4a565f;--ink-3:#7d8990;--line:#dfe4e7;--accent:#276876;--warn:#a5591c;--bad:#a33b32}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#10161a;--card:#161d22;--ink:#e7ecee;--ink-2:#a5b1b7;--ink-3:#76848b;--line:#263037;--accent:#6fb6c4;--warn:#d99a55;--bad:#e08a80}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 -apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:0 16px}
header{padding:28px 0 12px}h1{margin:0 0 8px;font-size:clamp(1.5rem,5vw,2.2rem);line-height:1.15}
.lede{color:var(--ink-2);max-width:70ch;margin:0 0 8px}.how{color:var(--ink-3);font-size:.9rem;margin:0}
.bar{display:flex;flex-wrap:wrap;gap:6px;position:static;top:0;background:var(--paper);padding:10px 0;z-index:5;border-bottom:1px solid var(--line)}
.chip{font:500 .85rem/1 inherit;padding:8px 12px;border:1px solid var(--line);background:var(--card);color:var(--ink-2);border-radius:3px;cursor:pointer}
.chip[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#fff}
.pair{background:var(--card);border:1px solid var(--line);border-radius:4px;padding:12px;margin:14px 0}
.pair h3{margin:0;font-size:1rem}.cap{margin:2px 0 6px;color:var(--ink-2);font-size:.86rem;font-variant-numeric:tabular-nums}
.cut{display:inline-block;margin:0 8px 6px 0;font-size:.8rem;color:var(--warn)}.warn{color:var(--bad);font-size:.8rem}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:8px}.col{min-width:0}
.lab{display:block;font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);margin-bottom:4px}
a.im{display:block;margin-bottom:6px;line-height:0}a.im img{width:100%;height:auto;display:block;border:1px solid var(--line)}
a.crop img{image-rendering:pixelated}
.nohd{padding:18px 10px;border:1px dashed var(--line);color:var(--ink-2);font-size:.88rem}.nohd b{display:block;color:var(--bad);margin-bottom:4px}
.pair[hidden]{display:none}
footer{padding:20px 0 60px;color:var(--ink-3);font-size:.85rem}
@media (min-width:760px){.cols{gap:14px}.bar{position:sticky}}
</style></head><body>
<header><div class="wrap"><h1>Вырезка товара: было и стало</h1>
<p class="lede">Слева — вход, который шёл в пробу 3D (фото из фида, 450 px). Справа — то же самое по крупному фото из базы (<code>image_url_hd</code>) и после чистки клочков тени.
Фон розовый нарочно: на нём видны остатки фона, тень и потерянные ножки. Под каждой картинкой — низ предмета крупно (там живёт тень и ножки).</p>
<p class="how">Товаров: {n} · с крупным фото: {ok} · «HD нет»: {nohd} · сбоев: {bad}. Нажмите на картинку — откроется в полном размере.</p></div></header>
<div class="wrap"><div class="bar"><button class="chip" data-f="all" aria-pressed="true">все</button>{chips}</div>
<main id="list">
{cards}
</main>
<footer>Цепочка «стало»: фото магазина → BiRefNet (1024) → наш гибрид по цвету фона → чистка отдельных светлых клочков у низа. Эталонной маски нет — оценка глазами. Проба; в боевой конвейер не включено.</footer></div>
<script>(function(){var c=[].slice.call(document.querySelectorAll('.chip')),p=[].slice.call(document.querySelectorAll('.pair'));
function ap(f){c.forEach(function(x){x.setAttribute('aria-pressed',String(x.dataset.f===f))});p.forEach(function(x){x.hidden=!(f==='all'||x.dataset.role===f)})}
c.forEach(function(x){x.addEventListener('click',function(){ap(x.dataset.f)})});})();</script></body></html>
"""

if __name__ == '__main__':
    main()
