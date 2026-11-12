#!/usr/bin/env python3
"""ЭКЗАМЕН СПАЛЬНИ (план onb-05 Т5): сцены `bedroom-scenes.json` → солвер спальни → отчёт jsonl + PNG-галерея.

  tools/scout/run.sh bedroom-exam                 # все сцены
  BEDROOM_EXAM_ONLY=id1,id2 tools/scout/run.sh bedroom-exam

Гейт (критерии плана): «должна решаться» ≥ 90 % годных (0 жёстких, обязательное стоит); «не должна» — 100 % с кодом
причины; повторная проверка годной раскладки — 0 жёстких; тот же вход → та же раскладка; сцена ≤ 10 с.
Картинки — в НОВУЮ папку с меткой времени (`bedroom-exam-<ммдд-ччмм>/`), старое не трогаем.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))

from planner.bedroom import solve_bedroom                     # noqa: E402
from planner.models import Item, Opening, Radiator, Room, Severity   # noqa: E402
from planner.validate import validate                         # noqa: E402

SCENES = os.path.join(HERE, 'bedroom-scenes.json')
FLAT = os.path.join(HERE, 'flat215-bedrooms.json')
SCENE_MAX_S = 10.0


def _room(spec: dict, purpose: str, child_age: str | None) -> Room:
    return Room(width_cm=spec['w'], depth_cm=spec['d'], contour=spec.get('contour'),
                openings=[Opening(**{k: v for k, v in o.items() if not k.startswith('_')}) for o in spec.get('openings', [])],
                radiators=[Radiator(**{k: v for k, v in r.items() if not k.startswith('_')}) for r in spec.get('radiators', [])],
                room_type='bedroom', purpose=purpose, child_age=child_age)


def load():
    sc = json.load(open(SCENES, encoding='utf-8'))
    flat = {f"flat215:{r['id']}:{r['variant']}": r for r in json.load(open(FLAT, encoding='utf-8'))['rooms']}
    rooms = {**sc['rooms'], **flat}
    only = {s for s in os.environ.get('BEDROOM_EXAM_ONLY', '').split(',') if s}
    scenes = [s for s in sc['scenes'] if not only or s['id'] in only]
    return scenes, rooms, sc['kits']


def _sig(lay) -> list:
    return [(p.role, round(p.x, 1), round(p.y, 1), int(p.rot)) for p in lay.placements]


def run_scene(s: dict, rooms: dict, kits: dict) -> dict:
    room = _room(rooms[s['room']], s['purpose'], s.get('childAge'))
    items = [Item(role=r, w_cm=w, d_cm=d, h_cm=h) for r, w, d, h in kits[s['kit']]]
    t = time.time()
    lay = solve_bedroom(room, items)
    dt = time.time() - t
    again = solve_bedroom(room, items)
    re = validate(room, lay.placements) if lay.placements else None
    hard = [v.code for v in lay.violations if v.severity is Severity.HARD]
    soft = [v.code for v in lay.violations if v.severity is Severity.SOFT]
    re_hard = [v.code for v in re.violations if v.severity is Severity.HARD] if re else []
    reason = lay.meta.get('reason', [])
    ok = lay.ok and bool(lay.placements)
    exp = s['expect']
    if exp == 'solve':
        passed = ok and not re_hard
    elif exp == 'fail':
        passed = (not ok) and bool(reason)
    else:   # pending — ждёт onb-04
        passed = 'PURPOSE_PENDING' in reason
    return {'id': s['id'], 'room': s['room'], 'purpose': s['purpose'], 'kit': s['kit'], 'expect': exp,
            'pass': passed, 'ok': ok, 'reason': reason, 'hard': hard, 'soft': soft, 'revalidate_hard': re_hard,
            'unplaced': lay.unplaced, 'skipped_optional': lay.skipped_optional, 'template': lay.meta.get('template', ''),
            'deterministic': _sig(lay) == _sig(again), 'seconds': round(dt, 2),
            'floor_used_pct': lay.floor_used_pct, 'area_m2': round(room.area_m2, 1),
            # движок групп (T-20261112-38/2; env BEDROOM_ENGINE): вариант «сна», уровень состава, ступень 140, «кабинет»
            'engine': lay.meta.get('engine', 'items'),
            **{k: lay.meta[k] for k in ('sleep_variant', 'sleep_why', 'sleep_next', 'storage_why', 'room_label', 'composition')
               if lay.meta.get(k)},
            'placements': [{'role': p.role, 'x': p.x, 'y': p.y, 'rot': p.rot, 'w': p.item.w_cm, 'd': p.item.d_cm,
                            'h': p.item.h_cm, 'tpl': p.tpl_id} for p in lay.placements]}, room, lay


# ---------- картинка ----------
COL = {'кровать': (196, 160, 120), 'тумба прикроватная': (150, 120, 90), 'шкаф': (110, 130, 160), 'комод': (140, 160, 120),
       'стол рабочий': (190, 170, 100), 'стул рабочий': (170, 150, 90), 'туалетный столик': (200, 150, 170)}


def draw(room, lay, res: dict, path: str):
    from PIL import Image, ImageDraw, ImageFont

    from planner.bedroom_checks import bed_zones, bedroom_spec, both_sides, side_clear
    from planner.geometry import (access_zone, base_role, footprint, opening_polygon, radiator_polygon, room_polygon,
                                  swing_polygon)
    k, pad, top = 1.4, 30, 64
    W, H = int(room.width_cm * k + 2 * pad), int(room.depth_cm * k + 2 * pad + top)
    img = Image.new('RGB', (max(W, 520), H), (255, 255, 255))
    g = ImageDraw.Draw(img, 'RGBA')
    font = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    f12, f14 = ImageFont.truetype(font, 12), ImageFont.truetype(font, 14)

    def P(poly):   # y вглубь → вниз на картинке
        if poly.is_empty:
            return []
        geoms = [poly] if poly.geom_type == 'Polygon' else [q for q in getattr(poly, 'geoms', []) if q.geom_type == 'Polygon']
        return [[(pad + x * k, top + pad + y * k) for x, y in q.exterior.coords] for q in geoms]

    for q in P(room_polygon(room)):
        g.polygon(q, fill=(246, 244, 240), outline=(40, 40, 40), width=3)
    for p in lay.placements:   # зоны: проходы кровати и фронты — полупрозрачно
        if base_role(p.role) == 'кровать':
            z = bed_zones(p)
            others = [o for o in lay.placements if o is not p]
            sides = [s for s in ('left', 'right') if both_sides(room, p) or side_clear(room, z, s, others)]
            keys = ['foot'] + sides + [f'{s}_head' for s in sides if f'{s}_head' in z]   # у изголовья — T-20261112-31
            for key in keys:
                for q in P(z[key]):
                    g.polygon(q, fill=(120, 180, 120, 50), outline=(90, 150, 90, 120))
        sp = bedroom_spec(p.role)
        if sp is not None:
            for q in P(access_zone(p, spec=sp)):
                g.polygon(q, fill=(120, 140, 200, 45), outline=(100, 120, 190, 120))
    for op in room.openings:
        for q in P(swing_polygon(room, op)):
            g.polygon(q, fill=(230, 120, 80, 60), outline=(200, 90, 60))
        col = (60, 140, 230) if op.kind == 'window' else (220, 90, 50)
        for q in P(opening_polygon(room, op).buffer(4)):
            g.polygon(q, fill=col)
    for r in room.radiators:
        for q in P(radiator_polygon(room, r)):
            g.polygon(q, fill=(200, 60, 60, 160))
    for p in lay.placements:
        for q in P(footprint(p)):
            g.polygon(q, fill=COL.get(base_role(p.role), (160, 160, 160)), outline=(30, 30, 30), width=2)
        c = footprint(p).centroid
        lab = p.role.replace('тумба прикроватная', 'тумба').replace(' рабочий', '')
        g.text((pad + c.x * k, top + pad + c.y * k), lab, fill=(0, 0, 0), font=f12, anchor='mm')
        if base_role(p.role) == 'кровать':   # изголовье — толстая линия
            hb = bed_zones(p)['back']
            for q in P(hb.buffer(-4)):
                g.polygon(q, fill=(60, 40, 20))
    mark = {'solve': ('ГОДНО', 'НЕ СДАНО'), 'fail': ('ОТКАЗ — ВЕРНО', 'ОШИБКА: ДОЛЖЕН БЫТЬ ОТКАЗ'),
            'pending': ('ЖДЁТ onb-04', 'НЕТ КОДА PURPOSE_PENDING')}[res['expect']][0 if res['pass'] else 1]
    g.text((pad, 8), f"{res['id']}  ·  {res['area_m2']} м²  ·  {res['purpose']}  ·  {mark}", fill=(0, 0, 0), font=f14)
    sub = f"жёстких {len(res['hard'])}, мягких {len(res['soft'])}; без места: {', '.join(res['skipped_optional']) or '—'}"
    if res['reason']:
        sub += f"; причина: {','.join(res['reason'])}"
    if res.get('engine') == 'groups':
        comp = res.get('composition') or {}
        sub += f"; {comp.get('template', '')} ур. {comp.get('level') or '—'}"
        if res.get('sleep_next'):
            sub += f"; дальше {res['sleep_next']}"
    g.text((pad, 30), sub[:110], fill=(80, 80, 80), font=f12)
    img.save(path)


def sheet(paths: list[str], out: str, cols: int = 4):
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


def main() -> int:
    scenes, rooms, kits = load()
    stamp = time.strftime('%m%d-%H%M')
    outdir = os.environ.get('BEDROOM_EXAM_OUT') or os.path.join(HERE, f'bedroom-exam-{stamp}')
    os.makedirs(outdir, exist_ok=True)
    sfx = os.environ.get('BEDROOM_EXAM_SUFFIX', '')
    rep = os.path.join(HERE, f'bedroom-exam-report{sfx}.jsonl')
    rows, pngs = [], []
    with open(rep, 'w', encoding='utf-8') as fh:
        for s in scenes:
            res, room, lay = run_scene(s, rooms, kits)
            png = os.path.join(outdir, f"{res['id']}.png")
            draw(room, lay, res, png)
            pngs.append(png)
            fh.write(json.dumps(res, ensure_ascii=False) + '\n')
            rows.append(res)
            print(f"{'OK ' if res['pass'] else 'FAIL'} {res['id']:<44} {res['seconds']:>5}s  hard={res['hard']} "
                  f"skip={res['skipped_optional']} reason={res['reason']}", flush=True)
    sheet(pngs, os.path.join(outdir, '_all.png'))
    by = {e: [r for r in rows if r['expect'] == e] for e in ('solve', 'fail', 'pending')}
    solve_ok = sum(r['pass'] for r in by['solve'])
    fail_ok = sum(r['pass'] for r in by['fail'])
    nondet = [r['id'] for r in rows if not r['deterministic']]
    slow = [r['id'] for r in rows if r['seconds'] > SCENE_MAX_S]
    rate = solve_ok / len(by['solve']) if by['solve'] else 1.0
    summary = {'engine': rows[0]['engine'] if rows else None, 'scenes': len(rows), 'solve': f"{solve_ok}/{len(by['solve'])}", 'solve_rate': round(rate, 3),
               'fail_with_reason': f"{fail_ok}/{len(by['fail'])}",
               'pending_onb04': f"{sum(r['pass'] for r in by['pending'])}/{len(by['pending'])}",
               'nondeterministic': nondet, 'slow': slow, 'max_seconds': max((r['seconds'] for r in rows), default=0),
               'soft_codes': _count(c for r in rows if r['ok'] for c in r['soft']),
               'skipped_optional': _count(c for r in rows for c in r['skipped_optional']), 'gallery': outdir}
    gate = rate >= 0.9 and fail_ok == len(by['fail']) and not nondet and not slow
    summary['gate'] = 'PASS' if gate else 'FAIL'
    json.dump(summary, open(os.path.join(HERE, f'bedroom-exam-report{sfx}.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if gate else 1


def _count(it) -> dict:
    out = {}
    for c in it:
        out[c] = out.get(c, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


if __name__ == '__main__':
    sys.exit(main())
