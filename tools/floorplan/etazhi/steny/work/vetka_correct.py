#!/usr/bin/env python3
"""T-98/5 · «правка по чернилам» (директор 26.11, владелец TG 3292): после привязки — коррекция ответа нейросети. $0.
  python3 -I vetka_correct.py --plan plan.json --walls ik/walls.csv --out plan-corr.json [--report correction.json]
(1) стена класса «сдвинута» (параллельные чернила ≤40 см, ≥60 % длины; walls.csv: сдвиг_dx_см/dy_см — на СЕРЕДИНУ линии/пары линий) переносится; вместе с ней
    двигаются ТОЧКИ на её старом отрезке: концы соседних стен (стыки) и вершины контуров комнат. Проёмы привязаны к стене (wall+offset) → едут с ней.
    Точка на нескольких сдвинутых стенах: параллельные стены усредняются, разные направления складываются (угол двух стен).
(2) СТОРОЖ ПОВОРОТА: правка не поворачивает ни одну стену больше чем на MAX_ROT_DEG (2°). Если поворот получается — виновные сдвинутые стены НЕ трогаем, помечаем («не тронута: поворот»).
(3) «выдуманная» / «неполная» — НЕ удаляются, только помечаются в report (для круга правки нейросетью, р.1).
Допуск «точка лежит на стене»: половина толщины (не меньше 5 см) + 2 см. «Остаток подгонки» (<15 см) не трогаем.
Принятие правки (общие ворота) — accept_correction.py: берём, только если Б выросло И А не ухудшилось, иначе откат к «до»."""
import argparse
import copy
import csv
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vetka_fit import UNIT  # noqa: E402

MAX_ROT_DEG = 2.0
V2 = os.environ.get('CORRECT_V2') == '1'      # ВЫКЛЮЧАТЕЛЬ Fable 8: ворота по стене (комнаты ↔ цифры), без «Б выросло»
STRICT_A = os.environ.get('STRICT_A') == '1'             # ВЫКЛЮЧАТЕЛЬ (T-98/14, директор 26.11 вечер): любое ухудшение А у комнаты с цифрой — откат переноса этой стены; по умолчанию ВЫКЛ
STRICT_EPS = 0.02                                        # м²: меньше — шум округления контура (2 дм²), не ухудшение
PASSPORT_ONLY = os.environ.get('PASSPORT_ONLY') == '1'   # ВЫКЛЮЧАТЕЛЬ (шаг 2 Fable 11, T-98/14): А в воротах — только цифры паспорта; комната без цифры → перенос не применять; по умолчанию ВЫКЛ
SHRINK_CM = 8.0


def printed_map(plan0, k, fit_path):
    """Цифры ворот ИЗ ПАСПОРТА листа (Fable 8 §5): env PASSPORT_SID=<id листа>; None — паспорт не задан (тогда цифры плана нейросети, помечается в отчёте)."""
    sid = os.environ.get('PASSPORT_SID')
    if not sid or not os.path.exists(fit_path):
        return None
    from passport_load import printed_for_plan
    return printed_for_plan(sid, plan0, k, json.load(open(fit_path, encoding='utf-8')))


def room_table(plan, k, printed=None):
    """{id комнаты: (имя, печатная площадь м², площадь контура минус 8 см по краю м²)} — комнаты с цифрой, без балкона/лоджии.
    printed — {id: площадь из паспорта}: берём ТОЛЬКО их (у комнаты без паспортной цифры — нет цифры)."""
    from shapely.geometry import Polygon
    out = {}
    for lv in plan['levels']:
        for r in lv.get('rooms', []):
            if printed is not None:
                if r.get('id', '') not in printed:
                    continue
            elif not r.get('area'):
                continue
            if r.get('use') in ('balcony', 'outdoor') or r.get('ceiling') is False or any(x in str(r.get('name', '')).lower() for x in ('балкон', 'лодж', 'balcon', 'loggia', 'terrace')):
                continue
            g = Polygon([(x * k, y * k) for x, y in r['polygon']])
            g = g if g.is_valid else g.buffer(0)
            area_ = printed[r.get('id', '')] if printed is not None else float(r['area']) * (k / 100.0) ** 2
            out[r.get('id', '')] = (r.get('name', ''), area_, g.buffer(-SHRINK_CM).area / 1e4)
    return out



def seg_dist(p, a, b):
    ab = (b[0] - a[0], b[1] - a[1])
    L2 = ab[0] ** 2 + ab[1] ** 2
    if L2 == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1]), 0.0
    t = ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / L2
    tc = max(0.0, min(1.0, t))
    q = (a[0] + ab[0] * tc, a[1] + ab[1] * tc)
    return math.hypot(p[0] - q[0], p[1] - q[1]), t


