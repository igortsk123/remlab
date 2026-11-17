"""СОГЛАСОВАННОСТЬ ДВУХ ВИДОВ В ЗАДАНИИ МОДЕЛИ (план photo-tariff-mass-01, T-20261117-03; проба П1.67 — `sd_probe/consistency.py`, урок 690).

Модель рисует лист из двух видов одной комнаты и на дешёвом тарифе mass сама решает, что висит на каких стенах: на спальне она придумывала окно,
которого нет ни на одном из кадров 3D, и роняла картины на втором виде. Абзац ниже собирает КОД из данных заказа — комната (размеры, проёмы),
камеры C1/C2 (x, y, rot, fov), мебель (роль, поворот), декор — и говорит прямо: какие стены и проёмы видит каждая камера, какого окна не
рисовать, на какой стене картины и что они одинаковы в обоих видах. Общее правило: ни ID комнат, туров и товаров, только геометрия.

Соглашения кода рендера (`draft_render.cams_from_request` / `_fixture_openings`): взгляд камеры — (sin a, −cos a) в плане (x вправо, y вглубь),
правая рука камеры — (−fy, fx); стены south y=0, north y=D, west x=0, east x=W; предмет «спиной» к стене — (sin a, −cos a); горизонтальный угол
кадра = `fov` камеры (`scene_mesh.project_pts`), точка съёмки зажата внутрь комнаты на 3 см (`cams_from_request`).

  skip_reason(payload) → None | причина: данных не хватает — абзац не пишем (вызывающий печатает `consistency: skip <причина>`)
  block(payload) → текст абзаца | None;  insert(prompt, block) → промпт с абзацем перед `OUTPUT`;  geometry_sig(payload) → отпечаток геометрии
"""
import hashlib
import json
import math

WALLS = ('north', 'south', 'west', 'east')
KINDS = ('door', 'window', 'opening')                              # opening — проём без створки (арка, широкий проход): есть в реальных турах
_LABEL = {'opening': 'doorless opening'}
_lab = lambda k: _LABEL.get(k, k)
EN = {'диван': 'sofa', 'кровать': 'bed', 'комод': 'chest of drawers'}
STEP = 8.0            # см между точками выборки вдоль стены
PAD = 3.0             # точка съёмки зажимается внутрь комнаты (как `draft_render.cams_from_request`)
ART_BASES = ('картин', 'зеркал')
ANCHORS = ('диван', 'кровать', 'комод')    # как в промпте: картины над диваном, иначе над кроватью, иначе над комодом


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _cams(payload: dict) -> list:
    """Камеры C1 и C2 по порядку имён (так же сортируются кадры `views`); не две — пусто."""
    cs = [c for c in (payload.get('cams') or []) if isinstance(c, dict) and c.get('name') in ('C1', 'C2')]
    cs = sorted(cs, key=lambda c: c['name'])
    return cs if [c['name'] for c in cs] == ['C1', 'C2'] else []


def skip_reason(payload: dict) -> str | None:
    """Полнота данных: комната с размерами и проёмами, две камеры с позой, кадры той же комнаты. Неполно — причина словом, абзац пропускается."""
    room = payload.get('room')
    if not isinstance(room, dict) or not (_num(room.get('w')) and _num(room.get('d')) and room['w'] > 0 and room['d'] > 0):
        return 'нет размеров комнаты'
    ops = room.get('openings')
    if not isinstance(ops, list) or not ops:
        return 'нет проёмов комнаты'
    for o in ops:
        if not (isinstance(o, dict) and o.get('kind') in KINDS and o.get('wall') in WALLS
                and _num(o.get('offset_cm')) and _num(o.get('width_cm')) and o['width_cm'] > 0):
            return 'проём без стены или размера'
    cams = _cams(payload)
    if not cams:
        return 'нет камер C1 и C2'
    for c in cams:
        if not all(_num(c.get(k)) for k in ('x', 'y', 'rot')) or (c.get('fov') is not None and not _num(c['fov'])):
            return f"поза камеры {c['name']} неполна"
    vs = sorted([v for v in (payload.get('views') or []) if isinstance(v, dict)], key=lambda v: str(v.get('camera')))
    if len(vs) >= 2 and [v.get('camera') for v in vs[:2]] != ['C1', 'C2']:
        return 'кадры не C1 и C2'
    import draft_trial as DT
    want = DT.room_sig(room)
    if any(isinstance(v.get('room'), str) and v['room'] and v['room'] != want for v in vs[:2]):
        return 'кадры другой комнаты'
    return None


