#!/usr/bin/env python3
"""ЭКЗАМЕН ПРИХОЖЕЙ (план onb-13 Т3, T-20261105-34; по образцу `bedroom_exam.py`): сцены `hall-scenes.json` + прихожая
flat215 (`flat215-hall.json`) → солвер прихожей → отчёт jsonl + PNG-галерея (вид сверху).

  tools/scout/run.sh hall-exam                    # все сцены
  HALL_EXAM_ONLY=id1,id2 tools/scout/run.sh hall-exam

Гейт: «должна решаться» ≥ 90 % (0 жёстких, хранение одежды стоит); «не должна» — 100 % с кодом причины; повторная
проверка годной раскладки (`validate_hall`) — 0 жёстких; тот же вход → та же раскладка; сцена ≤ 10 с.
Картинки — в НОВУЮ папку с меткой времени (`hall-exam-<ммдд-ччмм>/`), старое не трогаем.
"""
import json
import os
import sys
import time
import typing

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))

from planner.hall import solve_hall                                   # noqa: E402
from planner.hall_checks import validate_hall                         # noqa: E402
from planner.models import Item, Opening, Radiator, Room, RoomType, Severity   # noqa: E402

SCENES = os.path.join(HERE, 'hall-scenes.json')
FLAT = os.path.join(HERE, 'flat215-hall.json')
SCENE_MAX_S = 10.0
# «hall» в словаре RoomType добавляет интегратор (T-37); до того комната идёт со значением по умолчанию — солвер и
# проверки прихожей поле не читают
HALL_TYPE = {'room_type': 'hall'} if 'hall' in typing.get_args(RoomType) else {}


def _room(spec: dict) -> Room:
    return Room(width_cm=spec['w'], depth_cm=spec['d'], contour=spec.get('contour'),
                openings=[Opening(**{k: v for k, v in o.items() if not k.startswith('_')}) for o in spec.get('openings', [])],
                radiators=[Radiator(**{k: v for k, v in r.items() if not k.startswith('_')}) for r in spec.get('radiators', [])],
                **HALL_TYPE)


def load():
    sc = json.load(open(SCENES, encoding='utf-8'))
    flat = {f"flat215:{r['id']}:{r['variant']}": r for r in json.load(open(FLAT, encoding='utf-8'))['rooms']}
    rooms = {**sc['rooms'], **flat}
    only = {s for s in os.environ.get('HALL_EXAM_ONLY', '').split(',') if s}
    scenes = [s for s in sc['scenes'] if not only or s['id'] in only]
    return scenes, rooms, {k: v for k, v in sc['kits'].items() if not k.startswith('_')}


def _sig(lay) -> list:
    return [(p.role, round(p.x, 1), round(p.y, 1), int(p.rot), round(p.elev_cm or 0, 1)) for p in lay.placements]


def run_scene(s: dict, rooms: dict, kits: dict):
    room = _room(rooms[s['room']])
    items = [Item(role=r, w_cm=w, d_cm=d, h_cm=h) for r, w, d, h in kits[s['kit']]]
    t = time.time()
    lay = solve_hall(room, items)
    dt = time.time() - t
    again = solve_hall(room, items)
    re = validate_hall(room, lay.placements) if lay.placements else None
    hard = [v.code for v in lay.violations if v.severity is Severity.HARD]
    soft = [v.code for v in lay.violations if v.severity is Severity.SOFT]
    re_hard = [v.code for v in re.violations if v.severity is Severity.HARD] if re else []
    reason = lay.meta.get('reason', [])
    ok = lay.ok and bool(lay.placements) and not lay.unplaced
    passed = (ok and not re_hard) if s['expect'] == 'solve' else ((not ok) and bool(reason))
    res = {'id': s['id'], 'room': s['room'], 'purpose': s['purpose'], 'kit': s['kit'], 'expect': s['expect'],
           'pass': passed, 'ok': ok, 'reason': reason, 'hard': hard, 'soft': soft, 'revalidate_hard': re_hard,
           'unplaced': lay.unplaced, 'skipped_optional': lay.skipped_optional, 'template': lay.meta.get('template', ''),
           'deterministic': _sig(lay) == _sig(again), 'seconds': round(dt, 2), 'area_m2': round(room.area_m2, 1),
           'placements': [{'role': p.role, 'x': p.x, 'y': p.y, 'rot': p.rot, 'w': p.item.w_cm, 'd': p.item.d_cm,
                           'h': p.item.h_cm, 'elev': p.elev_cm, 'tpl': p.tpl_id} for p in lay.placements]}
    return res, room, lay


