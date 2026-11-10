"""Правки комнат агента поверх прочитанного плана (план trial-room-edit-01, Е3; T-20261110-36; таблица `db/init/028-trial-room-edits.sql`).

Канон — `result` задания (как прочитано); правки живут отдельно (сервер отдаёт их в claim пересборки: `edits`) и накладываются на
КОПИЮ перед каждой сборкой — «Обустроить», текст агента (перечитывание плана) и сама правка. Так правка переживает перечитывание
плана, а отмена правки (вернули размер как прочитано) — просто её отсутствие.

Комната правки — по (панель, id прочитанного плана); не нашлась (перечитывание сменило id) — ближайшая в той же панели по центру охвата
в долях охвата панели (`anchor`, как считает сервер `lib/trial/repo-room-edit.ts:roomNow`), не дальше `ANCHOR_MAX`.

Что делает правка с комнатой копии:
  * имя и вид — как у правки (вид по имени считает сервер, `lib/trial/room-kind.ts`); `user_name` — имя сменил агент;
  * ширина × длина (`w_cm`×`d_cm` — охват контура по осям листа): контур масштабируется от центра охвата (sx = W/w, sy = D/d), площадь —
    в sx·sy; исходные охват и контур — в `plan` (2D-план тура и привязка проёмов — по ним: `trial_room.openings_of`, `trial_bundle`),
    `edited` = {w, d}, флаг `user_dims` — размер дал человек: проверка размера снята, фото можно (`trial_bundle.size_check/photo_ok`).
Проёмы панели не двигаются: привязка считается по исходным контурам, центр проёма своей комнаты переносится тем же масштабом.
Будущие правки проёмов (окно/дверь руками, часть 3) — своя таблица и свой шаг поверх этого, комнаты их не касаются.
"""
from __future__ import annotations

import copy

USER_DIMS = 'user_dims'                      # = tools/scout/trial_bundle.USER_DIMS
ANCHOR_MAX = 0.12                            # доля охвата панели: дальше — правку не к чему приложить (комнаты нет)
KINDS = ('living', 'bedroom', 'kitchen', 'bathroom', 'hall', 'other')


def _union(rooms: list) -> tuple[float, float, float, float]:
    bs = [r['bbox'] for r in rooms if r.get('bbox')]
    x0, y0 = min(b['x'] for b in bs), min(b['y'] for b in bs)
    sx = max(b['x'] + b['w'] for b in bs) - x0 or 1.0
    sy = max(b['y'] + b['d'] for b in bs) - y0 or 1.0
    return x0, y0, sx, sy


def anchor_of(panel: dict, room: dict) -> tuple[float, float]:
    """Центр охвата комнаты в долях охвата комнат панели (как `roomNow` сервера)."""
    x0, y0, sx, sy = _union(panel.get('rooms') or [])
    b = room['bbox']
    return (b['x'] + b['w'] / 2 - x0) / sx, (b['y'] + b['d'] / 2 - y0) / sy


def find(result: dict, edit: dict, taken: set) -> tuple[dict, dict] | None:
    """→ (панель, комната) правки или None."""
    pan = next((p for p in result.get('panels') or [] if p.get('id') == edit.get('panel')), None)
    if pan is None:
        return None
    rooms = [r for r in pan.get('rooms') or [] if r.get('bbox') and id(r) not in taken]
    hit = next((r for r in rooms if str(r.get('id')) == str(edit.get('srcId'))), None)
    if hit is not None:
        return pan, hit
    a = edit.get('anchor') or {}
    try:
        ax, ay = float(a['x']), float(a['y'])
    except (KeyError, TypeError, ValueError):
        return None
    best = None
    for r in rooms:
        cx, cy = anchor_of(pan, r)
        d = ((cx - ax) ** 2 + (cy - ay) ** 2) ** 0.5
        if d <= ANCHOR_MAX and (best is None or d < best[0]):
            best = (d, r)
    return (pan, best[1]) if best else None


def _scaled(room: dict, w: float, d: float) -> None:
    b = room['bbox']
    sx, sy = float(w) / float(b['w']), float(d) / float(b['d'])
    cx, cy = b['x'] + b['w'] / 2, b['y'] + b['d'] / 2
    room['plan'] = {'bbox': dict(b), 'contour': [list(p) for p in room.get('contour') or []], 'sx': sx, 'sy': sy, 'cx': cx, 'cy': cy}
    room['contour'] = [[round(cx + (p[0] - cx) * sx, 1), round(cy + (p[1] - cy) * sy, 1)] for p in room.get('contour') or []]
    room['bbox'] = {'x': round(cx - w / 2, 1), 'y': round(cy - d / 2, 1), 'w': float(w), 'd': float(d)}
    if room.get('areaM2'):
        room['areaM2'] = round(float(room['areaM2']) * sx * sy, 2)
    room['edited'] = {'w': int(w), 'd': int(d)}
    if USER_DIMS not in (room.get('flags') or []):
        room['flags'] = list(room.get('flags') or []) + [USER_DIMS]


def apply(result: dict, edits: list | None) -> tuple[dict, list]:
    """Копия результата с правками → (результат, [(правка, панель, id комнаты плана)] — приложенные). Неприложимая правка
    (комнаты нет) — пропуск: страница её не покажет как правленую, остальные идут."""
    res = copy.deepcopy(result)
    hits, taken = [], set()
    for e in edits or []:                        # сперва все комнаты по НЕТРОНУТЫМ охватам (центр в долях панели — как у сервера)
        got = find(res, e, taken)
        if got is not None:
            taken.add(id(got[1]))
            hits.append((e, *got))
    done = []
    for e, pan, room in hits:
        name = str(e.get('name') or '').strip()
        if name and name != str(room.get('name') or ''):
            room['name'] = name[:60]
            room['user_name'] = True
        if e.get('kind') in KINDS:
            room['kind'] = e['kind']
        w, d = e.get('wCm'), e.get('dCm')
        if isinstance(w, (int, float)) and isinstance(d, (int, float)) and w > 0 and d > 0 and room['bbox']['w'] > 0 and room['bbox']['d'] > 0:
            _scaled(room, float(w), float(d))
        done.append((e, pan['id'], str(room['id'])))
    return res, done


def dirty_keys(done: list) -> set:
    """Комнаты непостроенных правок (`built` false) — (панель, id плана): их стадия пересобирает, прочие берёт как были."""
    return {(pan, rid) for e, pan, rid in done if not e.get('built')}