def apply(plan0, shifted, k):
    """→ (новый план, число сдвинутых точек, {стена: поворот°}, {стена: {id сдвинутых, влиявших на её концы}})."""
    plan = copy.deepcopy(plan0)

    def displacement(p):
        groups = []
        for s in shifted:
            dist, t = seg_dist(p, s['a'], s['b'])
            if dist > s['tol']:
                continue
            L = math.hypot(s['b'][0] - s['a'][0], s['b'][1] - s['a'][1]) or 1.0
            if t < -s['tol'] / L or t > 1 + s['tol'] / L:
                continue
            n = (-(s['b'][1] - s['a'][1]) / L, (s['b'][0] - s['a'][0]) / L)
            for g in groups:
                if abs(g[0][0] * n[0] + g[0][1] * n[1]) > 0.97:
                    g[1].append((s['d'], s['id']))
                    break
            else:
                groups.append((n, [(s['d'], s['id'])]))
        dx = sum(sum(d[0][0] for d in ds) / len(ds) for _, ds in groups)
        dy = sum(sum(d[0][1] for d in ds) / len(ds) for _, ds in groups)
        who = {d[1] for _, ds in groups for d in ds}
        return dx, dy, who

    moved, influence, room_aff = 0, {}, {}
    for lv in plan['levels']:
        for w in lv.get('walls', []):
            for key in ('from', 'to'):
                dx, dy, who = displacement((w[key][0] * k, w[key][1] * k))
                if who:
                    w[key] = [round(w[key][0] + dx / k, 4), round(w[key][1] + dy / k, 4)]
                    moved += 1
                    influence.setdefault(w.get('id', ''), set()).update(who)
        for r in lv.get('rooms', []):
            for j, v in enumerate(r['polygon']):
                dx, dy, who = displacement((v[0] * k, v[1] * k))
                if who:
                    r['polygon'][j] = [round(v[0] + dx / k, 4), round(v[1] + dy / k, 4)]
                    moved += 1
                    room_aff.setdefault(r.get('id', ''), set()).update(who)
    old = {w['id']: w for lv in plan0['levels'] for w in lv.get('walls', []) if w.get('id')}
    rot = {}
    for lv in plan['levels']:
        for w in lv.get('walls', []):
            o = old.get(w.get('id'))
            if not o:
                continue
            a0 = math.atan2(o['to'][1] - o['from'][1], o['to'][0] - o['from'][0])
            a1 = math.atan2(w['to'][1] - w['from'][1], w['to'][0] - w['from'][0])
            rot[w['id']] = abs((math.degrees(a1 - a0) + 180) % 360 - 180)
    return plan, moved, rot, influence, room_aff


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', required=True)
    ap.add_argument('--walls', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--report')
    a = ap.parse_args()
    plan0 = json.load(open(a.plan, encoding='utf-8'))
    k = UNIT.get(plan0.get('units', 'cm'), 1.0)             # единиц плана → см
    rows = {r['стена']: r for r in csv.DictReader(open(a.walls, encoding='utf-8'))}
    cand = []
    for lv in plan0['levels']:
        for w in lv.get('walls', []):
            r = rows.get(w.get('id', ''))
            if r and r['класс'] == 'сдвинута' and r['сдвиг_dx_см'] != '':
                th = float(w['thickness']) * k if w.get('thickness') else {'exterior': 30.0, 'partition': 8.0}.get(w.get('kind'), 12.0)
                cand.append({'id': w['id'], 'a': (w['from'][0] * k, w['from'][1] * k), 'b': (w['to'][0] * k, w['to'][1] * k),
                             'd': (float(r['сдвиг_dx_см']), float(r['сдвиг_dy_см'])), 'tol': max(th / 2, 5.0) + 2.0})
    shifted = list(cand)
    untouched = []                                           # [{стена, причина}]
    gate_cancel, no_numbers = [], set()
    pm = printed_map(plan0, k, os.path.join(os.path.dirname(os.path.abspath(a.walls)), 'fit.json')) if V2 else None
    printed = pm[0] if pm else None
    pstat = pm[1] if pm else 'цифры из ответа нейросети (паспорт не задан)'
    if PASSPORT_ONLY and V2 and printed is None:             # шаг 2 Fable 11: площадь из ответа нейросети цифрой не считать — цифр нет вовсе
        printed, pstat = {}, 'паспорт не свидетель — цифр нет (площадь из ответа нейросети не считается)'
    tab0 = room_table(plan0, k, printed) if V2 else {}
    outdoor_ids = {r.get('id', '') for lv in plan0['levels'] for r in lv.get('rooms', [])
                   if r.get('use') in ('balcony', 'outdoor') or r.get('ceiling') is False or any(x in str(r.get('name', '')).lower() for x in ('балкон', 'лодж', 'balcon', 'loggia', 'terrace'))}
    flags_nofig = []
    for _ in range(2 * len(cand) + 2):
        plan, moved, rot, infl, raff = apply(plan0, shifted, k)
        bad = {w for w, d in rot.items() if d > MAX_ROT_DEG}
        if bad:
            culprits = set()
            for w in bad:
                culprits |= infl.get(w, set())
            if not culprits:
                break
            for s in [s for s in shifted if s['id'] in culprits]:
                untouched.append({'стена': s['id'], 'причина': f'правка повернула бы стену(ы) {sorted(bad)} на >{MAX_ROT_DEG}°'})
            shifted = [s for s in shifted if s['id'] not in culprits]
            if not shifted:
                plan, moved, rot, infl, raff = apply(plan0, [], k)
                break
            continue
        if not V2:
            break
        # ВОРОТА ПО СТЕНЕ (Fable 8 §3): перенос остаётся, если все задетые комнаты после него сходятся с цифрами (±8 % от 6 м², ±0,4 м² мелкие) или стали ближе; иначе отменяется ТОЛЬКО он
        tab1 = room_table(plan, k, printed)
        failed = None
        no_numbers = set()
        if PASSPORT_ONLY:                                    # шаг 2: задета комната (не балкон) без цифры паспорта — перенос НЕ применять, оставить флажком
            blocked = [(rid, who) for rid, who in raff.items() if rid not in tab0 and rid not in outdoor_ids]
            if blocked:
                drop = {w for _, who in blocked for w in who} & {s['id'] for s in shifted}
                if drop:
                    for s in [s for s in shifted if s['id'] in drop]:
                        flags_nofig.append({'стена': s['id'], 'dx_см': s['d'][0], 'dy_см': s['d'][1],
                                            'причина': 'задета комната без цифры паспорта: ' + ', '.join(sorted(str(r) for r, who in blocked if s['id'] in who)) + ' — перенос не применён, флажок'})
                    shifted = [s for s in shifted if s['id'] not in drop]
                    if not shifted:
                        plan, moved, rot, infl, raff = apply(plan0, [], k)
                        break
                    continue
        for rid, who in raff.items():
            if rid not in tab0:
                no_numbers.add(rid)
                continue
            nm, P_, N0 = tab0[rid]
            N1 = tab1[rid][2]
            d0, d1 = abs(N0 - P_), abs(N1 - P_)
            tol_ = 0.08 * P_ if P_ >= 6 else 0.4
            if STRICT_A:                                     # правило ворот директора 26.11: ухудшил А хоть у одной комнаты с цифрой — откат переноса этой стены
                ok_room = d1 <= d0 + STRICT_EPS
            else:
                ok_room = d1 <= tol_ or d1 <= d0 + 1e-6
            if not ok_room:
                failed = (rid, nm, who, P_, N0, N1)
                break
        if not failed:
            break
        rid, nm, who, P_, N0, N1 = failed
        cands = [s for s in shifted if s['id'] in who]
        if not cands:
            break
        c = max(cands, key=lambda s: math.hypot(*s['d']))
        gate_cancel.append({'стена': c['id'], 'причина': f'комната {nm}: печатная {P_:.2f} м², была {N0:.2f}, после переноса {N1:.2f} — дальше от цифры и вне допуска', 'комната': rid})
        shifted = [s for s in shifted if s['id'] != c['id']]
        if not shifted:
            plan, moved, rot, infl, raff = apply(plan0, [], k)
            break
    json.dump(plan, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    marked = {'выдуманные': [i for i, r in rows.items() if r['класс'] == 'выдуманная'], 'неполные': [i for i, r in rows.items() if r['класс'] == 'неполная'],
              'цифры_ворот': pstat, 'не_тронуты_из_за_поворота': untouched, 'отменены_воротами_по_комнатам': gate_cancel, 'задеты_комнаты_без_цифр': sorted(no_numbers), 'флажки_переносов_без_цифр': flags_nofig}
    rep = {'перенесено_стен': [{'стена': s['id'], 'dx_см': s['d'][0], 'dy_см': s['d'][1]} for s in shifted], 'сдвинуто_точек': moved,
           'макс_поворот_град': round(max(rot.values()) if rot else 0.0, 2), 'помечены_для_круга_нейросети': marked}
    if a.report:
        json.dump(rep, open(a.report, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps({'перенесено_стен': len(shifted), 'кандидатов': len(cand), 'не_тронуты_из_за_поворота': len(untouched), 'отменены_воротами_по_комнатам': len(gate_cancel), 'сдвинуто_точек': moved,
                      'макс_поворот_град': rep['макс_поворот_град'], 'помечено': {k_: len(v) for k_, v in marked.items()}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