def _seg(room: dict, wall: str, a: float, b: float) -> list:
    """Точки (x, y) вдоль стены от a до b см по её длине (north/south — вдоль x, west/east — вдоль y)."""
    W, D = float(room['w']), float(room['d'])
    n = max(2, int(abs(b - a) / STEP) + 1)
    out = []
    for i in range(n + 1):
        t = a + (b - a) * i / n
        out.append({'south': (t, 0.0), 'north': (t, D), 'west': (0.0, t), 'east': (W, t)}[wall])
    return out


def _eye(room: dict, cam: dict) -> tuple:
    return (min(max(float(cam['x']), PAD), float(room['w']) - PAD), min(max(float(cam['y']), PAD), float(room['d']) - PAD))


def _rel(room: dict, cam: dict, pt: tuple) -> float:
    """Угол точки от взгляда камеры, градусы (− влево, + вправо); 999 — за спиной."""
    a = math.radians(float(cam.get('rot') or 0))
    fx, fy = math.sin(a), -math.cos(a)
    ex, ey = _eye(room, cam)
    dx, dy = pt[0] - ex, pt[1] - ey
    fwd = dx * fx + dy * fy
    if fwd <= 1.0:
        return 999.0
    return math.degrees(math.atan2(dx * (-fy) + dy * fx, fwd))


def _view(room: dict, cam: dict, pts: list) -> tuple:
    """(доля точек в кадре, положение: left part | centre | right part)."""
    half = float(cam.get('fov') or 72.0) / 2
    rels = [_rel(room, cam, p) for p in pts]
    ins = [r for r in rels if abs(r) <= half]
    if not ins:
        return 0.0, ''
    m = sum(ins) / len(ins)
    return len(ins) / len(rels), ('left part' if m < -half / 3 else 'right part' if m > half / 3 else 'centre')


def _facing(cam: dict) -> str:
    a = math.radians(float(cam.get('rot') or 0))
    fx, fy = math.sin(a), -math.cos(a)
    return max(WALLS, key=lambda w: {'north': fy, 'south': -fy, 'east': fx, 'west': -fx}[w])


def _anchor(items: list) -> tuple:
    """Опорный предмет картин → (роль, стена спинки, отрезок вдоль стены); нет предмета — ('', '', (0, 0))."""
    for base in ANCHORS:
        for it in items or []:
            if str(it.get('role') or '').split(' ')[0] == base and all(_num(it.get(k)) for k in ('x', 'y', 'w', 'd')):
                a = math.radians(float(it.get('rot') or 0))
                bx, by = math.sin(a), -math.cos(a)
                wall = max(WALLS, key=lambda w: {'north': by, 'south': -by, 'east': bx, 'west': -bx}[w])
                along_x = abs(math.cos(a)) > 0.5                      # ширина предмета вдоль x при повороте 0/180
                half_w = (float(it['w']) if along_x else float(it['d'])) / 2
                half_d = (float(it['d']) if along_x else float(it['w'])) / 2
                c, e = (float(it['x']), half_w) if wall in ('north', 'south') else (float(it['y']), half_d)
                return it['role'], wall, (c - e, c + e)
    return '', '', (0.0, 0.0)


def facts(payload: dict) -> dict:
    """Факты по видам: что видит каждая камера, где проёмы и стена картин."""
    room, cams, ops = payload['room'], _cams(payload), payload['room'].get('openings') or []
    role, awall, aspan = _anchor(payload.get('items') or [])
    out = {'anchor': EN.get(role.split(' ')[0], '') if role else '', 'art_wall': awall, 'views': []}
    for cam in cams:
        v = {'name': cam['name'], 'facing': _facing(cam), 'walls': {}, 'openings': [], 'art': None}
        for w in WALLS:
            ln = float(room['w']) if w in ('north', 'south') else float(room['d'])
            fr, pos = _view(room, cam, _seg(room, w, 0.0, ln))
            if fr >= 0.08:
                v['walls'][w] = (round(fr, 2), pos)
        for o in ops:
            a0 = float(o['offset_cm'])
            fr, pos = _view(room, cam, _seg(room, o['wall'], a0, a0 + float(o['width_cm'])))
            v['openings'].append({'kind': o['kind'], 'wall': o['wall'], 'frac': round(fr, 2), 'pos': pos})
        if awall:
            fr, pos = _view(room, cam, _seg(room, awall, aspan[0], aspan[1]))
            v['art'] = (round(fr, 2), pos)
        out['views'].append(v)
    return out


def _walls_text(v: dict) -> str:
    rows = sorted(v['walls'].items(), key=lambda kv: -kv[1][0])
    return ', '.join(f"{w.upper()} wall ({'whole' if fr > 0.9 else 'part'}, {pos})" for w, (fr, pos) in rows) or 'no wall'


