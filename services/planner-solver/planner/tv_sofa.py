"""П1 МАСТЕРА tv-sofa-pair: генератор ПАР «позиция медиа-блока × позиция блока посадки».

Свод владельца 13.08 (§3–7): алгоритм не делает «ТВ → потом где-нибудь диван» —
он ищет сразу ПАРУ. Стены ранжируются WallScore; длина стены — только tie-breaker.

Всё в терминах ШАБЛОНОВ: пара = (якорь медиа-БЛОКА, якорь БЛОКА посадки). Составы
блоков — из паспортов (лестница ступеней), внутрь блоков генератор не заглядывает.
Числа — `rules/templates.json → tv_sofa_pair` (WallScore, углы, цель дистанции).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .invariants import TEMPLATES
from .models import Item, Room
from .room_map import RoomMap, WallSegment

_CFG = TEMPLATES.get('tv_sofa_pair', {})
_WS = _CFG.get('wall_score', {})
_ANGLE = _CFG.get('view_angle_deg', {'perfect': 15, 'ok': 30})

WALL_ROT = {'south': 0.0, 'north': 180.0, 'west': 90.0, 'east': 270.0}
# rot дивана, СМОТРЯЩЕГО на данную стену
SOFA_ROT_FACING = {'south': 180.0, 'north': 0.0, 'west': 270.0, 'east': 90.0}


@dataclass
class Pair:
    media_wall: str
    media_x: float
    media_y: float
    media_rot: float
    sofa_x: float
    sofa_y: float
    sofa_rot: float
    sofa_scheme: str            # 'opposite_wall' | 'floating_pair' | 'window_back'
    score: float
    dist_cm: float
    angle_deg: float


def _tv_target_cm(media: Item) -> float:
    """Целевая дистанция RTINGS 1.6×диагональ — ЕДИНЫЙ источник planner/tv.py
    (антиошибка №1: не заводить второе число рядом с существующим)."""
    # как в зелёном замере 13.08 (медиа 252/252): аппроксимация диагонали от ширины
    # носителя; переход на tv.distance_target — вместе с порогами L2 large-room-mode
    diag = max(media.w_cm - 20.0, 80.0)
    return 1.6 * diag


def _media_positions(rmap: RoomMap, media: Item):
    """Позиции якоря медиа-блока по участкам стен: центр участка; для участков с
    окном за спиной — только НИЗКИЙ носитель (решает вызывающая сторона)."""
    for wall, info in rmap.walls.items():
        for seg in info.segments:
            if seg.length_cm < media.w_cm + 40.0:
                continue
            mid = (seg.start_cm + seg.end_cm) / 2
            yield wall, seg, mid


def _to_xy(room: Room, wall: str, along: float, depth_off: float) -> tuple[float, float]:
    if wall == 'south':
        return along, depth_off
    if wall == 'north':
        return along, room.depth_cm - depth_off
    if wall == 'west':
        return depth_off, along
    return room.width_cm - depth_off, along


def _pair_metrics(room: Room, wall: str, mx: float, my: float,
                  sx: float, sy: float, sofa_rot: float) -> tuple[float, float]:
    """(дистанция по прямой, угол между осью взгляда дивана и направлением на медиа)."""
    dx, dy = mx - sx, my - sy
    dist = math.hypot(dx, dy)
    r = math.radians(sofa_rot)
    fx, fy = math.sin(r), math.cos(r)
    cosang = (fx * dx + fy * dy) / (dist or 1.0)
    ang = math.degrees(math.acos(max(-1.0, min(1.0, cosang))))
    return dist, ang


def _route_cuts_pair(rmap: RoomMap, mx, my, sx, sy) -> bool:
    """Основной маршрут пересекает отрезок диван→медиа (свод §7: поток вокруг
    seating group, не сквозь)."""
    from shapely.geometry import LineString
    axis = LineString([(sx, sy), (mx, my)])
    return any(axis.crosses(rt) for rt in rmap.routes)


def generate_pairs(room: Room, rmap: RoomMap, media: Item, sofa: Item,
                   top_k: int = 6) -> list[Pair]:
    """Топ-K пар по WallScore. Позиции дивана на пару медиа-позиции:
    напротив у стены / floating на ТВ-вилке / (спинкой к окну — если стена с окном).
    """
    target = _tv_target_cm(media)
    out: list[Pair] = []
    for wall, seg, mid in _media_positions(rmap, media):
        m_rot = WALL_ROT[wall]
        mx, my = _to_xy(room, wall, mid, media.d_cm / 2)
        opp = rmap.opposite(wall)
        s_rot = SOFA_ROT_FACING[wall]
        # кандидаты дивана: у противоположной стены; floating на целевой дистанции
        sofa_spots: list[tuple[float, float, str]] = []
        far = (room.depth_cm if wall in ('south', 'north') else room.width_cm)
        wall_off = sofa.d_cm / 2 + 5.0
        sofa_spots.append((far - wall_off, 'opposite_wall'))
        sofa_spots.append((media.d_cm + target + sofa.d_cm / 2, 'floating_pair'))
        _pen = _CFG.get('wall_sofa_penalty', {})
        for depth_off, scheme in sofa_spots:
            if depth_off >= far - 10:
                continue
            sx, sy = _to_xy(room, wall, mid, depth_off)
            dist, ang = _pair_metrics(room, wall, mx, my, sx, sy, s_rot)
            # скоринг WallScore (числа из паспорта)
            score = float(_WS.get('fits_media', 20))
            d_err = abs(dist - target) / max(target, 1.0)
            score += float(_WS.get('distance_near_target', 20)) * max(0.0, 1 - d_err)
            # L2 (large-room): пороги 1.2×/1.5×V — только в large-режиме
            if rmap.mode == 'large' and scheme == 'opposite_wall':
                ratio = dist / max(target, 1.0)
                if ratio > float(_pen.get('prefer_floating_ratio', 1.5)):
                    score -= 30.0          # «5 м пустоты» проигрывает всегда
                elif ratio > float(_pen.get('ok_ratio', 1.2)):
                    score -= 10.0          # floating предпочтителен
            if ang <= _ANGLE.get('perfect', 15):
                score += float(_WS.get('sofa_opposite', 15))
            elif ang <= _ANGLE.get('ok', 30):
                score += float(_WS.get('sofa_opposite', 15)) * 0.5
            if not _route_cuts_pair(rmap, mx, my, sx, sy):
                score += float(_WS.get('route_not_cutting', 15))
            opp_wins = rmap.walls[opp].windows
            if not seg.has_window_behind and not opp_wins:
                score += float(_WS.get('no_window_conflict', 15))
            elif seg.has_window_behind:
                score += 0.0            # низкий носитель可, но балла нет
            else:
                score += float(_WS.get('no_window_conflict', 15)) * 0.4
            score += float(_WS.get('free_length', 5)) * min(1.0, seg.length_cm / 400.0)
            out.append(Pair(media_wall=wall, media_x=mx, media_y=my, media_rot=m_rot,
                            sofa_x=sx, sofa_y=sy, sofa_rot=s_rot, sofa_scheme=scheme,
                            score=round(score, 1), dist_cm=round(dist),
                            angle_deg=round(ang)))
    out.sort(key=lambda p: -p.score)
    return out[:top_k]
