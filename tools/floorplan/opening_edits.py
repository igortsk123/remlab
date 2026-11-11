"""Окна и двери агента поверх прочитанного плана (план trial-room-edit-01, Е4; T-20261110-39; таблица `db/init/029-trial-opening-edits.sql`).

Как правки комнат (`room_edits.py`): канон — `result` задания как прочитан, правки проёмов живут отдельно (claim пересборки:
`openingEdits`) и накладываются на КОПИЮ перед каждой сборкой — после правок комнат. Комнаты правка проёма не трогает, только список
`panels[].openings` своей панели: распознанный проём заменён (тип, центр, ширина) или снят («ложная дверь»), добавленный — дописан.

Координаты — см листа, как прочитано: проёмы панели стоят на ИСХОДНЫХ стенах (правка размера комнаты стены не двигает — привязка
`trial_room.openings_of` идёт по исходным контурам, `plan`), поэтому окно и дверь агента ставит страница на исходный контур.

Правка распознанного проёма — ключ `s<номер>` и центр как прочитан (`srcC`): проём ищется по номеру, если центр рядом, иначе ближайший
к `srcC` в `MATCH_CM` (перечитывание плана сменило номера); не нашёлся — правка не ложится (исход честный, остальные идут).
Добавленный — ключ `u<токен>`. У каждого проёма копии — `key` (страница по нему шлёт правку), у правленых — `user`.

Пересобираются комнаты, чьих стен правка коснулась: контур (исходный) в `TOUCH_CM` от прежнего или нового центра — комнаты по обе
стороны стены (`dirty_rooms`, вместе с правками комнат — `conveyor.EditRebuild`).
"""
from __future__ import annotations

import copy
import math

KINDS = ('door', 'window')
MATCH_CM = 30.0      # распознанный проём после перечитывания плана: центр не дальше — тот же
NEAR_CM = 35.0       # = rules/trial-room.json opening_near_cm: комната у проёма (по обе стороны внутренней стены — обе)
TOUCH_CM = 60.0      # > opening_far_cm (50): стена комнаты задета — её 3D и мебель пересобрать
EXACT_CM = 1.0       # строгое соответствие: центр как прочитан (округление до 0,1 см)


def _seg(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L)) if L else 0.0
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def contour_of(room: dict) -> list:
    """Контур, на котором стоят проёмы: исходный (`plan` правки размера), иначе как есть."""
    return (room.get('plan') or {}).get('contour') or room.get('contour') or []


def wall_dist(room: dict, p) -> float:
    P = contour_of(room)
    return min((_seg(p, P[i], P[(i + 1) % len(P)]) for i in range(len(P))), default=math.inf)


def inside(room: dict, p) -> bool:
    P = contour_of(room)
    c = False
    for i in range(len(P)):
        a, b = P[i], P[i - 1]
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]:
            c = not c
    return c


