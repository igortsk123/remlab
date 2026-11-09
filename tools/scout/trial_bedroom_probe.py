#!/usr/bin/env python3
"""ЗАМЕР «сколько спален загруженного плана решается уже сейчас» (MASTER-agent-trial T6, задача T-20261109-15).

НЕ продакшен-адаптер. Перевод комнаты временный и простой: bbox пола + проёмы панели — на ближайшую сторону bbox (как
`tools/scout/uk-bedrooms.json`: south — низ листа, offset — от начала стены запад→восток / юг→север), радиатор — под каждым
наружным окном. Продакшен-перевод (`orthogonalize`, ядро, хвосты Г-формы) — `tools/scout/trial_room.py` (T-12, план
agent-trial-03-living); спальни потом идут через него, этот файл заменяется.

Решение — нынешний путь спальни (как `tools/scout/canon_bedroom.py`): `planner.bedroom.solve_bedroom` на наборе-идеале слотов
сборщика (`rules/bedroom-composition.json`) + повторная `planner.validate.validate`. Назначения по цепочке (`chain`): ширина
кровати — от размера комнаты по UK Nationally Described Space Standard (2015, табл. 1 и прим. 2–7: двуспальная спальня
≥ 11,5 м², ширина ≥ 2,55 м у второй и ≥ 2,75 м у главной; односпальная ≥ 7,5 м² и ≥ 2,15 м), не встала — следующая, уже.

Вход — модели стенда (`model-<план>-<i>.json`, метры) или результат пробы (`contracts/trial.ts:floorplanResult`, см):

  ~/venvs/scout/bin/python tools/scout/trial_bedroom_probe.py ~/remlab-logs/floorplan-bench/blind-run-1400/{D,E}/model-*.json
  ~/venvs/scout/bin/python tools/scout/trial_bedroom_probe.py tools/scout/tests/fixtures/trial-bedrooms/*.json --no-png

Итог — `~/remlab-logs/trial-bedroom/run-<ЧЧММ>/`: `probe.json`, `table.md`, кадры сверху `<план>-<этаж>-<комната>.png`.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))

from canon_bedroom import kit as _canon_kit  # noqa: E402  (тот же набор, что у страницы шаблонов)
from planner.bedroom import solve_bedroom  # noqa: E402
from planner.bedroom_checks import bedroom_role  # noqa: E402
from planner.geometry import footprint  # noqa: E402
from planner.models import Opening, Radiator, Room, Severity  # noqa: E402
from planner.validate import validate  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

COMP = json.load(open(os.path.join(HERE, 'rules', 'bedroom-composition.json'), encoding='utf-8'))
OUT_ROOT = os.path.expanduser('~/remlab-logs/trial-bedroom')

BED_NAME = re.compile(r'\b(bed\s?room|bedroom|master|bed\s?\d|guest\s?room|box\s?room|nursery)\b', re.I)
NOT_BED = re.compile(r'en[\s-]?suite|bath|wc|shower|dressing|landing|closet|linen', re.I)
SNAP_CM = 35.0            # центр проёма дальше от стороны bbox — не этой комнаты (стена ~10–30 см)
DOOR_SWING_MAX = 90.0     # створка UK 762–838 мм; широкий проём (двустворчатый) — створка не шире 90
SILL_CM = 85.0            # подоконник (как uk-bedrooms.json; правила солвера — rules/occupancy.json)
RAD_W_MAX = 140.0
OUTSIDE_TOL_CM = 5.0      # край пола со стенда косой на 1–2 см (заполнение 0,99) — шум распознавания, не «вне пола»
OUTSIDE_CM2 = 25.0        # за полом + допуск вылезло больше 5×5 см — «вне пола» (bbox врёт: ниша, Г-форма)

# UK NDSS 2015 (Technical housing standards — nationally described space standard, табл. 1 прим. 2–7)
NDSS = {'double_m2': 11.5, 'double_w': 255.0, 'single_m2': 7.5, 'single_w': 215.0}


@dataclass
class RoomIn:
    plan: str
    panel: str
    rid: str
    name: str
    rings: list            # кольца пола, см, координаты листа (x вправо, y вниз)
    openings: list         # [{kind, c:(x,y) см, width, exterior}] — все проёмы панели
    flags: list = field(default_factory=list)


# ── вход ──────────────────────────────────────────────────────────────────────────────────────────────
def _is_bedroom(names: list[str]) -> str | None:
    """Имя спальни или None. «Bathroom/Landing», «En-suite» — не спальня; «Bedroom 2 / En-suite» — спальня с флагом."""
    for n in names:
        if BED_NAME.search(n) and not NOT_BED.search(n):
            return n
    return None


def from_bench_model(m: dict, plan: str | None = None) -> list[RoomIn]:
    """Модель стенда (`tools/floorplan`): метры → см; пол комнаты — `floors[*]` с её `room`."""
    plan = plan or m.get('plan') or '?'
    ops = [{'kind': o['kind'], 'c': (o['c'][0] * 100, o['c'][1] * 100), 'width': o['width_m'] * 100,
            'exterior': bool(o.get('exterior'))} for o in m.get('openings') or []]
    out = []
    for r in m.get('rooms') or []:
        names = r.get('names') or []
        name = _is_bedroom(names)
        if not name:
            continue
        rings = [[(x * 100, y * 100) for x, y in f['outer']] for f in m.get('floors') or [] if f.get('room') == r['id']]
        if not rings:
            continue
        flags = ['mixed_names'] if len(names) > 1 else []
        out.append(RoomIn(plan, m.get('panel') or '', str(r['id']), name, rings, ops, flags))
    return out


def from_trial_result(res: dict, plan: str) -> list[RoomIn]:
    """`floorplanResult` (см): комнаты `kind == "bedroom"` или с именем спальни; проёмы — панели."""
    out = []
    for p in res.get('panels') or []:
        ops = [{'kind': o['kind'], 'c': tuple(o['c']), 'width': o['widthCm'], 'exterior': bool(o.get('exterior'))}
               for o in p.get('openings') or []]
        for r in p.get('rooms') or []:
            name = r.get('name') or ''
            if r.get('kind') != 'bedroom' and not _is_bedroom([name]):
                continue
            out.append(RoomIn(plan, p.get('title') or p.get('id') or '', str(r['id']), name or 'bedroom',
                              [[tuple(pt) for pt in r['contour']]], ops, list(r.get('flags') or [])))
    return out


def load(path: str) -> tuple[list[RoomIn], dict]:
    """Файл → комнаты. Фикстура теста — `{"_expect": {...}, "result": floorplanResult}`; иначе модель стенда."""
    d = json.load(open(path, encoding='utf-8'))
    stem = os.path.splitext(os.path.basename(path))[0]
    if 'result' in d and isinstance(d['result'], dict):
        return from_trial_result(d['result'], d.get('plan') or stem), d.get('_expect') or {}
    if d.get('units') == 'cm' and 'panels' in d:
        return from_trial_result(d, stem), {}
    return from_bench_model(d), {}


# ── временный перевод в комнату солвера ───────────────────────────────────────────────────────────────
def _area(ring) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]))) / 2


def to_room(ri: RoomIn) -> tuple[Room, dict]:
    """bbox пола → Room; проём → ближайшая сторона bbox (в пределах SNAP_CM); радиатор под наружным окном."""
    xs = [x for r in ri.rings for x, _ in r]
    ys = [y for r in ri.rings for _, y in r]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, d = round(x1 - x0, 1), round(y1 - y0, 1)
    fill = sum(_area(r) for r in ri.rings) / (w * d) if w and d else 0.0
    flags = list(ri.flags)
    if fill < 0.95:
        flags.append('not_rect')          # bbox больше пола: Г-форма, ниша, скос — продакшен-адаптер берёт контур
    openings, rads, used = [], [], []
    for o in ri.openings:
        cx, cy = o['c']
        if not (x0 - SNAP_CM <= cx <= x1 + SNAP_CM and y0 - SNAP_CM <= cy <= y1 + SNAP_CM):
            continue
        # сторона листа → стена солвера: низ листа = south (y солвера = y1 − y листа, хиральность та же)
        side = min((abs(cy - y1), 'south'), (abs(cy - y0), 'north'), (abs(cx - x0), 'west'), (abs(cx - x1), 'east'))
        if side[0] > SNAP_CM:
            continue
        wall = side[1]
        L = w if wall in ('south', 'north') else d
        along = (cx - x0) if wall in ('south', 'north') else (y1 - cy)
        width = min(o['width'], L - 2)
        if width < o['width']:
            flags.append(f'opening_clipped:{o["kind"]}')
        off = max(0.0, min(along - width / 2, L - width))
        kind = o['kind'] if o['kind'] in ('door', 'window', 'opening') else 'opening'
        if kind == 'door':
            openings.append(Opening(kind='door', wall=wall, offset_cm=round(off, 1), width_cm=round(width, 1),
                                    swing_cm=round(min(width, DOOR_SWING_MAX), 1)))
        elif kind == 'window':
            openings.append(Opening(kind='window', wall=wall, offset_cm=round(off, 1), width_cm=round(width, 1),
                                    sill_cm=SILL_CM))
            if o.get('exterior'):
                rw = max(min(40.0, width), min(width - 10, RAD_W_MAX))   # малое окно — радиатор не шире окна
                roff = max(0.0, min(off + (width - rw) / 2, L - rw))
                rads.append(Radiator(wall=wall, offset_cm=round(roff, 1), width_cm=round(rw, 1)))
        else:
            openings.append(Opening(kind='opening', wall=wall, offset_cm=round(off, 1), width_cm=round(width, 1), swing_cm=0))
        used.append({'kind': kind, 'wall': wall, 'offset': round(off, 1), 'width': round(width, 1),
                     'exterior': o.get('exterior')})
    if not any(op.kind == 'door' for op in openings) and not any(op.kind == 'opening' for op in openings):
        flags.append('no_door')
    if not any(op.kind == 'window' for op in openings):
        flags.append('no_window')
    room = Room(width_cm=w, depth_cm=d, room_type='bedroom', openings=openings, radiators=rads)
    # настоящий пол в координатах солвера — проверить, не встала ли мебель за пределы пола (bbox Г-формы/ниши)
    floor = unary_union([Polygon([(x - x0, y1 - y) for x, y in r]).buffer(0) for r in ri.rings])
    return room, {'w': w, 'd': d, 'm2': round(w * d / 1e4, 2), 'fill': round(fill, 3), 'openings': used, 'flags': flags,
                  '_floor': floor}


# ── решение ───────────────────────────────────────────────────────────────────────────────────────────
def slot_kit(purpose: str):
    """Набор банка: только слоты сборщика (без примеров страницы шаблонов: стол, туалетный столик)."""
    slots = {s['role'] for s in (COMP['purposes'].get(purpose) or {}).get('slots') or []}
    return [x for x in _canon_kit(purpose) if bedroom_role(x.role) in slots]


def chain(w: float, d: float) -> tuple[list[str], list[str]]:
    """Назначения по убыванию ширины кровати — с какого начинать по размеру комнаты (NDSS), и флаги."""
    m2, short = w * d / 1e4, min(w, d)
    flags = []
    if m2 < NDSS['single_m2'] or short < NDSS['single_w']:
        flags.append('below_ndss_single')     # по UK-норме это не спальня; пробуем узкую, отказ — честный
    if m2 >= NDSS['double_m2'] and short >= NDSS['double_w']:
        return ['couple', 'single', 'single_narrow'], flags
    if m2 >= 9.0 and short >= 250:            # малая двуспальная UK 4 ft (120) — промежуточная, норма её не выделяет
        return ['single', 'single_narrow'], flags
    return ['single_narrow'], flags


def solve_one(room: Room, purpose: str, floor=None) -> dict:
    r = room.model_copy(update={'purpose': purpose})
    t = time.perf_counter()
    lay = solve_bedroom(r, slot_kit(purpose))
    ms = round((time.perf_counter() - t) * 1000)
    hard = sorted({v.code for v in lay.violations if v.severity is Severity.HARD})
    if lay.placements:
        hard = sorted(set(hard) | {v.code for v in validate(r, lay.placements).violations if v.severity is Severity.HARD})
    soft = sorted({v.code for v in lay.violations if v.severity is not Severity.HARD})
    placed = {}
    for p in lay.placements:
        b = bedroom_role(p.role)
        placed.setdefault(b, []).append(f'{p.item.w_cm:.0f}×{p.item.d_cm:.0f}')
    tol = floor.buffer(OUTSIDE_TOL_CM, join_style=2) if floor is not None else None
    outside = sorted({p.role for p in lay.placements
                      if tol is not None and footprint(p).difference(tol).area > OUTSIDE_CM2})
    ok = bool(lay.placements) and not hard and not lay.unplaced and not outside
    return {'purpose': purpose, 'ok': ok, 'ms': ms, 'placed': placed, 'hard': hard, 'soft': soft, 'outside_floor': outside,
            'skipped': lay.skipped_optional, 'unplaced': lay.unplaced, 'reason': lay.meta.get('reason') or [],
            'template': lay.meta.get('template', ''), '_room': r, '_lay': lay}


def probe_room(ri: RoomIn, all_purposes: bool = False) -> dict:
    room, info = to_room(ri)
    floor = info.pop('_floor')
    order, f2 = chain(room.width_cm, room.depth_cm)
    info['flags'] += f2
    tried, pick = [], None
    for p in (['couple', 'single', 'single_narrow'] if all_purposes else order):
        res = solve_one(room, p, floor)
        tried.append(res)
        if pick is None and res['ok'] and p in order:
            pick = res
            if not all_purposes:
                break
    rec = {'plan': ri.plan, 'panel': ri.panel, 'rid': ri.rid, 'name': ri.name, **info, 'chain': order,
           'tried': [{k: v for k, v in t.items() if not k.startswith('_')} for t in tried],
           'pick': pick['purpose'] if pick else None, 'ms_total': sum(t['ms'] for t in tried)}
    if pick is None:
        last = tried[-1]
        rec['refusal'] = ','.join(last['reason'] or last['hard'] or ['NO_LAYOUT'])
    rec['_best'] = pick or next((t for t in tried if t['_lay'].placements), tried[-1])
    return rec


# ── итог ──────────────────────────────────────────────────────────────────────────────────────────────
def _png_name(r: dict) -> str:
    safe = re.sub(r'[^A-Za-z0-9]+', '_', f"{r['plan']}-{r['panel']}-{r['name']}").strip('_')
    return f'{safe}.png'


def render(r: dict, out_dir: str) -> str | None:
    from canon_gallery import artifact          # тяжёлый импорт (шаблоны гостиной) — только когда рисуем
    from render_plan import render_artifact
    best = r['_best']
    room, lay = best['_room'], best['_lay']
    path = os.path.join(out_dir, _png_name(r))
    try:
        render_artifact(artifact(room, lay.placements), path, band='31-40', radiators=True,
                        font_px=max(11, round((room.width_cm * 2.6 + 40) / 30)), labels_inside=True)
    except Exception as e:  # кадр — вспомогательный; причина — в таблицу, замер не роняем
        r['png_error'] = f'{type(e).__name__}: {e}'[:200]
        return None
    return os.path.basename(path)


def _cell(placed: dict, role: str) -> str:
    v = placed.get(role) or []
    return ', '.join(v) if v else '—'


def table(rows: list[dict]) -> str:
    head = ['план', 'этаж', 'комната', 'Ш×Г м', 'м²', 'пол/bbox', 'проёмы', 'цепочка', 'итог', 'кровать', 'тумбы',
            'шкаф', 'комод', 'жёсткие', 'мягкие', 'отказ/причина', 'флаги', 'мс']
    md = ['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)]
    for r in rows:
        best = r['_best']
        ops = ' '.join(f"{o['kind'][0]}{o['wall'][0]}{o['width']:.0f}" for o in r['openings']) or '—'
        cells = [r['plan'], r['panel'], r['name'], f"{r['w'] / 100:.2f}×{r['d'] / 100:.2f}", f"{r['m2']:.1f}",
                 f"{r['fill']:.2f}", ops, '→'.join(r['chain']), r['pick'] or f"нет ({best['purpose']})",
                 _cell(best['placed'], 'кровать'), _cell(best['placed'], 'тумба прикроватная'), _cell(best['placed'], 'шкаф'),
                 _cell(best['placed'], 'комод'),
                 ', '.join(best['hard'] + [f'вне пола: {x}' for x in best['outside_floor']]) or '0',
                 ', '.join(best['soft']) or '—',
                 r.get('refusal') or (', '.join(best['skipped']) and 'нет места: ' + ', '.join(best['skipped'])) or '—',
                 ', '.join(r['flags']) or '—', str(r['ms_total'])]
        md.append('| ' + ' | '.join(str(c) for c in cells) + ' |')
    return '\n'.join(md) + '\n'


def summary(rows: list[dict]) -> list[str]:
    n = len(rows)
    ok = [r for r in rows if r['pick']]
    by = {}
    for r in ok:
        by[r['pick']] = by.get(r['pick'], 0) + 1
    ms = sorted(r['ms_total'] for r in rows)
    p50 = ms[len(ms) // 2] if ms else 0
    lines = [f'- спален найдено: {n}; решено без жёстких: {len(ok)} '
             f"({', '.join(f'{k} {v}' for k, v in sorted(by.items())) or '—'}); отказ: {n - len(ok)}",
             f'- время солвера на комнату (вся цепочка): p50 {p50} мс, max {max(ms) if ms else 0} мс']
    for r in rows:
        if not r['pick']:
            lines.append(f"- отказ {r['plan']} {r['panel']} {r['name']}: {r.get('refusal')}")
    return lines


def run(paths: list[str], out_dir: str | None, png: bool = True, all_purposes: bool = False) -> list[dict]:
    rows = []
    for p in paths:
        rooms, _exp = load(p)
        rows += [probe_room(ri, all_purposes) for ri in rooms]
    if out_dir:
        os.makedirs(out_dir, exist_ok=False)
        for r in rows:
            if png:
                r['png'] = render(r, out_dir)
        md = (f"# Спальни на загруженном плане — замер {datetime.now().isoformat(timespec='minutes')}\n\n"
              'Временный перевод bbox + проёмы на сторону (НЕ продакшен-адаптер). Проёмы: d/w/o — дверь/окно/проём, '
              'вторая буква — стена (s/n/w/e), число — ширина, см.\n\n' + table(rows) + '\n## Итог\n\n' +
              '\n'.join(summary(rows)) + '\n')
        open(os.path.join(out_dir, 'table.md'), 'w', encoding='utf-8').write(md)
        clean = [{k: v for k, v in r.items() if not k.startswith('_')} | {'best': {k: v for k, v in r['_best'].items()
                                                                                   if not k.startswith('_')}} for r in rows]
        json.dump(clean, open(os.path.join(out_dir, 'probe.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return rows


def new_dir(root: str) -> str:
    stem = os.path.join(root, 'run-' + datetime.now().strftime('%H%M'))
    for i in range(1, 100):
        d = stem if i == 1 else f'{stem}-{i}'
        if not os.path.exists(d):
            return d
    raise RuntimeError('нет свободного имени папки')


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Замер: сколько спален загруженного плана решает нынешний солвер.')
    ap.add_argument('inputs', nargs='+', help='model-*.json стенда или floorplanResult / фикстура теста')
    ap.add_argument('--out', default=None, help=f'папка итога (по умолчанию новая {OUT_ROOT}/run-ЧЧММ)')
    ap.add_argument('--no-png', action='store_true')
    ap.add_argument('--all-purposes', action='store_true', help='прогнать все три назначения у каждой комнаты (для сравнения)')
    a = ap.parse_args(argv)
    out = a.out or new_dir(OUT_ROOT)
    rows = run(a.inputs, out, png=not a.no_png, all_purposes=a.all_purposes)
    print(open(os.path.join(out, 'table.md'), encoding='utf-8').read())
    print(f'итог: {out}')
    return 0 if rows else 1


if __name__ == '__main__':
    sys.exit(main())
