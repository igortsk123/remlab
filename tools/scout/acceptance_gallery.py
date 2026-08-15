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


def _debug_overlay(art: dict, out_png: str) -> bool:
    """V4-G свода №10: debug-оверлей для рефери — entry reserve, дуги дверей,
    главный маршрут (эрозия на замеренную ширину), крупнейший незакреплённый регион.
    Только в referee-галерею; пользовательский рендер не трогаем."""
    try:
        import sys
        sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))
        from PIL import Image, ImageDraw
        from planner.models import Item, Opening, Placement, Room
        from planner.zones import route_reserve
        from planner.geometry import room_polygon, swing_polygon, footprint
        from planner.quality import _free_space, zone_cohesion
        rm = art.get('_room') or {}
        if not rm.get('w'):
            return False
        room = Room(width_cm=rm['w'], depth_cm=rm['d'],
                    contour=[tuple(pt) for pt in rm['contour']] if rm.get('contour') else None,
                    openings=[Opening(**{k: v for k, v in op.items()
                                         if k in ('kind', 'wall', 'offset_cm', 'width_cm',
                                                  'swing_cm', 'sill_cm', 'hinge')})
                              for op in (rm.get('openings') or [])])
        ps = []
        for role, v in art.items():
            if role.startswith('_') or not isinstance(v, dict) or 'x' not in v:
                continue
            ps.append(Placement(role=role, x=v['x'], y=v['z'],
                                rot=float(v.get('rot') or 0),
                                item=Item(role=role, w_cm=v.get('w') or 40,
                                          d_cm=v.get('d') or 40, h_cm=80)))
        SC = 2
        img = Image.new('RGB', (int(room.width_cm) * SC // 1, int(room.depth_cm) * SC // 1),
                        '#ffffff')
        dr = ImageDraw.Draw(img, 'RGBA')
        def poly(g, fill, outline=None):
            geoms = getattr(g, 'geoms', [g])
            for gg in geoms:
                if gg.is_empty or not hasattr(gg, 'exterior'):
                    continue
                pts = [(x * SC, (room.depth_cm - y) * SC) for x, y in gg.exterior.coords]
                dr.polygon(pts, fill=fill, outline=outline)
        poly(room_polygon(room), '#ffffff', '#333333')
        # главный маршрут: эрозия свободного пола на замеренную ширину
        free = _free_space(room, ps)
        rw = float(art.get('_route_cm') or 75)
        core = free.buffer(-rw / 2, resolution=4)
        if not core.is_empty:
            poly(core.buffer(rw / 2, resolution=4).intersection(free), (46, 125, 50, 70))
        # entry reserve + дуги
        poly(route_reserve(room), (33, 150, 243, 60))
        for op in room.openings:
            if op.kind in ('door', 'balcony'):
                poly(swing_polygon(room, op), (33, 150, 243, 90))
        # мебель поверх
        for p in ps:
            poly(footprint(p), (120, 120, 120, 120), '#555555')
        # крупнейший незакреплённый регион — контур
        try:
            zc = (art.get('_axes') or {}).get('zone_cohesion') or {}
            if zc.get('largest_unassigned_m2', 0) > 0:
                from planner.quality import zone_envelopes
                from shapely.ops import unary_union
                env = zone_envelopes(room, ps); env.pop('other', None)
                rest = room_polygon(room).difference(
                    unary_union(list(env.values()) + [route_reserve(room)]))
                comps = sorted(getattr(rest, 'geoms', [rest]), key=lambda g: -g.area)
                if comps and not comps[0].is_empty:
                    poly(comps[0], (255, 152, 0, 60), '#E65100')
        except Exception:
            pass
        img.save(out_png)
        return True
    except Exception:
        return False

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
    _dbg_ok = False
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
        if os.environ.get('DEBUG_OVERLAY', '1') != '0':
            _dbg_ok = _debug_overlay(data, os.path.join(OUT, f"{sid}-debug.png"))
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
    # НОМЕР ПЛАНА (просьба владельца 12.08: «сделай каждому плану номер — так проще»):
    # сквозной 1..252 в порядке галереи, чтобы можно было сказать «план №37».
    cards.append(
        f"<section id='plan{len(cards)+1}'>"
        f"<h2><a href='#plan{len(cards)+1}' style='text-decoration:none'>План №{len(cards)+1}</a>"
        f" — {html.escape(sid)} <small>({html.escape(room_note)}"
        f"{'✅ ' + status if ok else '❌ ' + status}"
        f"{' · ' + html.escape(fails) if fails else ''}"
        f"{f' · soft {soft}' if soft is not None else ''}"
        f"{html.escape(extra)})"
        f" · <a href='{html.escape(sid)}.json'>координаты</a>"
        + (f" · <a href='{html.escape(sid)}-debug.png'>debug</a>" if _dbg_ok else '')
        + f"</small><br>"
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
