#!/usr/bin/env python3
"""ЛИСТ-СНИМОК БАНКА СПАЛЬНИ для приёмки глазами (план onb-06 Т4): на каждый набор — фото предметов (роль, цена, меш),
план сверху по раскладке солвера (стены, окна, дверь с дугой, батареи, мебель, ковёр) и пробелы. Только чтение банка.

  python3 bedroom_sheet.py BANK.json OUT_DIR      # → OUT_DIR/bedroom-sheet.html (+ PNG, если есть Playwright)
"""
import html
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

COL = {'кровать': '#8fb3d9', 'тумба прикроватная': '#e0b080', 'шкаф': '#9bc49b', 'комод': '#c9a3d6', 'ковёр': '#f1e3c8',
       'лампа': '#f5d76e'}
LABEL = {'кровать': 'кровать', 'тумба прикроватная': 'тумба', 'шкаф': 'шкаф', 'комод': 'комод', 'ковёр': 'ковёр',
         'лампа': 'лампа'}
PURPOSE = {'couple': 'пара', 'single': 'один', 'guest': 'гостевая', 'office': 'кабинет', 'child:0-3': 'детская 0–3',
           'child:3-7': 'детская 3–7', 'child:7-12': 'детская 7–12', 'child:teen': 'подросток'}
MESH = {'ready': ('меш ✓', '#2e7d32'), 'generated': ('меш ~', '#ef6c00'), None: ('нет меша', '#c62828')}


def _wall_seg(w, d, wall, off, width):
    """Отрезок проёма на стене (координаты комнаты: x вправо, y вглубь; south — y=0)."""
    if wall == 'south':
        return (off, 0, off + width, 0)
    if wall == 'north':
        return (off, d, off + width, d)
    if wall == 'west':
        return (0, off, 0, off + width)
    return (w, off, w, off + width)


def _rect(cx, cy, w, d, rot):
    a = math.radians(-rot)
    pts = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        lx, ly = sx * w / 2, sy * d / 2
        pts.append((cx + lx * math.cos(a) - ly * math.sin(a), cy + lx * math.sin(a) + ly * math.cos(a)))
    return pts


def plan_svg(lay: dict, px: int = 300) -> str:
    rm = lay['_room']
    W, D = rm['w'], rm['d']
    k = px / max(W, D)
    pad = 12

    def P(x, y):      # y комнаты вглубь → в картинке вверх (south внизу, как на чертеже)
        return f'{pad + x * k:.1f},{pad + (D - y) * k:.1f}'
    out = [f'<svg width="{W * k + 2 * pad:.0f}" height="{D * k + 2 * pad:.0f}" xmlns="http://www.w3.org/2000/svg">',
           f'<polygon points="{P(0, 0)} {P(W, 0)} {P(W, D)} {P(0, D)}" fill="#fafafa" stroke="#333" stroke-width="3"/>']
    for r in rm.get('radiators', []):
        x1, y1, x2, y2 = _wall_seg(W, D, r['wall'], r['offset_cm'], r['width_cm'])
        out.append(f'<polyline points="{P(x1, y1)} {P(x2, y2)}" stroke="#d66" stroke-width="7" stroke-opacity=".45"/>')
    for o in rm.get('openings', []):
        x1, y1, x2, y2 = _wall_seg(W, D, o['wall'], o['offset_cm'], o['width_cm'])
        c = '#4aa3df' if o['kind'] == 'window' else '#fff'
        out.append(f'<polyline points="{P(x1, y1)} {P(x2, y2)}" stroke="{c}" stroke-width="5"/>')
        if o['kind'] == 'door':
            r = o.get('swing_cm') or o['width_cm']
            out.append(f'<path d="M{P(x1, y1)} L{P(x1, y1 + r)} A{r * k:.1f},{r * k:.1f} 0 0,1 {P(x2, y2)}" '
                       f'fill="none" stroke="#999" stroke-dasharray="4 3"/>')
    order = ['ковёр', 'кровать', 'тумба прикроватная', 'тумба прикроватная 2', 'шкаф', 'комод', 'лампа', 'лампа 2']
    for role in order:
        p = lay.get(role)
        if not p or 'x' not in p or not p.get('w'):
            continue
        base = role.rsplit(' ', 1)[0] if role[-1].isdigit() else role
        pts = ' '.join(P(x, y) for x, y in _rect(p['x'], p['z'], p['w'], p['d'] or p['w'], p['rot']))
        fill = COL.get(base, '#ccc')
        if base == 'лампа':
            out.append(f'<circle cx="{pad + p["x"] * k:.1f}" cy="{pad + (D - p["z"]) * k:.1f}" r="5" fill="{fill}" stroke="#555"/>')
            continue
        op = '.75' if base == 'ковёр' else '1'
        out.append(f'<polygon points="{pts}" fill="{fill}" fill-opacity="{op}" stroke="#444"/>')
        if base not in ('ковёр',):
            out.append(f'<text x="{pad + p["x"] * k:.1f}" y="{pad + (D - p["z"]) * k + 4:.1f}" font-size="10" '
                       f'text-anchor="middle">{LABEL.get(base, base)}</text>')
    out.append('</svg>')
    return ''.join(out)


