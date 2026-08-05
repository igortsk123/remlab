#!/usr/bin/env python3
"""Страница-арбитраж: стиль по тексту против стиля по фотографии.

Замер показал, что одна и та же сильная модель, увидев фотографию, меняет главный стиль у
половины товаров, а на декоре — у восьми из десяти. Кто из двух прав, машина решить не может:
арбитр здесь человек. Страница показывает фото товара, то, ЧТО модель видела в тексте, и два
ответа — чтобы владелец ткнул пальцем.

  ~/venvs/scout/bin/python style_check_page.py
"""
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.expanduser('~/scout-scenes/golden')
sys.path.insert(0, HERE)
from golden_label import prompt  # noqa: E402

ORDER = {'нет': 0, 'низкая': 1, 'средняя': 2, 'высокая': 3}


def top(st: dict) -> str:
    return max(st, key=lambda k: ORDER.get(st[k], 0)) if st else '—'


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    golden = {f'{i["mid"]}:{i["eid"]}': i for i in json.load(open(os.path.join(HERE, 'golden.json')))}
    txt = json.load(open(os.path.join(HERE, 'golden-ref.json')))['labels']
    vis = json.load(open(os.path.join(HERE, 'golden-ref-vision.json')))['labels']
    rows = []
    for k in vis:
        if k not in txt or k not in golden:
            continue
        a, b = top(txt[k].get('styles') or {}), top(vis[k].get('styles') or {})
        if a == b:
            continue
        rows.append((golden[k], a, b, txt[k], vis[k]))
    rows.sort(key=lambda r: r[0]['role_feed'])
    cards = []
    for it, a, b, ta, tb in rows[:36]:
        img = it['img']
        img = 'https:' + img if img.startswith('//') else img
        seen = html.escape(prompt(it)).replace('\n', '<br>')
        cards.append(f"""<article class="c">
  <div class="ph"><img src="{html.escape(img)}" loading="lazy" alt=""></div>
  <div class="b">
    <div class="role">{html.escape(it['role_feed'])}</div>
    <h3>{html.escape(it['name'][:80])}</h3>
    <div class="verdicts">
      <div class="v t"><span>по тексту</span><b>{html.escape(a)}</b></div>
      <div class="v p"><span>по фото</span><b>{html.escape(b)}</b></div>
    </div>
    <details><summary>что модель видела в тексте</summary><div class="seen">{seen}</div></details>
  </div>
</article>""")

    css = """
:root{--bg:#f5f4f1;--panel:#fff;--ink:#1a1917;--dim:#6d6a64;--line:#e2ded7;--txt:#8a5b34;
      --pic:#2f6b7d;--chip:#eeeae2}
@media (prefers-color-scheme:dark){:root{--bg:#141310;--panel:#1d1c18;--ink:#eeeae2;--dim:#a09a90;
      --line:#302e27;--txt:#c99a63;--pic:#7cb8c9;--chip:#26241f}}
:root[data-theme=dark]{--bg:#141310;--panel:#1d1c18;--ink:#eeeae2;--dim:#a09a90;--line:#302e27;
      --txt:#c99a63;--pic:#7cb8c9;--chip:#26241f}
:root[data-theme=light]{--bg:#f5f4f1;--panel:#fff;--ink:#1a1917;--dim:#6d6a64;--line:#e2ded7;
      --txt:#8a5b34;--pic:#2f6b7d;--chip:#eeeae2}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font:16px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:32px 20px 70px}
h1{font-size:27px;margin:0 0 8px}
.lede{color:var(--dim);max-width:72ch;margin:0 0 8px}
.nums{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 26px}
.nums div{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
.nums b{display:block;font-size:22px;font-variant-numeric:tabular-nums}
.nums span{font-size:12.5px;color:var(--dim)}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(320px,1fr))}
.c{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden;
   display:flex;gap:12px;padding:12px}
.ph{width:110px;flex:0 0 110px;aspect-ratio:1;background:#fff;border-radius:8px;overflow:hidden;
    display:flex;align-items:center;justify-content:center}
.ph img{max-width:100%;max-height:100%;object-fit:contain}
.b{min-width:0;flex:1}
.role{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim)}
h3{font-size:14px;margin:3px 0 9px;font-weight:600;line-height:1.3}
.verdicts{display:flex;gap:8px}
.v{flex:1;background:var(--chip);border-radius:8px;padding:6px 9px}
.v span{display:block;font-size:11px;color:var(--dim)}
.v b{font-size:14px}
.v.t b{color:var(--txt)}
.v.p b{color:var(--pic)}
details{margin-top:9px}
summary{font-size:12.5px;color:var(--dim);cursor:pointer}
.seen{font-size:12px;color:var(--dim);background:var(--chip);border-radius:8px;padding:9px;
      margin-top:6px;font-family:ui-monospace,Menlo,monospace;line-height:1.5}
"""
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Стиль по тексту против стиля по фото</title><style>{css}</style></head><body><div class="wrap">
<h1>Стиль по тексту против стиля по фотографии</h1>
<p class="lede">Одна и та же сильная модель размечала товары дважды: сначала по тексту карточки,
потом по тексту вместе с фотографией. Роль и функцию текст определяет надёжно, а стиль —
нет: увидев вещь, модель меняет главный стиль у половины товаров. Здесь те, где ответы разошлись.
Скажите, чей ответ ближе к правде — по этому решится, гонять ли весь каталог с картинками.</p>
<div class="nums">
  <div><b>88%</b><span>совпадение по роли<br>текст ↔ фото</span></div>
  <div><b>91%</b><span>по функции<br>текст ↔ фото</span></div>
  <div><b>76%</b><span>по материалу</span></div>
  <div><b>53%</b><span>по главному стилю</span></div>
  <div><b>16%</b><span>стиль по тексту ↔ стиль<br>по картинке (CLIP), 3 748 тов.</span></div>
  <div><b>12.3%</b><span>товаров с годным<br>описанием</span></div>
</div>
<div class="grid">{''.join(cards)}</div>
</div></body></html>"""
    p = os.path.join(OUT, 'style-check.html')
    open(p, 'w').write(page)
    print(f'страница: {p}; примеров: {len(cards)} из {len(rows)} расхождений')


if __name__ == '__main__':
    main()