# ---------- картинка ----------
COL = {'шкаф-купе': (110, 130, 160), 'шкаф': (110, 130, 160), 'прихожая': (120, 120, 170), 'обувница': (150, 120, 90),
       'банкетка': (196, 160, 120), 'консоль': (190, 170, 100), 'вешалка': (140, 160, 120), 'зеркало': (150, 200, 220)}


def draw(room, lay, res: dict, path: str):
    from PIL import Image, ImageDraw, ImageFont

    from planner.geometry import access_zone, base_role, footprint, opening_polygon, radiator_polygon, room_polygon, swing_polygon
    from planner.hall_checks import door_front, entrance, hall_spec, is_wall_mirror
    k, pad, top = 1.4, 56, 64
    W, H = int(room.width_cm * k + 2 * pad), int(room.depth_cm * k + 2 * pad + top)
    img = Image.new('RGB', (max(W, 560), H), (255, 255, 255))
    g = ImageDraw.Draw(img, 'RGBA')
    font = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    f11, f14 = ImageFont.truetype(font, 11), ImageFont.truetype(font, 14)

    def P(poly):   # y вглубь → вниз на картинке
        if poly.is_empty:
            return []
        geoms = [poly] if poly.geom_type == 'Polygon' else [q for q in getattr(poly, 'geoms', []) if q.geom_type == 'Polygon']
        return [[(pad + x * k, top + pad + y * k) for x, y in q.exterior.coords] for q in geoms]

    for q in P(room_polygon(room)):
        g.polygon(q, fill=(246, 244, 240), outline=(40, 40, 40), width=3)
    ent = entrance(room)
    for op in room.openings:
        if op.kind in ('door', 'opening', 'balcony'):
            for q in P(door_front(room, op)):    # полоса перед дверью — свободна
                g.polygon(q, fill=(230, 180, 80, 40), outline=(210, 160, 60, 110))
    for p in lay.placements:
        sp = hall_spec(p.role)
        if sp is not None:
            for q in P(access_zone(p, spec=sp)):
                g.polygon(q, fill=(120, 140, 200, 45), outline=(100, 120, 190, 120))
    for op in room.openings:
        for q in P(swing_polygon(room, op)):
            g.polygon(q, fill=(230, 120, 80, 60), outline=(200, 90, 60))
        col = (60, 140, 230) if op.kind == 'window' else (20, 150, 60) if op is ent else (220, 90, 50)
        for q in P(opening_polygon(room, op).buffer(4)):
            g.polygon(q, fill=col)
    for r in room.radiators:
        for q in P(radiator_polygon(room, r)):
            g.polygon(q, fill=(200, 60, 60, 160))
    for p in sorted(lay.placements, key=is_wall_mirror):    # зеркало — поверх низкой мебели
        mir = is_wall_mirror(p)
        fp = footprint(p)
        for q in P(fp.buffer(2) if mir else fp):
            g.polygon(q, fill=COL.get(base_role(p.role), (160, 160, 160)), outline=(30, 30, 30), width=2)
        c = fp.centroid
        lab = p.role + (f' ↑{p.elev_cm:.0f}' if mir else '')
        dy = -10 if mir else 0
        g.text((pad + c.x * k, top + pad + c.y * k + dy), lab, fill=(0, 0, 0), font=f11, anchor='mm')
    mark = {'solve': ('ГОДНО', 'НЕ СДАНО'), 'fail': ('ОТКАЗ — ВЕРНО', 'ОШИБКА: ДОЛЖЕН БЫТЬ ОТКАЗ')}[res['expect']][0 if res['pass'] else 1]
    g.text((pad, 8), f"{res['id']}  ·  {res['area_m2']} м²  ·  {mark}", fill=(0, 0, 0), font=f14)
    sub = f"жёстких {len(res['hard'])}, мягких {len(res['soft'])}; без места: {', '.join(res['skipped_optional']) or '—'}"
    if res['reason']:
        sub += f"; причина: {','.join(res['reason'])}"
    g.text((pad, 30), sub[:100], fill=(80, 80, 80), font=f11)
    g.text((pad, 46), 'зелёная — вход; жёлтое — полоса перед дверью; синее — фронт мебели', fill=(120, 120, 120), font=f11)
    img.save(path)


