#!/usr/bin/env python3
"""Галерея приёмки: все сцены на ОДНОЙ странице — «название, план» подряд + координаты.

Зачем (владелец 10.08): просматривать 252 плана подряд и писать комментарии постепенно;
карты глубины сюда НЕ собираются (отдельный процесс). К каждой сцене — ссылка на
машиночитаемые координаты (тот же v3setN-layout-acc-… .json, которым пользуется судья).

  ~/venvs/scout/bin/python acceptance_gallery.py            # → ~/scout-scenes/acc-gallery/
  … затем scp каталога на прод в /opt/remlab/test/acceptance-plans/
"""
import html
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.expanduser('~/scout-scenes/acc-gallery')
REPORT = os.path.join(HERE, 'acceptance-report-zoned.jsonl')

os.makedirs(OUT, exist_ok=True)
rows = [json.loads(l) for l in open(REPORT) if l.strip()]
rows.sort(key=lambda r: (r.get('set') or 0, r.get('id') or ''))

cards = []
combined = {}
for r in rows:
    sid = r['id']; n = r.get('set')
    png = os.path.join(HERE, f"v3set{n}-layout-acc-zoned-{sid}.png")
    lay = os.path.join(HERE, f"v3set{n}-layout-acc-zoned-{sid}.json")
    if not os.path.exists(png):
        continue
    shutil.copy(png, os.path.join(OUT, f"{sid}.png"))
    if os.path.exists(lay):
        shutil.copy(lay, os.path.join(OUT, f"{sid}.json"))
        combined[sid] = json.load(open(lay))
    ok = r.get('verdict') == 'OK' or r.get('ok')
    status = 'OK' if ok else 'FAIL'
    fails = ', '.join(r.get('fails') or r.get('hard') or []) if not ok else ''
    soft = r.get('soft_score')
    cards.append(
        f"<section id='{html.escape(sid)}'>"
        f"<h2>{html.escape(sid)} <small>({'✅ ' + status if ok else '❌ ' + status}"
        f"{' · ' + html.escape(fails) if fails else ''}"
        f"{f' · soft {soft}' if soft is not None else ''})"
        f" · <a href='{html.escape(sid)}.json'>координаты</a></small></h2>"
        f"<img src='{html.escape(sid)}.png' loading='lazy' alt='{html.escape(sid)}'>"
        f"</section>")

json.dump(combined, open(os.path.join(OUT, 'layouts-all.json'), 'w'),
          ensure_ascii=False, indent=1)

page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Приёмка: планы всех сцен</title>
<style>
body{{margin:0;background:#fff;color:#1A1F1C;font:15px/1.5 system-ui,sans-serif}}
.wrap{{max-width:920px;margin:0 auto;padding:20px 14px 60px}}
h1{{font-size:20px}} .sub{{color:#5C655E;font-size:13px;margin-bottom:14px}}
section{{border-top:1px solid #E4E6E2;padding:14px 0}}
h2{{font-size:16px;margin:0 0 8px}} h2 small{{color:#5C655E;font-weight:400;font-size:13px}}
img{{max-width:100%;height:auto;border:1px solid #ECEEEA;border-radius:4px}}
a{{color:#2F6B8F}}
</style></head><body><div class="wrap">
<h1>Приёмка — планы всех сцен ({len(cards)})</h1>
<p class="sub">Прогон с правилами kb-rules-merge · «название, план» подряд · у каждой сцены —
машиночитаемые координаты (JSON, система координат описана в
<a href="layouts-all.json">layouts-all.json</a>) · карты глубины не собираются (отдельный
процесс) · комментарии можно писать постепенно — сеты от них не пересобираются, партия
уходит в конвейер судьи</p>
{''.join(cards)}
</div></body></html>"""
open(os.path.join(OUT, 'index.html'), 'w').write(page)
print(f"OK: {len(cards)} сцен → {OUT}")
