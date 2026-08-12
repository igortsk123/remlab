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
    sid = r['scene']; n = r.get('set')
    png = os.path.join(HERE, f"v3set{n}-layout-acc-zoned-{sid}.png")
    lay = os.path.join(HERE, f"v3set{n}-layout-acc-zoned-{sid}.json")
    if not os.path.exists(png):
        continue
    shutil.copy(png, os.path.join(OUT, f"{sid}.png"))
    room_note = ''
    if os.path.exists(lay):
        data = json.load(open(lay))
        rm = data.get('_room') or {}
        # владелец 10.08: площадь и габариты комнаты — и в подпись, и в координаты
        # (судья-LLM должен видеть размеры)
        if rm.get('w') and rm.get('d'):
            rm['m2'] = round(rm['w'] * rm['d'] / 10_000, 1)
            rm['size_note'] = f"комната {rm['w']}×{rm['d']} см, {rm['m2']} м²"
            room_note = f"{rm['m2']} м² · {rm['w']}×{rm['d']} см · "
        json.dump(data, open(os.path.join(OUT, f"{sid}.json"), 'w'),
                  ensure_ascii=False, indent=1)
        combined[sid] = data
    ok = r.get('ok')
    status = 'OK' if ok else 'FAIL'
    ub = r.get('used_of_bank') or None
    fillp = r.get('fill_pct')
    zones_tag = (r.get('group') or '').split('+', 1)[1] if '+' in (r.get('group') or '') else ''
    _ZN = {'tpl': 'посадка', 'tpl-min': 'посадка(мин)', 'tv': 'медиа', 'tvfp': 'медиа+камин',
           'fp': 'камин', 'din': 'столовая', 'st': 'хранение', 'st2': 'хранение2',
           'st3': 'хранение3', 'pf': 'пуф', 'dc': 'декор', 'rd': 'чтение', 'qz': 'тихая',
           'notpl': 'нет схемы'}
    zones_ru = ' · '.join(_ZN.get(t, t) for t in zones_tag.split('+') if t) if zones_tag else '—'
    extra = (f" · из банка сета {ub[0]}/{ub[1]}" if ub else '') + \
            (f" · заполнение {fillp}%" if fillp else '')
    fails = ', '.join(r.get('fails') or []) if not ok else ''
    soft = r.get('soft_score')
    cards.append(
        f"<section id='{html.escape(sid)}'>"
        f"<h2>{html.escape(sid)} <small>({html.escape(room_note)}"
        f"{'✅ ' + status if ok else '❌ ' + status}"
        f"{' · ' + html.escape(fails) if fails else ''}"
        f"{f' · soft {soft}' if soft is not None else ''}"
        f"{html.escape(extra)})"
        f" · <a href='{html.escape(sid)}.json'>координаты</a></small><br>"
        f"<small style='color:#2E7D4F'>зоны: {html.escape(zones_ru)}</small></h2>"
        f"<img src='{html.escape(sid)}.png' loading='lazy' alt='{html.escape(sid)}'>"
        f"</section>")

json.dump(combined, open(os.path.join(OUT, 'layouts-all.json'), 'w'),
          ensure_ascii=False, indent=1)

page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<meta http-equiv="cache-control" content="no-store, no-cache, must-revalidate, max-age=0">
<title>Приёмка: планы всех сцен</title>
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
<p class="sub">Расстановка ТОЛЬКО шаблонами зон (правило владельца): у каждой сцены видно,
какие зоны применились и сколько предметов взято из банка сета · «название, план» подряд · у каждой сцены —
машиночитаемые координаты (JSON, система координат описана в
<a href="layouts-all.json">layouts-all.json</a>) · карты глубины не собираются (отдельный
процесс) · комментарии можно писать постепенно — сеты от них не пересобираются, партия
уходит в конвейер судьи</p>
{''.join(cards)}
</div></body></html>"""
open(os.path.join(OUT, 'index.html'), 'w').write(page)
print(f"OK: {len(cards)} сцен → {OUT}")