def sheet(paths: list, out: str, cols: int = 7):
    from PIL import Image
    ims = [Image.open(p) for p in paths]
    if not ims:
        return
    cw, ch = max(i.width for i in ims), max(i.height for i in ims)
    rows = (len(ims) + cols - 1) // cols
    S = Image.new('RGB', (cw * cols, ch * rows), (255, 255, 255))
    for n, im in enumerate(ims):
        S.paste(im, ((n % cols) * cw, (n // cols) * ch))
    S.save(out)


def _count(it) -> dict:
    out: dict = {}
    for c in it:
        out[c] = out.get(c, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def main() -> int:
    scenes, rooms, kits = load()
    outdir = os.environ.get('HALL_EXAM_OUT') or os.path.join(HERE, f"hall-exam-{time.strftime('%m%d-%H%M')}")
    os.makedirs(outdir, exist_ok=True)
    sfx = os.environ.get('HALL_EXAM_SUFFIX', '')
    rows, pngs = [], []
    with open(os.path.join(HERE, f'hall-exam-report{sfx}.jsonl'), 'w', encoding='utf-8') as fh:
        for s in scenes:
            res, room, lay = run_scene(s, rooms, kits)
            png = os.path.join(outdir, f"{res['id']}.png")
            draw(room, lay, res, png)
            pngs.append(png)
            fh.write(json.dumps(res, ensure_ascii=False) + '\n')
            rows.append(res)
            print(f"{'OK ' if res['pass'] else 'FAIL'} {res['id']:<30} {res['seconds']:>5}s  hard={res['hard']} "
                  f"soft={res['soft']} skip={res['skipped_optional']} reason={res['reason']}", flush=True)
    sheet(pngs, os.path.join(outdir, '_all.png'))
    by = {e: [r for r in rows if r['expect'] == e] for e in ('solve', 'fail')}
    solve_ok = sum(r['pass'] for r in by['solve'])
    fail_ok = sum(r['pass'] for r in by['fail'])
    nondet = [r['id'] for r in rows if not r['deterministic']]
    slow = [r['id'] for r in rows if r['seconds'] > SCENE_MAX_S]
    rate = solve_ok / len(by['solve']) if by['solve'] else 1.0
    summary = {'scenes': len(rows), 'solve': f"{solve_ok}/{len(by['solve'])}", 'solve_rate': round(rate, 3),
               'fail_with_reason': f"{fail_ok}/{len(by['fail'])}", 'nondeterministic': nondet, 'slow': slow,
               'max_seconds': max((r['seconds'] for r in rows), default=0),
               'soft_codes': _count(c for r in rows if r['ok'] for c in r['soft']),
               'skipped_optional': _count(c for r in rows for c in r['skipped_optional']), 'gallery': outdir}
    gate = rate >= 0.9 and fail_ok == len(by['fail']) and not nondet and not slow
    summary['gate'] = 'PASS' if gate else 'FAIL'
    json.dump(summary, open(os.path.join(HERE, f'hall-exam-report{sfx}.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if gate else 1


if __name__ == '__main__':
    sys.exit(main())
