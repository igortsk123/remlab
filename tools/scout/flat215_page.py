#!/usr/bin/env python3
"""Витрина «квартира 215 → гостиная»: предпосчитанные варианты расстановки для РЕАЛЬНОЙ планировки
(первый вертикальный срез продукта, владелец 26.08). Остальные комнаты — заглушки.

Планировка и допущения — `flat215.json`; варианты считаются солвером офлайн (P1 метаплана),
страница только показывает готовое: ничего не считается на лету.

  ~/venvs/scout/bin/python flat215_page.py [--publish]   # → /test/flat215/
"""
import glob
import html
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.expanduser('~/scout-scenes/flat215')
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))
from render_plan import render_artifact  # noqa: E402

VARIANTS = [(1, 'сканди'), (4, 'современный'), (7, 'минимализм'),
            (10, 'лофт'), (13, 'неоклассика'), (16, 'джапанди')]


def build() -> list[dict]:
    os.makedirs(OUT, exist_ok=True)
    flat = json.load(open(os.path.join(HERE, 'flat215.json'), encoding='utf-8'))
    liv = flat['rooms'][0]
    cards = []
    for n, style in VARIANTS:
        fs = sorted(glob.glob(os.path.join(HERE, f'v3set{n}-layout.json')),
                    key=os.path.getmtime, reverse=True)
        if not fs:
            continue
        art = json.load(open(fs[0], encoding='utf-8'))
        png = os.path.join(OUT, f'variant-{n}.png')
        render_artifact(art, png, band='14-16')
        roles = [k for k in art if not k.startswith('_')]
        sets = json.load(open(os.path.join(HERE, 'sets3.json'), encoding='utf-8'))
        items = sets[n - 1].get('items') or {}
        cards.append({'n': n, 'style': style, 'png': os.path.basename(png),
                      'fill': art.get('_fill_pct'), 'roles': sorted(roles),
                      'sofa': (items.get('диван') or {}).get('name', ''),
                      'rug': (items.get('ковёр') or {}).get('name', '')})
    return cards, liv


def main() -> None:
    cards, liv = build()
    ver = str(int(time.time()))
    body = []
    for c in cards:
        body.append(
            f"<section><h2>Вариант «{html.escape(c['style'])}»</h2>"
            f"<img src='{c['png']}?v={ver}' alt='{html.escape(c['style'])}'>"
            f"<div class='meta'><b>Заполнение пола:</b> {c['fill']} % · "
            f"<b>предметов:</b> {len(c['roles'])}<br>"
            f"<b>состав:</b> {html.escape(', '.join(c['roles']))}<br>"
            f"<b>диван:</b> {html.escape(c['sofa'][:60])}<br>"
            f"<b>ковёр:</b> {html.escape(c['rug'][:60])}</div></section>")
    style = ("body{margin:0;background:#fff;color:#1A1F1C;font:17px/1.5 system-ui}"
             ".wrap{max-width:1050px;margin:0 auto;padding:20px 14px 60px}h1{font-size:23px}"
             "section{border-top:1px solid #E4E6E2;padding:18px 0}h2{font-size:19px;margin:0 0 10px}"
             "img{max-width:100%;border:1px solid #ECEEEA;border-radius:4px}"
             ".meta{font-size:15px;color:#3A423C;margin-top:8px}"
             ".head{margin:10px 0;padding:10px 12px;border-left:3px solid #3B76A2;"
             "background:#F4F7FA;font-size:15.5px}")
    head = (f"<div class='head'>Квартира №215 (73.7 м²), <b>гостиная {liv['w']}×{liv['d']} см "
            f"({liv['w'] * liv['d'] / 10000:.1f} м²)</b>. Габариты сняты с чертежа по масштабу — "
            "точные ждём от застройщика. Окно на наружной стене, дверь из холла, радиатор под окном. "
            "Варианты <b>предпосчитаны офлайн</b>: страница ничего не считает. Остальные комнаты "
            "квартиры пока заглушки.</div>")
    page = ("<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<meta name='robots' content='noindex'><meta http-equiv='cache-control' content='no-store'>"
            f"<title>Квартира 215 — гостиная</title><style>{style}</style></head><body><div class='wrap'>"
            f"<h1>Квартира №215 — гостиная: варианты из шаблонов</h1>{head}{''.join(body)}</div></body></html>")
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(page)
    print(f'OK: {len(cards)} вариантов → {OUT}')
    if '--publish' in sys.argv:
        subprocess.run(f"cd {os.path.dirname(OUT)} && tar czf /tmp/flat215.tgz flat215 && "
                       "scp -q -P 22222 /tmp/flat215.tgz root@89.167.127.0:/tmp/ && "
                       "ssh -p 22222 root@89.167.127.0 'cd /tmp && rm -rf flat215 && tar xzf flat215.tgz && "
                       "rm -rf /opt/remlab/test/flat215 && mv flat215 /opt/remlab/test/flat215 && rm flat215.tgz' && "
                       "rm -f /tmp/flat215.tgz", shell=True, check=True)
        print('опубликовано: /test/flat215/')


if __name__ == '__main__':
    main()