def block(payload: dict) -> str | None:
    """Абзац согласованности видов для промпта (английский, как весь промпт); данных не хватает — None."""
    if skip_reason(payload):
        return None
    f = facts(payload)
    ops = payload['room'].get('openings') or []
    lines = ['VIEW CONSISTENCY — derived from the room data of THIS scene; it is exact and overrides any guess. Both views show the SAME room and agree in every '
             'wall, opening and picture. The compass names only label the walls of the room'
             + (f' (the {f["anchor"]} stands against the {f["art_wall"].upper()} wall)' if f['anchor'] else '') + '.']
    for i, v in enumerate(f['views']):
        seen = [o for o in v['openings'] if o['frac'] > 0]
        txt = f"VIEW {i + 1} ({'upper' if i == 0 else 'lower'} picture) faces the {v['facing'].upper()} wall and shows: {_walls_text(v)}. "
        txt += ('Openings in this view: ' + '; '.join(f"{_lab(o['kind'])} in the {o['wall'].upper()} wall "
                                                       f"({'whole' if o['frac'] > 0.9 else 'partly'}, {o['pos']})" for o in seen) + '.'
                if seen else 'NO window, door or opening is visible in this view: draw none, every wall here is plain wall.')
        lines.append(txt)
    for o in ops:
        sees = [i + 1 for i, v in enumerate(f['views']) if any(x['wall'] == o['wall'] and x['kind'] == o['kind'] and x['frac'] > 0 for x in v['openings'])]
        w = f"the {_lab(o['kind'])} ({o['wall'].upper()} wall, {round(float(o['width_cm']))} cm wide)"
        lines.append(f"* {w[0].upper() + w[1:]}: " + (f"seen in VIEW {' and VIEW '.join(map(str, sees))} only, exactly as the placeholder in IMAGE 1 shows it."
                     if sees else 'seen in NEITHER view — do NOT draw it, and do not invent any window, door or opening anywhere else.'))
    lines.append('Windows, doors and doorless openings exist ONLY where IMAGE 1 shows them (blue = window, brown = door). A wall without one in IMAGE 1 stays plain: '
                 'no window, glass, curtain, door or opening is added to it in either view.')
    arts = [d for d in payload.get('decor') or [] if isinstance(d, dict) and str(d.get('role') or '').startswith(ART_BASES)]
    if arts and f['art_wall']:
        if all(d.get('shown') for d in arts):                       # картины уже нарисованы в кадре 3D — их место задал кадр
            lines.append('WALL ART: the pictures are already drawn in IMAGE 1: each stays exactly on the wall where IMAGE 1 shows it, never moves to another wall, '
                         'and appears in every view that shows that wall — the SAME pictures, same size, same height, same position; never a second copy.')
        else:
            seen = [f"VIEW {i + 1} ({v['art'][1]})" for i, v in enumerate(f['views']) if v['art'] and v['art'][0] > 0]
            lines.append(f"WALL ART: the {len(arts)} bought picture(s) not yet in IMAGE 1 hang ONLY on the {f['art_wall'].upper()} wall above the {f['anchor']}, as one group. "
                         + (f"That wall segment is visible in {' and '.join(seen)}: show the SAME pictures there, same artwork, same size, same height, same position on the wall."
                            if seen else 'That wall segment is visible in neither view.')
                         + ' Pictures never appear on any other wall, and never twice.')
    return '\n'.join(lines)


def insert(prompt: str, text: str) -> str:
    """Абзац — перед финальным абзацем OUTPUT (его нет — в конец)."""
    i = prompt.rfind('\nOUTPUT')
    return prompt[:i].rstrip() + '\n\n' + text + '\n\n' + prompt[i:].lstrip() if i > 0 else prompt.rstrip() + '\n\n' + text


def geometry_sig(payload: dict) -> str:
    """Отпечаток всего, от чего зависит абзац: размеры и проёмы комнаты, позы камер, мебель (роль, место, поворот), декор (роль, показано)."""
    room = payload.get('room') if isinstance(payload.get('room'), dict) else {}
    r = lambda v: round(float(v), 1) if _num(v) else None
    data = {'room': [r(room.get('w')), r(room.get('d')),
                     sorted(([o.get('kind'), o.get('wall'), r(o.get('offset_cm')), r(o.get('width_cm'))] for o in (room.get('openings') or []) if isinstance(o, dict)), key=str)],
            'cams': [[c.get('name'), r(c.get('x')), r(c.get('y')), r(c.get('rot')), r(c.get('fov'))] for c in _cams(payload)],
            'items': sorted(([it.get('role'), r(it.get('x')), r(it.get('y')), r(it.get('rot')), r(it.get('w')), r(it.get('d'))]
                            for it in (payload.get('items') or []) if isinstance(it, dict)), key=str),
            'decor': sorted(([d.get('role'), bool(d.get('shown'))] for d in (payload.get('decor') or []) if isinstance(d, dict)), key=str)}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