def _img(it: dict) -> str:
    """Своя маленькая картинка из кэша сборщика (thumbs/) — лист самодостаточен и не ждёт сеть; иначе адрес фида."""
    import base64
    import compose_common as CC
    p = CC.thumb_path(it.get('mid'), str(it.get('eid')))
    if os.path.exists(p):
        return 'data:image/png;base64,' + base64.b64encode(open(p, 'rb').read()).decode()
    u = it.get('img') or ''
    return ('https:' + u) if u.startswith('//') else u


def card(s: dict) -> str:
    items = []
    for role, it in s['items'].items():
        mt, mc = ('меш брак', '#c62828') if it.get('mesh_defect') else MESH.get(it.get('mesh'), MESH[None])
        soft = role in ('шторы', 'плед', 'ковёр')
        q = f' ×{it["qty"]}' if (it.get('qty') or 1) > 1 else ''
        dims = '×'.join(f'{v:g}' for v in (it.get('w'), it.get('d'), it.get('h')) if v)
        items.append(f'<div class="it"><img src="{html.escape(_img(it))}"><b>{html.escape(role)}{q}</b>'
                     f'<span>{it.get("price", 0):,} ₽ · стиль {it.get("style_score", "—")}</span><span>{dims}</span>'
                     + ('' if soft else f'<span style="color:{mc}">{mt}</span>')
                     + f'<span class="nm">{html.escape(it.get("name", ""))}</span></div>')
    meta = s['layout'].get('_meta', {})
    notes = []
    if s.get('gaps'):
        notes.append('пробелы: ' + '; '.join(s['gaps']))
    if meta.get('skipped_optional'):
        notes.append('без места: ' + ', '.join(meta['skipped_optional']))
    if meta.get('soft'):
        notes.append('мягкие замечания: ' + ', '.join(meta['soft']))
    return (f'<div class="card"><h3>{html.escape(s["style"])} · {s["tier"]} · {s["total"]:,} ₽ · фит {s["style_fit"]}'
            f' · нужен меш {len(s["mesh_need"])}</h3><div class="row"><div class="plan">{plan_svg(s["layout"])}</div>'
            f'<div class="items">{"".join(items)}</div></div>'
            + (f'<p class="nt">{html.escape(" · ".join(notes))}</p>' if notes else '') + '</div>')


def write(bank: list, report: dict, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    groups: dict = {}
    for s in bank:
        groups.setdefault((s['room_id'], s['purpose']), []).append(s)
    parts = ['<!doctype html><meta charset="utf-8"><title>Спальни — наборы и расстановка</title><style>',
             'body{font:13px system-ui;margin:16px;background:#fff;color:#222}h2{margin:24px 0 8px}',
             '.card{border:1px solid #ddd;border-radius:8px;padding:8px;margin:8px 0}.card h3{margin:0 0 6px;font-size:14px}',
             '.row{display:flex;gap:12px;align-items:flex-start}.items{display:flex;flex-wrap:wrap;gap:6px}',
             '.it{width:118px;display:flex;flex-direction:column;font-size:11px}.it img{width:118px;height:88px;object-fit:contain;'
             'background:#f4f4f4}.it .nm{color:#777;font-size:10px;max-height:26px;overflow:hidden}.nt{color:#a55;margin:4px 0 0}',
             '</style>', '<h1>Спальни квартиры 215 — наборы по стилям и расстановка солвером</h1>',
             '<p>План: вид сверху, дверь — пунктир дуги, окна — синие, батареи — красные. «меш ✓» — готов, «меш ~» — сгенерирован '
             '(ориентация не решена), «нет меша» — нужен меш.</p>']
    for (room, purpose), sets in groups.items():
        parts.append(f'<h2>{html.escape(room)} · {PURPOSE.get(purpose, purpose)} · наборов {len(sets)}</h2>')
        parts += [card(s) for s in sets]
    empty = [c for c in report.get('cells', []) if c.get('empty')]
    if empty:
        parts.append('<h2>Пустые ячейки</h2><ul>' + ''.join(
            f'<li>{html.escape(c["room_id"])} · {PURPOSE.get(c["purpose"], c["purpose"])}'
            + (f' · {c["style"]} · {c["tier"]}' if c.get('style') else '') + f' — {html.escape(c["empty"])}'
            + (f': {html.escape(c["why"])}' if c.get('why') else '') + '</li>' for c in empty) + '</ul>')
    p = os.path.join(out_dir, 'bedroom-sheet.html')
    open(p, 'w', encoding='utf-8').write('\n'.join(parts))
    return p


if __name__ == '__main__':
    bank = json.load(open(sys.argv[1], encoding='utf-8'))
    rp = os.path.splitext(sys.argv[1])[0] + '.report.json'
    rep = json.load(open(rp, encoding='utf-8')) if os.path.exists(rp) else {}
    print(write(bank, rep, sys.argv[2]))
