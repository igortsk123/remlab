#!/usr/bin/env python3
"""Отчёт по сету одной командой: план сверху + два вида (зона отдыха и ТВ-зона) + HTML товаров.

Владелец проверяет сет глазами, поэтому текстовых списков мало: нужен пакет из четырёх файлов.
Раньше это собиралось руками по кусочкам — теперь один вызов, ничего не забывается.

  ~/venvs/scout/bin/python set_report.py 21            # всё: раскладка + 2 генерации + HTML
  ~/venvs/scout/bin/python set_report.py 21 --no-gen   # без генераций (быстро, из готовых кадров)
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.expanduser('~/venvs/scout/bin/python')
OUT = os.environ.get('REPORT_DIR') or os.path.join(HERE, 'reports')


def money(v):
    return f"{int(v or 0):,}".replace(',', ' ')


def thumb_data(mid, eid):
    p = os.path.join(HERE, 'thumbs', f"{mid}-{re.sub(r'[^A-Za-z0-9]', '_', str(eid))[:40]}.png")
    if not os.path.exists(p):
        return ''
    return 'data:image/png;base64,' + base64.b64encode(open(p, 'rb').read()).decode()


def img_data(path):
    if not os.path.exists(path):
        return ''
    ext = 'jpeg' if path.lower().endswith(('.jpg', '.jpeg')) else 'png'
    return f'data:image/{ext};base64,' + base64.b64encode(open(path, 'rb').read()).decode()


def build_html(n, s, files):
    cards = []
    for role, it in s['items'].items():
        img = thumb_data(it['mid'], it['eid'])
        dims = ' x '.join(str(int(it[k])) for k in ('w', 'd', 'h') if it.get(k))
        ph = f'<img src="{img}">' if img else '<span class=no>нет фото</span>'
        link = f'<br><a href="{it["url"]}" target=_blank>карточка товара</a>' if it.get('url') else ''
        cards.append(
            f'<div class=c><div class=ph>{ph}</div><div class=t><b>{role}</b><br>'
            f'{(it.get("name") or "")[:70]}<br><span class=m>{dims} см · {it.get("shop", "")}</span>'
            f'<br><span class=p>{money(it.get("price"))} ₽</span>{link}</div></div>'
        )
    shots = []
    for title, path in files:
        d = img_data(path)
        if d:
            shots.append(f'<figure><img src="{d}"><figcaption>{title}</figcaption></figure>')
    style = (
        "body{font:14px/1.45 system-ui;background:#faf8f5;margin:24px;color:#222}"
        "h1{font-size:20px;margin:0 0 4px} h2{font-size:16px;margin:26px 0 10px}"
        ".sub{color:#777;margin-bottom:18px}"
        ".g{display:flex;flex-wrap:wrap;gap:14px}"
        ".c{width:250px;background:#fff;border:1px solid #e6e0d8;border-radius:10px;padding:10px}"
        ".ph{height:170px;display:flex;align-items:center;justify-content:center}"
        ".ph img{max-width:100%;max-height:170px}"
        ".m{color:#777} .p{color:#b4552a;font-weight:600} .no{color:#bbb} a{color:#3a6ea5}"
        "figure{margin:0 0 18px} figure img{max-width:100%;border:1px solid #e6e0d8;border-radius:10px}"
        "figcaption{color:#777;padding-top:6px}"
    )
    return (
        f'<meta charset=utf-8><title>Сет {n}</title><style>{style}</style>'
        f'<h1>Сет {n} · {s["band"]} м² · {s["tier"]} · стиль {s["style"]}</h1>'
        f'<div class=sub>итого {money(s.get("total"))} ₽ · предметов {len(s["items"])}</div>'
        f'<h2>Как это выглядит</h2>{"".join(shots)}'
        f'<h2>Товары сета</h2><div class=g>{"".join(cards)}</div>'
    )


def main():
    n = int(sys.argv[1])
    no_gen = '--no-gen' in sys.argv
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    s = sets[n - 1]
    env = dict(os.environ, LAYOUT_ENGINE='beam')
    if not no_gen:
        subprocess.run([PY, os.path.join(HERE, 'solver_run.py'), str(n), '--v3'], env=env, check=False)
        for view in ('A', 'B'):
            subprocess.run([PY, os.path.join(HERE, 'pipeline2.py'), str(n), '--v3', '--layout', view],
                           check=False)
    os.makedirs(OUT, exist_ok=True)
    plan = os.path.join(HERE, f'v3set{n}-layout.png')
    view_a = os.path.join(HERE, f'v3set{n}-pipe2-A.jpg')
    view_b = os.path.join(HERE, f'v3set{n}-pipe2-B.jpg')
    files = [('План сверху (размеры, углы, стрелка — куда смотрит предмет)', plan),
             ('Вид 1 — зона отдыха', view_a),
             ('Вид 2 — ТВ-зона', view_b)]
    html = build_html(n, s, files)
    out_html = os.path.join(OUT, f'set{n}.html')
    open(out_html, 'w').write(html)
    made = [out_html]
    for _, p in files:
        if os.path.exists(p):
            dst = os.path.join(OUT, os.path.basename(p))
            shutil.copy(p, dst)
            made.append(dst)
    print('\n'.join(made))


if __name__ == '__main__':
    main()
