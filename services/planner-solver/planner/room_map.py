"""П0 МАСТЕРА tv-sofa-pair: КАРТА ОГРАНИЧЕНИЙ комнаты — считается ДО любой мебели.

Свод владельца 13.08 (§1): «сначала вообще ничего не расставляем — строим карту»:
для каждой стены — длина, НЕПРЕРЫВНЫЕ свободные участки (за вычетом проёмов и
радиаторов), окно и его ширина, дверь и петли; отдельно — маршруты движения,
которые СТАРШЕ мебели (Houzz: основной 76–122 см, H&G ~91; вторичный ≥60).

Пороги — `rules/zones.json → quality_gate` (числа в данных, не в коде).
Карта — вход для генератора пар «медиа-блок × блок посадки» (П1).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import LineString

from .geometry import opening_polygon, radiator_polygon, room_polygon
from .models import Opening, Radiator, Room

WALLS = ('south', 'east', 'north', 'west')


@dataclass
class WallSegment:
    """Непрерывный свободный участок стены (между проёмами/радиаторами/углами)."""

    wall: str
    start_cm: float          # от начала стены (запад→восток / юг→север)
    end_cm: float
    has_window_behind: bool = False    # за участком окно (низкой мебели можно)

    @property
    def length_cm(self) -> float:
        return self.end_cm - self.start_cm


@dataclass
class WallInfo:
    wall: str
    length_cm: float
    segments: list[WallSegment] = field(default_factory=list)
    windows: list[Opening] = field(default_factory=list)
    doors: list[Opening] = field(default_factory=list)
    radiators: list[Radiator] = field(default_factory=list)

    @property
    def max_free_cm(self) -> float:
        return max((s.length_cm for s in self.segments), default=0.0)


@dataclass
class RoomMap:
    walls: dict[str, WallInfo]
    routes: list[LineString]           # основные маршруты (дверь→дверь/окно/центр)
    light_walls: list[str]             # стены с окнами — источники света
    mode: str = 'transitional'         # small / transitional / large (room_mode)
    shape: str = 'normal'              # normal / slightly / elongated / strongly (room_shape)

    def wall(self, w: str) -> WallInfo:
        return self.walls[w]

    def opposite(self, w: str) -> str:
        return {'south': 'north', 'north': 'south', 'west': 'east', 'east': 'west'}[w]


def _wall_length(room: Room, wall: str) -> float:
    return room.width_cm if wall in ('south', 'north') else room.depth_cm


def _blocked_spans(room: Room, wall: str) -> list[tuple[float, float, str]]:
    """Занятые интервалы стены: (от, до, тип) — двери жёстко, окна помечаются
    (за окном может стоять НИЗКОЕ — решает паспорт шаблона, не карта)."""
    out: list[tuple[float, float, str]] = []
    for op in room.openings:
        if op.wall != wall:
            continue
        kind = 'door' if op.kind in ('door', 'balcony') else 'window'
        out.append((op.offset_cm, op.offset_cm + op.width_cm, kind))
    for rad in room.radiators:
        if rad.wall == wall:
            out.append((rad.offset_cm, rad.offset_cm + rad.width_cm, 'radiator'))
    return sorted(out)


def _segments(room: Room, wall: str) -> list[WallSegment]:
    """Непрерывные участки: двери РЕЖУТ участок; окна/радиаторы — НЕ режут, но
    помечают его (низкий носитель перед окном законен — решение владельца 13.08)."""
    L = _wall_length(room, wall)
    hard = [(a, b) for a, b, k in _blocked_spans(room, wall) if k == 'door']
    soft = [(a, b) for a, b, k in _blocked_spans(room, wall) if k != 'door']
    cur, segs = 0.0, []
    for a, b in sorted(hard) + [(L, L)]:
        if a - cur >= 40.0:                     # осколки короче 40 см не участок
            seg = WallSegment(wall=wall, start_cm=cur, end_cm=a)
            seg.has_window_behind = any(not (sb <= seg.start_cm or sa >= seg.end_cm)
                                        for sa, sb in soft)
            segs.append(seg)
        cur = max(cur, b)
    return segs


def _routes(room: Room) -> list[LineString]:
    """Маршруты: от каждой двери — к другим дверям, к окну (доступ к шторам) и в
    центр комнаты. Прямые оси; фактическую ширину меряет quality.route_width_cm."""
    doors = [op for op in room.openings if op.kind in ('door', 'balcony')]
    wins = [op for op in room.openings if op.kind == 'window']
    pts = []
    for op in doors + wins:
        c = opening_polygon(room, op).centroid
        pts.append((c.x, c.y))
    ctr = room_polygon(room).centroid
    out = []
    for i, a in enumerate(pts):
        out.append(LineString([a, (ctr.x, ctr.y)]))
        for b in pts[i + 1:]:
            out.append(LineString([a, b]))
    return out


def tv_axis_depth(room: Room, media_wall: str) -> float:
    """Глубина комнаты ПО ОСИ ТВ: от стены носителя до противоположной."""
    return room.depth_cm if media_wall in ('south', 'north') else room.width_cm


def room_shape(room: Room) -> str:
    """Форма комнаты (свод №4): normal / slightly / elongated / strongly — ОРТОГОНАЛЬНА
    режиму small/large (315×475 = small И elongated 1.51). Пороги — паспорт room_shape."""
    from .invariants import TEMPLATES
    th = TEMPLATES.get('room_shape', {}).get('thresholds',
                                             {'slightly': 1.25, 'elongated': 1.40,
                                              'strongly': 1.70})
    ratio = max(room.width_cm, room.depth_cm) / max(min(room.width_cm, room.depth_cm), 1.0)
    if ratio >= th['strongly']:
        return 'strongly'
    if ratio >= th['elongated']:
        return 'elongated'
    if ratio >= th['slightly']:
        return 'slightly'
    return 'normal'


def room_mode(room: Room) -> str:
    """Режимная триада (своды владельца 13.08 №2/№3, единый источник — здесь):
    small / transitional / large. Прежний `_deep = max(сторона)>430` в template.py —
    двойник, подлежит замене на этот режим (сверка конфликтов large-room-mode)."""
    area = room.width_cm * room.depth_cm / 10_000
    short = min(room.width_cm, room.depth_cm)
    long_ = max(room.width_cm, room.depth_cm)
    if area >= 25.0 or long_ >= 600.0 or any(
            tv_axis_depth(room, w) >= 500.0 for w in WALLS):
        if area <= 25.0 and short <= 360.0:
            return 'transitional'
        return 'large'
    if area <= 18.0 or short <= 350.0:
        return 'small'
    return 'transitional'


def build_room_map(room: Room) -> RoomMap:
    walls: dict[str, WallInfo] = {}
    for w in WALLS:
        walls[w] = WallInfo(
            wall=w, length_cm=_wall_length(room, w), segments=_segments(room, w),
            windows=[op for op in room.openings if op.kind == 'window' and op.wall == w],
            doors=[op for op in room.openings
                   if op.kind in ('door', 'balcony') and op.wall == w],
            radiators=[r for r in room.radiators if r.wall == w])
    return RoomMap(walls=walls, routes=_routes(room),
                   light_walls=[w for w in WALLS if walls[w].windows],
                   mode=room_mode(room), shape=room_shape(room))