def _pt(v):
    try:
        x, y = float(v[0]), float(v[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return [round(x, 1), round(y, 1)] if math.isfinite(x) and math.isfinite(y) else None


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def _src_idx(e: dict):
    k = str(e.get('key') or '')
    if e.get('srcIdx') is not None:
        try:
            return int(e['srcIdx'])
        except (TypeError, ValueError):
            return None
    return int(k[1:]) if k[:1] == 's' and k[1:].isdigit() else None


def _match(ops: list, e: dict, taken: set, strict: bool = False):
    """Номер распознанного проёма правки или None. `strict` («перечитать планировку», T-20261111-02) — только свой номер с центром
    как прочитан (`EXACT_CM`): номер и центр уже перевела однозначная пара проёмов (`translate`), ближайший мог бы быть чужим."""
    sc = _pt(e.get('srcC') or [])
    i = _src_idx(e)
    if sc is None:
        return None
    if i is not None and 0 <= i < len(ops) and i not in taken and math.dist(ops[i]['c'], sc) <= (EXACT_CM if strict else MATCH_CM):
        return i
    if strict:
        return None
    best = None
    for j, o in enumerate(ops):
        d = math.dist(o['c'], sc)
        if j not in taken and d <= MATCH_CM and (best is None or d < best[0]):
            best = (d, j)
    return best[1] if best else None


def apply(result: dict, edits: list | None, strict: bool = False) -> tuple[dict, list]:
    """Копия результата с проёмами агента → (результат, [(правка, панель, [задетые точки])] — приложенные). `strict` — см. `_match`."""
    res = copy.deepcopy(result)
    done = []
    by_panel: dict = {}
    for e in edits or []:
        by_panel.setdefault(str(e.get('panel')), []).append(e)
    for pan in res.get('panels') or []:
        es = by_panel.get(str(pan.get('id')))
        ops = [dict(o) for o in pan.get('openings') or []]
        if not es:
            if edits:
                pan['openings'] = [dict(o, key=f's{i}') for i, o in enumerate(ops)]
            continue
        rooms = pan.get('rooms') or []
        out = {i: dict(o, key=f's{i}') for i, o in enumerate(ops)}
        taken, added = set(), []
        for e in es:
            key, kind, c, w = str(e.get('key') or ''), e.get('kind'), _pt(e.get('c') or []), _num(e.get('widthCm'))
            removed = bool(e.get('removed'))
            if key[:1] == 'u':                       # добавленный агентом
                if removed:                          # снят после сборки (сервер пишет снятие только опубликованного): исчезает,
                    if c is not None:                # комнаты у его стены — пересобрать (мебель стояла под эту дверь; e2e T-39/2 H1)
                        done.append((e, pan['id'], [c]))
                    continue
                if kind not in KINDS or c is None or w is None:
                    continue
                # наружный — у стены только одной комнаты; комната, чей контур накрывает точку (контуры распознавания наезжают:
                # дверь спальни в санузел aRQ лежала внутри санузла в 58 см от его стены), — тоже по ту сторону (e2e T-39)
                near = sum(1 for r in rooms if wall_dist(r, c) <= NEAR_CM or inside(r, c))
                added.append({'kind': kind, 'c': c, 'widthCm': round(w, 1), 'exterior': near <= 1, 'key': key, 'user': True})
                done.append((e, pan['id'], [c]))
                continue
            i = _match(ops, e, taken, strict)
            if i is None:
                continue
            taken.add(i)
            old = ops[i]
            if removed:
                out.pop(i, None)
                done.append((e, pan['id'], [old['c']]))
                continue
            if kind not in KINDS or c is None or w is None:
                continue
            out[i] = dict(old, kind=kind, c=c, widthCm=round(w, 1), key=key or f's{i}', user=True, srcC=list(old['c']))
            done.append((e, pan['id'], [old['c'], c]))
        pan['openings'] = [out[i] for i in sorted(out)] + added
    return res, done


def _scaled(v, k: float):
    p = _pt(v or [])
    return None if p is None else [round(p[0] * k, 1), round(p[1] * k, 1)]


def translate(edits: list | None, old: dict, new: dict, k: float) -> tuple[list, list, list]:
    """«Перечитать планировку» (T-20261111-02): правки проёмов прежнего плана → на перечитанный. `k` — см нового на см прежнего
    (масштаб мог смениться; `regress.pair_canon`). Распознанный проём (`s<номер>`) — тот же номер и центр в прежнем плане, в новом —
    ЕДИНСТВЕННЫЙ проём того же вида в `MATCH_CM` от его места; добавленный (`u…`) — центр в новом масштабе, у стены комнаты новой панели
    (`NEAR_CM`). → (правки на новых номерах и центрах, карта для публикации [{panel, key, to, srcIdx, srcC, c}], не легли [(правка, почему)])."""
    oldp = {str(p.get('id')): p for p in old.get('panels') or []}
    newp = {str(p.get('id')): p for p in new.get('panels') or []}
    out, omap, bad, taken = [], [], [], set()
    for e in edits or []:
        pid, key = str(e.get('panel')), str(e.get('key') or '')
        po, pn = oldp.get(pid), newp.get(pid)
        c = _scaled(e.get('c'), k)
        if po is None or pn is None or c is None:
            bad.append((e, 'панели нет в перечитанном плане' if pn is None else 'нет центра'))
            continue
        if key[:1] == 'u':
            if not e.get('removed') and min((wall_dist(r, c) for r in pn.get('rooms') or []), default=math.inf) > NEAR_CM:
                bad.append((e, 'добавленный проём не у стены перечитанного плана'))
                continue
            out.append({**e, 'c': c})
            omap.append({'panel': pid, 'key': key, 'to': key, 'srcIdx': None, 'srcC': None, 'c': c})
            continue
        ops_o, ops_n = po.get('openings') or [], pn.get('openings') or []
        i, sc = _src_idx(e), _pt(e.get('srcC') or [])
        if i is None or sc is None or not 0 <= i < len(ops_o) or math.dist(ops_o[i]['c'], sc) > MATCH_CM:
            bad.append((e, 'проёма правки нет в прежнем плане'))
            continue
        at = _scaled(ops_o[i]['c'], k)
        near = [j for j, o in enumerate(ops_n) if o.get('kind') == ops_o[i].get('kind') and math.dist(o['c'], at) <= MATCH_CM]
        if len(near) != 1 or (pid, near[0]) in taken:
            bad.append((e, 'нет однозначной пары проёма' if len(near) != 1 else 'два проёма на одном'))
            continue
        j = near[0]
        taken.add((pid, j))
        src_c = [round(float(ops_n[j]['c'][0]), 1), round(float(ops_n[j]['c'][1]), 1)]
        out.append({**e, 'key': f's{j}', 'srcIdx': j, 'srcC': src_c, 'c': c})
        omap.append({'panel': pid, 'key': key, 'to': f's{j}', 'srcIdx': j, 'srcC': src_c, 'c': c})
    return out, omap, bad


def dirty_rooms(result: dict, done: list) -> set:
    """Комнаты (панель, id плана), чьих стен коснулись непостроенные правки проёмов (`built` false)."""
    pans = {p.get('id'): p for p in result.get('panels') or []}
    out = set()
    for e, pid, pts in done:
        if e.get('built'):
            continue
        for r in (pans.get(pid) or {}).get('rooms') or []:
            if any(wall_dist(r, p) <= TOUCH_CM for p in pts):
                out.add((pid, str(r['id'])))
    return out
